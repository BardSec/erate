import requests
from datetime import date

USAC_BASE = 'https://opendata.usac.org/resource'

# Known USAC dataset IDs (Socrata)
DATASETS = {
    'entity_info': '7i5i-83qf',       # E-Rate Supplemental Entity Information
    'form471_frn': 'avi8-svp9',        # E-Rate Recipient Details And Commitments
    'frn_status': 'qdmp-ygft',         # E-Rate FRN Status (Form 471)
    'c2_budget': '6brt-5pbv',          # E-Rate C2 Budget Tool Data FY2021+
    'form470': 'jp7a-89nd',            # E-Rate Open Competitive Bidding: Basic Information (Form 470)
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
    Uses dataset 7i5i-83qf (E-Rate Supplemental Entity Information).
    """
    params = {
        '$q': query,
        '$limit': 50,
        '$select': 'entity_number,entity_name,entity_type,physical_city,physical_state',
    }
    if state:
        params['$where'] = f"upper(physical_state)='{state.upper()}'"

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

    Uses dataset 7i5i-83qf (E-Rate Supplemental Entity Information).
    """
    params = {
        '$where': f"entity_number='{entity_number}'",
        '$limit': 10,
    }
    results = _fetch('entity_info', params, app_token)
    if not results:
        raise USACImportError(f'Entity {entity_number} not found in USAC database.')

    latest = results[0]

    entity = {
        'entity_number': latest.get('entity_number', ''),
        'name': latest.get('entity_name', ''),
        'entity_type': latest.get('entity_type', ''),
        'parent_entity_number': latest.get('parent_entity_number', ''),
        'parent_entity_name': latest.get('parent_entity_name', ''),
        'address': latest.get('physical_address_1', ''),
        'city': latest.get('physical_city', ''),
        'state': latest.get('physical_state', ''),
        'zip': latest.get('physical_zip_code', ''),
        'urban_rural': 'urban' if (latest.get('urban_rural_status', '') or '').lower() in ('urban', 'u') else 'rural',
        'discount_rate_c1': _safe_int(latest.get('category_one_discount_rate')),
        'discount_rate_c2': _safe_int(latest.get('category_two_discount_rate')),
        'c2_student_count': _safe_int(latest.get('c2_district_student_count') or latest.get('c2_school_student_count')),
    }

    return entity


def fetch_funding_year_data(entity_number, app_token=None):
    """Fetch per-funding-year data from the recipient details dataset.

    Uses dataset avi8-svp9 (E-Rate Recipient Details And Commitments).
    Returns funding year info including enrollment, NSLP, discount rate.
    """
    # Try as billed entity first (district level)
    params = {
        '$where': f"billed_entity_number='{entity_number}'",
        '$select': 'funding_year,recipient_entity_number,recipient_entity_name,'
                   'recipient_urban_rural_status,'
                   'recipient_total_number_of_full_time_students,'
                   'recipient_number_of_nslp_students',
        '$group': 'funding_year,recipient_entity_number,recipient_entity_name,'
                  'recipient_urban_rural_status,'
                  'recipient_total_number_of_full_time_students,'
                  'recipient_number_of_nslp_students',
        '$order': 'funding_year DESC',
        '$limit': 500,
    }

    try:
        results = _fetch('form471_frn', params, app_token)
    except USACImportError:
        results = []

    if not results:
        # Try as recipient entity
        params['$where'] = f"recipient_entity_number='{entity_number}'"
        try:
            results = _fetch('form471_frn', params, app_token)
        except USACImportError:
            results = []

    # Aggregate by funding year
    funding_years = {}
    for r in results:
        fy = r.get('funding_year', '')
        if not fy:
            continue
        fy_int = _safe_int(fy)
        if not fy_int or fy_int in funding_years:
            continue

        enrollment = _safe_int(r.get('recipient_total_number_of_full_time_students'))
        nslp = _safe_int(r.get('recipient_number_of_nslp_students'))
        nslp_pct = None
        if enrollment and nslp:
            nslp_pct = round(nslp / enrollment * 100, 1)

        urban_rural_raw = r.get('recipient_urban_rural_status', '') or ''
        urban_rural = 'urban' if urban_rural_raw.lower() in ('urban', 'u') else 'rural'

        funding_years[fy_int] = {
            'year': fy_int,
            'enrollment': enrollment,
            'nslp_students': nslp,
            'nslp_percentage': nslp_pct,
            'discount_rate': None,  # Will be filled from entity info or calculated
            'urban_rural': urban_rural,
        }

    return sorted(funding_years.values(), key=lambda x: x['year'], reverse=True)


def fetch_frn_data(entity_number, app_token=None):
    """Fetch FRN data from the recipient details and commitments dataset.

    Uses dataset avi8-svp9 (E-Rate Recipient Details And Commitments).
    """
    params = {
        '$where': f"billed_entity_number='{entity_number}'",
        '$limit': 5000,
        '$order': 'funding_year DESC',
    }
    results = _fetch('form471_frn', params, app_token)

    frns = {}
    for r in results:
        frn = r.get('funding_request_number', '')
        if not frn or frn in frns:
            continue

        frns[frn] = {
            'frn': frn,
            'funding_year': _safe_int(r.get('funding_year')),
            'application_number': r.get('application_number', ''),
            'category': _categorize(r.get('category_of_service', '')),
            'service_type': r.get('service_type', ''),
            'status': r.get('form_471_status', '') or r.get('frn_status', ''),
            'spin': r.get('service_provider_number', ''),
            'vendor_name': r.get('service_provider_name', ''),
            'amount_requested': _safe_float(r.get('original_commitment_request_amount') or
                                            r.get('pre_discount_extended_eligible_line_item_costs')),
            'amount_committed': _safe_float(r.get('commitment_amount')),
            'narrative': r.get('narrative', ''),
        }

    return list(frns.values())


def fetch_frn_status_data(entity_number, app_token=None):
    """Fetch FRN status / FCDL data.

    Uses dataset qdmp-ygft (E-Rate FRN Status).
    """
    params = {
        '$where': f"billed_entity_number='{entity_number}'",
        '$limit': 5000,
        '$order': 'funding_year DESC',
    }

    try:
        results = _fetch('frn_status', params, app_token)
    except USACImportError:
        return []

    statuses = {}
    for r in results:
        frn = r.get('funding_request_number', '')
        if not frn or frn in statuses:
            continue

        statuses[frn] = {
            'frn': frn,
            'funding_year': _safe_int(r.get('funding_year')),
            'status': (r.get('frn_status', '') or '').lower(),
            'committed_amount': _safe_float(r.get('commitment_amount') or r.get('committed_amount')),
            'vendor_name': r.get('service_provider_name', ''),
            'spin': r.get('service_provider_number', ''),
            'fcdl_date': r.get('fcdl_comment_date', '') or r.get('fcdl_date', ''),
            'category': _categorize(r.get('category_of_service', '')),
        }

    return statuses


def fetch_c2_budget(entity_number, app_token=None):
    """Fetch Category 2 budget data for an entity.

    Uses dataset 6brt-5pbv (E-Rate C2 Budget Tool Data FY2021+).
    """
    params = {
        '$where': f"entity_number='{entity_number}'",
        '$limit': 100,
    }

    try:
        results = _fetch('c2_budget', params, app_token)
    except USACImportError:
        # Try alternate field name
        params = {
            '$where': f"billed_entity_number='{entity_number}'",
            '$limit': 100,
        }
        try:
            results = _fetch('c2_budget', params, app_token)
        except USACImportError:
            return []

    budgets = []
    for r in results:
        budgets.append({
            'entity_name': r.get('organization_name', '') or r.get('entity_name', ''),
            'budget_cycle': r.get('budget_cycle', ''),
            'c2_budget': _safe_float(r.get('c2_budget') or r.get('c2_budget_total')),
            'budget_version': r.get('budget_version', ''),
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
        'vendors': {},
        'c2_budgets': [],
        'errors': [],
    }

    # Entity info
    try:
        entity = fetch_entity_details(entity_number, app_token)
        result['entity'] = entity
    except USACImportError as e:
        result['errors'].append(f'Entity info: {str(e)}')

    # Funding year data from recipient details
    try:
        funding_years = fetch_funding_year_data(entity_number, app_token)
        result['funding_years'] = funding_years

        # If we have entity discount rate, apply to latest FY
        if result['entity'] and funding_years:
            dr = result['entity'].get('discount_rate_c1')
            if dr and not funding_years[0].get('discount_rate'):
                funding_years[0]['discount_rate'] = dr
    except USACImportError as e:
        result['errors'].append(f'Funding year data: {str(e)}')

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

    # FRN status / FCDL data — merge with FRNs
    try:
        status_data = fetch_frn_status_data(entity_number, app_token)
        if isinstance(status_data, dict):
            for frn in result['frns']:
                status = status_data.get(frn['frn'])
                if status:
                    if not frn.get('amount_committed') and status.get('committed_amount'):
                        frn['amount_committed'] = status['committed_amount']
                    if status.get('status'):
                        frn['usac_status'] = status['status']
                    if status.get('fcdl_date'):
                        frn['fcdl_date'] = status['fcdl_date']
                    # Fill vendor info from status if missing
                    spin = status.get('spin', '')
                    if spin and spin not in result['vendors']:
                        result['vendors'][spin] = {
                            'name': status.get('vendor_name', ''),
                            'spin': spin,
                        }
    except USACImportError as e:
        result['errors'].append(f'FRN status data: {str(e)}')

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
