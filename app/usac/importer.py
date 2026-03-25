import requests
from datetime import date

USAC_BASE = 'https://opendata.usac.org/resource'

# Known USAC dataset IDs (Socrata)
DATASETS = {
    'entity_info': '7i5i-83qf',       # E-Rate Supplemental Entity Information
    'form471_frn': 'avi8-svp9',        # E-Rate Recipient Details And Commitments
    'frn_status': 'qdmp-ygft',         # E-Rate FRN Status (Form 471)
    'c2_budget': '6brt-5pbv',          # E-Rate C2 Budget Tool Data FY2021+
    'form470': 'jp7a-89nd',            # E-Rate Open Competitive Bidding (Form 470)
}

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
        data = resp.json()
        if isinstance(data, dict) and data.get('error'):
            raise USACImportError(f"USAC API: {data.get('message', 'Unknown error')}")
        return data
    except requests.exceptions.Timeout:
        raise USACImportError('USAC API request timed out. Try again later.')
    except requests.exceptions.ConnectionError:
        raise USACImportError('Could not connect to USAC Open Data.')
    except requests.exceptions.HTTPError as e:
        raise USACImportError(f'USAC API error: {e.response.status_code} {e.response.text[:200]}')
    except ValueError:
        raise USACImportError('Invalid response from USAC API.')


def _get(record, *keys, default=None):
    """Get first matching key from a record (handles field name variations)."""
    for key in keys:
        val = record.get(key)
        if val is not None and val != '':
            return val
    return default


# ══════════════════════════════════════════════════════════
# SEARCH
# ══════════════════════════════════════════════════════════

def search_entities(query, state=None, app_token=None):
    """Search for school districts/entities by name or entity number."""
    # Check if query looks like an entity number
    if query.strip().isdigit():
        params = {
            '$where': f"entity_number='{query.strip()}'",
            '$limit': 50,
        }
    else:
        params = {
            '$q': query,
            '$limit': 50,
        }

    if state:
        where = params.get('$where', '')
        state_filter = f"upper(physical_state)='{state.upper()}'"
        params['$where'] = f"{where} AND {state_filter}" if where else state_filter

    results = _fetch('entity_info', params, app_token)

    seen = set()
    entities = []
    for r in results:
        en = _get(r, 'entity_number', default='')
        if not en or en in seen:
            continue
        seen.add(en)
        entities.append({
            'entity_number': en,
            'name': _get(r, 'entity_name', default=''),
            'entity_type': _get(r, 'entity_type', default=''),
            'city': _get(r, 'physical_city', default=''),
            'state': _get(r, 'physical_state', default=''),
        })
    return entities


# ══════════════════════════════════════════════════════════
# ENTITY DETAILS
# ══════════════════════════════════════════════════════════

def fetch_entity_details(entity_number, app_token=None):
    """Fetch detailed info for a specific entity."""
    params = {
        '$where': f"entity_number='{entity_number}'",
        '$limit': 5,
    }
    results = _fetch('entity_info', params, app_token)
    if not results:
        raise USACImportError(f'Entity {entity_number} not found.')

    r = results[0]
    urban_raw = _get(r, 'urban_rural_status', 'user_entered_urban_rural_status', default='')
    return {
        'entity_number': _get(r, 'entity_number', default=''),
        'name': _get(r, 'entity_name', default=''),
        'entity_type': _get(r, 'entity_type', default=''),
        'parent_entity_number': _get(r, 'parent_entity_number', default=''),
        'parent_entity_name': _get(r, 'parent_entity_name', default=''),
        'address': _get(r, 'physical_address_1', 'physical_address', default=''),
        'city': _get(r, 'physical_city', default=''),
        'state': _get(r, 'physical_state', default=''),
        'zip': _get(r, 'physical_zip_code', 'physical_zipcode', default=''),
        'urban_rural': 'urban' if 'urban' in urban_raw.lower() else 'rural',
        'discount_rate_c1': _safe_int(_get(r, 'category_one_discount_rate')),
        'discount_rate_c2': _safe_int(_get(r, 'category_two_discount_rate')),
        'student_count': _safe_int(_get(r, 'c2_district_student_count', 'c2_school_student_count')),
        'square_footage': _safe_int(_get(r, 'recipient_square_footage', 'square_footage')),
    }


# ══════════════════════════════════════════════════════════
# SCHOOLS (child entities of a district)
# ══════════════════════════════════════════════════════════

def fetch_schools(district_entity_number, app_token=None):
    """Fetch schools that belong to a district using parent_entity_number."""
    params = {
        '$where': f"parent_entity_number='{district_entity_number}'",
        '$limit': 500,
    }
    results = _fetch('entity_info', params, app_token)

    schools = []
    seen = set()
    for r in results:
        en = _get(r, 'entity_number', default='')
        etype = (_get(r, 'entity_type', default='') or '').lower()
        if not en or en == str(district_entity_number) or en in seen:
            continue
        if 'school' in etype or 'nif' in etype:
            seen.add(en)
            schools.append({
                'entity_number': en,
                'name': _get(r, 'entity_name', default=''),
                'entity_type': _get(r, 'entity_type', default=''),
                'address': _get(r, 'physical_address_1', 'physical_address', default=''),
                'city': _get(r, 'physical_city', default=''),
                'state': _get(r, 'physical_state', default=''),
                'zip': _get(r, 'physical_zip_code', 'physical_zipcode', default=''),
                'square_footage': _safe_int(_get(r, 'recipient_square_footage', 'square_footage')),
            })

    return schools


# ══════════════════════════════════════════════════════════
# FUNDING YEAR DATA (from Recipient Details)
# ══════════════════════════════════════════════════════════

def fetch_funding_year_data(entity_number, app_token=None):
    """Fetch per-funding-year data from the recipient details dataset."""
    params = {
        '$where': f"billed_entity_number='{entity_number}'",
        '$limit': 5000,
        '$order': 'funding_year DESC',
    }

    try:
        results = _fetch('form471_frn', params, app_token)
    except USACImportError:
        results = []

    # Aggregate by funding year — pick best enrollment/NSLP data per year
    fy_data = {}
    for r in results:
        fy = _safe_int(_get(r, 'funding_year'))
        if not fy:
            continue

        enrollment = _safe_int(_get(r, 'recipient_total_number_of_full_time_students',
                                    'total_number_of_full_time_students',
                                    'number_of_full_time_students'))
        nslp = _safe_int(_get(r, 'recipient_number_of_nslp_students',
                              'number_of_nslp_students'))
        discount = _safe_int(_get(r, 'discount_percentage', 'discount_rate',
                                  'category_one_discount_rate'))
        urban_raw = _get(r, 'recipient_urban_rural_status', 'urban_rural_status', default='')
        urban_rural = 'urban' if 'urban' in urban_raw.lower() else 'rural'

        # Keep the record with the best (most complete) data
        if fy not in fy_data or (enrollment and not fy_data[fy].get('enrollment')):
            nslp_pct = None
            if enrollment and nslp:
                nslp_pct = round(nslp / enrollment * 100, 1)
            fy_data[fy] = {
                'year': fy,
                'enrollment': enrollment,
                'nslp_students': nslp,
                'nslp_percentage': nslp_pct,
                'discount_rate': discount,
                'urban_rural': urban_rural,
            }

    return sorted(fy_data.values(), key=lambda x: x['year'], reverse=True)


# ══════════════════════════════════════════════════════════
# FRN DATA (from Recipient Details + Commitments)
# ══════════════════════════════════════════════════════════

def fetch_frn_data(entity_number, app_token=None):
    """Fetch FRN data from the recipient details dataset."""
    params = {
        '$where': f"billed_entity_number='{entity_number}'",
        '$limit': 5000,
        '$order': 'funding_year DESC',
    }
    results = _fetch('form471_frn', params, app_token)

    frns = {}
    for r in results:
        frn = _get(r, 'funding_request_number', default='')
        if not frn or frn in frns:
            continue

        frns[frn] = {
            'frn': frn,
            'funding_year': _safe_int(_get(r, 'funding_year')),
            'application_number': _get(r, 'application_number', default=''),
            'category': _categorize(_get(r, 'category_of_service', default='')),
            'service_type': _get(r, 'service_type', default=''),
            'status': _get(r, 'form_471_status', 'frn_status',
                          'funding_request_status', default=''),
            'spin': _get(r, 'service_provider_number', default=''),
            'vendor_name': _get(r, 'service_provider_name', default=''),
            'amount_requested': _safe_float(_get(r, 'original_commitment_request_amount',
                                                 'pre_discount_extended_eligible_line_item_costs',
                                                 'frn_total_pre_discount_costs')),
            'amount_committed': _safe_float(_get(r, 'commitment_amount',
                                                 'funding_commitment_amount')),
            'discount_rate': _safe_int(_get(r, 'discount_percentage')),
            'narrative': _get(r, 'funding_request_narrative', 'narrative', default=''),
        }

    return list(frns.values())


# ══════════════════════════════════════════════════════════
# FRN STATUS / FCDL DATA
# ══════════════════════════════════════════════════════════

def fetch_frn_status_data(entity_number, app_token=None):
    """Fetch FRN status / FCDL data from the FRN Status dataset."""
    params = {
        '$where': f"billed_entity_number='{entity_number}'",
        '$limit': 5000,
        '$order': 'funding_year DESC',
    }

    try:
        results = _fetch('frn_status', params, app_token)
    except USACImportError:
        return {}

    statuses = {}
    for r in results:
        frn = _get(r, 'funding_request_number', default='')
        if not frn or frn in statuses:
            continue

        statuses[frn] = {
            'frn': frn,
            'funding_year': _safe_int(_get(r, 'funding_year')),
            'status': (_get(r, 'funding_request_status', 'frn_status', default='') or '').lower(),
            'committed_amount': _safe_float(_get(r, 'funding_commitment_amount',
                                                 'commitment_amount', 'committed_amount')),
            'vendor_name': _get(r, 'service_provider_name', default=''),
            'spin': _get(r, 'service_provider_number', default=''),
            'fcdl_date': _get(r, 'fcdl_comment_date', 'fcdl_date', default=''),
            'category': _categorize(_get(r, 'category_of_service', default='')),
            'discount_rate': _safe_int(_get(r, 'discount_percentage')),
            'contract_expiration': _get(r, 'contract_expiration_date', default=''),
        }

    return statuses


# ══════════════════════════════════════════════════════════
# C2 BUDGET DATA
# ══════════════════════════════════════════════════════════

def fetch_c2_budget(entity_number, app_token=None):
    """Fetch Category 2 budget data."""
    # Try entity_number first, then billed_entity_number
    for field in ['entity_number', 'billed_entity_number']:
        params = {
            '$where': f"{field}='{entity_number}'",
            '$limit': 100,
        }
        try:
            results = _fetch('c2_budget', params, app_token)
            if results:
                break
        except USACImportError:
            results = []

    budgets = []
    for r in results:
        budgets.append({
            'entity_name': _get(r, 'organization_name', 'entity_name', default=''),
            'entity_number': _get(r, 'entity_number', default=''),
            'budget_cycle': _get(r, 'budget_cycle', default=''),
            'c2_budget': _safe_float(_get(r, 'c2_budget', 'budget_amount',
                                         'c2_budget_total')),
            'budget_version': _get(r, 'budget_version', default=''),
        })

    return budgets


# ══════════════════════════════════════════════════════════
# FORM 470 DATA
# ══════════════════════════════════════════════════════════

def fetch_form470_data(entity_number, app_token=None):
    """Fetch Form 470 filings."""
    params = {
        '$where': f"billed_entity_number='{entity_number}'",
        '$limit': 500,
        '$order': 'funding_year DESC',
    }

    try:
        results = _fetch('form470', params, app_token)
    except USACImportError:
        return []

    forms = []
    seen = set()
    for r in results:
        app_num = _get(r, 'application_number', 'form_470_number', default='')
        if not app_num or app_num in seen:
            continue
        seen.add(app_num)

        forms.append({
            'application_number': app_num,
            'funding_year': _safe_int(_get(r, 'funding_year')),
            'category': _categorize(_get(r, 'category_of_service', default='')),
            'status': _get(r, 'form_470_status', 'window_status', default=''),
            'allowable_contract_date': _get(r, 'allowable_contract_date', default=''),
        })

    return forms


# ══════════════════════════════════════════════════════════
# IMPORT ALL
# ══════════════════════════════════════════════════════════

def import_all(entity_number, app_token=None):
    """Fetch all available E-rate data for an entity."""
    result = {
        'entity': None,
        'schools': [],
        'funding_years': [],
        'frns': [],
        'vendors': {},
        'c2_budgets': [],
        'form470s': [],
        'errors': [],
    }

    # 1. Entity info
    try:
        entity = fetch_entity_details(entity_number, app_token)
        result['entity'] = entity
    except USACImportError as e:
        result['errors'].append(f'Entity info: {str(e)}')

    # 2. Schools (child entities)
    try:
        schools = fetch_schools(entity_number, app_token)
        result['schools'] = schools
    except USACImportError as e:
        result['errors'].append(f'Schools: {str(e)}')

    # 3. Funding year data
    try:
        funding_years = fetch_funding_year_data(entity_number, app_token)
        result['funding_years'] = funding_years

        # Apply entity discount rate to latest FY if missing
        if result['entity'] and funding_years:
            dr = result['entity'].get('discount_rate_c1')
            if dr and not funding_years[0].get('discount_rate'):
                funding_years[0]['discount_rate'] = dr
    except USACImportError as e:
        result['errors'].append(f'Funding year data: {str(e)}')

    # 4. FRN data
    try:
        frns = fetch_frn_data(entity_number, app_token=app_token)
        result['frns'] = frns
        for frn in frns:
            spin = frn.get('spin', '')
            if spin and spin not in result['vendors']:
                result['vendors'][spin] = {
                    'name': frn.get('vendor_name', ''),
                    'spin': spin,
                }
    except USACImportError as e:
        result['errors'].append(f'FRN data: {str(e)}')

    # 5. FRN status / FCDL — merge with FRNs
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
                    if not frn.get('discount_rate') and status.get('discount_rate'):
                        frn['discount_rate'] = status['discount_rate']
                    spin = status.get('spin', '')
                    if spin and spin not in result['vendors']:
                        result['vendors'][spin] = {
                            'name': status.get('vendor_name', ''),
                            'spin': spin,
                        }
    except USACImportError as e:
        result['errors'].append(f'FRN status data: {str(e)}')

    # 6. C2 budget
    try:
        c2 = fetch_c2_budget(entity_number, app_token)
        result['c2_budgets'] = c2
    except USACImportError as e:
        result['errors'].append(f'C2 budget: {str(e)}')

    # 7. Form 470
    try:
        form470s = fetch_form470_data(entity_number, app_token)
        result['form470s'] = form470s
    except USACImportError as e:
        result['errors'].append(f'Form 470 data: {str(e)}')

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
