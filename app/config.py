import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///erate.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
    }

    # Debug must be explicitly enabled — off by default
    DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'

    ALLOW_LOCAL_AUTH = os.environ.get('ALLOW_LOCAL_AUTH', 'false').lower() == 'true'
    SUBDOMAIN_TENANCY = os.environ.get('SUBDOMAIN_TENANCY', 'false').lower() == 'true'

    # Session security
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 3600  # 1 hour

    # Disable strict Referer checking for CSRF behind reverse proxy (Cloudflare Tunnel)
    WTF_CSRF_SSL_STRICT = False

    # Trust Cloudflare proxy headers (CF-Connecting-IP, X-Forwarded-For)
    # Number of trusted proxies — 1 for Cloudflare Tunnel
    PROXY_TRUST_LEVEL = int(os.environ.get('PROXY_TRUST_LEVEL', '1'))

    # R2 / S3
    R2_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL', '')
    R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID', '')
    R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY', '')
    R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME', 'erate-documents')

    # Encryption
    FIELD_ENCRYPTION_KEY = os.environ.get('FIELD_ENCRYPTION_KEY', '')

    # Upload fallback
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads'))
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB

    # Email / SMTP
    SMTP_HOST = os.environ.get('SMTP_HOST', '')
    SMTP_PORT = os.environ.get('SMTP_PORT', '587')
    SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
    SMTP_FROM_EMAIL = os.environ.get('SMTP_FROM_EMAIL', 'noreply@example.com')
    SMTP_FROM_NAME = os.environ.get('SMTP_FROM_NAME', 'E-RateKeeper')
    SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', 'true')


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    WTF_CSRF_ENABLED = False
    ALLOW_LOCAL_AUTH = True
    FIELD_ENCRYPTION_KEY = ''
    SESSION_COOKIE_SECURE = False
    PROXY_TRUST_LEVEL = 0
