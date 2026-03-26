# E-RateKeeper

A multi-tenant SaaS web application for K-12 school districts to manage their FCC E-rate program participation.

## Features

- **Multi-tenant architecture** — each school district gets isolated data and branding
- **Dashboard** — funding summary, C2 budget utilization, upcoming deadlines
- **C2 Budget Tracker** — auto-calculate 5-year budgets with FY2021 and FY2026 multipliers
- **Application Tracker** — Form 470, Form 471/FRN, invoice, and appeal management
- **Deadline Calendar** — monthly calendar view with color-coded deadlines
- **Vendor & Contract Manager** — vendor directory with SPIN numbers, contract renewal alerts
- **Document Repository** — upload to Cloudflare R2 with search, categorization, and completeness checklists
- **Compliance & Audit Readiness** — per-funding-year checklists, audit readiness scores, record retention tracking
- **PDF Reports** — annual summary, deadlines, document inventory, vendor summary
- **Platform Admin** — tenant management, user management, cross-tenant funding stats

## Tech Stack

- **Backend:** Flask 3.1.0, Python 3.12, SQLAlchemy 2.0, PostgreSQL
- **Auth:** Microsoft Entra ID (MSAL), Google OIDC (authlib), local fallback
- **Storage:** Cloudflare R2 (S3-compatible) with local filesystem fallback
- **Frontend:** Jinja2, Bootstrap 5.3.3, Bootstrap Icons 1.11.3, vanilla JS
- **Deployment:** Docker Compose with Cloudflare Tunnel

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.12 (for local development)

### Production (Docker + Cloudflare Tunnel)

```bash
# Copy environment file and configure all values
cp .env.example .env
# IMPORTANT: Set strong values for SECRET_KEY, POSTGRES_PASSWORD, FIELD_ENCRYPTION_KEY
# Configure CLOUDFLARE_TUNNEL_TOKEN from your Zero Trust dashboard
# Set the tunnel ingress to route to http://app:8000

# Start services (no ports exposed — traffic goes through Cloudflare Tunnel only)
docker compose up -d

# Migrations run automatically on startup, but to create the admin user:
docker compose exec app flask init-db
```

### Local Development

```bash
# Start with dev overrides (exposes ports on localhost only)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Or run without Docker:
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export FLASK_DEBUG=1
export ALLOW_LOCAL_AUTH=true
export SESSION_COOKIE_SECURE=false
export PROXY_TRUST_LEVEL=0
export DATABASE_URL=postgresql://erate:yourpassword@localhost:5432/erate_manager
export SECRET_KEY=dev-secret-only

flask db upgrade
flask init-db
flask seed-demo
flask run --debug
```

### Login

- **Platform Admin:** http://localhost:5000/auth/login/admin
- **Demo Tenant:** http://localhost:5000/auth/login/demo
  - Email: `admin@demo.example.com`
  - Password: `demo1234`

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

## Environment Variables

See `.env.example` for all configuration options.

| Variable | Description |
|---|---|
| `SECRET_KEY` | Flask session secret key (generate a strong random value) |
| `DATABASE_URL` | PostgreSQL connection string |
| `POSTGRES_PASSWORD` | Database password (required, no default) |
| `ALLOW_LOCAL_AUTH` | Enable email/password login (`false` in production) |
| `SESSION_COOKIE_SECURE` | Require HTTPS for cookies (`true` in production) |
| `PROXY_TRUST_LEVEL` | Proxy depth for X-Forwarded-For (`1` for Cloudflare Tunnel) |
| `SUBDOMAIN_TENANCY` | Use subdomains instead of /t/\<slug\>/ paths |
| `R2_ENDPOINT_URL` | Cloudflare R2 endpoint |
| `R2_ACCESS_KEY_ID` | R2 access key |
| `R2_SECRET_ACCESS_KEY` | R2 secret key |
| `R2_BUCKET_NAME` | R2 bucket name |
| `FIELD_ENCRYPTION_KEY` | Fernet key for encrypting OIDC secrets at rest |
| `CLOUDFLARE_TUNNEL_TOKEN` | Cloudflare Tunnel token (required for production) |

## Security Architecture

**Production deployment** is designed for Cloudflare Tunnel exposure with no publicly bound ports:

- **PostgreSQL** — internal network only, no port mapping
- **Flask app** — internal network only, reachable only by cloudflared
- **cloudflared** — outbound-only tunnel to Cloudflare (no inbound ports)
- **Non-root container** — app runs as dedicated `erate` user
- **Read-only filesystem** — containers use `read_only: true` with tmpfs for /tmp
- **Security headers** — X-Content-Type-Options, X-Frame-Options, HSTS, Referrer-Policy
- **ProxyFix** — trusts CF-Connecting-IP so `request.remote_addr` reflects real client IPs
- **Secure sessions** — HttpOnly, SameSite=Lax, Secure flag (HTTPS required)
- **CSRF protection** — all forms use Flask-WTF CSRF tokens
- **Encrypted secrets** — OIDC client secrets encrypted at rest with Fernet

For local development, use `docker-compose.dev.yml` override which binds ports to `127.0.0.1` only.
