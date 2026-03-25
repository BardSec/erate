from app.extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    display_name = db.Column(db.String(255))
    hashed_password = db.Column(db.String(255))
    role = db.Column(db.String(50), nullable=False, default='readonly')
    is_platform_admin = db.Column(db.Boolean, default=False, nullable=False)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'email', name='uq_user_tenant_email'),
    )

    def set_password(self, password):
        self.hashed_password = generate_password_hash(password)

    def check_password(self, password):
        if not self.hashed_password:
            return False
        return check_password_hash(self.hashed_password, password)

    @property
    def is_admin(self):
        return self.role == 'district_admin' or self.is_platform_admin

    @property
    def is_pending(self):
        return self.role == 'pending'

    @property
    def can_write(self):
        return self.is_platform_admin or self.role in ('district_admin', 'staff', 'consultant')

    def __repr__(self):
        return f'<User {self.email}>'
