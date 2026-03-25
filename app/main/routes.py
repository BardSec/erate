from flask import (Blueprint, render_template, redirect, url_for, request,
                   flash, g, abort, jsonify)
from flask_login import login_required, current_user
from app.extensions import db
from app.models.tenant import Tenant
from app.models.erate import (FundingYear, C2Budget, C2Expenditure, School,
                               Form470, Form471, Invoice, CalendarEvent,
                               AuditLog, Vendor, Contract, Appeal)
from app.models.document import Document
from app.tenant.context import require_tenant
from datetime import date, datetime, timedelta, timezone
from functools import wraps

main_bp = Blueprint('main', __name__, template_folder='../templates/main')


def tenant_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        slug = kwargs.get('slug')
        if not slug:
            abort(404)
        tenant = Tenant.query.filter_by(slug=slug, is_active=True).first_or_404()
        g.tenant = tenant
        if not current_user.is_platform_admin and current_user.tenant_id != tenant.id:
            abort(403)
        if current_user.is_pending:
            return redirect(url_for('auth.pending_approval', slug=slug))
        return f(*args, **kwargs)
    return decorated


@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_platform_admin:
            return redirect(url_for('admin.index'))
        if current_user.tenant:
            return redirect(url_for('main.dashboard', slug=current_user.tenant.slug))
    return render_template('main/index.html')


@main_bp.route('/t/<slug>/')
@login_required
@tenant_required
def dashboard(slug):
    tenant = g.tenant
    today = date.today()

    # Current funding year
    current_fy = FundingYear.query.filter_by(tenant_id=tenant.id).order_by(
        FundingYear.year.desc()).first()

    # C2 Budget
    c2_budget = C2Budget.query.filter_by(tenant_id=tenant.id).order_by(
        C2Budget.cycle_end_year.desc()).first()

    # Open FRNs
    open_frns = Form471.query.filter_by(tenant_id=tenant.id).filter(
        Form471.status.in_(['pending', 'committed', 'appealed'])).all()

    # Upcoming deadlines (next 30 days)
    upcoming_deadlines = CalendarEvent.query.filter_by(
        tenant_id=tenant.id, is_complete=False
    ).filter(
        CalendarEvent.due_date >= today,
        CalendarEvent.due_date <= today + timedelta(days=30)
    ).order_by(CalendarEvent.due_date).all()

    # Next 5 events
    next_events = CalendarEvent.query.filter_by(
        tenant_id=tenant.id, is_complete=False
    ).filter(CalendarEvent.due_date >= today).order_by(
        CalendarEvent.due_date).limit(5).all()

    # Document count
    doc_count = Document.query.filter_by(tenant_id=tenant.id).count()

    # Recent activity
    recent_activity = AuditLog.query.filter_by(tenant_id=tenant.id).order_by(
        AuditLog.created_at.desc()).limit(10).all()

    # Bandwidth calculator
    total_enrollment = current_fy.total_enrollment if current_fy else 0

    return render_template('main/dashboard.html',
                           tenant=tenant, slug=slug,
                           current_fy=current_fy,
                           c2_budget=c2_budget,
                           open_frns=open_frns,
                           upcoming_deadlines=upcoming_deadlines,
                           next_events=next_events,
                           doc_count=doc_count,
                           recent_activity=recent_activity,
                           today=today,
                           total_enrollment=total_enrollment)


# ── District Profile ──────────────────────────────────────
@main_bp.route('/t/<slug>/profile')
@login_required
@tenant_required
def profile(slug):
    tenant = g.tenant
    funding_years = FundingYear.query.filter_by(tenant_id=tenant.id).order_by(
        FundingYear.year.desc()).all()
    schools = School.query.filter_by(tenant_id=tenant.id, is_active=True).all()
    return render_template('main/profile.html', tenant=tenant, slug=slug,
                           funding_years=funding_years, schools=schools)


@main_bp.route('/t/<slug>/profile/funding-year', methods=['POST'])
@login_required
@tenant_required
def add_funding_year(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)

    year = int(request.form.get('year', 0))
    nslp = float(request.form.get('nslp_percentage', 0))
    enrollment = int(request.form.get('total_enrollment', 0))
    urban_rural = request.form.get('urban_rural', 'urban')
    discount = FundingYear.calculate_discount_rate(nslp, urban_rural)

    existing = FundingYear.query.filter_by(tenant_id=tenant.id, year=year).first()
    if existing:
        existing.nslp_percentage = nslp
        existing.discount_rate = discount
        existing.total_enrollment = enrollment
        existing.urban_rural = urban_rural
        existing.notes = request.form.get('notes', '')
        flash(f'Funding Year {year} updated.', 'success')
    else:
        fy = FundingYear(
            tenant_id=tenant.id, year=year, nslp_percentage=nslp,
            discount_rate=discount, total_enrollment=enrollment,
            urban_rural=urban_rural, notes=request.form.get('notes', ''),
        )
        db.session.add(fy)
        flash(f'Funding Year {year} added.', 'success')

    _audit('create_funding_year', 'FundingYear', None, {'year': year})
    db.session.commit()
    return redirect(url_for('main.profile', slug=slug))


@main_bp.route('/t/<slug>/profile/school', methods=['POST'])
@login_required
@tenant_required
def add_school(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)

    school = School(
        tenant_id=tenant.id,
        name=request.form.get('name', ''),
        usac_entity_number=request.form.get('usac_entity_number', ''),
        address=request.form.get('address', ''),
        city=request.form.get('city', ''),
        state=request.form.get('state', ''),
        zip=request.form.get('zip', ''),
        square_footage=int(request.form.get('square_footage', 0) or 0),
        building_count=int(request.form.get('building_count', 1) or 1),
        enrollment=int(request.form.get('enrollment', 0) or 0) or None,
        nslp_count=int(request.form.get('nslp_count', 0) or 0) or None,
    )
    db.session.add(school)
    _audit('create_school', 'School', None, {'name': school.name})
    db.session.commit()
    flash(f'School "{school.name}" added.', 'success')
    return redirect(url_for('main.profile', slug=slug))


@main_bp.route('/t/<slug>/profile/school/<int:school_id>/edit', methods=['POST'])
@login_required
@tenant_required
def edit_school(slug, school_id):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    school = School.query.filter_by(id=school_id, tenant_id=tenant.id).first_or_404()
    school.name = request.form.get('name', school.name)
    school.usac_entity_number = request.form.get('usac_entity_number', school.usac_entity_number)
    school.address = request.form.get('address', school.address)
    school.city = request.form.get('city', school.city)
    school.state = request.form.get('state', school.state)
    school.zip = request.form.get('zip', school.zip)
    school.square_footage = int(request.form.get('square_footage', 0) or 0)
    school.building_count = int(request.form.get('building_count', 1) or 1)
    school.enrollment = int(request.form.get('enrollment', 0) or 0) or None
    school.nslp_count = int(request.form.get('nslp_count', 0) or 0) or None
    _audit('update_school', 'School', school.id, {'name': school.name})
    db.session.commit()
    flash(f'School "{school.name}" updated.', 'success')
    return redirect(url_for('main.profile', slug=slug))


# ── Calendar ──────────────────────────────────────────────
@main_bp.route('/t/<slug>/calendar')
@login_required
@tenant_required
def calendar(slug):
    tenant = g.tenant
    view = request.args.get('view', 'month')
    filter_type = request.args.get('type', '')
    today = date.today()

    events_q = CalendarEvent.query.filter_by(tenant_id=tenant.id)
    if filter_type:
        events_q = events_q.filter_by(event_type=filter_type)

    events = events_q.order_by(CalendarEvent.due_date).all()

    # Build calendar data for monthly view
    year = int(request.args.get('year', today.year))
    month = int(request.args.get('month', today.month))

    import calendar as cal_module
    cal = cal_module.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(year, month)

    events_by_day = {}
    for evt in events:
        if evt.due_date.year == year and evt.due_date.month == month:
            events_by_day.setdefault(evt.due_date.day, []).append(evt)

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    import calendar as cal_mod
    month_name = cal_mod.month_name[month]

    return render_template('main/calendar.html', tenant=tenant, slug=slug,
                           events=events, view=view, filter_type=filter_type,
                           today=today, year=year, month=month,
                           month_name=month_name, month_days=month_days,
                           events_by_day=events_by_day,
                           prev_month=prev_month, prev_year=prev_year,
                           next_month=next_month, next_year=next_year)


@main_bp.route('/t/<slug>/calendar/populate-deadlines', methods=['POST'])
@login_required
@tenant_required
def populate_deadlines(slug):
    """Pre-populate standard E-rate deadlines for a funding year."""
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)

    fy_year = int(request.form.get('funding_year', 0))
    if not fy_year:
        flash('Please select a funding year.', 'warning')
        return redirect(url_for('main.calendar', slug=slug))

    # E-rate deadlines are based on the funding year.
    # FY2026 means the E-rate program year starting July 1, 2026.
    # The application cycle for FY2026 happens mostly during calendar year 2025-2026.
    # "FY year" = the year services are delivered.
    # Application activities happen in the year BEFORE the FY.
    app_year = fy_year - 1  # Year when most application activities occur

    standard_deadlines = [
        # Admin Window & Form 470 (year before FY)
        (date(app_year, 10, 1),
         f'FY{fy_year} Admin Window Opens',
         'deadline',
         f'EPC opens for FY{fy_year} profile updates. Verify discount rate, entity info, and contacts.'),

        (date(app_year, 10, 1),
         f'FY{fy_year} Form 470 Filing Opens',
         'deadline',
         f'Competitive bidding opens. File Form 470 to begin 28-day bid window.'),

        # Form 471 window (usually Jan–Mar of app_year+1, which is the FY year)
        (date(fy_year, 1, 15),
         f'FY{fy_year} Form 471 Window Opens',
         'milestone',
         f'Form 471 filing window typically opens mid-January. Check USAC for exact date.'),

        (date(fy_year, 3, 26),
         f'FY{fy_year} Form 471 Filing Deadline',
         'deadline',
         f'Typical deadline for FY{fy_year} Form 471 submissions. Verify exact date with USAC.'),

        # FCDL waves (summer of FY year)
        (date(fy_year, 6, 1),
         f'FY{fy_year} FCDL Wave 1 Expected',
         'milestone',
         f'First Funding Commitment Decision Letters typically issued in June.'),

        # Service delivery deadlines
        (date(fy_year + 1, 6, 30),
         f'FY{fy_year} Recurring Services Delivery Deadline',
         'deadline',
         f'All recurring (Category 1) services for FY{fy_year} must be delivered by this date.'),

        (date(fy_year + 1, 9, 30),
         f'FY{fy_year} Non-Recurring Services Delivery Deadline',
         'deadline',
         f'All non-recurring (Category 2) services for FY{fy_year} must be delivered by this date.'),

        # Invoice deadlines (120 days after service delivery)
        (date(fy_year + 1, 10, 28),
         f'FY{fy_year} BEAR Invoice Deadline (Recurring)',
         'deadline',
         f'Form 472 (BEAR) for FY{fy_year} recurring services due 120 days after service delivery deadline.'),

        (date(fy_year + 2, 1, 28),
         f'FY{fy_year} BEAR Invoice Deadline (Non-Recurring)',
         'deadline',
         f'Form 472 (BEAR) for FY{fy_year} non-recurring services due 120 days after service delivery deadline.'),

        # Document retention reminder
        (date(fy_year + 1, 7, 1),
         f'FY{fy_year} Document Retention Start',
         'reminder',
         f'Begin 10-year document retention period for FY{fy_year}. Retain all records until {fy_year + 11}.'),
    ]

    created = 0
    for due_date, title, event_type, description in standard_deadlines:
        # Skip if an event with the same title already exists for this tenant
        existing = CalendarEvent.query.filter_by(
            tenant_id=tenant.id, title=title).first()
        if existing:
            continue

        evt = CalendarEvent(
            tenant_id=tenant.id,
            title=title,
            event_type=event_type,
            due_date=due_date,
            description=description,
            is_recurring=False,
            is_complete=due_date < date.today(),
            created_by=current_user.id,
        )
        db.session.add(evt)
        created += 1

    if created:
        _audit('populate_deadlines', 'CalendarEvent', None,
               {'funding_year': fy_year, 'events_created': created})
        db.session.commit()
        flash(f'{created} standard E-rate deadlines added for FY{fy_year}.', 'success')
    else:
        flash(f'FY{fy_year} deadlines already exist.', 'info')

    return redirect(url_for('main.calendar', slug=slug))


@main_bp.route('/t/<slug>/calendar/add', methods=['POST'])
@login_required
@tenant_required
def add_event(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)

    evt = CalendarEvent(
        tenant_id=tenant.id,
        title=request.form.get('title', ''),
        event_type=request.form.get('event_type', 'custom'),
        due_date=datetime.strptime(request.form['due_date'], '%Y-%m-%d').date(),
        description=request.form.get('description', ''),
        is_recurring=request.form.get('is_recurring') == 'on',
        created_by=current_user.id,
    )
    db.session.add(evt)
    _audit('create_event', 'CalendarEvent', None, {'title': evt.title})
    db.session.commit()
    flash('Event added.', 'success')
    return redirect(url_for('main.calendar', slug=slug))


@main_bp.route('/t/<slug>/calendar/<int:event_id>/complete', methods=['POST'])
@login_required
@tenant_required
def complete_event(slug, event_id):
    tenant = g.tenant
    evt = CalendarEvent.query.filter_by(id=event_id, tenant_id=tenant.id).first_or_404()
    evt.is_complete = not evt.is_complete
    _audit('toggle_event', 'CalendarEvent', evt.id, {'complete': evt.is_complete})
    db.session.commit()
    flash('Event updated.', 'success')
    return redirect(url_for('main.calendar', slug=slug))


@main_bp.route('/t/<slug>/calendar/<int:event_id>/delete', methods=['POST'])
@login_required
@tenant_required
def delete_event(slug, event_id):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    evt = CalendarEvent.query.filter_by(id=event_id, tenant_id=tenant.id).first_or_404()
    db.session.delete(evt)
    _audit('delete_event', 'CalendarEvent', event_id, {'title': evt.title})
    db.session.commit()
    flash('Event deleted.', 'success')
    return redirect(url_for('main.calendar', slug=slug))


# ── Compliance / Audit Readiness ─────────────────────────
@main_bp.route('/t/<slug>/compliance')
@login_required
@tenant_required
def compliance(slug):
    tenant = g.tenant
    funding_years = FundingYear.query.filter_by(tenant_id=tenant.id).order_by(
        FundingYear.year.desc()).all()

    checklists = []
    for fy in funding_years:
        docs = Document.query.filter_by(tenant_id=tenant.id, funding_year=fy.year).all()
        doc_cats = {d.category for d in docs}
        form470s = Form470.query.filter_by(tenant_id=tenant.id, funding_year_id=fy.id).all()
        form471s = Form471.query.filter_by(tenant_id=tenant.id, funding_year_id=fy.id).all()
        invoices = []
        for f in form471s:
            invoices.extend(Invoice.query.filter_by(tenant_id=tenant.id, form471_id=f.id).all())
        contracts = Contract.query.filter_by(tenant_id=tenant.id).all()

        items = [
            ('Form 470 filed', len(form470s) > 0),
            ('Form 470 document on file', 'form470' in doc_cats),
            ('28-day bidding window respected', any(f.days_until_bid_close is not None and f.days_until_bid_close <= 0 for f in form470s) if form470s else False),
            ('Bid evaluation docs', 'bid_doc' in doc_cats),
            ('Form 471 filed', len(form471s) > 0),
            ('Form 471 document on file', 'form471' in doc_cats),
            ('FCDL on file', 'fcdl' in doc_cats),
            ('Contracts on file', 'contract' in doc_cats),
            ('Invoices on file', 'invoice' in doc_cats),
        ]
        complete = sum(1 for _, v in items if v)
        score = round(complete / len(items) * 100) if items else 0

        checklists.append({
            'year': fy.year,
            'items': items,
            'score': score,
        })

    # Red flag alerts
    alerts = []
    today = date.today()
    for c in Contract.query.filter_by(tenant_id=tenant.id).all():
        if c.end_date and c.end_date < today:
            alerts.append(('danger', f'Contract expired: {c.description or "Unnamed"} (ended {c.end_date})'))
        elif c.is_expiring_soon:
            alerts.append(('warning', f'Contract expiring soon: {c.description or "Unnamed"} ({c.days_until_expiry} days)'))

    overdue_events = CalendarEvent.query.filter_by(
        tenant_id=tenant.id, is_complete=False
    ).filter(CalendarEvent.due_date < today).all()
    for evt in overdue_events:
        alerts.append(('danger', f'Overdue deadline: {evt.title} (was due {evt.due_date})'))

    return render_template('main/compliance.html', tenant=tenant, slug=slug,
                           checklists=checklists, alerts=alerts, funding_years=funding_years,
                           today=today)


# ── Reports ──────────────────────────────────────────────
@main_bp.route('/t/<slug>/reports')
@login_required
@tenant_required
def reports(slug):
    tenant = g.tenant
    funding_years = FundingYear.query.filter_by(tenant_id=tenant.id).order_by(
        FundingYear.year.desc()).all()
    return render_template('main/reports.html', tenant=tenant, slug=slug,
                           funding_years=funding_years)


@main_bp.route('/t/<slug>/reports/annual/<int:fy_id>')
@login_required
@tenant_required
def report_annual(slug, fy_id):
    from app.reports.pdf import generate_annual_summary
    tenant = g.tenant
    fy = FundingYear.query.filter_by(id=fy_id, tenant_id=tenant.id).first_or_404()
    form471s = Form471.query.filter_by(tenant_id=tenant.id, funding_year_id=fy.id).all()
    c2_budget = C2Budget.query.filter_by(tenant_id=tenant.id).order_by(C2Budget.cycle_end_year.desc()).first()
    invoices = []
    for f in form471s:
        invoices.extend(Invoice.query.filter_by(tenant_id=tenant.id, form471_id=f.id).all())

    buf = generate_annual_summary(tenant, fy, form471s, c2_budget, invoices)
    from flask import send_file
    return send_file(buf, mimetype='application/pdf',
                     download_name=f'erate_summary_fy{fy.year}.pdf', as_attachment=True)


@main_bp.route('/t/<slug>/reports/deadlines')
@login_required
@tenant_required
def report_deadlines(slug):
    from app.reports.pdf import generate_deadline_report
    tenant = g.tenant
    events = CalendarEvent.query.filter_by(tenant_id=tenant.id).order_by(CalendarEvent.due_date).all()
    buf = generate_deadline_report(tenant, events)
    from flask import send_file
    return send_file(buf, mimetype='application/pdf',
                     download_name='deadlines.pdf', as_attachment=True)


@main_bp.route('/t/<slug>/reports/documents')
@login_required
@tenant_required
def report_documents(slug):
    from app.reports.pdf import generate_document_inventory
    tenant = g.tenant
    docs = Document.query.filter_by(tenant_id=tenant.id).order_by(Document.uploaded_at.desc()).all()
    buf = generate_document_inventory(tenant, docs)
    from flask import send_file
    return send_file(buf, mimetype='application/pdf',
                     download_name='document_inventory.pdf', as_attachment=True)


@main_bp.route('/t/<slug>/reports/vendors')
@login_required
@tenant_required
def report_vendors(slug):
    from app.reports.pdf import generate_vendor_summary
    tenant = g.tenant
    vendors = Vendor.query.filter_by(tenant_id=tenant.id).all()
    contracts = Contract.query.filter_by(tenant_id=tenant.id).all()
    buf = generate_vendor_summary(tenant, vendors, contracts)
    from flask import send_file
    return send_file(buf, mimetype='application/pdf',
                     download_name='vendor_summary.pdf', as_attachment=True)


# ── User Management (District Admin) ─────────────────────
@main_bp.route('/t/<slug>/users')
@login_required
@tenant_required
def users(slug):
    tenant = g.tenant
    if not current_user.is_admin:
        abort(403)
    from app.models.user import User
    all_users = User.query.filter_by(tenant_id=tenant.id).order_by(User.created_at.desc()).all()
    pending_count = sum(1 for u in all_users if u.is_pending)
    return render_template('main/users.html', tenant=tenant, slug=slug,
                           users=all_users, pending_count=pending_count)


@main_bp.route('/t/<slug>/users/<int:user_id>/role', methods=['POST'])
@login_required
@tenant_required
def update_user_role(slug, user_id):
    tenant = g.tenant
    if not current_user.is_admin:
        abort(403)
    from app.models.user import User
    user = User.query.filter_by(id=user_id, tenant_id=tenant.id).first_or_404()
    old_role = user.role
    new_role = request.form.get('role', 'readonly')
    if new_role in ('district_admin', 'staff', 'readonly', 'consultant', 'pending'):
        user.role = new_role
        _audit('update_user_role', 'User', user.id,
               {'email': user.email, 'old_role': old_role, 'new_role': new_role})
        db.session.commit()
        flash(f'{user.display_name or user.email} updated to {new_role}.', 'success')
    return redirect(url_for('main.users', slug=slug))


@main_bp.route('/t/<slug>/activity')
@login_required
@tenant_required
def activity(slug):
    tenant = g.tenant
    if not current_user.is_admin:
        abort(403)
    page = request.args.get('page', 1, type=int)
    per_page = 50
    logs = AuditLog.query.filter_by(tenant_id=tenant.id).order_by(
        AuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    total = AuditLog.query.filter_by(tenant_id=tenant.id).count()
    has_next = total > page * per_page
    return render_template('main/activity.html', tenant=tenant, slug=slug,
                           logs=logs, page=page, has_next=has_next, total=total)


# ══════════════════════════════════════════════════════════
# BACKUP & RESTORE
# ══════════════════════════════════════════════════════════
@main_bp.route('/t/<slug>/backups')
@login_required
@tenant_required
def backups(slug):
    tenant = g.tenant
    if not current_user.is_admin:
        abort(403)
    from app.backup.service import list_backups
    backup_list = list_backups(tenant)
    return render_template('main/backups.html', tenant=tenant, slug=slug,
                           backups=backup_list)


@main_bp.route('/t/<slug>/backups/create', methods=['POST'])
@login_required
@tenant_required
def create_backup(slug):
    tenant = g.tenant
    if not current_user.is_admin:
        abort(403)

    from app.backup.service import export_tenant_json, save_backup_to_storage
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    filename = f'{tenant.slug}_backup_{timestamp}.json'

    try:
        backup_bytes = export_tenant_json(tenant.id)
        r2_key = save_backup_to_storage(tenant, backup_bytes, filename)
        _audit('create_backup', 'Backup', None, {
            'filename': filename,
            'size': len(backup_bytes),
            'key': r2_key,
        })
        db.session.commit()
        flash(f'Backup created: {filename} ({len(backup_bytes) / 1024:.1f} KB)', 'success')
    except Exception as e:
        flash(f'Backup failed: {str(e)}', 'danger')

    return redirect(url_for('main.backups', slug=slug))


@main_bp.route('/t/<slug>/backups/download/<filename>')
@login_required
@tenant_required
def download_backup(slug, filename):
    tenant = g.tenant
    if not current_user.is_admin:
        abort(403)

    from app.backup.service import download_backup as dl_backup
    data = dl_backup(tenant, filename)
    if not data:
        flash('Backup file not found.', 'danger')
        return redirect(url_for('main.backups', slug=slug))

    from flask import send_file
    buf = __import__('io').BytesIO(data)
    return send_file(buf, mimetype='application/json',
                     download_name=filename, as_attachment=True)


@main_bp.route('/t/<slug>/backups/restore', methods=['POST'])
@login_required
@tenant_required
def restore_backup(slug):
    tenant = g.tenant
    if not current_user.is_admin:
        abort(403)

    import json as json_mod
    from app.backup.service import restore_tenant_data, download_backup as dl_backup

    # Source: either uploaded file or existing backup
    source = request.form.get('source', 'upload')

    try:
        if source == 'existing':
            filename = request.form.get('filename', '')
            if not filename:
                flash('No backup selected.', 'warning')
                return redirect(url_for('main.backups', slug=slug))
            raw = dl_backup(tenant, filename)
            if not raw:
                flash('Backup file not found.', 'danger')
                return redirect(url_for('main.backups', slug=slug))
            backup_data = json_mod.loads(raw)
        else:
            file = request.files.get('backup_file')
            if not file or not file.filename:
                flash('No file uploaded.', 'warning')
                return redirect(url_for('main.backups', slug=slug))
            backup_data = json_mod.load(file)

        stats = restore_tenant_data(tenant.id, backup_data)

        _audit('restore_backup', 'Backup', None, {'source': source, 'stats': stats})
        db.session.commit()

        # Build summary
        parts = []
        for key, counts in stats.items():
            created = counts.get('created', 0)
            updated = counts.get('updated', 0)
            if created or updated:
                label = key.replace('_', ' ')
                bits = []
                if created:
                    bits.append(f'{created} created')
                if updated:
                    bits.append(f'{updated} updated')
                parts.append(f'{label}: {", ".join(bits)}')

        if parts:
            flash(f'Restore complete. {"; ".join(parts)}.', 'success')
        else:
            flash('Restore complete. No new data to import.', 'info')

    except json_mod.JSONDecodeError:
        flash('Invalid backup file — not valid JSON.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Restore failed: {str(e)}', 'danger')

    return redirect(url_for('main.backups', slug=slug))


# ══════════════════════════════════════════════════════════
# USAC DATA IMPORT
# ══════════════════════════════════════════════════════════
@main_bp.route('/t/<slug>/import', methods=['GET'])
@login_required
@tenant_required
def usac_import(slug):
    tenant = g.tenant
    if not current_user.is_admin:
        abort(403)
    return render_template('main/import.html', tenant=tenant, slug=slug)


@main_bp.route('/t/<slug>/import/search', methods=['POST'])
@login_required
@tenant_required
def usac_search(slug):
    tenant = g.tenant
    if not current_user.is_admin:
        abort(403)

    query = request.form.get('query', '').strip()
    state = request.form.get('state', '').strip()
    if not query:
        flash('Please enter a search term.', 'warning')
        return redirect(url_for('main.usac_import', slug=slug))

    from app.usac.importer import search_entities, USACImportError
    try:
        results = search_entities(query, state=state or None)
    except USACImportError as e:
        flash(f'USAC search failed: {str(e)}', 'danger')
        return redirect(url_for('main.usac_import', slug=slug))

    return render_template('main/import.html', tenant=tenant, slug=slug,
                           search_results=results, query=query, state=state)


@main_bp.route('/t/<slug>/import/debug/<entity_number>')
@login_required
@tenant_required
def usac_debug(slug, entity_number):
    """Show raw USAC API responses for debugging field names."""
    tenant = g.tenant
    if not current_user.is_admin:
        abort(403)

    from app.usac.importer import _fetch, USACImportError
    debug_data = {}

    # Fetch 1 record from each dataset to see actual field names
    datasets_to_check = {
        'entity_info': {'$where': f"entity_number='{entity_number}'", '$limit': 1},
        'form471_frn': {'$where': f"billed_entity_number='{entity_number}'", '$limit': 1},
        'frn_status': {'$where': f"billed_entity_number='{entity_number}'", '$limit': 1},
        'c2_budget': {'$where': f"entity_number='{entity_number}'", '$limit': 1},
        'form470': {'$where': f"billed_entity_number='{entity_number}'", '$limit': 1},
    }

    for dataset_key, params in datasets_to_check.items():
        try:
            results = _fetch(dataset_key, params)
            if results:
                debug_data[dataset_key] = {
                    'fields': sorted(results[0].keys()),
                    'sample': results[0],
                }
            else:
                debug_data[dataset_key] = {'fields': [], 'sample': None, 'note': 'No results'}
        except USACImportError as e:
            debug_data[dataset_key] = {'fields': [], 'sample': None, 'error': str(e)}

    return jsonify(debug_data)


@main_bp.route('/t/<slug>/import/preview/<entity_number>')
@login_required
@tenant_required
def usac_preview(slug, entity_number):
    tenant = g.tenant
    if not current_user.is_admin:
        abort(403)

    from app.usac.importer import import_all, USACImportError
    try:
        data = import_all(entity_number)
    except USACImportError as e:
        flash(f'USAC import failed: {str(e)}', 'danger')
        return redirect(url_for('main.usac_import', slug=slug))

    if data['errors']:
        for err in data['errors']:
            flash(f'Warning: {err}', 'warning')

    return render_template('main/import_preview.html', tenant=tenant, slug=slug,
                           data=data, entity_number=entity_number)


@main_bp.route('/t/<slug>/import/confirm', methods=['POST'])
@login_required
@tenant_required
def usac_confirm_import(slug):
    tenant = g.tenant
    if not current_user.is_admin:
        abort(403)

    entity_number = request.form.get('entity_number', '')
    from app.usac.importer import import_all, USACImportError

    try:
        data = import_all(entity_number)
    except USACImportError as e:
        flash(f'Import failed: {str(e)}', 'danger')
        return redirect(url_for('main.usac_import', slug=slug))

    imported = {'schools': 0, 'funding_years': 0, 'frns': 0, 'vendors': 0,
                'c2_budgets': 0, 'form470s': 0}
    updated = {'schools': 0, 'funding_years': 0, 'frns': 0, 'vendors': 0,
               'c2_budgets': 0, 'form470s': 0}

    # Import selections
    import_schools = request.form.get('import_schools') == 'on'
    import_fy = request.form.get('import_funding_years') == 'on'
    import_frns = request.form.get('import_frns') == 'on'
    import_vendors = request.form.get('import_vendors') == 'on'
    import_c2 = request.form.get('import_c2') == 'on'
    import_470 = request.form.get('import_form470s') == 'on'

    def _merge(obj, field, new_val):
        """Update a field if the new value is non-empty and the current is empty."""
        if new_val is not None and new_val != '' and new_val != 0:
            old_val = getattr(obj, field, None)
            if old_val is None or old_val == '' or old_val == 0:
                setattr(obj, field, new_val)
                return True
        return False

    # Import Schools
    if import_schools and data.get('schools'):
        for s_data in data['schools']:
            en = s_data.get('entity_number', '')
            existing = School.query.filter_by(
                tenant_id=tenant.id, usac_entity_number=en).first() if en else None
            if existing:
                changed = False
                changed |= _merge(existing, 'name', s_data.get('name'))
                changed |= _merge(existing, 'address', s_data.get('address'))
                changed |= _merge(existing, 'city', s_data.get('city'))
                changed |= _merge(existing, 'state', s_data.get('state'))
                changed |= _merge(existing, 'zip', s_data.get('zip'))
                changed |= _merge(existing, 'square_footage', s_data.get('square_footage'))
                if changed:
                    updated['schools'] += 1
            else:
                school = School(
                    tenant_id=tenant.id,
                    name=s_data.get('name', 'Unknown School'),
                    usac_entity_number=en,
                    address=s_data.get('address', ''),
                    city=s_data.get('city', ''),
                    state=s_data.get('state', ''),
                    zip=s_data.get('zip', ''),
                    is_active=True,
                    square_footage=s_data.get('square_footage'),
                    building_count=1,
                )
                db.session.add(school)
                imported['schools'] += 1

    # Import Funding Years
    if import_fy and data.get('funding_years'):
        for fy_data in data['funding_years']:
            year = fy_data.get('year')
            if not year:
                continue
            existing = FundingYear.query.filter_by(tenant_id=tenant.id, year=year).first()
            if existing:
                changed = False
                changed |= _merge(existing, 'nslp_percentage', fy_data.get('nslp_percentage'))
                changed |= _merge(existing, 'discount_rate', fy_data.get('discount_rate'))
                changed |= _merge(existing, 'total_enrollment', fy_data.get('enrollment'))
                changed |= _merge(existing, 'urban_rural', fy_data.get('urban_rural'))
                if changed:
                    updated['funding_years'] += 1
            else:
                fy = FundingYear(
                    tenant_id=tenant.id,
                    year=year,
                    nslp_percentage=fy_data.get('nslp_percentage'),
                    discount_rate=fy_data.get('discount_rate'),
                    total_enrollment=fy_data.get('enrollment'),
                    urban_rural=fy_data.get('urban_rural', 'urban'),
                )
                db.session.add(fy)
                imported['funding_years'] += 1

    db.session.flush()

    # Import Vendors
    vendor_map = {}  # spin -> vendor_id
    if import_vendors and data.get('vendors'):
        for spin, v_data in data['vendors'].items():
            existing = Vendor.query.filter_by(tenant_id=tenant.id, spin_number=spin).first()
            if existing:
                vendor_map[spin] = existing.id
                changed = _merge(existing, 'name', v_data.get('name'))
                if changed:
                    updated['vendors'] += 1
            else:
                vendor = Vendor(
                    tenant_id=tenant.id,
                    name=v_data.get('name', 'Unknown'),
                    spin_number=spin,
                    service_types=[],
                )
                db.session.add(vendor)
                db.session.flush()
                vendor_map[spin] = vendor.id
                imported['vendors'] += 1

    # Import FRNs (Form 471s)
    if import_frns:
        for frn_data in data.get('frns', []):
            frn_num = frn_data.get('frn', '')
            if not frn_num:
                continue

            year = frn_data.get('funding_year')
            fy = FundingYear.query.filter_by(tenant_id=tenant.id, year=year).first() if year else None
            committed_amount = frn_data.get('amount_committed', 0) or 0
            frn_status = frn_data.get('usac_status', '') or frn_data.get('status', 'pending')
            status = _map_frn_status(frn_status)
            spin = frn_data.get('spin', '')
            vendor_id = vendor_map.get(spin) if spin else None

            fcdl_date = None
            fcdl_date_str = frn_data.get('fcdl_date', '')
            if fcdl_date_str:
                try:
                    fcdl_date = datetime.fromisoformat(fcdl_date_str.replace('T', ' ').split('.')[0]).date()
                except (ValueError, AttributeError):
                    pass

            existing = Form471.query.filter_by(tenant_id=tenant.id, frn=frn_num).first()
            if existing:
                changed = False
                changed |= _merge(existing, 'funding_year_id', fy.id if fy else None)
                changed |= _merge(existing, 'vendor_id', vendor_id)
                changed |= _merge(existing, 'category', frn_data.get('category'))
                changed |= _merge(existing, 'amount_requested', frn_data.get('amount_requested', 0) or 0)
                changed |= _merge(existing, 'amount_committed', committed_amount)
                changed |= _merge(existing, 'fcdl_date', fcdl_date)
                changed |= _merge(existing, 'notes', f"Imported from USAC. {frn_data.get('narrative', '')}".strip())
                # Always update status if USAC has a more definitive one
                if status != 'pending' and existing.status == 'pending':
                    existing.status = status
                    changed = True
                if changed:
                    updated['frns'] += 1
            else:
                f471 = Form471(
                    tenant_id=tenant.id,
                    funding_year_id=fy.id if fy else None,
                    frn=frn_num,
                    vendor_id=vendor_id,
                    category=frn_data.get('category'),
                    amount_requested=frn_data.get('amount_requested', 0) or 0,
                    amount_committed=committed_amount,
                    status=status,
                    fcdl_date=fcdl_date,
                    notes=f"Imported from USAC. {frn_data.get('narrative', '')}".strip(),
                )
                db.session.add(f471)
                imported['frns'] += 1

    # Import C2 Budget
    if import_c2 and data.get('c2_budgets'):
        # Group by budget cycle
        cycles = {}
        for b_data in data['c2_budgets']:
            cycle_str = b_data.get('budget_cycle', '')
            budget_amount = b_data.get('c2_budget', 0) or 0
            version = (b_data.get('budget_version', '') or '').lower()

            # Parse cycle string (e.g., "FY2021-2025")
            if 'FY2021' in cycle_str or '2021' in cycle_str:
                cycle_key = (2021, 2025)
            elif 'FY2026' in cycle_str or '2026' in cycle_str:
                cycle_key = (2026, 2030)
            else:
                continue

            # Prefer 'confirmed' over 'preliminary' over 'forecast'
            version_priority = {'confirmed': 3, 'preliminary': 2, 'forecast': 1}
            priority = version_priority.get(version, 0)

            if cycle_key not in cycles or priority > cycles[cycle_key].get('_priority', 0):
                cycles[cycle_key] = {
                    'total': budget_amount,
                    '_priority': priority,
                }

        for (start, end), amounts in cycles.items():
            multiplier = 201.57 if start >= 2026 else 167.0
            floor = 30175.0 if start >= 2026 else 25000.0
            existing = C2Budget.query.filter_by(
                tenant_id=tenant.id, cycle_start_year=start, cycle_end_year=end).first()
            if existing:
                changed = _merge(existing, 'calculated_budget', amounts['total'])
                if changed:
                    updated['c2_budgets'] += 1
            elif amounts['total'] > 0:
                c2 = C2Budget(
                    tenant_id=tenant.id,
                    cycle_start_year=start,
                    cycle_end_year=end,
                    multiplier_per_student=multiplier,
                    funding_floor=floor,
                    calculated_budget=amounts['total'],
                    spent_to_date=0,
                )
                db.session.add(c2)
                imported['c2_budgets'] += 1

    # Import Form 470s
    if import_470 and data.get('form470s'):
        for f470_data in data['form470s']:
            year = f470_data.get('funding_year')
            fy = FundingYear.query.filter_by(tenant_id=tenant.id, year=year).first() if year else None

            # Check for existing by app number
            app_num = f470_data.get('application_number', '')

            filing_date = None
            contract_date_str = f470_data.get('allowable_contract_date', '')
            if contract_date_str:
                try:
                    from datetime import timedelta as td
                    contract_date = datetime.fromisoformat(
                        contract_date_str.replace('T', ' ').split('.')[0]).date()
                    filing_date = contract_date - td(days=28)
                except (ValueError, AttributeError):
                    pass

            f470 = Form470(
                tenant_id=tenant.id,
                funding_year_id=fy.id if fy else None,
                filing_date=filing_date,
                service_type=f470_data.get('category') or 'both',
                description=f'Form 470 #{app_num}' if app_num else 'Imported from USAC',
                status=f470_data.get('status', 'closed').lower() if f470_data.get('status') else 'closed',
                bid_due_date=None,
                notes=f'USAC Application #{app_num}' if app_num else '',
            )
            db.session.add(f470)
            imported['form470s'] += 1

    try:
        _audit('usac_import', 'Tenant', tenant.id, {
            'entity_number': entity_number,
            'imported': imported,
        })
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Import failed during save: {str(e)}', 'danger')
        return redirect(url_for('main.usac_import', slug=slug))

    total_new = sum(imported.values())
    total_updated = sum(updated.values())
    parts = []
    for key in ['schools', 'funding_years', 'frns', 'vendors', 'c2_budgets', 'form470s']:
        label = key.replace('_', ' ').replace('form470s', 'Form 470s').replace('c2 budgets', 'C2 budgets')
        n, u = imported[key], updated[key]
        if n and u:
            parts.append(f'{n} new + {u} updated {label}')
        elif n:
            parts.append(f'{n} new {label}')
        elif u:
            parts.append(f'{u} updated {label}')
    if total_new + total_updated > 0:
        flash(f'Import complete: {", ".join(parts)}.', 'success')
    else:
        flash('No new or updated records found — everything is already up to date.', 'info')
    return redirect(url_for('main.dashboard', slug=slug))


def _map_frn_status(usac_status):
    """Map USAC status strings to our internal status values."""
    if not usac_status:
        return 'pending'
    s = usac_status.lower()
    if 'committed' in s or 'funded' in s:
        return 'committed'
    if 'denied' in s or 'reject' in s:
        return 'denied'
    if 'appeal' in s:
        return 'appealed'
    if 'cancel' in s or 'withdrawn' in s:
        return 'cancelled'
    return 'pending'


# ── Audit helper ─────────────────────────────────────────
def _audit(action, entity_type, entity_id, detail=None):
    log = AuditLog(
        tenant_id=g.tenant.id,
        user_id=current_user.id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail,
        ip_address=request.remote_addr,
    )
    db.session.add(log)
