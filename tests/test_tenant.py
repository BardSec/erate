from app.models.tenant import Tenant


def test_tenant_resolution_path(client, db):
    """Test path-based tenant resolution."""
    tenant = Tenant(slug='demo', name='Demo District', is_active=True)
    db.session.add(tenant)
    db.session.commit()

    # Dashboard requires login, should redirect
    resp = client.get('/t/demo/')
    assert resp.status_code in (302, 401)


def test_invalid_tenant_slug(client, db):
    """Test that invalid slugs return 404."""
    resp = client.get('/t/nonexistent/')
    assert resp.status_code == 404


def test_tenant_isolation(db):
    """Test that tenants have separate data."""
    t1 = Tenant(slug='district-a', name='District A', is_active=True)
    t2 = Tenant(slug='district-b', name='District B', is_active=True)
    db.session.add_all([t1, t2])
    db.session.commit()

    assert t1.id != t2.id
    assert Tenant.query.filter_by(slug='district-a').first().name == 'District A'
    assert Tenant.query.filter_by(slug='district-b').first().name == 'District B'
