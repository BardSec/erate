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
    """Get first matching key from a record."""
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
        en = r.get('entity_number', '')
        if not en or en in seen:
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


# ══════════════════════════════════════════════════════════
# ENTITY DETAILS (7i5i-83qf)
# Fields: entity_number, entity_name, entity_type, parent_entity_number,
#   parent_entity_name, physical_address, physical_city, physical_state,
#   physical_zipcode, category_one_discount_rate, category_two_discount_rate,
#   c2_student_count_reporting_type
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
    return {
        'entity_number': r.get('entity_number', ''),
        'name': r.get('entity_name', ''),
        'entity_type': r.get('entity_type', ''),
        'parent_entity_number': r.get('parent_entity_number', ''),
        'parent_entity_name': r.get('parent_entity_name', ''),
        'address': r.get('physical_address', ''),
        'city': r.get('physical_city', ''),
        'state': r.get('physical_state', ''),
        'zip': r.get('physical_zipcode', ''),
        'discount_rate_c1': _safe_int(r.get('category_one_discount_rate')),
        'discount_rate_c2': _safe_int(r.get('category_two_discount_rate')),
    }


# ══════════════════════════════════════════════════════════
# SCHOOLS (child entities of a district, from 7i5i-83qf)
# Uses parent_entity_number to find children
# ══════════════════════════════════════════════════════════

def fetch_schools(district_entity_number, app_token=None):
    """Fetch schools that belong to a district."""
    params = {
        '$where': f"parent_entity_number='{district_entity_number}'",
        '$limit': 500,
    }
    results = _fetch('entity_info', params, app_token)

    schools = []
    seen = set()
    for r in results:
        en = r.get('entity_number', '')
        etype = (r.get('entity_type', '') or '').lower()
        if not en or en == str(district_entity_number) or en in seen:
            continue
        if 'school' in etype or 'nif' in etype:
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


# ══════════════════════════════════════════════════════════
# FRN DATA (from avi8-svp9, Recipient Details And Commitments)
# Confirmed fields: billed_entity_number, funding_request_number,
#   funding_year, chosen_category_of_service, dis_pct,
#   form_471_frn_status_name, form_471_status_name, spin_number,
#   spin_name, pre_discount_extended_eligible_line_item_costs,
#   original_allocation, ros_entity_number, ros_entity_name,
#   form_471_service_type_name, form_471_function_name
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
    funding_year_data = {}  # Collect discount rates per FY

    for r in results:
        frn = r.get('funding_request_number', '')
        fy = _safe_int(r.get('funding_year'))

        # Collect discount rate per funding year
        if fy and fy not in funding_year_data:
            discount = _safe_float(r.get('dis_pct'))
            if discount is not None:
                # dis_pct is 0.5 for 50% — convert to percentage
                discount_pct = int(discount * 100) if discount < 1 else int(discount)
                funding_year_data[fy] = {
                    'year': fy,
                    'discount_rate': discount_pct,
                    'enrollment': None,  # Not available in this dataset
                    'nslp_percentage': None,  # Not available in this dataset
                    'urban_rural': None,
                }

        if not frn or frn in frns:
            continue

        # Status
        status = r.get('form_471_frn_status_name', '') or r.get('form_471_status_name', '')
        category = _categorize(r.get('chosen_category_of_service', ''))
        service_desc = r.get('form_471_service_type_name', '')
        function_name = r.get('form_471_function_name', '')
        product = r.get('form_471_product_name', '')
        narrative_parts = [p for p in [service_desc, function_name, product] if p]

        frns[frn] = {
            'frn': frn,
            'funding_year': fy,
            'application_number': r.get('application_number', ''),
            'category': category,
            'service_type': service_desc,
            'status': status,
            'spin': r.get('spin_number', ''),
            'vendor_name': r.get('spin_name', ''),
            'amount_requested': _safe_float(r.get('pre_discount_extended_eligible_line_item_costs')),
            'amount_committed': _safe_float(r.get('original_allocation')),
            'discount_rate': _safe_float(r.get('dis_pct')),
            'narrative': ' — '.join(narrative_parts) if narrative_parts else '',
            'pending_reason': r.get('pending_reason', ''),
        }

    return list(frns.values()), funding_year_data


# ══════════════════════════════════════════════════════════
# FRN STATUS (qdmp-ygft)
# The filter field is NOT billed_entity_number. Let's discover it.
# We'll query by application_number instead, obtained from frn data.
# ══════════════════════════════════════════════════════════

def fetch_frn_status_by_app(application_numbers, app_token=None):
    """Fetch FRN status data by application numbers."""
    if not application_numbers:
        return {}

    # Query up to 20 application numbers at a time
    statuses = {}
    app_nums = list(set(application_numbers))[:50]

    for app_num in app_nums:
        params = {
            '$where': f"application_number='{app_num}'",
            '$limit': 100,
        }
        try:
            results = _fetch('frn_status', params, app_token)
            for r in results:
                frn = r.get('funding_request_number', '')
                if not frn or frn in statuses:
                    continue
                statuses[frn] = {
                    'frn': frn,
                    'status': r.get('funding_request_status', ''),
                    'committed_amount': _safe_float(r.get('funding_commitment_amount')),
                    'vendor_name': r.get('service_provider_name', ''),
                    'spin': r.get('service_provider_number', ''),
                    'contract_expiration': r.get('contract_expiration_date', ''),
                    'fcc_form_471_service_start_date': r.get('fcc_form_471_service_start_date', ''),
                }
        except USACImportError:
            continue

    return statuses


# ══════════════════════════════════════════════════════════
# C2 BUDGET (6brt-5pbv)
# Field is 'ben' not 'entity_number'
# ══════════════════════════════════════════════════════════

def fetch_c2_budget(entity_number, app_token=None):
    """Fetch Category 2 budget data."""
    # First try with 'ben' field (confirmed from error message)
    for field in ['ben', 'entity_number', 'billed_entity_number']:
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
            'entity_name': _get(r, 'billed_entity_name', 'organization_name',
                               'entity_name', default=''),
            'entity_number': _get(r, 'ben', 'entity_number', default=''),
            'budget_cycle': _get(r, 'budget_cycle', default=''),
            'c2_budget': _safe_float(_get(r, 'c2_budget', 'budget_amount',
                                         'c2_budget_total')),
            'budget_version': _get(r, 'budget_version', default=''),
        })

    return budgets


# ══════════════════════════════════════════════════════════
# FORM 470 (jp7a-89nd)
# Field might be different — try multiple
# ══════════════════════════════════════════════════════════

def fetch_form470_data(entity_number, app_token=None):
    """Fetch Form 470 filings."""
    for field in ['ben', 'billed_entity_number', 'entity_number']:
        params = {
            '$where': f"{field}='{entity_number}'",
            '$limit': 500,
            '$order': 'funding_year DESC',
        }
        try:
            results = _fetch('form470', params, app_token)
            if results:
                break
        except USACImportError:
            results = []

    forms = []
    seen = set()
    for r in results:
        app_num = _get(r, 'application_number', 'form_470_number', default='')
        if not app_num or app_num in seen:
            continue
        seen.add(app_num)

        forms.append({
            'application_number': app_num,
            'funding_year': _safe_int(r.get('funding_year')),
            'category': _categorize(_get(r, 'category_of_service',
                                        'chosen_category_of_service', default='')),
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

    # 3. FRN data (also yields funding year discount rates)
    app_numbers = set()
    try:
        frns, fy_from_frns = fetch_frn_data(entity_number, app_token=app_token)
        result['frns'] = frns

        # Collect application numbers for status lookup
        for frn in frns:
            if frn.get('application_number'):
                app_numbers.add(frn['application_number'])

        # Extract vendors
        for frn in frns:
            spin = frn.get('spin', '')
            if spin and spin not in result['vendors']:
                result['vendors'][spin] = {
                    'name': frn.get('vendor_name', ''),
                    'spin': spin,
                }

        # Build funding years from FRN data
        for fy_int, fy_data in fy_from_frns.items():
            result['funding_years'].append(fy_data)

        # Apply entity discount rates if we have them
        if result['entity']:
            dr_c1 = result['entity'].get('discount_rate_c1')
            if dr_c1 and result['funding_years']:
                # Apply to any FY missing discount rate
                for fy in result['funding_years']:
                    if not fy.get('discount_rate'):
                        fy['discount_rate'] = dr_c1

        result['funding_years'].sort(key=lambda x: x['year'], reverse=True)

    except USACImportError as e:
        result['errors'].append(f'FRN data: {str(e)}')

    # 4. FRN status — merge commitment amounts
    try:
        if app_numbers:
            status_data = fetch_frn_status_by_app(list(app_numbers), app_token)
            for frn in result['frns']:
                status = status_data.get(frn['frn'])
                if status:
                    if status.get('committed_amount') and not frn.get('amount_committed'):
                        frn['amount_committed'] = status['committed_amount']
                    if status.get('status'):
                        frn['usac_status'] = status['status']
                    spin = status.get('spin', '')
                    if spin and spin not in result['vendors']:
                        result['vendors'][spin] = {
                            'name': status.get('vendor_name', ''),
                            'spin': spin,
                        }
    except USACImportError as e:
        result['errors'].append(f'FRN status data: {str(e)}')

    # 5. C2 budget
    try:
        c2 = fetch_c2_budget(entity_number, app_token)
        result['c2_budgets'] = c2
    except USACImportError as e:
        result['errors'].append(f'C2 budget: {str(e)}')

    # 6. Form 470
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
