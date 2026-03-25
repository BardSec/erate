import msal
from authlib.integrations.flask_client import OAuth
from authlib.integrations.requests_client import OAuth2Session

oauth = OAuth()

GOOGLE_CONF_URL = 'https://accounts.google.com/.well-known/openid-configuration'
GOOGLE_AUTHORIZE_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
GOOGLE_JWKS_URI = 'https://www.googleapis.com/oauth2/v3/certs'


def get_msal_app(tenant):
    """Build MSAL ConfidentialClientApplication for a tenant."""
    authority = f'https://login.microsoftonline.com/{tenant.azure_tenant_id}'
    return msal.ConfidentialClientApplication(
        tenant.azure_client_id,
        authority=authority,
        client_credential=tenant.azure_client_secret,
    )


def get_microsoft_auth_url(tenant, redirect_uri):
    """Get Microsoft OIDC authorization URL."""
    app = get_msal_app(tenant)
    flow = app.initiate_auth_code_flow(
        scopes=['User.Read'],
        redirect_uri=redirect_uri,
    )
    return flow


def complete_microsoft_auth(tenant, flow, auth_response):
    """Complete the MSAL auth code flow."""
    app = get_msal_app(tenant)
    result = app.acquire_token_by_auth_code_flow(flow, auth_response)
    return result


def get_google_auth_url(tenant, redirect_uri):
    """Build Google OIDC authorization URL with tenant-specific credentials."""
    import secrets
    from flask import session

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    session['_google_oauth_state'] = state
    session['_google_oauth_nonce'] = nonce

    params = {
        'client_id': tenant.google_client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'nonce': nonce,
        'access_type': 'online',
        'prompt': 'select_account',
    }

    from urllib.parse import urlencode
    return f'{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}'


def complete_google_auth(tenant, code, redirect_uri):
    """Exchange Google auth code for tokens and return user info."""
    import requests as req

    # Exchange code for tokens
    token_response = req.post(GOOGLE_TOKEN_URL, data={
        'client_id': tenant.google_client_id,
        'client_secret': tenant.google_client_secret,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': redirect_uri,
    })

    if token_response.status_code != 200:
        raise Exception(f'Token exchange failed: {token_response.text}')

    tokens = token_response.json()
    if 'error' in tokens:
        raise Exception(f'Token error: {tokens.get("error_description", tokens["error"])}')

    # Fetch user info
    userinfo_response = req.get(GOOGLE_USERINFO_URL, headers={
        'Authorization': f'Bearer {tokens["access_token"]}',
    })

    if userinfo_response.status_code != 200:
        raise Exception(f'Failed to fetch user info: {userinfo_response.text}')

    return userinfo_response.json()
