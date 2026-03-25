import requests
from datetime import date

USAC_BASE = 'https://opendata.usac.org/resource'

# Known USAC dataset IDs (Socrata)
DATASETS = {
    'entity_info': 'sumt-yrv3',
    'form471_frn': 'avi8-svp9',
    'fcdl': 'qdmp-ygft',
    'c2_budget': '8z69-hkn9',
}

# Request timeout
TIMEOUT = 30


class USACImportError(Exception):
    pass


def _fetch(dataset_key, params, app_token=None):
    """Fetch data from a USAC dataset via SODA API."""
    dataset_id = DATASETS.get(dataset_key)
    if not dataset_id:
        raise USACImportError(f'Unknown dataset: {dataset_key}')

    url = f'{USAC_BASE}/{dataset_id}.json'
    headers = {}
    if app_token:
        headers['X-App-Token'] = app_token

    params.setdefault('$limit', 5000)

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        raise USACImportError('USAC API request timed out. Try again later.')
    except requests.exceptions.ConnectionError:
        raise USACImportError('Could not connect to USAC Open Data. Check your internet connection.')
    except requests.exceptions.HTTPError as e:
        raise USACImportError(f'USAC API error: {e.response.status_code} {e.response.text[:200]}')
    except ValueError:
        raise USACImportError('Invalid response from USAC API.')


def search_entities(query, state=None, app_token=None):
    """Search for school districts/entities by name.

    Returns list of dicts with entity_number, entity_name, city, state, entity_type.
    """
    params = {
        '$q': query,
        '$limit': 50,
        '$select': 'entity_number,entity_name,entity_type,physical_city,physical_state',
    }
    if state:
        params['physical_state'] = state.upper()

    results = _fetch('entity_info', params, app_token)

    seen = set()
    entities = []
    for r in results:
        en = r.get('entity_number', '')
        if en in seen:
            continue
        seen.add(en)
        entities.append({
            'entity_number': en,
            'name': r.get('entity_name', ''),
            'entity_type': r.get('entity_type', ''),
            'city': r.get('physical_city', ''),
            'state': r.get('physical_state', ''),
        })
    return entities


def fetch_entity_details(entity_number, app_token=None):
    """Fetch detailed info for a specific entity (district or school).

    Returns dict with name, address, NSLP data, discount rate, etc.
    """
    params = {
        'entity_number': str(entity_number),
        '$limit': 100,
        '$order': 'funding_year DESC',
    }
    results = _fetch('entity_info', params, app_token)
    if not results:
        raise USACImportError(f'Entity {entity_number} not found in USAC database.')

    # Group by funding year, take most recent info
    latest = results[0]

    entity = {
        'entity_number': latest.get('entity_number', ''),
        'name': latest.get('entity_name', ''),
        'entity_type': latest.get('entity_type', ''),
        'address': latest.get('physical_address', ''),
        'city': latest.get('physical_city', ''),
        'state': latest.get('physical_state', ''),
        'zip': latest.get('physical_zipcode', ''),
        'urban_rural': 'urban' if latest.get('urban_rural_status', '').lower() in ('urban', 'u') else 'rural',
    }

    # Collect funding year data
    funding_years = []
    seen_years = set()
    for r in results:
        fy = r.get('funding_year', '')
        if not fy or fy in seen_years:
            continue
        seen_years.add(fy)

        # Parse enrollment and NSLP
        enrollment = _safe_int(r.get('number_of_eligible_students'))
        nslp_students = _safe_int(r.get('number_of_nslp_students'))
        nslp_pct = None
        if enrollment and nslp_students:
            nslp_pct = round(nslp_students / enrollment * 100, 1)

        discount_rate = _safe_int(r.get('discount_rate'))

        funding_years.append({
            'year': _safe_int(fy),
            'enrollment': enrollment,
            'nslp_students': nslp_students,
            'nslp_percentage': nslp_pct,
            'discount_rate': discount_rate,
            'urban_rural': entity['urban_rural'],
        })

    entity['funding_years'] = sorted(funding_years, key=lambda x: x['year'] or 0, reverse=True)
    return entity


def fetch_child_entities(parent_ben, app_token=None):
    """Fetch schools belonging to a district (by looking up entities sharing the same BEN in FRNs).

    This is a heuristic — we look for distinct entity_numbers in the Form 471 data
    that have the parent BEN as billed entity.
    """
    # Try fetching entity_info records that match the district
    params = {
        '$where': f"entity_number='{parent_ben}'",
        '$limit': 1,
    }
    results = _fetch('entity_info', params, app_token)

    if not results:
        return []

    # Search for entities in the same state/city with similar names
    parent = results[0]
    parent_name = parent.get('entity_name', '')
    state = parent.get('physical_state', '')

    # Get base name for searching (e.g., "Springfield" from "Springfield School District")
    # Search broadly in same state
    search_params = {
        '$where': f"physical_state='{state}'",
        '$q': parent_name.split(' ')[0] if parent_name else '',
        '$limit': 200,
        '$select': 'entity_number,entity_name,entity_type,physical_address,physical_city,physical_state,physical_zipcode',
    }

    all_entities = _fetch('entity_info', search_params, app_token)

    # Filter to schools (not the district itself)
    schools = []
    seen = set()
    for r in all_entities:
        en = r.get('entity_number', '')
        etype = r.get('entity_type', '').lower()
        if en == str(parent_ben) or en in seen:
            continue
        if 'school' in etype:
            seen.add(en)
            schools.append({
                'entity_number': en,
                'name': r.get('entity_name', ''),
                'entity_type': r.get('entity_type', ''),
                'address': r.get('physical_address', ''),
                'city': r.get('physical_city', ''),
                'state': r.get('physical_state', ''),
                'zip': r.get('physical_zipcode', ''),
            })

    return schools


def fetch_frn_data(ben, funding_year=None, app_token=None):
    """Fetch Form 471 / FRN data for an entity.

    Returns list of FRN dicts.
    """
    where_parts = [f"ben='{ben}'"]
    if funding_year:
        where_parts.append(f"funding_year='{funding_year}'")

    params = {
        '$where': ' AND '.join(where_parts),
        '$limit': 5000,
        '$order': 'funding_year DESC',
    }
    results = _fetch('form471_frn', params, app_token)

    frns = []
    seen = set()
    for r in results:
        frn = r.get('funding_request_number', '')
        if not frn or frn in seen:
            continue
        seen.add(frn)

        frns.append({
            'frn': frn,
            'funding_year': _safe_int(r.get('funding_year')),
            'category': _categorize(r.get('category_of_service', '')),
            'service_type': r.get('service_type', ''),
            'status': r.get('form_471_status', ''),
            'spin': r.get('service_provider_number', ''),
            'vendor_name': r.get('service_provider_name', ''),
            'amount_requested': _safe_float(r.get('pre_discount_extended_eligible_line_item_costs')),
            'narrative': r.get('narrative', ''),
        })

    return frns


def fetch_fcdl_data(ben, funding_year=None, app_token=None):
    """Fetch commitment (FCDL) data for an entity.

    Returns list of commitment dicts.
    """
    where_parts = [f"ben='{ben}'"]
    if funding_year:
        where_parts.append(f"funding_year='{funding_year}'")

    params = {
        '$where': ' AND '.join(where_parts),
        '$limit': 5000,
        '$order': 'funding_year DESC',
    }
    results = _fetch('fcdl', params, app_token)

    commitments = []
    seen = set()
    for r in results:
        frn = r.get('funding_request_number', '')
        if not frn or frn in seen:
            continue
        seen.add(frn)

        commitments.append({
            'frn': frn,
            'funding_year': _safe_int(r.get('funding_year')),
            'category': _categorize(r.get('category_of_service', '')),
            'status': (r.get('frn_status', '') or '').lower(),
            'committed_amount': _safe_float(r.get('committed_amount') or r.get('commitment_amount')),
            'vendor_name': r.get('service_provider_name', ''),
            'spin': r.get('service_provider_number', ''),
            'fcdl_date': r.get('fcdl_date', ''),
        })

    return commitments


def fetch_c2_budget(entity_number, app_token=None):
    """Fetch Category 2 budget data for an entity.

    Returns list of C2 budget dicts by funding year.
    """
    params = {
        'entity_number': str(entity_number),
        '$limit': 100,
        '$order': 'funding_year DESC',
    }
    results = _fetch('c2_budget', params, app_token)

    budgets = []
    for r in results:
        budgets.append({
            'funding_year': _safe_int(r.get('funding_year')),
            'c2_budget_total': _safe_float(r.get('c2_budget_total')),
            'c2_committed': _safe_float(r.get('c2_committed')),
            'c2_remaining': _safe_float(r.get('c2_remaining')),
            'c2_disbursed': _safe_float(r.get('c2_disbursed')),
        })

    return budgets


def import_all(entity_number, app_token=None):
    """Fetch all available E-rate data for an entity.

    Returns a comprehensive dict with entity info, funding years,
    FRNs, commitments, vendors, and C2 budget data.
    """
    result = {
        'entity': None,
        'funding_years': [],
        'frns': [],
        'commitments': [],
        'vendors': {},
        'c2_budgets': [],
        'errors': [],
    }

    # Entity info
    try:
        entity = fetch_entity_details(entity_number, app_token)
        result['entity'] = entity
        result['funding_years'] = entity.get('funding_years', [])
    except USACImportError as e:
        result['errors'].append(f'Entity info: {str(e)}')

    # FRN data
    try:
        frns = fetch_frn_data(entity_number, app_token=app_token)
        result['frns'] = frns
        # Extract unique vendors
        for frn in frns:
            spin = frn.get('spin', '')
            if spin and spin not in result['vendors']:
                result['vendors'][spin] = {
                    'name': frn.get('vendor_name', ''),
                    'spin': spin,
                }
    except USACImportError as e:
        result['errors'].append(f'FRN data: {str(e)}')

    # FCDL / commitment data
    try:
        commitments = fetch_fcdl_data(entity_number, app_token=app_token)
        result['commitments'] = commitments
        # Merge vendor info from commitments
        for c in commitments:
            spin = c.get('spin', '')
            if spin and spin not in result['vendors']:
                result['vendors'][spin] = {
                    'name': c.get('vendor_name', ''),
                    'spin': spin,
                }
    except USACImportError as e:
        result['errors'].append(f'Commitment data: {str(e)}')

    # C2 budget
    try:
        c2 = fetch_c2_budget(entity_number, app_token)
        result['c2_budgets'] = c2
    except USACImportError as e:
        result['errors'].append(f'C2 budget: {str(e)}')

    return result


# ── Helpers ──────────────────────────────────────────────

def _safe_int(value):
    if value is None:
        return None
    try:
        return int(float(str(value).replace(',', '')))
    except (ValueError, TypeError):
        return None


def _safe_float(value):
    if value is None:
        return None
    try:
        return round(float(str(value).replace(',', '').replace('$', '')), 2)
    except (ValueError, TypeError):
        return None


def _categorize(category_str):
    """Normalize category of service to C1 or C2."""
    if not category_str:
        return None
    cat = category_str.lower()
    if '1' in cat or 'one' in cat:
        return 'C1'
    if '2' in cat or 'two' in cat:
        return 'C2'
    return category_str
