import json
from datetime import date, datetime, timezone
from io import BytesIO
from flask import current_app

from app.extensions import db
from app.models.tenant import Tenant
from app.models.user import User
from app.models.erate import (FundingYear, C2Budget, C2Expenditure, School,
                               Form470, Form471, Invoice, Appeal, Vendor,
                               Contract, CalendarEvent, AuditLog, Form486)
from app.models.document import Document


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles date and datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        return super().default(obj)


def export_tenant_data(tenant_id):
    """Export all data for a tenant as a JSON-serializable dict.

    Does NOT include: audit logs (too large), document file contents (in R2),
    or user passwords. Does include document metadata.
    """
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        raise ValueError(f'Tenant {tenant_id} not found')

    data = {
        '_meta': {
            'version': '1.0',
            'exported_at': datetime.now(timezone.utc).isoformat(),
            'tenant_slug': tenant.slug,
            'tenant_name': tenant.name,
        },
        'tenant': {
            'slug': tenant.slug,
            'name': tenant.name,
            'primary_color': tenant.primary_color,
            'logo_url': tenant.logo_url,
        },
        'users': [],
        'schools': [],
        'funding_years': [],
        'c2_budgets': [],
        'c2_expenditures': [],
        'form470s': [],
        'form471s': [],
        'invoices': [],
        'appeals': [],
        'form486s': [],
        'vendors': [],
        'contracts': [],
        'calendar_events': [],
        'documents': [],
    }

    # Users (no passwords)
    for u in User.query.filter_by(tenant_id=tenant_id).all():
        data['users'].append({
            'email': u.email,
            'display_name': u.display_name,
            'role': u.role,
            'last_login': u.last_login,
            'created_at': u.created_at,
        })

    # Schools
    for s in School.query.filter_by(tenant_id=tenant_id).all():
        data['schools'].append({
            'id': s.id,
            'name': s.name,
            'usac_entity_number': s.usac_entity_number,
            'address': s.address,
            'city': s.city,
            'state': s.state,
            'zip': s.zip,
            'is_active': s.is_active,
            'square_footage': s.square_footage,
            'building_count': s.building_count,
            'enrollment': s.enrollment,
            'nslp_count': s.nslp_count,
        })

    # Funding Years
    for fy in FundingYear.query.filter_by(tenant_id=tenant_id).all():
        data['funding_years'].append({
            'id': fy.id,
            'year': fy.year,
            'nslp_percentage': fy.nslp_percentage,
            'discount_rate': fy.discount_rate,
            'total_enrollment': fy.total_enrollment,
            'urban_rural': fy.urban_rural,
            'notes': fy.notes,
        })

    # C2 Budgets
    for b in C2Budget.query.filter_by(tenant_id=tenant_id).all():
        data['c2_budgets'].append({
            'id': b.id,
            'cycle_start_year': b.cycle_start_year,
            'cycle_end_year': b.cycle_end_year,
            'multiplier_per_student': b.multiplier_per_student,
            'funding_floor': b.funding_floor,
            'total_enrollment': b.total_enrollment,
            'calculated_budget': b.calculated_budget,
            'spent_to_date': b.spent_to_date,
            'notes': b.notes,
        })

    # C2 Expenditures
    for e in C2Expenditure.query.filter_by(tenant_id=tenant_id).all():
        data['c2_expenditures'].append({
            'id': e.id,
            'c2_budget_id': e.c2_budget_id,
            'funding_year': e.funding_year,
            'amount_spent': e.amount_spent,
            'description': e.description,
            'created_at': e.created_at,
        })

    # Vendors
    for v in Vendor.query.filter_by(tenant_id=tenant_id).all():
        data['vendors'].append({
            'id': v.id,
            'name': v.name,
            'spin_number': v.spin_number,
            'contact_name': v.contact_name,
            'contact_email': v.contact_email,
            'contact_phone': v.contact_phone,
            'service_types': v.service_types,
            'notes': v.notes,
        })

    # Form 470s
    for f in Form470.query.filter_by(tenant_id=tenant_id).all():
        data['form470s'].append({
            'id': f.id,
            'funding_year_id': f.funding_year_id,
            'filing_date': f.filing_date,
            'service_type': f.service_type,
            'description': f.description,
            'status': f.status,
            'bid_due_date': f.bid_due_date,
            'notes': f.notes,
        })

    # Form 471s
    for f in Form471.query.filter_by(tenant_id=tenant_id).all():
        data['form471s'].append({
            'id': f.id,
            'funding_year_id': f.funding_year_id,
            'form470_id': f.form470_id,
            'frn': f.frn,
            'vendor_id': f.vendor_id,
            'category': f.category,
            'amount_requested': f.amount_requested,
            'amount_committed': f.amount_committed,
            'status': f.status,
            'fcdl_date': f.fcdl_date,
            'notes': f.notes,
        })

    # Invoices
    for i in Invoice.query.filter_by(tenant_id=tenant_id).all():
        data['invoices'].append({
            'id': i.id,
            'form471_id': i.form471_id,
            'invoice_type': i.invoice_type,
            'submitted_date': i.submitted_date,
            'amount_claimed': i.amount_claimed,
            'amount_reimbursed': i.amount_reimbursed,
            'status': i.status,
            'notes': i.notes,
        })

    # Appeals
    for a in Appeal.query.filter_by(tenant_id=tenant_id).all():
        data['appeals'].append({
            'id': a.id,
            'form471_id': a.form471_id,
            'filed_date': a.filed_date,
            'reason': a.reason,
            'status': a.status,
            'resolution': a.resolution,
            'notes': a.notes,
        })

    # Form 486s
    for f in Form486.query.filter_by(tenant_id=tenant_id).all():
        data['form486s'].append({
            'id': f.id,
            'form471_id': f.form471_id,
            'funding_year': f.funding_year,
            'service_start_date': f.service_start_date,
            'filed_date': f.filed_date,
            'status': f.status,
            'contact_email': f.contact_email,
            'notes': f.notes,
        })

    # Contracts
    for c in Contract.query.filter_by(tenant_id=tenant_id).all():
        data['contracts'].append({
            'id': c.id,
            'vendor_id': c.vendor_id,
            'form471_id': c.form471_id,
            'start_date': c.start_date,
            'end_date': c.end_date,
            'auto_renews': c.auto_renews,
            'renewal_notice_days': c.renewal_notice_days,
            'description': c.description,
            'notes': c.notes,
        })

    # Calendar Events
    for e in CalendarEvent.query.filter_by(tenant_id=tenant_id).all():
        data['calendar_events'].append({
            'id': e.id,
            'title': e.title,
            'event_type': e.event_type,
            'due_date': e.due_date,
            'description': e.description,
            'is_recurring': e.is_recurring,
            'recurrence_rule': e.recurrence_rule,
            'is_complete': e.is_complete,
            'created_by': e.created_by,
        })

    # Documents (metadata only, not file contents)
    for d in Document.query.filter_by(tenant_id=tenant_id).all():
        data['documents'].append({
            'id': d.id,
            'filename': d.filename,
            'original_filename': d.original_filename,
            'r2_key': d.r2_key,
            'file_size': d.file_size,
            'mime_type': d.mime_type,
            'category': d.category,
            'funding_year': d.funding_year,
            'form471_id': d.form471_id,
            'tags': d.tags,
            'notes': d.notes,
            'uploaded_at': d.uploaded_at,
        })

    return data


def export_tenant_json(tenant_id):
    """Export tenant data as JSON bytes."""
    data = export_tenant_data(tenant_id)
    return json.dumps(data, cls=DateTimeEncoder, indent=2).encode('utf-8')


def save_backup_to_storage(tenant, backup_bytes, filename):
    """Save backup JSON to R2 or local storage. Returns the storage key."""
    from app.documents.r2 import upload_file, _get_s3_client, _get_bucket
    import os

    r2_key = f'backups/{tenant.slug}/{filename}'

    client = _get_s3_client()
    if client:
        try:
            buf = BytesIO(backup_bytes)
            client.upload_fileobj(
                buf,
                _get_bucket(),
                r2_key,
                ExtraArgs={'ContentType': 'application/json'},
            )
            return r2_key
        except Exception as e:
            current_app.logger.warning(f'R2 backup upload failed ({e}), falling back to local')

    # Local fallback
    upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    local_path = os.path.join(upload_dir, r2_key)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, 'wb') as f:
        f.write(backup_bytes)
    return r2_key


def list_backups(tenant):
    """List available backups for a tenant from R2 or local storage."""
    import os
    from app.documents.r2 import _get_s3_client, _get_bucket

    prefix = f'backups/{tenant.slug}/'
    backups = []

    client = _get_s3_client()
    if client:
        try:
            response = client.list_objects_v2(Bucket=_get_bucket(), Prefix=prefix)
            for obj in response.get('Contents', []):
                key = obj['Key']
                name = key.replace(prefix, '')
                if name.endswith('.json'):
                    backups.append({
                        'key': key,
                        'filename': name,
                        'size': obj.get('Size', 0),
                        'last_modified': obj.get('LastModified'),
                        'storage': 'r2',
                    })
        except Exception:
            pass

    # Also check local
    upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    local_dir = os.path.join(upload_dir, prefix)
    if os.path.isdir(local_dir):
        for name in sorted(os.listdir(local_dir), reverse=True):
            if name.endswith('.json'):
                path = os.path.join(local_dir, name)
                stat = os.stat(path)
                # Skip if already found in R2
                if not any(b['filename'] == name for b in backups):
                    backups.append({
                        'key': prefix + name,
                        'filename': name,
                        'size': stat.st_size,
                        'last_modified': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                        'storage': 'local',
                    })

    backups.sort(key=lambda b: b['filename'], reverse=True)
    return backups


def download_backup(tenant, filename):
    """Download a backup file and return its bytes."""
    import os
    from app.documents.r2 import _get_s3_client, _get_bucket

    r2_key = f'backups/{tenant.slug}/{filename}'

    client = _get_s3_client()
    if client:
        try:
            buf = BytesIO()
            client.download_fileobj(_get_bucket(), r2_key, buf)
            buf.seek(0)
            return buf.read()
        except Exception:
            pass

    # Local fallback
    upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    local_path = os.path.join(upload_dir, r2_key)
    if os.path.exists(local_path):
        with open(local_path, 'rb') as f:
            return f.read()

    return None


def _parse_date(val):
    """Parse a date string from backup JSON."""
    if not val:
        return None
    try:
        return date.fromisoformat(val)
    except (ValueError, TypeError):
        return None


def _parse_datetime(val):
    """Parse a datetime string from backup JSON."""
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None


def restore_tenant_data(tenant_id, backup_data):
    """Restore tenant data from a backup dict.

    This MERGES data — it creates records that don't exist and updates
    records that do. It does NOT delete existing data not in the backup.

    Returns a summary dict of what was created/updated.
    """
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        raise ValueError(f'Tenant {tenant_id} not found')

    stats = {}
    id_maps = {}  # maps old IDs to new IDs for foreign key resolution

    # 1. Schools
    created, updated = 0, 0
    id_maps['schools'] = {}
    for s_data in backup_data.get('schools', []):
        existing = None
        if s_data.get('usac_entity_number'):
            existing = School.query.filter_by(
                tenant_id=tenant_id, usac_entity_number=s_data['usac_entity_number']).first()
        if not existing and s_data.get('name'):
            existing = School.query.filter_by(
                tenant_id=tenant_id, name=s_data['name']).first()

        if existing:
            for field in ['address', 'city', 'state', 'zip', 'square_footage',
                         'building_count', 'enrollment', 'nslp_count']:
                new_val = s_data.get(field)
                if new_val is not None and not getattr(existing, field, None):
                    setattr(existing, field, new_val)
            id_maps['schools'][s_data.get('id')] = existing.id
            updated += 1
        else:
            s = School(tenant_id=tenant_id, name=s_data.get('name', ''),
                      usac_entity_number=s_data.get('usac_entity_number'),
                      address=s_data.get('address'), city=s_data.get('city'),
                      state=s_data.get('state'), zip=s_data.get('zip'),
                      is_active=s_data.get('is_active', True),
                      square_footage=s_data.get('square_footage'),
                      building_count=s_data.get('building_count', 1),
                      enrollment=s_data.get('enrollment'),
                      nslp_count=s_data.get('nslp_count'))
            db.session.add(s)
            db.session.flush()
            id_maps['schools'][s_data.get('id')] = s.id
            created += 1
    stats['schools'] = {'created': created, 'updated': updated}

    # 2. Funding Years
    created, updated = 0, 0
    id_maps['funding_years'] = {}
    for fy_data in backup_data.get('funding_years', []):
        existing = FundingYear.query.filter_by(
            tenant_id=tenant_id, year=fy_data.get('year')).first()
        if existing:
            for field in ['nslp_percentage', 'discount_rate', 'total_enrollment', 'urban_rural', 'notes']:
                new_val = fy_data.get(field)
                if new_val is not None and not getattr(existing, field, None):
                    setattr(existing, field, new_val)
            id_maps['funding_years'][fy_data.get('id')] = existing.id
            updated += 1
        else:
            fy = FundingYear(tenant_id=tenant_id, year=fy_data.get('year'),
                            nslp_percentage=fy_data.get('nslp_percentage'),
                            discount_rate=fy_data.get('discount_rate'),
                            total_enrollment=fy_data.get('total_enrollment'),
                            urban_rural=fy_data.get('urban_rural'),
                            notes=fy_data.get('notes'))
            db.session.add(fy)
            db.session.flush()
            id_maps['funding_years'][fy_data.get('id')] = fy.id
            created += 1
    stats['funding_years'] = {'created': created, 'updated': updated}

    # 3. Vendors
    created, updated = 0, 0
    id_maps['vendors'] = {}
    for v_data in backup_data.get('vendors', []):
        existing = None
        if v_data.get('spin_number'):
            existing = Vendor.query.filter_by(
                tenant_id=tenant_id, spin_number=v_data['spin_number']).first()
        if not existing and v_data.get('name'):
            existing = Vendor.query.filter_by(
                tenant_id=tenant_id, name=v_data['name']).first()

        if existing:
            id_maps['vendors'][v_data.get('id')] = existing.id
            updated += 1
        else:
            v = Vendor(tenant_id=tenant_id, name=v_data.get('name', ''),
                      spin_number=v_data.get('spin_number'),
                      contact_name=v_data.get('contact_name'),
                      contact_email=v_data.get('contact_email'),
                      contact_phone=v_data.get('contact_phone'),
                      service_types=v_data.get('service_types', []),
                      notes=v_data.get('notes'))
            db.session.add(v)
            db.session.flush()
            id_maps['vendors'][v_data.get('id')] = v.id
            created += 1
    stats['vendors'] = {'created': created, 'updated': updated}

    # 4. C2 Budgets
    created = 0
    id_maps['c2_budgets'] = {}
    for b_data in backup_data.get('c2_budgets', []):
        existing = C2Budget.query.filter_by(
            tenant_id=tenant_id, cycle_start_year=b_data.get('cycle_start_year'),
            cycle_end_year=b_data.get('cycle_end_year')).first()
        if existing:
            id_maps['c2_budgets'][b_data.get('id')] = existing.id
        else:
            b = C2Budget(tenant_id=tenant_id,
                        cycle_start_year=b_data.get('cycle_start_year'),
                        cycle_end_year=b_data.get('cycle_end_year'),
                        multiplier_per_student=b_data.get('multiplier_per_student'),
                        funding_floor=b_data.get('funding_floor'),
                        total_enrollment=b_data.get('total_enrollment'),
                        calculated_budget=b_data.get('calculated_budget'),
                        spent_to_date=b_data.get('spent_to_date', 0),
                        notes=b_data.get('notes'))
            db.session.add(b)
            db.session.flush()
            id_maps['c2_budgets'][b_data.get('id')] = b.id
            created += 1
    stats['c2_budgets'] = {'created': created}

    # 5. Form 470s
    created = 0
    id_maps['form470s'] = {}
    for f_data in backup_data.get('form470s', []):
        fy_id = id_maps['funding_years'].get(f_data.get('funding_year_id'))
        f = Form470(tenant_id=tenant_id, funding_year_id=fy_id,
                   filing_date=_parse_date(f_data.get('filing_date')),
                   service_type=f_data.get('service_type'),
                   description=f_data.get('description'),
                   status=f_data.get('status'),
                   bid_due_date=_parse_date(f_data.get('bid_due_date')),
                   notes=f_data.get('notes'))
        db.session.add(f)
        db.session.flush()
        id_maps['form470s'][f_data.get('id')] = f.id
        created += 1
    stats['form470s'] = {'created': created}

    # 6. Form 471s
    created = 0
    id_maps['form471s'] = {}
    for f_data in backup_data.get('form471s', []):
        existing = None
        if f_data.get('frn'):
            existing = Form471.query.filter_by(tenant_id=tenant_id, frn=f_data['frn']).first()
        if existing:
            id_maps['form471s'][f_data.get('id')] = existing.id
        else:
            fy_id = id_maps['funding_years'].get(f_data.get('funding_year_id'))
            f470_id = id_maps['form470s'].get(f_data.get('form470_id'))
            v_id = id_maps['vendors'].get(f_data.get('vendor_id'))
            f = Form471(tenant_id=tenant_id, funding_year_id=fy_id,
                       form470_id=f470_id, frn=f_data.get('frn'),
                       vendor_id=v_id, category=f_data.get('category'),
                       amount_requested=f_data.get('amount_requested'),
                       amount_committed=f_data.get('amount_committed'),
                       status=f_data.get('status', 'pending'),
                       fcdl_date=_parse_date(f_data.get('fcdl_date')),
                       notes=f_data.get('notes'))
            db.session.add(f)
            db.session.flush()
            id_maps['form471s'][f_data.get('id')] = f.id
            created += 1
    stats['form471s'] = {'created': created}

    # 7. Invoices
    created = 0
    for i_data in backup_data.get('invoices', []):
        f471_id = id_maps['form471s'].get(i_data.get('form471_id'))
        if not f471_id:
            continue
        inv = Invoice(tenant_id=tenant_id, form471_id=f471_id,
                     invoice_type=i_data.get('invoice_type'),
                     submitted_date=_parse_date(i_data.get('submitted_date')),
                     amount_claimed=i_data.get('amount_claimed'),
                     amount_reimbursed=i_data.get('amount_reimbursed'),
                     status=i_data.get('status'), notes=i_data.get('notes'))
        db.session.add(inv)
        created += 1
    stats['invoices'] = {'created': created}

    # 8. Calendar Events
    created = 0
    for e_data in backup_data.get('calendar_events', []):
        existing = CalendarEvent.query.filter_by(
            tenant_id=tenant_id, title=e_data.get('title'),
            due_date=_parse_date(e_data.get('due_date'))).first()
        if not existing:
            evt = CalendarEvent(tenant_id=tenant_id,
                               title=e_data.get('title', ''),
                               event_type=e_data.get('event_type', 'custom'),
                               due_date=_parse_date(e_data.get('due_date')),
                               description=e_data.get('description'),
                               is_recurring=e_data.get('is_recurring', False),
                               recurrence_rule=e_data.get('recurrence_rule'),
                               is_complete=e_data.get('is_complete', False))
            db.session.add(evt)
            created += 1
    stats['calendar_events'] = {'created': created}

    # 9. Contracts
    created = 0
    for c_data in backup_data.get('contracts', []):
        v_id = id_maps['vendors'].get(c_data.get('vendor_id'))
        f471_id = id_maps['form471s'].get(c_data.get('form471_id'))
        if not v_id:
            continue
        c = Contract(tenant_id=tenant_id, vendor_id=v_id, form471_id=f471_id,
                    start_date=_parse_date(c_data.get('start_date')),
                    end_date=_parse_date(c_data.get('end_date')),
                    auto_renews=c_data.get('auto_renews', False),
                    renewal_notice_days=c_data.get('renewal_notice_days'),
                    description=c_data.get('description'),
                    notes=c_data.get('notes'))
        db.session.add(c)
        created += 1
    stats['contracts'] = {'created': created}

    db.session.commit()
    return stats
