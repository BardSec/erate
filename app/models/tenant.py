from app.extensions import db
from datetime import datetime, timezone
from cryptography.fernet import Fernet
from flask import current_app


class Tenant(db.Model):
    __tablename__ = 'tenants'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(63), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    logo_url = db.Column(db.String(512))
    primary_color = db.Column(db.String(7), default='#1a73e8')
    azure_client_id = db.Column(db.String(255))
    azure_tenant_id = db.Column(db.String(255))
    _azure_client_secret = db.Column('azure_client_secret', db.Text)
    google_client_id = db.Column(db.String(255))
    _google_client_secret = db.Column('google_client_secret', db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    users = db.relationship('User', backref='tenant', lazy='dynamic')
    schools = db.relationship('School', backref='tenant', lazy='dynamic')
    funding_years = db.relationship('FundingYear', backref='tenant', lazy='dynamic')

    def _get_fernet(self):
        key = current_app.config.get('FIELD_ENCRYPTION_KEY', '')
        if not key:
            return None
        try:
            return Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, Exception):
            return None

    @property
    def azure_client_secret(self):
        if not self._azure_client_secret:
            return None
        f = self._get_fernet()
        if f:
            try:
                return f.decrypt(self._azure_client_secret.encode()).decode()
            except Exception:
                return self._azure_client_secret
        return self._azure_client_secret

    @azure_client_secret.setter
    def azure_client_secret(self, value):
        if not value:
            self._azure_client_secret = None
            return
        f = self._get_fernet()
        if f:
            self._azure_client_secret = f.encrypt(value.encode()).decode()
        else:
            self._azure_client_secret = value

    @property
    def google_client_secret(self):
        if not self._google_client_secret:
            return None
        f = self._get_fernet()
        if f:
            try:
                return f.decrypt(self._google_client_secret.encode()).decode()
            except Exception:
                return self._google_client_secret
        return self._google_client_secret

    @google_client_secret.setter
    def google_client_secret(self, value):
        if not value:
            self._google_client_secret = None
            return
        f = self._get_fernet()
        if f:
            self._google_client_secret = f.encrypt(value.encode()).decode()
        else:
            self._google_client_secret = value

    def __repr__(self):
        return f'<Tenant {self.slug}>'
