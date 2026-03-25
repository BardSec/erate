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

    return render_template('main/dashboard.html',
                           tenant=tenant, slug=slug,
                           current_fy=current_fy,
                           c2_budget=c2_budget,
                           open_frns=open_frns,
                           upcoming_deadlines=upcoming_deadlines,
                           next_events=next_events,
                           doc_count=doc_count,
                           recent_activity=recent_activity,
                           today=today)


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
