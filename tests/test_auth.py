from app.models.user import User
from app.models.tenant import Tenant


def test_login_page_loads(client, db):
    """Test that the login page loads for a tenant."""
    tenant = Tenant(slug='test', name='Test District', is_active=True)
    db.session.add(tenant)
    db.session.commit()

    resp = client.get('/auth/login/test')
    assert resp.status_code == 200
    assert b'Test District' in resp.data


def test_local_login(client, db, app):
    """Test local auth login flow."""
    app.config['ALLOW_LOCAL_AUTH'] = True

    tenant = Tenant(slug='test', name='Test District', is_active=True)
    db.session.add(tenant)
    db.session.flush()

    user = User(tenant_id=tenant.id, email='user@test.com',
                display_name='Test User', role='district_admin')
    user.set_password('password123')
    db.session.add(user)
    db.session.commit()

    resp = client.post('/auth/login/test/local', data={
        'email': 'user@test.com',
        'password': 'password123',
    }, follow_redirects=False)
    assert resp.status_code in (302, 303)


def test_invalid_login(client, db, app):
    """Test that invalid credentials are rejected."""
    app.config['ALLOW_LOCAL_AUTH'] = True

    tenant = Tenant(slug='test', name='Test District', is_active=True)
    db.session.add(tenant)
    db.session.commit()

    resp = client.post('/auth/login/test/local', data={
        'email': 'wrong@test.com',
        'password': 'wrong',
    }, follow_redirects=True)
    assert b'Invalid email or password' in resp.data


def test_logout(client, db):
    """Test logout redirects."""
    resp = client.get('/auth/logout', follow_redirects=False)
    assert resp.status_code in (302, 401)
