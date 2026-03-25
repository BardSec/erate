from flask import (Blueprint, render_template, redirect, url_for, request,
                   flash, session, g, current_app, abort)
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models.user import User
from app.models.tenant import Tenant
from app.models.erate import AuditLog
from datetime import datetime, timezone

auth_bp = Blueprint('auth', __name__, template_folder='../templates/auth')


@auth_bp.route('/login')
@auth_bp.route('/login/<slug>')
def login(slug=None):
    if current_user.is_authenticated:
        if current_user.is_platform_admin:
            return redirect(url_for('admin.index'))
        if current_user.tenant:
            return redirect(url_for('main.dashboard', slug=current_user.tenant.slug))
        return redirect('/')

    tenant = None
    if slug:
        tenant = Tenant.query.filter_by(slug=slug, is_active=True).first_or_404()

    allow_local = current_app.config.get('ALLOW_LOCAL_AUTH', False)
    return render_template('auth/login.html', tenant=tenant, slug=slug, allow_local=allow_local)


@auth_bp.route('/login/<slug>/local', methods=['POST'])
def local_login(slug):
    if not current_app.config.get('ALLOW_LOCAL_AUTH', False):
        abort(403)

    tenant = Tenant.query.filter_by(slug=slug, is_active=True).first_or_404()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')

    user = User.query.filter_by(tenant_id=tenant.id, email=email).first()
    if user and user.check_password(password):
        user.last_login = datetime.now(timezone.utc)
        db.session.commit()
        login_user(user)
        _log_audit(tenant.id, user.id, 'login', 'user', user.id, {'method': 'local'})
        if user.is_pending:
            return redirect(url_for('auth.pending_approval', slug=slug))
        flash('Logged in successfully.', 'success')
        return redirect(url_for('main.dashboard', slug=slug))

    flash('Invalid email or password.', 'danger')
    return redirect(url_for('auth.login', slug=slug))


@auth_bp.route('/login/admin', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and current_user.is_platform_admin:
        return redirect(url_for('admin.index'))

    if request.method == 'POST':
        if not current_app.config.get('ALLOW_LOCAL_AUTH', False):
            abort(403)
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email, is_platform_admin=True).first()
        if user and user.check_password(password):
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            login_user(user)
            flash('Logged in as platform admin.', 'success')
            return redirect(url_for('admin.index'))
        flash('Invalid credentials.', 'danger')

    allow_local = current_app.config.get('ALLOW_LOCAL_AUTH', False)
    return render_template('auth/admin_login.html', allow_local=allow_local)


@auth_bp.route('/callback/microsoft/<slug>')
def microsoft_callback(slug):
    tenant = Tenant.query.filter_by(slug=slug, is_active=True).first_or_404()
    flow = session.pop('_ms_auth_flow', None)
    if not flow:
        flash('Authentication session expired.', 'danger')
        return redirect(url_for('auth.login', slug=slug))

    from .oidc import complete_microsoft_auth
    result = complete_microsoft_auth(tenant, flow, request.args)

    if 'error' in result:
        flash(f'Authentication failed: {result.get("error_description", "Unknown error")}', 'danger')
        return redirect(url_for('auth.login', slug=slug))

    claims = result.get('id_token_claims', {})
    email = claims.get('preferred_username') or claims.get('email', '')
    name = claims.get('name', email)

    user = _find_or_create_user(tenant, email, name)
    login_user(user)
    _log_audit(tenant.id, user.id, 'login', 'user', user.id, {'method': 'microsoft'})
    if user.is_pending:
        return redirect(url_for('auth.pending_approval', slug=slug))
    flash('Logged in successfully.', 'success')
    return redirect(url_for('main.dashboard', slug=slug))


@auth_bp.route('/login/<slug>/microsoft')
def microsoft_login(slug):
    tenant = Tenant.query.filter_by(slug=slug, is_active=True).first_or_404()
    if not tenant.azure_client_id:
        flash('Microsoft SSO is not configured for this district.', 'warning')
        return redirect(url_for('auth.login', slug=slug))

    from .oidc import get_microsoft_auth_url
    redirect_uri = url_for('auth.microsoft_callback', slug=slug, _external=True)
    flow = get_microsoft_auth_url(tenant, redirect_uri)
    session['_ms_auth_flow'] = flow
    return redirect(flow['auth_uri'])


@auth_bp.route('/login/<slug>/google')
def google_login(slug):
    tenant = Tenant.query.filter_by(slug=slug, is_active=True).first_or_404()
    if not tenant.google_client_id:
        flash('Google SSO is not configured for this district.', 'warning')
        return redirect(url_for('auth.login', slug=slug))

    from .oidc import get_google_auth_url
    redirect_uri = url_for('auth.google_callback', slug=slug, _external=True)
    auth_url = get_google_auth_url(tenant, redirect_uri)
    return redirect(auth_url)


@auth_bp.route('/callback/google/<slug>')
def google_callback(slug):
    tenant = Tenant.query.filter_by(slug=slug, is_active=True).first_or_404()

    # Verify state
    expected_state = session.pop('_google_oauth_state', None)
    received_state = request.args.get('state')
    if not expected_state or expected_state != received_state:
        flash('Invalid authentication state. Please try again.', 'danger')
        return redirect(url_for('auth.login', slug=slug))

    code = request.args.get('code')
    if not code:
        error = request.args.get('error', 'Unknown error')
        flash(f'Google authentication failed: {error}', 'danger')
        return redirect(url_for('auth.login', slug=slug))

    from .oidc import complete_google_auth
    try:
        redirect_uri = url_for('auth.google_callback', slug=slug, _external=True)
        userinfo = complete_google_auth(tenant, code, redirect_uri)
    except Exception as e:
        flash(f'Google authentication failed: {str(e)}', 'danger')
        return redirect(url_for('auth.login', slug=slug))

    email = userinfo.get('email', '')
    name = userinfo.get('name', email)

    user = _find_or_create_user(tenant, email, name)
    login_user(user)
    _log_audit(tenant.id, user.id, 'login', 'user', user.id, {'method': 'google'})
    if user.is_pending:
        return redirect(url_for('auth.pending_approval', slug=slug))
    flash('Logged in successfully.', 'success')
    return redirect(url_for('main.dashboard', slug=slug))


@auth_bp.route('/pending/<slug>')
@login_required
def pending_approval(slug):
    tenant = Tenant.query.filter_by(slug=slug, is_active=True).first_or_404()
    # If user has been approved since last check, send them to dashboard
    if not current_user.is_pending:
        return redirect(url_for('main.dashboard', slug=slug))
    # Find district admin(s) to display contact info
    admins = User.query.filter_by(tenant_id=tenant.id, role='district_admin').all()
    return render_template('auth/pending.html', tenant=tenant, slug=slug, admins=admins)


@auth_bp.route('/logout')
@login_required
def logout():
    slug = None
    if current_user.tenant:
        slug = current_user.tenant.slug
    logout_user()
    session.clear()
    flash('You have been logged out.', 'info')
    if slug:
        return redirect(url_for('auth.login', slug=slug))
    return redirect('/')


def _find_or_create_user(tenant, email, display_name):
    user = User.query.filter_by(tenant_id=tenant.id, email=email).first()
    if not user:
        # First user in the tenant becomes district_admin, rest are pending approval
        existing_count = User.query.filter_by(tenant_id=tenant.id).filter(
            User.role != 'pending').count()
        role = 'district_admin' if existing_count == 0 else 'pending'
        user = User(
            tenant_id=tenant.id,
            email=email,
            display_name=display_name,
            role=role,
        )
        db.session.add(user)
        db.session.flush()
        # Notify district admins of new pending user
        if role == 'pending':
            try:
                from app.notifications.email import send_pending_user_notification
                admins = User.query.filter_by(tenant_id=tenant.id, role='district_admin').all()
                for admin in admins:
                    send_pending_user_notification(admin, user, tenant)
            except Exception:
                pass  # Don't block login if email fails
    user.last_login = datetime.now(timezone.utc)
    if display_name and display_name != user.display_name:
        user.display_name = display_name
    db.session.commit()
    return user


def _log_audit(tenant_id, user_id, action, entity_type, entity_id, detail=None):
    log = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail,
        ip_address=request.remote_addr,
    )
    db.session.add(log)
    db.session.commit()
