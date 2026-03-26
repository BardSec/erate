import requests

URBAN_BASE = 'https://educationdata.urban.org/api/v1'
TIMEOUT = 30


class NCESImportError(Exception):
    pass


def _fetch(url, params=None):
    """Fetch data from the Urban Institute Education Data API."""
    try:
        resp = requests.get(url, params=params or {}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get('results', []) if isinstance(data, dict) else data
    except requests.exceptions.Timeout:
        raise NCESImportError('NCES API request timed out.')
    except requests.exceptions.ConnectionError:
        raise NCESImportError('Could not connect to NCES Education Data API.')
    except requests.exceptions.HTTPError as e:
        raise NCESImportError(f'NCES API error: {e.response.status_code}')
    except ValueError:
        raise NCESImportError('Invalid response from NCES API.')


def search_districts(name, state_fips=None):
    """Search for school districts by name.

    Uses the CCD directory endpoint.
    Returns list of dicts with leaid, lea_name, state, city, enrollment.
    """
    url = f'{URBAN_BASE}/school-districts/ccd/directory'

    # Try the most recent years first
    for year in [2022, 2021, 2020]:
        try:
            params = {'lea_name': name}
            if state_fips:
                params['fips'] = state_fips
            full_url = f'{url}/{year}/'
            results = _fetch(full_url, params)
            if results:
                districts = []
                seen = set()
                for r in results:
                    leaid = r.get('leaid', '')
                    if leaid in seen:
                        continue
                    seen.add(leaid)
                    districts.append({
                        'leaid': leaid,
                        'name': r.get('lea_name', ''),
                        'state': r.get('state_name', ''),
                        'state_fips': r.get('fips', ''),
                        'city': r.get('city_location', ''),
                        'enrollment': r.get('enrollment', None),
                        'year': year,
                    })
                return districts
        except NCESImportError:
            continue

    return []


def fetch_district_enrollment(leaid):
    """Fetch enrollment data for a district across available years.

    Returns list of dicts with year, enrollment, free_lunch, reduced_lunch.
    """
    results_by_year = []

    for year in range(2022, 2014, -1):
        url = f'{URBAN_BASE}/school-districts/ccd/enrollment/{year}/'
        params = {'leaid': leaid}
        try:
            results = _fetch(url, params)
            if results:
                # Aggregate across grade levels
                total_enrollment = 0
                for r in results:
                    enr = r.get('enrollment', 0)
                    if enr and isinstance(enr, (int, float)):
                        total_enrollment += int(enr)

                if total_enrollment > 0:
                    results_by_year.append({
                        'year': year,
                        'enrollment': total_enrollment,
                    })
        except NCESImportError:
            continue

    return results_by_year


def fetch_school_data(leaid):
    """Fetch individual school data for a district including enrollment and lunch counts.

    Uses the schools/ccd/directory endpoint which has enrollment and lunch data.
    """
    schools = []

    for year in [2022, 2021, 2020]:
        url = f'{URBAN_BASE}/schools/ccd/directory/{year}/'
        params = {'leaid': leaid}
        try:
            results = _fetch(url, params)
            if results:
                seen = set()
                for r in results:
                    ncessch = r.get('ncessch', '')
                    if ncessch in seen:
                        continue
                    seen.add(ncessch)

                    enrollment = r.get('enrollment', None)
                    free_lunch = r.get('free_lunch', None) or r.get('free_or_reduced_price_lunch', None)
                    reduced_lunch = r.get('reduced_price_lunch', None)

                    # Calculate total NSLP
                    nslp = None
                    if free_lunch is not None:
                        nslp = int(free_lunch)
                        if reduced_lunch is not None:
                            nslp += int(reduced_lunch)

                    schools.append({
                        'ncessch': ncessch,
                        'name': r.get('school_name', ''),
                        'city': r.get('city_location', ''),
                        'state': r.get('state_name', ''),
                        'enrollment': int(enrollment) if enrollment else None,
                        'free_lunch': int(free_lunch) if free_lunch else None,
                        'reduced_lunch': int(reduced_lunch) if reduced_lunch else None,
                        'nslp_count': nslp,
                        'year': year,
                    })
                return schools
        except NCESImportError:
            continue

    return schools


def fetch_all(leaid):
    """Fetch all NCES data for a district.

    Returns dict with district info, schools with enrollment/NSLP data.
    """
    result = {
        'district': None,
        'schools': [],
        'enrollment_history': [],
        'errors': [],
    }

    # District info
    try:
        for year in [2022, 2021, 2020]:
            url = f'{URBAN_BASE}/school-districts/ccd/directory/{year}/'
            params = {'leaid': leaid}
            data = _fetch(url, params)
            if data:
                d = data[0]
                result['district'] = {
                    'leaid': d.get('leaid', ''),
                    'name': d.get('lea_name', ''),
                    'city': d.get('city_location', ''),
                    'state': d.get('state_name', ''),
                    'enrollment': d.get('enrollment'),
                    'year': year,
                }
                break
    except NCESImportError as e:
        result['errors'].append(f'District info: {str(e)}')

    # Schools with enrollment
    try:
        result['schools'] = fetch_school_data(leaid)
    except NCESImportError as e:
        result['errors'].append(f'School data: {str(e)}')

    # Enrollment history
    try:
        result['enrollment_history'] = fetch_district_enrollment(leaid)
    except NCESImportError as e:
        result['errors'].append(f'Enrollment history: {str(e)}')

    return result


# US State FIPS codes for filtering
STATE_FIPS = {
    'AL': 1, 'AK': 2, 'AZ': 4, 'AR': 5, 'CA': 6, 'CO': 8, 'CT': 9,
    'DE': 10, 'DC': 11, 'FL': 12, 'GA': 13, 'HI': 15, 'ID': 16, 'IL': 17,
    'IN': 18, 'IA': 19, 'KS': 20, 'KY': 21, 'LA': 22, 'ME': 23, 'MD': 24,
    'MA': 25, 'MI': 26, 'MN': 27, 'MS': 28, 'MO': 29, 'MT': 30, 'NE': 31,
    'NV': 32, 'NH': 33, 'NJ': 34, 'NM': 35, 'NY': 36, 'NC': 37, 'ND': 38,
    'OH': 39, 'OK': 40, 'OR': 41, 'PA': 42, 'RI': 44, 'SC': 45, 'SD': 46,
    'TN': 47, 'TX': 48, 'UT': 49, 'VT': 50, 'VA': 51, 'WA': 53, 'WV': 54,
    'WI': 55, 'WY': 56,
}
