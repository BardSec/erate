# E-Rate Manager

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

### Docker Setup

```bash
# Copy environment file
cp .env.example .env
# Edit .env with your settings

# Start services
docker compose up -d

# Run migrations and create admin user
docker compose exec app flask db upgrade
docker compose exec app flask init-db

# (Optional) Seed demo data
docker compose exec app flask seed-demo
```

### Local Development

```bash
# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment
export FLASK_ENV=development
export ALLOW_LOCAL_AUTH=true
export DATABASE_URL=postgresql://erate:erate@localhost:5432/erate_manager
export SECRET_KEY=dev-secret

# Run migrations
flask db upgrade

# Create admin user
flask init-db

# Seed demo data
flask seed-demo

# Run development server
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
| `SECRET_KEY` | Flask session secret key |
| `DATABASE_URL` | PostgreSQL connection string |
| `ALLOW_LOCAL_AUTH` | Enable email/password login (dev only) |
| `SUBDOMAIN_TENANCY` | Use subdomains instead of /t/<slug>/ paths |
| `R2_ENDPOINT_URL` | Cloudflare R2 endpoint |
| `R2_ACCESS_KEY_ID` | R2 access key |
| `R2_SECRET_ACCESS_KEY` | R2 secret key |
| `R2_BUCKET_NAME` | R2 bucket name |
| `FIELD_ENCRYPTION_KEY` | Fernet key for encrypting OIDC secrets |
| `CLOUDFLARE_TUNNEL_TOKEN` | Cloudflare Tunnel token |
