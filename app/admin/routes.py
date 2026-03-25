from flask import (Blueprint, render_template, redirect, url_for, request,
                   flash, session, abort)
from flask_login import login_required, current_user
from app.extensions import db
from app.models.tenant import Tenant
from app.models.user import User
from app.models.erate import FundingYear, Form471, AuditLog
from functools import wraps

admin_bp = Blueprint('admin', __name__, template_folder='../templates/admin')


def platform_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_platform_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/')
@login_required
@platform_admin_required
def index():
    tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
    tenant_stats = []
    for t in tenants:
        user_count = User.query.filter_by(tenant_id=t.id).count()
        last_activity = AuditLog.query.filter_by(tenant_id=t.id).order_by(
            AuditLog.created_at.desc()).first()
        tenant_stats.append({
            'tenant': t,
            'user_count': user_count,
            'last_activity': last_activity.created_at if last_activity else None,
        })

    total_users = User.query.filter(User.tenant_id.isnot(None)).count()
    total_tenants = Tenant.query.count()
    active_tenants = Tenant.query.filter_by(is_active=True).count()

    return render_template('admin/index.html',
                           tenant_stats=tenant_stats,
                           total_users=total_users,
                           total_tenants=total_tenants,
                           active_tenants=active_tenants)


@admin_bp.route('/tenants/create', methods=['GET', 'POST'])
@login_required
@platform_admin_required
def create_tenant():
    if request.method == 'POST':
        slug = request.form.get('slug', '').strip().lower()
        name = request.form.get('name', '').strip()

        if not slug or not name:
            flash('Slug and name are required.', 'danger')
            return render_template('admin/create_tenant.html')

        if Tenant.query.filter_by(slug=slug).first():
            flash(f'Slug "{slug}" is already taken.', 'danger')
            return render_template('admin/create_tenant.html')

        tenant = Tenant(
            slug=slug,
            name=name,
            primary_color=request.form.get('primary_color', '#1a73e8'),
            is_active=True,
        )

        # OIDC config
        if request.form.get('azure_client_id'):
            tenant.azure_client_id = request.form['azure_client_id']
            tenant.azure_tenant_id = request.form.get('azure_tenant_id', '')
            tenant.azure_client_secret = request.form.get('azure_client_secret', '')
        if request.form.get('google_client_id'):
            tenant.google_client_id = request.form['google_client_id']
            tenant.google_client_secret = request.form.get('google_client_secret', '')

        db.session.add(tenant)
        db.session.flush()

        # Create first admin user if email provided
        admin_email = request.form.get('admin_email', '').strip()
        if admin_email:
            admin_user = User(
                tenant_id=tenant.id,
                email=admin_email,
                display_name=request.form.get('admin_name', 'District Admin'),
                role='district_admin',
            )
            admin_password = request.form.get('admin_password', '')
            if admin_password:
                admin_user.set_password(admin_password)
            db.session.add(admin_user)

        db.session.commit()
        flash(f'Tenant "{name}" created.', 'success')
        return redirect(url_for('admin.index'))

    return render_template('admin/create_tenant.html')


@admin_bp.route('/tenants/<int:tenant_id>/edit', methods=['GET', 'POST'])
@login_required
@platform_admin_required
def edit_tenant(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)

    if request.method == 'POST':
        tenant.name = request.form.get('name', tenant.name)
        tenant.primary_color = request.form.get('primary_color', tenant.primary_color)
        tenant.is_active = request.form.get('is_active') == 'on'

        if request.form.get('azure_client_id'):
            tenant.azure_client_id = request.form['azure_client_id']
            tenant.azure_tenant_id = request.form.get('azure_tenant_id', '')
        if request.form.get('azure_client_secret'):
            tenant.azure_client_secret = request.form['azure_client_secret']
        if request.form.get('google_client_id'):
            tenant.google_client_id = request.form['google_client_id']
        if request.form.get('google_client_secret'):
            tenant.google_client_secret = request.form['google_client_secret']

        db.session.commit()
        flash(f'Tenant "{tenant.name}" updated.', 'success')
        return redirect(url_for('admin.index'))

    users = User.query.filter_by(tenant_id=tenant.id).all()
    return render_template('admin/edit_tenant.html', tenant=tenant, users=users)


@admin_bp.route('/tenants/<int:tenant_id>/suspend', methods=['POST'])
@login_required
@platform_admin_required
def suspend_tenant(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    tenant.is_active = not tenant.is_active
    db.session.commit()
    status = 'activated' if tenant.is_active else 'suspended'
    flash(f'Tenant "{tenant.name}" {status}.', 'success')
    return redirect(url_for('admin.index'))


@admin_bp.route('/tenants/<int:tenant_id>/impersonate', methods=['POST'])
@login_required
@platform_admin_required
def impersonate_tenant(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    session['impersonating_tenant_id'] = tenant.id
    session['original_user_id'] = current_user.id
    flash(f'Now impersonating tenant: {tenant.name}', 'info')
    return redirect(url_for('main.dashboard', slug=tenant.slug))


@admin_bp.route('/stop-impersonating')
@login_required
def stop_impersonating():
    session.pop('impersonating_tenant_id', None)
    session.pop('original_user_id', None)
    flash('Stopped impersonating.', 'info')
    return redirect(url_for('admin.index'))


@admin_bp.route('/users')
@login_required
@platform_admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    tenants = Tenant.query.all()
    return render_template('admin/users.html', users=all_users, tenants=tenants)


@admin_bp.route('/users/<int:user_id>/edit', methods=['POST'])
@login_required
@platform_admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    user.role = request.form.get('role', user.role)
    user.display_name = request.form.get('display_name', user.display_name)
    if request.form.get('password'):
        user.set_password(request.form['password'])
    db.session.commit()
    flash(f'User "{user.email}" updated.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/create', methods=['POST'])
@login_required
@platform_admin_required
def create_user():
    tenant_id = int(request.form.get('tenant_id', 0)) or None
    user = User(
        tenant_id=tenant_id,
        email=request.form.get('email', '').strip(),
        display_name=request.form.get('display_name', ''),
        role=request.form.get('role', 'readonly'),
        is_platform_admin=request.form.get('is_platform_admin') == 'on',
    )
    password = request.form.get('password', '')
    if password:
        user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f'User "{user.email}" created.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/funding-summary')
@login_required
@platform_admin_required
def funding_summary():
    """Cross-tenant funding summary stats."""
    tenants = Tenant.query.filter_by(is_active=True).all()
    summary = []
    for t in tenants:
        fy = FundingYear.query.filter_by(tenant_id=t.id).order_by(
            FundingYear.year.desc()).first()
        frns = Form471.query.filter_by(tenant_id=t.id).all()
        total_requested = sum(f.amount_requested or 0 for f in frns)
        total_committed = sum(f.amount_committed or 0 for f in frns)
        summary.append({
            'tenant': t,
            'current_fy': fy.year if fy else None,
            'discount_rate': fy.discount_rate if fy else None,
            'frn_count': len(frns),
            'total_requested': total_requested,
            'total_committed': total_committed,
        })
    return render_template('admin/funding_summary.html', summary=summary)
