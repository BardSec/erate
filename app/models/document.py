from app.extensions import db
from datetime import datetime, timezone


class Document(db.Model):
    __tablename__ = 'documents'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    r2_key = db.Column(db.String(512))
    file_size = db.Column(db.Integer)
    mime_type = db.Column(db.String(100))
    category = db.Column(db.String(50), default='other')
    funding_year = db.Column(db.Integer)
    tags = db.Column(db.JSON, default=list)
    notes = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    uploader = db.relationship('User', backref='documents')

    CATEGORIES = [
        ('form470', 'Form 470'),
        ('form471', 'Form 471'),
        ('fcdl', 'FCDL'),
        ('contract', 'Contract'),
        ('invoice', 'Invoice'),
        ('appeal', 'Appeal'),
        ('bid_doc', 'Bid Document'),
        ('tech_plan', 'Technology Plan'),
        ('correspondence', 'Correspondence'),
        ('other', 'Other'),
    ]
