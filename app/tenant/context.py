from flask import g, abort


def require_tenant():
    """Abort 404 if no tenant resolved."""
    if not getattr(g, 'tenant', None):
        abort(404)
    return g.tenant


def get_tenant():
    """Return current tenant or None."""
    return getattr(g, 'tenant', None)
