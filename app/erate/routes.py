import os
from flask import (Blueprint, render_template, redirect, url_for, request,
                   flash, g, abort, send_file, jsonify)
from flask_login import login_required, current_user
from app.extensions import db
from app.models.tenant import Tenant
from app.models.erate import (FundingYear, C2Budget, C2Expenditure, School,
                               Form470, Form471, Invoice, Appeal, Vendor,
                               Contract, CalendarEvent, AuditLog)
from app.models.document import Document
from app.documents.r2 import (upload_file, generate_r2_key,
                                get_presigned_download_url, delete_file,
                                get_local_file_path)
from datetime import date, datetime, timezone
from functools import wraps

erate_bp = Blueprint('erate', __name__, template_folder='../templates/erate')


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


# ══════════════════════════════════════════════════════════
# C2 BUDGET TRACKER
# ══════════════════════════════════════════════════════════
@erate_bp.route('/t/<slug>/c2-budget')
@login_required
@tenant_required
def c2_budget(slug):
    tenant = g.tenant
    budgets = C2Budget.query.filter_by(tenant_id=tenant.id).order_by(
        C2Budget.cycle_start_year.desc()).all()
    schools = School.query.filter_by(tenant_id=tenant.id, is_active=True).all()

    # "Use it or lose it" warning
    warnings = []
    today = date.today()
    for b in budgets:
        cycle_end = date(b.cycle_end_year, 6, 30)  # E-rate cycle typically ends June 30
        months_remaining = (cycle_end.year - today.year) * 12 + (cycle_end.month - today.month)
        if 0 < months_remaining <= 12 and b.percent_used < 80:
            warnings.append(f'Budget cycle {b.cycle_start_year}–{b.cycle_end_year} ends in '
                          f'{months_remaining} months with {100 - b.percent_used:.1f}% remaining!')

    return render_template('erate/c2_budget.html', tenant=tenant, slug=slug,
                           budgets=budgets, schools=schools, warnings=warnings)


@erate_bp.route('/t/<slug>/c2-budget/add', methods=['POST'])
@login_required
@tenant_required
def add_c2_budget(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)

    cycle_start = int(request.form.get('cycle_start_year', 0))
    cycle_end = int(request.form.get('cycle_end_year', 0))
    enrollment = int(request.form.get('total_enrollment', 0))
    num_schools = School.query.filter_by(tenant_id=tenant.id, is_active=True).count()

    # Determine multiplier/floor by cycle
    if cycle_start >= 2026:
        multiplier = 201.57
        floor = 30175.0
    else:
        multiplier = 167.0
        floor = 25000.0

    calculated = C2Budget.calculate_budget(enrollment, num_schools, multiplier, floor)

    budget = C2Budget(
        tenant_id=tenant.id,
        cycle_start_year=cycle_start,
        cycle_end_year=cycle_end,
        multiplier_per_student=multiplier,
        funding_floor=floor,
        total_enrollment=enrollment,
        calculated_budget=calculated,
        spent_to_date=0.0,
        notes=request.form.get('notes', ''),
    )
    db.session.add(budget)
    _audit('create_c2_budget', 'C2Budget', None,
           {'cycle': f'{cycle_start}-{cycle_end}', 'budget': calculated})
    db.session.commit()
    flash(f'C2 Budget created: ${calculated:,.2f}', 'success')
    return redirect(url_for('erate.c2_budget', slug=slug))


@erate_bp.route('/t/<slug>/c2-budget/<int:budget_id>/recalculate', methods=['POST'])
@login_required
@tenant_required
def recalculate_c2(slug, budget_id):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    budget = C2Budget.query.filter_by(id=budget_id, tenant_id=tenant.id).first_or_404()
    new_enrollment = int(request.form.get('total_enrollment', budget.total_enrollment))
    num_schools = School.query.filter_by(tenant_id=tenant.id, is_active=True).count()
    new_budget = C2Budget.calculate_budget(
        new_enrollment, num_schools, budget.multiplier_per_student, budget.funding_floor)
    if new_budget > budget.calculated_budget:
        budget.total_enrollment = new_enrollment
        budget.calculated_budget = new_budget
        _audit('recalculate_c2', 'C2Budget', budget.id,
               {'old_budget': budget.calculated_budget, 'new_budget': new_budget})
        db.session.commit()
        flash(f'Budget recalculated to ${new_budget:,.2f}', 'success')
    else:
        flash('New enrollment does not increase the budget.', 'warning')
    return redirect(url_for('erate.c2_budget', slug=slug))


@erate_bp.route('/t/<slug>/c2-budget/<int:budget_id>/expenditure', methods=['POST'])
@login_required
@tenant_required
def add_expenditure(slug, budget_id):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    budget = C2Budget.query.filter_by(id=budget_id, tenant_id=tenant.id).first_or_404()
    amount = float(request.form.get('amount_spent', 0))
    exp = C2Expenditure(
        tenant_id=tenant.id,
        c2_budget_id=budget.id,
        funding_year=int(request.form.get('funding_year', 0)),
        amount_spent=amount,
        description=request.form.get('description', ''),
    )
    db.session.add(exp)
    budget.spent_to_date = (budget.spent_to_date or 0) + amount
    _audit('add_expenditure', 'C2Expenditure', None, {'amount': amount})
    db.session.commit()
    flash(f'Expenditure of ${amount:,.2f} recorded.', 'success')
    return redirect(url_for('erate.c2_budget', slug=slug))


# ══════════════════════════════════════════════════════════
# APPLICATION TRACKER
# ══════════════════════════════════════════════════════════
@erate_bp.route('/t/<slug>/applications')
@login_required
@tenant_required
def applications(slug):
    tenant = g.tenant
    tab = request.args.get('tab', 'form470')
    form470s = Form470.query.filter_by(tenant_id=tenant.id).order_by(Form470.filing_date.desc()).all()
    form471s = Form471.query.filter_by(tenant_id=tenant.id).order_by(Form471.frn).all()
    invoices = Invoice.query.filter_by(tenant_id=tenant.id).all()
    appeals = Appeal.query.filter_by(tenant_id=tenant.id).all()
    funding_years = FundingYear.query.filter_by(tenant_id=tenant.id).order_by(FundingYear.year.desc()).all()
    vendors = Vendor.query.filter_by(tenant_id=tenant.id).all()
    return render_template('erate/applications.html', tenant=tenant, slug=slug, tab=tab,
                           form470s=form470s, form471s=form471s, invoices=invoices,
                           appeals=appeals, funding_years=funding_years, vendors=vendors)


@erate_bp.route('/t/<slug>/applications/form470/add', methods=['POST'])
@login_required
@tenant_required
def add_form470(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    filing_date = datetime.strptime(request.form['filing_date'], '%Y-%m-%d').date()
    bid_due = filing_date + __import__('datetime').timedelta(days=28)
    f470 = Form470(
        tenant_id=tenant.id,
        funding_year_id=int(request.form['funding_year_id']),
        filing_date=filing_date,
        service_type=request.form.get('service_type', 'C2'),
        description=request.form.get('description', ''),
        status='open',
        bid_due_date=bid_due,
        notes=request.form.get('notes', ''),
    )
    db.session.add(f470)
    _audit('create_form470', 'Form470', None, {'service_type': f470.service_type})
    db.session.commit()
    flash('Form 470 added. 28-day bidding window set.', 'success')
    return redirect(url_for('erate.applications', slug=slug, tab='form470'))


@erate_bp.route('/t/<slug>/applications/form471/add', methods=['POST'])
@login_required
@tenant_required
def add_form471(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    f471 = Form471(
        tenant_id=tenant.id,
        funding_year_id=int(request.form['funding_year_id']),
        form470_id=int(request.form.get('form470_id') or 0) or None,
        frn=request.form.get('frn', ''),
        vendor_id=int(request.form.get('vendor_id') or 0) or None,
        category=request.form.get('category', 'C2'),
        amount_requested=float(request.form.get('amount_requested', 0)),
        status='pending',
        notes=request.form.get('notes', ''),
    )
    db.session.add(f471)
    _audit('create_form471', 'Form471', None, {'frn': f471.frn})
    db.session.commit()
    flash(f'FRN {f471.frn} added.', 'success')
    return redirect(url_for('erate.applications', slug=slug, tab='form471'))


@erate_bp.route('/t/<slug>/applications/form471/<int:frn_id>/status', methods=['POST'])
@login_required
@tenant_required
def update_frn_status(slug, frn_id):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    f471 = Form471.query.filter_by(id=frn_id, tenant_id=tenant.id).first_or_404()
    old_status = f471.status
    f471.status = request.form.get('status', f471.status)
    # Log status change
    if old_status != f471.status:
        from app.models.erate import FRNStatusChange
        change = FRNStatusChange(
            tenant_id=tenant.id,
            form471_id=f471.id,
            old_status=old_status,
            new_status=f471.status,
            changed_by=current_user.id,
            notes=request.form.get('notes', ''),
        )
        db.session.add(change)
    f471.amount_committed = float(request.form.get('amount_committed', f471.amount_committed or 0))
    if request.form.get('fcdl_date'):
        f471.fcdl_date = datetime.strptime(request.form['fcdl_date'], '%Y-%m-%d').date()
    f471.notes = request.form.get('notes', f471.notes)
    _audit('update_form471', 'Form471', f471.id,
           {'old_status': old_status, 'new_status': f471.status})
    db.session.commit()
    flash(f'FRN {f471.frn} updated.', 'success')
    return redirect(url_for('erate.applications', slug=slug, tab='form471'))


@erate_bp.route('/t/<slug>/applications/form471/bulk-update', methods=['POST'])
@login_required
@tenant_required
def bulk_update_frn_status(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)

    frn_ids = request.form.getlist('frn_ids')
    new_status = request.form.get('bulk_status', '')
    fcdl_date_str = request.form.get('bulk_fcdl_date', '')
    notes = request.form.get('bulk_notes', '')

    if not frn_ids or not new_status:
        flash('Please select FRNs and a status.', 'warning')
        return redirect(url_for('erate.applications', slug=slug, tab='form471'))

    fcdl_date = None
    if fcdl_date_str:
        try:
            fcdl_date = datetime.strptime(fcdl_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    updated = 0
    from app.models.erate import FRNStatusChange
    for frn_id in frn_ids:
        f471 = Form471.query.filter_by(id=int(frn_id), tenant_id=tenant.id).first()
        if f471 and f471.status != new_status:
            old_status = f471.status
            f471.status = new_status
            if fcdl_date:
                f471.fcdl_date = fcdl_date
            if notes:
                f471.notes = (f471.notes or '') + f'\n{notes}'.strip()
            change = FRNStatusChange(
                tenant_id=tenant.id,
                form471_id=f471.id,
                old_status=old_status,
                new_status=new_status,
                changed_by=current_user.id,
                notes=notes,
            )
            db.session.add(change)
            updated += 1

    if updated:
        _audit('bulk_update_frn_status', 'Form471', None,
               {'count': updated, 'new_status': new_status})
        db.session.commit()
        flash(f'{updated} FRN(s) updated to {new_status}.', 'success')
    else:
        flash('No FRNs were updated.', 'info')

    return redirect(url_for('erate.applications', slug=slug, tab='form471'))


@erate_bp.route('/t/<slug>/applications/invoice/add', methods=['POST'])
@login_required
@tenant_required
def add_invoice(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    inv = Invoice(
        tenant_id=tenant.id,
        form471_id=int(request.form['form471_id']),
        invoice_type=request.form.get('invoice_type', 'BEAR_472'),
        submitted_date=datetime.strptime(request.form['submitted_date'], '%Y-%m-%d').date() if request.form.get('submitted_date') else None,
        amount_claimed=float(request.form.get('amount_claimed', 0)),
        status='pending',
        notes=request.form.get('notes', ''),
    )
    db.session.add(inv)
    _audit('create_invoice', 'Invoice', None, {'type': inv.invoice_type})
    db.session.commit()
    flash('Invoice added.', 'success')
    return redirect(url_for('erate.applications', slug=slug, tab='invoices'))


@erate_bp.route('/t/<slug>/applications/invoice/<int:inv_id>/update', methods=['POST'])
@login_required
@tenant_required
def update_invoice(slug, inv_id):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    inv = Invoice.query.filter_by(id=inv_id, tenant_id=tenant.id).first_or_404()
    inv.amount_reimbursed = float(request.form.get('amount_reimbursed', inv.amount_reimbursed or 0))
    inv.status = request.form.get('status', inv.status)
    inv.notes = request.form.get('notes', inv.notes)
    _audit('update_invoice', 'Invoice', inv.id, {'status': inv.status})
    db.session.commit()
    flash('Invoice updated.', 'success')
    return redirect(url_for('erate.applications', slug=slug, tab='invoices'))


@erate_bp.route('/t/<slug>/applications/appeal/add', methods=['POST'])
@login_required
@tenant_required
def add_appeal(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    appeal = Appeal(
        tenant_id=tenant.id,
        form471_id=int(request.form['form471_id']),
        filed_date=datetime.strptime(request.form['filed_date'], '%Y-%m-%d').date() if request.form.get('filed_date') else None,
        reason=request.form.get('reason', ''),
        status='pending',
        notes=request.form.get('notes', ''),
    )
    db.session.add(appeal)
    _audit('create_appeal', 'Appeal', None, {'frn_id': appeal.form471_id})
    db.session.commit()
    flash('Appeal filed.', 'success')
    return redirect(url_for('erate.applications', slug=slug, tab='appeals'))


# ══════════════════════════════════════════════════════════
# VENDOR & CONTRACT MANAGER
# ══════════════════════════════════════════════════════════
@erate_bp.route('/t/<slug>/vendors')
@login_required
@tenant_required
def vendors(slug):
    tenant = g.tenant
    vendors = Vendor.query.filter_by(tenant_id=tenant.id).all()
    contracts = Contract.query.filter_by(tenant_id=tenant.id).order_by(Contract.end_date).all()
    form471s = Form471.query.filter_by(tenant_id=tenant.id).all()
    expiring_soon = [c for c in contracts if c.is_expiring_soon]
    return render_template('erate/vendors.html', tenant=tenant, slug=slug,
                           vendors=vendors, contracts=contracts, form471s=form471s,
                           expiring_soon=expiring_soon)


@erate_bp.route('/t/<slug>/vendors/add', methods=['POST'])
@login_required
@tenant_required
def add_vendor(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    service_types = request.form.getlist('service_types')
    vendor = Vendor(
        tenant_id=tenant.id,
        name=request.form.get('name', ''),
        spin_number=request.form.get('spin_number', ''),
        contact_name=request.form.get('contact_name', ''),
        contact_email=request.form.get('contact_email', ''),
        contact_phone=request.form.get('contact_phone', ''),
        service_types=service_types,
        notes=request.form.get('notes', ''),
    )
    db.session.add(vendor)
    _audit('create_vendor', 'Vendor', None, {'name': vendor.name})
    db.session.commit()
    flash(f'Vendor "{vendor.name}" added.', 'success')
    return redirect(url_for('erate.vendors', slug=slug))


@erate_bp.route('/t/<slug>/vendors/<int:vendor_id>/edit', methods=['POST'])
@login_required
@tenant_required
def edit_vendor(slug, vendor_id):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    vendor = Vendor.query.filter_by(id=vendor_id, tenant_id=tenant.id).first_or_404()
    vendor.name = request.form.get('name', vendor.name)
    vendor.spin_number = request.form.get('spin_number', vendor.spin_number)
    vendor.contact_name = request.form.get('contact_name', vendor.contact_name)
    vendor.contact_email = request.form.get('contact_email', vendor.contact_email)
    vendor.contact_phone = request.form.get('contact_phone', vendor.contact_phone)
    vendor.service_types = request.form.getlist('service_types')
    vendor.notes = request.form.get('notes', vendor.notes)
    _audit('update_vendor', 'Vendor', vendor.id, {'name': vendor.name})
    db.session.commit()
    flash(f'Vendor "{vendor.name}" updated.', 'success')
    return redirect(url_for('erate.vendors', slug=slug))


@erate_bp.route('/t/<slug>/contracts/add', methods=['POST'])
@login_required
@tenant_required
def add_contract(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    contract = Contract(
        tenant_id=tenant.id,
        vendor_id=int(request.form['vendor_id']),
        form471_id=int(request.form.get('form471_id') or 0) or None,
        start_date=datetime.strptime(request.form['start_date'], '%Y-%m-%d').date() if request.form.get('start_date') else None,
        end_date=datetime.strptime(request.form['end_date'], '%Y-%m-%d').date() if request.form.get('end_date') else None,
        auto_renews=request.form.get('auto_renews') == 'on',
        renewal_notice_days=int(request.form.get('renewal_notice_days', 0) or 0),
        description=request.form.get('description', ''),
        notes=request.form.get('notes', ''),
    )
    db.session.add(contract)
    _audit('create_contract', 'Contract', None, {'vendor_id': contract.vendor_id})
    db.session.commit()
    flash('Contract added.', 'success')
    return redirect(url_for('erate.vendors', slug=slug))


# ══════════════════════════════════════════════════════════
# DOCUMENT REPOSITORY
# ══════════════════════════════════════════════════════════
@erate_bp.route('/t/<slug>/documents')
@login_required
@tenant_required
def documents(slug):
    tenant = g.tenant
    q = request.args.get('q', '')
    category = request.args.get('category', '')
    fy = request.args.get('funding_year', '')

    query = Document.query.filter_by(tenant_id=tenant.id)
    if q:
        query = query.filter(Document.original_filename.ilike(f'%{q}%'))
    if category:
        query = query.filter_by(category=category)
    if fy:
        query = query.filter_by(funding_year=int(fy))

    docs = query.order_by(Document.uploaded_at.desc()).all()
    funding_years = FundingYear.query.filter_by(tenant_id=tenant.id).order_by(
        FundingYear.year.desc()).all()

    # Document completeness checklist
    checklist = {}
    for fyear in funding_years:
        cats = {d.category for d in docs if d.funding_year == fyear.year}
        required = ['form470', 'form471', 'fcdl', 'contract', 'invoice']
        checklist[fyear.year] = {cat: cat in cats for cat in required}

    form471s = Form471.query.filter_by(tenant_id=tenant.id).all()

    return render_template('erate/documents.html', tenant=tenant, slug=slug,
                           documents=docs, funding_years=funding_years,
                           categories=Document.CATEGORIES, checklist=checklist,
                           q=q, filter_category=category, filter_fy=fy,
                           form471s=form471s)


@erate_bp.route('/t/<slug>/documents/upload', methods=['POST'])
@login_required
@tenant_required
def upload_document(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)

    files = request.files.getlist('files')
    if not files or not files[0].filename:
        flash('No files selected.', 'warning')
        return redirect(url_for('erate.documents', slug=slug))

    category = request.form.get('category', 'other')
    fy = request.form.get('funding_year')
    tags = [t.strip() for t in request.form.get('tags', '').split(',') if t.strip()]
    notes = request.form.get('notes', '')

    count = 0
    for f in files:
        if not f.filename:
            continue
        r2_key = generate_r2_key(tenant.id, category, f.filename)
        f.seek(0, 2)
        file_size = f.tell()
        f.seek(0)
        upload_file(f, r2_key, content_type=f.content_type or 'application/octet-stream')

        doc = Document(
            tenant_id=tenant.id,
            form471_id=int(request.form.get('form471_id') or 0) or None,
            uploaded_by=current_user.id,
            filename=os.path.basename(r2_key),
            original_filename=f.filename,
            r2_key=r2_key,
            file_size=file_size,
            mime_type=f.content_type,
            category=category,
            funding_year=int(fy) if fy else None,
            tags=tags,
            notes=notes,
        )
        db.session.add(doc)
        count += 1

    _audit('upload_documents', 'Document', None, {'count': count, 'category': category})
    db.session.commit()
    flash(f'{count} document(s) uploaded.', 'success')
    return redirect(url_for('erate.documents', slug=slug))


@erate_bp.route('/t/<slug>/documents/<int:doc_id>/download')
@login_required
@tenant_required
def download_document(slug, doc_id):
    tenant = g.tenant
    doc = Document.query.filter_by(id=doc_id, tenant_id=tenant.id).first_or_404()

    presigned = get_presigned_download_url(doc.r2_key)
    if presigned:
        return redirect(presigned)

    # Local fallback
    local_path = get_local_file_path(doc.r2_key)
    if os.path.exists(local_path):
        return send_file(local_path, download_name=doc.original_filename, as_attachment=True)

    flash('File not found.', 'danger')
    return redirect(url_for('erate.documents', slug=slug))


@erate_bp.route('/t/<slug>/documents/<int:doc_id>/delete', methods=['POST'])
@login_required
@tenant_required
def delete_document(slug, doc_id):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    doc = Document.query.filter_by(id=doc_id, tenant_id=tenant.id).first_or_404()
    delete_file(doc.r2_key)
    _audit('delete_document', 'Document', doc.id, {'filename': doc.original_filename})
    db.session.delete(doc)
    db.session.commit()
    flash('Document deleted.', 'success')
    return redirect(url_for('erate.documents', slug=slug))


@erate_bp.route('/t/<slug>/documents/download-all')
@login_required
@tenant_required
def download_all_documents(slug):
    """Download all documents (or filtered subset) as a zip file."""
    import zipfile
    from io import BytesIO

    tenant = g.tenant

    # Apply same filters as the document list
    q = request.args.get('q', '')
    category = request.args.get('category', '')
    fy = request.args.get('funding_year', '')

    query = Document.query.filter_by(tenant_id=tenant.id)
    if q:
        query = query.filter(Document.original_filename.ilike(f'%{q}%'))
    if category:
        query = query.filter_by(category=category)
    if fy:
        query = query.filter_by(funding_year=int(fy))

    docs = query.order_by(Document.uploaded_at.desc()).all()

    if not docs:
        flash('No documents to download.', 'warning')
        return redirect(url_for('erate.documents', slug=slug))

    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        seen_names = {}
        for doc in docs:
            # Organize by category/filename
            folder = doc.category or 'other'
            if doc.funding_year:
                folder = f'FY{doc.funding_year}/{folder}'
            filename = doc.original_filename

            # Handle duplicate filenames
            full_path = f'{folder}/{filename}'
            if full_path in seen_names:
                seen_names[full_path] += 1
                name, ext = os.path.splitext(filename)
                filename = f'{name}_{seen_names[full_path]}{ext}'
                full_path = f'{folder}/{filename}'
            else:
                seen_names[full_path] = 0

            # Try to get the file content
            file_data = _get_file_bytes(doc.r2_key)
            if file_data:
                zf.writestr(full_path, file_data)

    buf.seek(0)

    # Name the zip file
    zip_name = f'{tenant.slug}_documents'
    if category:
        zip_name += f'_{category}'
    if fy:
        zip_name += f'_FY{fy}'
    zip_name += '.zip'

    _audit('download_all_documents', 'Document', None,
           {'count': len(docs), 'category': category, 'funding_year': fy})
    db.session.commit()

    return send_file(buf, mimetype='application/zip',
                     download_name=zip_name, as_attachment=True)


def _get_file_bytes(r2_key):
    """Get file content as bytes from R2 or local storage."""
    import requests as req

    # Try presigned URL from R2
    presigned = get_presigned_download_url(r2_key)
    if presigned:
        try:
            resp = req.get(presigned, timeout=30)
            if resp.status_code == 200:
                return resp.content
        except Exception:
            pass

    # Try local filesystem
    local_path = get_local_file_path(r2_key)
    if os.path.exists(local_path):
        with open(local_path, 'rb') as f:
            return f.read()

    return None


# ══════════════════════════════════════════════════════════
# FORM 486 TRACKING
# ══════════════════════════════════════════════════════════
@erate_bp.route('/t/<slug>/form486')
@login_required
@tenant_required
def form486_list(slug):
    tenant = g.tenant
    from app.models.erate import Form486
    form486s = Form486.query.filter_by(tenant_id=tenant.id).order_by(Form486.funding_year.desc()).all()
    form471s = Form471.query.filter_by(tenant_id=tenant.id).all()
    return render_template('erate/form486.html', tenant=tenant, slug=slug,
                           form486s=form486s, form471s=form471s)


@erate_bp.route('/t/<slug>/form486/add', methods=['POST'])
@login_required
@tenant_required
def add_form486(slug):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    from app.models.erate import Form486
    f486 = Form486(
        tenant_id=tenant.id,
        form471_id=int(request.form.get('form471_id') or 0) or None,
        funding_year=int(request.form.get('funding_year') or 0) or None,
        service_start_date=datetime.strptime(request.form['service_start_date'], '%Y-%m-%d').date() if request.form.get('service_start_date') else None,
        filed_date=datetime.strptime(request.form['filed_date'], '%Y-%m-%d').date() if request.form.get('filed_date') else None,
        status=request.form.get('status', 'pending'),
        contact_email=request.form.get('contact_email', ''),
        notes=request.form.get('notes', ''),
    )
    db.session.add(f486)
    _audit('create_form486', 'Form486', None, {'funding_year': f486.funding_year})
    db.session.commit()
    flash('Form 486 added.', 'success')
    return redirect(url_for('erate.form486_list', slug=slug))


@erate_bp.route('/t/<slug>/form486/<int:f486_id>/update', methods=['POST'])
@login_required
@tenant_required
def update_form486(slug, f486_id):
    tenant = g.tenant
    if not current_user.can_write:
        abort(403)
    from app.models.erate import Form486
    f486 = Form486.query.filter_by(id=f486_id, tenant_id=tenant.id).first_or_404()
    f486.status = request.form.get('status', f486.status)
    f486.filed_date = datetime.strptime(request.form['filed_date'], '%Y-%m-%d').date() if request.form.get('filed_date') else f486.filed_date
    f486.notes = request.form.get('notes', f486.notes)
    _audit('update_form486', 'Form486', f486.id, {'status': f486.status})
    db.session.commit()
    flash('Form 486 updated.', 'success')
    return redirect(url_for('erate.form486_list', slug=slug))


# ══════════════════════════════════════════════════════════
# CSV EXPORTS
# ══════════════════════════════════════════════════════════
@erate_bp.route('/t/<slug>/export/frns.csv')
@login_required
@tenant_required
def export_frns_csv(slug):
    import csv
    from io import StringIO
    tenant = g.tenant
    frns = Form471.query.filter_by(tenant_id=tenant.id).order_by(Form471.frn).all()
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(['FRN', 'Funding Year', 'Category', 'Vendor', 'Amount Requested',
                     'Amount Committed', 'Status', 'FCDL Date', 'Notes'])
    for f in frns:
        fy = f.funding_year.year if f.funding_year else ''
        vendor = f.vendor.name if f.vendor else ''
        writer.writerow([f.frn, fy, f.category, vendor, f.amount_requested,
                        f.amount_committed, f.status, f.fcdl_date, f.notes])
    output = si.getvalue()
    from flask import Response
    return Response(output, mimetype='text/csv',
                   headers={'Content-Disposition': f'attachment; filename={slug}_frns.csv'})


@erate_bp.route('/t/<slug>/export/vendors.csv')
@login_required
@tenant_required
def export_vendors_csv(slug):
    import csv
    from io import StringIO
    tenant = g.tenant
    vendors_list = Vendor.query.filter_by(tenant_id=tenant.id).all()
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(['Name', 'SPIN Number', 'Contact Name', 'Contact Email', 'Contact Phone', 'Service Types', 'Notes'])
    for v in vendors_list:
        services = ', '.join(v.service_types) if v.service_types else ''
        writer.writerow([v.name, v.spin_number, v.contact_name, v.contact_email, v.contact_phone, services, v.notes])
    output = si.getvalue()
    from flask import Response
    return Response(output, mimetype='text/csv',
                   headers={'Content-Disposition': f'attachment; filename={slug}_vendors.csv'})


@erate_bp.route('/t/<slug>/export/schools.csv')
@login_required
@tenant_required
def export_schools_csv(slug):
    import csv
    from io import StringIO
    tenant = g.tenant
    schools = School.query.filter_by(tenant_id=tenant.id).all()
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(['Name', 'Entity Number', 'Address', 'City', 'State', 'ZIP',
                     'Enrollment', 'NSLP Count', 'Square Footage', 'Buildings'])
    for s in schools:
        writer.writerow([s.name, s.usac_entity_number, s.address, s.city, s.state, s.zip,
                        s.enrollment, s.nslp_count, s.square_footage, s.building_count])
    output = si.getvalue()
    from flask import Response
    return Response(output, mimetype='text/csv',
                   headers={'Content-Disposition': f'attachment; filename={slug}_schools.csv'})


@erate_bp.route('/t/<slug>/export/documents.csv')
@login_required
@tenant_required
def export_documents_csv(slug):
    import csv
    from io import StringIO
    tenant = g.tenant
    docs = Document.query.filter_by(tenant_id=tenant.id).order_by(Document.uploaded_at.desc()).all()
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(['Filename', 'Category', 'Funding Year', 'FRN', 'Size (bytes)', 'Uploaded By', 'Uploaded At', 'Tags', 'Notes'])
    for d in docs:
        uploader = d.uploader.display_name if d.uploader else ''
        frn = d.form471.frn if d.form471 else ''
        tags = ', '.join(d.tags) if d.tags else ''
        writer.writerow([d.original_filename, d.category, d.funding_year, frn, d.file_size, uploader,
                        d.uploaded_at.strftime('%Y-%m-%d %H:%M') if d.uploaded_at else '', tags, d.notes])
    output = si.getvalue()
    from flask import Response
    return Response(output, mimetype='text/csv',
                   headers={'Content-Disposition': f'attachment; filename={slug}_documents.csv'})
