from flask import g, request, abort
from flask_login import current_user


def resolve_tenant():
    """Resolve tenant from URL slug or subdomain. Sets g.tenant."""
    from flask import current_app
    from app.models.tenant import Tenant

    g.tenant = None
    g.tenant_slug = None

    # Skip tenant resolution for static files, auth, admin, and root
    path = request.path
    if path.startswith('/static') or path.startswith('/auth') or path.startswith('/admin') or path == '/':
        return

    # Subdomain tenancy
    if current_app.config.get('SUBDOMAIN_TENANCY'):
        host = request.host.split(':')[0]
        parts = host.split('.')
        if len(parts) >= 3:
            slug = parts[0]
            tenant = Tenant.query.filter_by(slug=slug, is_active=True).first()
            if tenant:
                g.tenant = tenant
                g.tenant_slug = slug
                return
            abort(404)
        return

    # Path-based tenancy: /t/<slug>/...
    if path.startswith('/t/'):
        parts = path.split('/')
        if len(parts) >= 3:
            slug = parts[2]
            tenant = Tenant.query.filter_by(slug=slug, is_active=True).first()
            if tenant:
                g.tenant = tenant
                g.tenant_slug = slug
                return
            abort(404)
