import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app, url_for
from datetime import date, timedelta


def _get_smtp_config():
    """Get SMTP configuration from app config."""
    return {
        'host': current_app.config.get('SMTP_HOST', ''),
        'port': int(current_app.config.get('SMTP_PORT', 587)),
        'username': current_app.config.get('SMTP_USERNAME', ''),
        'password': current_app.config.get('SMTP_PASSWORD', ''),
        'from_email': current_app.config.get('SMTP_FROM_EMAIL', 'noreply@example.com'),
        'from_name': current_app.config.get('SMTP_FROM_NAME', 'E-RateKeeper'),
        'use_tls': current_app.config.get('SMTP_USE_TLS', 'true').lower() == 'true',
    }


def _send_email(to_email, subject, html_body, text_body=None):
    """Send an email via SMTP. Returns True on success, False on failure."""
    config = _get_smtp_config()
    if not config['host'] or not config['username']:
        current_app.logger.warning('SMTP not configured, skipping email send')
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{config['from_name']} <{config['from_email']}>"
    msg['To'] = to_email

    if text_body:
        msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))

    try:
        if config['use_tls']:
            server = smtplib.SMTP(config['host'], config['port'])
            server.starttls()
        else:
            server = smtplib.SMTP(config['host'], config['port'])
        server.login(config['username'], config['password'])
        server.sendmail(config['from_email'], to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        current_app.logger.error(f'Failed to send email to {to_email}: {e}')
        return False


def send_deadline_reminder(user, events, tenant):
    """Send upcoming deadline reminder email to a user."""
    subject = f'[{tenant.name}] Upcoming E-Rate Deadlines'

    events_html = ''
    for evt in events:
        days = (evt.due_date - date.today()).days
        color = '#dc3545' if days <= 3 else ('#ffc107' if days <= 14 else '#0d6efd')
        events_html += f'''
        <tr>
            <td style="padding:8px;border-bottom:1px solid #eee;">
                <span style="color:{color};font-weight:bold;">{evt.due_date.strftime('%b %d, %Y')}</span>
                <span style="color:#666;font-size:12px;">({days}d)</span>
            </td>
            <td style="padding:8px;border-bottom:1px solid #eee;">{evt.title}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;color:#666;font-size:13px;">{evt.description or ''}</td>
        </tr>'''

    html = f'''
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#1e293b;color:white;padding:20px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">{tenant.name}</h2>
            <p style="margin:5px 0 0;opacity:0.8;">E-Rate Deadline Reminder</p>
        </div>
        <div style="padding:20px;background:#fff;border:1px solid #e2e8f0;">
            <p>Hi {user.display_name or user.email},</p>
            <p>You have <strong>{len(events)} upcoming E-Rate deadline(s)</strong> in the next 14 days:</p>
            <table style="width:100%;border-collapse:collapse;margin:15px 0;">
                <tr style="background:#f8fafc;">
                    <th style="padding:8px;text-align:left;font-size:12px;color:#64748b;">DATE</th>
                    <th style="padding:8px;text-align:left;font-size:12px;color:#64748b;">DEADLINE</th>
                    <th style="padding:8px;text-align:left;font-size:12px;color:#64748b;">DETAILS</th>
                </tr>
                {events_html}
            </table>
            <p style="margin-top:20px;font-size:13px;color:#666;">
                Log in to E-RateKeeper to view all deadlines and mark them complete.
            </p>
        </div>
        <div style="padding:15px;background:#f8fafc;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 8px 8px;text-align:center;">
            <p style="margin:0;font-size:12px;color:#94a3b8;">E-RateKeeper — {tenant.name}</p>
            <p style="margin:4px 0 0;font-size:11px;color:#94a3b8;">Powered by BudgyK12.com</p>
        </div>
    </div>'''

    return _send_email(user.email, subject, html)


def send_contract_expiration_alert(user, contracts, tenant):
    """Send contract expiration alert email."""
    subject = f'[{tenant.name}] Contracts Expiring Soon'

    contracts_html = ''
    for c in contracts:
        days = c.days_until_expiry
        contracts_html += f'''
        <tr>
            <td style="padding:8px;border-bottom:1px solid #eee;">{c.vendor_rel.name if c.vendor_rel else 'Unknown'}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;">{c.description or '—'}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;">{c.end_date}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;color:#dc3545;font-weight:bold;">{days}d</td>
        </tr>'''

    html = f'''
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#1e293b;color:white;padding:20px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">{tenant.name}</h2>
            <p style="margin:5px 0 0;opacity:0.8;">Contract Expiration Alert</p>
        </div>
        <div style="padding:20px;background:#fff;border:1px solid #e2e8f0;">
            <p>Hi {user.display_name or user.email},</p>
            <p><strong>{len(contracts)} contract(s)</strong> are expiring within 60 days:</p>
            <table style="width:100%;border-collapse:collapse;margin:15px 0;">
                <tr style="background:#f8fafc;">
                    <th style="padding:8px;text-align:left;font-size:12px;color:#64748b;">VENDOR</th>
                    <th style="padding:8px;text-align:left;font-size:12px;color:#64748b;">CONTRACT</th>
                    <th style="padding:8px;text-align:left;font-size:12px;color:#64748b;">EXPIRES</th>
                    <th style="padding:8px;text-align:left;font-size:12px;color:#64748b;">DAYS</th>
                </tr>
                {contracts_html}
            </table>
            <p style="font-size:13px;color:#666;">Review these contracts and begin renewal or rebid processes as needed.</p>
        </div>
    </div>'''

    return _send_email(user.email, subject, html)


def send_pending_user_notification(admin, pending_user, tenant):
    """Notify district admin of a new pending user."""
    subject = f'[{tenant.name}] New User Awaiting Approval'

    html = f'''
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#1e293b;color:white;padding:20px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">{tenant.name}</h2>
            <p style="margin:5px 0 0;opacity:0.8;">User Approval Required</p>
        </div>
        <div style="padding:20px;background:#fff;border:1px solid #e2e8f0;">
            <p>Hi {admin.display_name or admin.email},</p>
            <p>A new user has signed in and is awaiting your approval:</p>
            <div style="background:#f8fafc;padding:15px;border-radius:6px;margin:15px 0;">
                <strong>{pending_user.display_name or 'Unknown'}</strong><br>
                <span style="color:#666;">{pending_user.email}</span>
            </div>
            <p style="font-size:13px;color:#666;">
                Log in to E-RateKeeper and go to <strong>Users</strong> to approve or deny access.
            </p>
        </div>
    </div>'''

    return _send_email(admin.email, subject, html)


def send_notifications_for_tenant(tenant):
    """Run all notification checks for a tenant. Called by CLI command."""
    from app.models.user import User
    from app.models.erate import CalendarEvent, Contract

    today = date.today()
    admins = User.query.filter_by(tenant_id=tenant.id, role='district_admin').all()
    if not admins:
        return 0

    sent = 0

    # 1. Upcoming deadlines (within 14 days)
    upcoming = CalendarEvent.query.filter_by(
        tenant_id=tenant.id, is_complete=False
    ).filter(
        CalendarEvent.due_date >= today,
        CalendarEvent.due_date <= today + timedelta(days=14)
    ).order_by(CalendarEvent.due_date).all()

    if upcoming:
        for admin in admins:
            if send_deadline_reminder(admin, upcoming, tenant):
                sent += 1

    # 2. Expiring contracts (within 60 days)
    contracts = Contract.query.filter_by(tenant_id=tenant.id).all()
    expiring = [c for c in contracts if c.is_expiring_soon]

    if expiring:
        for admin in admins:
            if send_contract_expiration_alert(admin, expiring, tenant):
                sent += 1

    # 3. Pending users
    pending = User.query.filter_by(tenant_id=tenant.id, role='pending').all()
    for pending_user in pending:
        for admin in admins:
            if send_pending_user_notification(admin, pending_user, tenant):
                sent += 1

    return sent
