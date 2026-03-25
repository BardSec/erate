from app.extensions import db
from datetime import datetime, timezone


class School(db.Model):
    __tablename__ = 'schools'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    usac_entity_number = db.Column(db.String(20))
    address = db.Column(db.String(255))
    city = db.Column(db.String(100))
    state = db.Column(db.String(2))
    zip = db.Column(db.String(10))
    is_active = db.Column(db.Boolean, default=True)
    square_footage = db.Column(db.Integer)
    building_count = db.Column(db.Integer, default=1)

    def __repr__(self):
        return f'<School {self.name}>'


class FundingYear(db.Model):
    __tablename__ = 'funding_years'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)
    nslp_percentage = db.Column(db.Float)
    discount_rate = db.Column(db.Integer)
    total_enrollment = db.Column(db.Integer)
    urban_rural = db.Column(db.String(10), default='urban')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    form470s = db.relationship('Form470', backref='funding_year', lazy='dynamic')
    form471s = db.relationship('Form471', backref='funding_year', lazy='dynamic')

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'year', name='uq_funding_year_tenant'),
    )

    @staticmethod
    def calculate_discount_rate(nslp_pct, urban_rural):
        """Calculate E-rate discount rate from NSLP% and urban/rural status."""
        is_urban = urban_rural == 'urban'
        if nslp_pct < 1:
            return 20 if is_urban else 25
        elif nslp_pct < 20:
            return 40 if is_urban else 50
        elif nslp_pct < 35:
            return 50 if is_urban else 60
        elif nslp_pct < 50:
            return 60 if is_urban else 70
        elif nslp_pct < 75:
            return 80 if is_urban else 80
        else:
            return 90 if is_urban else 90

    def __repr__(self):
        return f'<FundingYear {self.year}>'


class C2Budget(db.Model):
    __tablename__ = 'c2_budgets'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    cycle_start_year = db.Column(db.Integer, nullable=False)
    cycle_end_year = db.Column(db.Integer, nullable=False)
    multiplier_per_student = db.Column(db.Float, nullable=False)
    funding_floor = db.Column(db.Float, nullable=False)
    total_enrollment = db.Column(db.Integer)
    calculated_budget = db.Column(db.Float)
    spent_to_date = db.Column(db.Float, default=0.0)
    notes = db.Column(db.Text)

    expenditures = db.relationship('C2Expenditure', backref='budget', lazy='dynamic')

    @staticmethod
    def calculate_budget(enrollment, num_schools, multiplier, floor):
        """Calculate C2 budget: max(enrollment * multiplier, num_schools * floor)"""
        by_enrollment = enrollment * multiplier
        by_floor = num_schools * floor
        return max(by_enrollment, by_floor)

    @property
    def amount_remaining(self):
        return (self.calculated_budget or 0) - (self.spent_to_date or 0)

    @property
    def percent_used(self):
        if not self.calculated_budget:
            return 0
        return round((self.spent_to_date or 0) / self.calculated_budget * 100, 1)

    def __repr__(self):
        return f'<C2Budget {self.cycle_start_year}-{self.cycle_end_year}>'


class C2Expenditure(db.Model):
    __tablename__ = 'c2_expenditures'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    c2_budget_id = db.Column(db.Integer, db.ForeignKey('c2_budgets.id'), nullable=False)
    funding_year = db.Column(db.Integer, nullable=False)
    amount_spent = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Form470(db.Model):
    __tablename__ = 'form470s'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    funding_year_id = db.Column(db.Integer, db.ForeignKey('funding_years.id'), nullable=False)
    filing_date = db.Column(db.Date)
    service_type = db.Column(db.String(10))  # C1, C2, both
    description = db.Column(db.Text)
    status = db.Column(db.String(50), default='open')
    bid_due_date = db.Column(db.Date)
    notes = db.Column(db.Text)

    form471s = db.relationship('Form471', backref='form470', lazy='dynamic')

    @property
    def days_until_bid_close(self):
        if not self.bid_due_date:
            return None
        from datetime import date
        delta = self.bid_due_date - date.today()
        return delta.days

    def __repr__(self):
        return f'<Form470 FY{self.funding_year_id} {self.service_type}>'


class Form471(db.Model):
    __tablename__ = 'form471s'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    funding_year_id = db.Column(db.Integer, db.ForeignKey('funding_years.id'), nullable=False)
    form470_id = db.Column(db.Integer, db.ForeignKey('form470s.id'))
    frn = db.Column(db.String(20))
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'))
    category = db.Column(db.String(5))  # C1 or C2
    amount_requested = db.Column(db.Float, default=0)
    amount_committed = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='pending')  # pending/committed/denied/appealed/cancelled
    fcdl_date = db.Column(db.Date)
    notes = db.Column(db.Text)

    invoices = db.relationship('Invoice', backref='form471', lazy='dynamic')
    appeals = db.relationship('Appeal', backref='form471', lazy='dynamic')
    contracts = db.relationship('Contract', backref='form471', lazy='dynamic')

    def __repr__(self):
        return f'<Form471 FRN:{self.frn}>'


class Invoice(db.Model):
    __tablename__ = 'invoices'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    form471_id = db.Column(db.Integer, db.ForeignKey('form471s.id'), nullable=False)
    invoice_type = db.Column(db.String(10))  # BEAR_472, SPI_474
    submitted_date = db.Column(db.Date)
    amount_claimed = db.Column(db.Float, default=0)
    amount_reimbursed = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='pending')
    notes = db.Column(db.Text)


class Appeal(db.Model):
    __tablename__ = 'appeals'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    form471_id = db.Column(db.Integer, db.ForeignKey('form471s.id'), nullable=False)
    filed_date = db.Column(db.Date)
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    resolution = db.Column(db.Text)
    notes = db.Column(db.Text)


class Vendor(db.Model):
    __tablename__ = 'vendors'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    spin_number = db.Column(db.String(20))
    contact_name = db.Column(db.String(255))
    contact_email = db.Column(db.String(255))
    contact_phone = db.Column(db.String(20))
    service_types = db.Column(db.JSON, default=list)
    notes = db.Column(db.Text)

    form471s = db.relationship('Form471', backref='vendor', lazy='dynamic')

    def __repr__(self):
        return f'<Vendor {self.name}>'


class Contract(db.Model):
    __tablename__ = 'contracts'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=False)
    form471_id = db.Column(db.Integer, db.ForeignKey('form471s.id'))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    auto_renews = db.Column(db.Boolean, default=False)
    renewal_notice_days = db.Column(db.Integer)
    description = db.Column(db.Text)
    notes = db.Column(db.Text)

    vendor_rel = db.relationship('Vendor', backref='contracts', overlaps='contracts')

    @property
    def days_until_expiry(self):
        if not self.end_date:
            return None
        from datetime import date
        return (self.end_date - date.today()).days

    @property
    def is_expiring_soon(self):
        d = self.days_until_expiry
        return d is not None and 0 < d <= 60


class CalendarEvent(db.Model):
    __tablename__ = 'calendar_events'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    event_type = db.Column(db.String(20), default='custom')  # deadline/milestone/reminder/custom
    due_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text)
    is_recurring = db.Column(db.Boolean, default=False)
    recurrence_rule = db.Column(db.String(255))
    is_complete = db.Column(db.Boolean, default=False)
    related_form_id = db.Column(db.Integer)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50))
    entity_id = db.Column(db.Integer)
    detail = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref='audit_logs')
