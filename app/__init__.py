import os
from flask import Flask, g, redirect, url_for, render_template, request, session
from .extensions import db, migrate, login_manager, csrf
from .config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Trust proxy headers (Cloudflare Tunnel sends CF-Connecting-IP / X-Forwarded-For)
    # ProxyFix rewrites request.remote_addr from X-Forwarded-For
    proxy_level = app.config.get('PROXY_TRUST_LEVEL', 1)
    if proxy_level > 0:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=proxy_level,
            x_proto=proxy_level,
            x_host=proxy_level,
            x_prefix=proxy_level,
        )

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        from .models.user import User
        return db.session.get(User, int(user_id))

    # Register blueprints
    from .auth.routes import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from .main.routes import main_bp
    app.register_blueprint(main_bp)

    from .erate.routes import erate_bp
    app.register_blueprint(erate_bp)

    from .admin.routes import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # Tenant middleware
    from .tenant.middleware import resolve_tenant

    @app.before_request
    def before_request():
        session.permanent = True
        resolve_tenant()

    # Security headers on every response
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # Prevent caching of auth pages (stale CSRF tokens)
        if request.path.startswith('/auth'):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
        return response

    # Context processor for templates
    @app.context_processor
    def inject_tenant():
        return dict(current_tenant=getattr(g, 'tenant', None))

    # Error handlers
    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    # CLI commands
    register_cli(app)

    return app


def register_cli(app):
    import click

    @app.cli.command('init-db')
    def init_db():
        """Create platform admin user."""
        from .models.user import User
        email = os.environ.get('PLATFORM_ADMIN_EMAIL', 'admin@example.com')
        password = os.environ.get('PLATFORM_ADMIN_PASSWORD', 'changeme')
        existing = User.query.filter_by(email=email, is_platform_admin=True).first()
        if existing:
            click.echo(f'Platform admin {email} already exists.')
            return
        user = User(
            email=email,
            display_name='Platform Admin',
            is_platform_admin=True,
            role='platform_admin',
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f'Created platform admin: {email}')

    @app.cli.command('seed-demo')
    def seed_demo():
        """Create demo tenant with sample data."""
        from .models.tenant import Tenant
        from .models.user import User
        from .models.erate import (FundingYear, C2Budget, C2Expenditure, School,
                                    Form470, Form471, Vendor, Contract,
                                    CalendarEvent, Invoice)
        from .models.document import Document
        from datetime import date, datetime, timedelta

        # Create demo tenant
        tenant = Tenant.query.filter_by(slug='demo').first()
        if tenant:
            click.echo('Demo tenant already exists.')
            return

        tenant = Tenant(
            slug='demo',
            name='Demo School District',
            primary_color='#1a73e8',
            is_active=True,
        )
        db.session.add(tenant)
        db.session.flush()

        # Create demo admin user
        admin_user = User(
            tenant_id=tenant.id,
            email='admin@demo.example.com',
            display_name='Demo Admin',
            role='district_admin',
        )
        admin_user.set_password('demo1234')
        db.session.add(admin_user)

        # Create schools
        schools = []
        for name, entity_num, sqft, bldg in [
            ('Demo Elementary', '100001', 45000, 1),
            ('Demo Middle School', '100002', 65000, 1),
            ('Demo High School', '100003', 95000, 2),
        ]:
            s = School(tenant_id=tenant.id, name=name, usac_entity_number=entity_num,
                      address='123 Main St', city='Anytown', state='CA', zip='90210',
                      is_active=True, square_footage=sqft, building_count=bldg)
            db.session.add(s)
            schools.append(s)
        db.session.flush()

        # Funding years
        fy25 = FundingYear(tenant_id=tenant.id, year=2025, nslp_percentage=65.0,
                           discount_rate=80, total_enrollment=2500, urban_rural='urban')
        fy26 = FundingYear(tenant_id=tenant.id, year=2026, nslp_percentage=65.0,
                           discount_rate=80, total_enrollment=2600, urban_rural='urban')
        db.session.add_all([fy25, fy26])
        db.session.flush()

        # C2 Budget
        c2 = C2Budget(tenant_id=tenant.id, cycle_start_year=2021, cycle_end_year=2025,
                      multiplier_per_student=167.0, funding_floor=25000.0,
                      total_enrollment=2500, calculated_budget=417500.0,
                      spent_to_date=285000.0)
        db.session.add(c2)
        db.session.flush()

        # C2 Expenditures
        for yr, amt, desc in [(2021, 75000, 'Network switches'), (2022, 80000, 'WAPs'),
                               (2023, 65000, 'Structured cabling'), (2024, 65000, 'Firewall')]:
            db.session.add(C2Expenditure(tenant_id=tenant.id, c2_budget_id=c2.id,
                                         funding_year=yr, amount_spent=amt, description=desc))

        # Vendor
        vendor = Vendor(tenant_id=tenant.id, name='Acme Network Solutions',
                       spin_number='143000001', contact_name='John Smith',
                       contact_email='john@acmenet.example.com', contact_phone='555-0100',
                       service_types=['C1', 'C2'])
        db.session.add(vendor)
        db.session.flush()

        # Form 470
        f470 = Form470(tenant_id=tenant.id, funding_year_id=fy25.id,
                       filing_date=date(2024, 10, 15), service_type='C2',
                       description='Cat 2 Internal Connections',
                       status='closed', bid_due_date=date(2024, 11, 12))
        db.session.add(f470)
        db.session.flush()

        # Form 471
        f471 = Form471(tenant_id=tenant.id, funding_year_id=fy25.id, form470_id=f470.id,
                       frn='2511234567', vendor_id=vendor.id, category='C2',
                       amount_requested=85000.0, amount_committed=85000.0,
                       status='committed', fcdl_date=date(2025, 6, 1))
        db.session.add(f471)
        db.session.flush()

        # Invoice
        db.session.add(Invoice(tenant_id=tenant.id, form471_id=f471.id,
                               invoice_type='BEAR_472', submitted_date=date(2025, 8, 1),
                               amount_claimed=85000.0, amount_reimbursed=68000.0,
                               status='partial'))

        # Contract
        db.session.add(Contract(tenant_id=tenant.id, vendor_id=vendor.id, form471_id=f471.id,
                                start_date=date(2024, 7, 1), end_date=date(2027, 6, 30),
                                auto_renews=True, renewal_notice_days=90,
                                description='3-year network equipment and installation'))

        # Calendar events
        today = date.today()
        events = [
            ('Form 471 Filing Deadline', 'deadline', today + timedelta(days=30), 'FY2026 Form 471 due'),
            ('FCDL Expected', 'milestone', today + timedelta(days=90), 'FY2025 FCDL expected'),
            ('Invoice Deadline', 'deadline', today + timedelta(days=120), 'FY2024 BEAR deadline'),
            ('Contract Renewal Review', 'reminder', today + timedelta(days=45), 'Review Acme contract renewal'),
            ('Admin Window Opens', 'deadline', today + timedelta(days=180), 'FY2027 Admin Window'),
        ]
        for title, etype, due, desc in events:
            db.session.add(CalendarEvent(tenant_id=tenant.id, title=title, event_type=etype,
                                         due_date=due, description=desc, is_recurring=False,
                                         is_complete=False))

        db.session.commit()
        click.echo('Demo tenant created with sample data. Login: admin@demo.example.com / demo1234')

    @app.cli.command('send-notifications')
    def send_notifications():
        """Send email notifications for all active tenants."""
        from .models.tenant import Tenant
        from .notifications.email import send_notifications_for_tenant
        tenants = Tenant.query.filter_by(is_active=True).all()
        total = 0
        for tenant in tenants:
            sent = send_notifications_for_tenant(tenant)
            if sent:
                click.echo(f'  {tenant.name}: {sent} email(s) sent')
                total += sent
        click.echo(f'Done. {total} total email(s) sent.')

    @app.cli.command('backup-all')
    def backup_all():
        """Create backups for all active tenants and store in R2/local."""
        from .models.tenant import Tenant
        from .backup.service import export_tenant_json, save_backup_to_storage
        from datetime import datetime as dt, timezone as tz
        tenants = Tenant.query.filter_by(is_active=True).all()
        for tenant in tenants:
            timestamp = dt.now(tz.utc).strftime('%Y%m%d_%H%M%S')
            filename = f'{tenant.slug}_backup_{timestamp}.json'
            try:
                backup_bytes = export_tenant_json(tenant.id)
                key = save_backup_to_storage(tenant, backup_bytes, filename)
                click.echo(f'  {tenant.name}: {filename} ({len(backup_bytes) / 1024:.1f} KB) -> {key}')
            except Exception as e:
                click.echo(f'  {tenant.name}: FAILED - {e}')
        click.echo('Backup complete.')
