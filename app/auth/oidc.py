import msal
from authlib.integrations.flask_client import OAuth

oauth = OAuth()

GOOGLE_CONF_URL = 'https://accounts.google.com/.well-known/openid-configuration'


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


def register_google_oauth(app):
    """Register Google as an OAuth provider."""
    oauth.init_app(app)
    oauth.register(
        name='google',
        server_metadata_url=GOOGLE_CONF_URL,
        client_kwargs={'scope': 'openid email profile'},
    )


def get_google_redirect(tenant, redirect_uri):
    """Get Google OAuth redirect."""
    from flask import session
    # Store tenant-specific Google credentials in session for callback
    session['_google_client_id'] = tenant.google_client_id
    session['_google_client_secret'] = tenant.google_client_secret
    return oauth.google.authorize_redirect(redirect_uri)


def complete_google_auth():
    """Complete Google OAuth and return token with user info."""
    token = oauth.google.authorize_access_token()
    return token
