FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN groupadd -r erate && useradd -r -g erate -d /app -s /sbin/nologin erate

COPY --chown=erate:erate . .

# Ensure uploads dir exists and is writable
RUN mkdir -p /app/uploads && chown erate:erate /app/uploads

USER erate

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]
