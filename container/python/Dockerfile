FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libffi-dev \
    shared-mime-info \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

EXPOSE 5000

# Migrations are opt-in via RUN_MIGRATIONS_ON_START (S03 + 2026-05-27 hotfix).
# Default (unset / "false"): gunicorn launches directly — production-managed
#   deploys run `alembic upgrade heads` as a separate one-shot step (the
#   `vbwd_migrate` compose service or `make migrate-once`) so a hung migration
#   cannot block container readiness or strand a rollout mid-deploy.
# "true": migrations run inline before gunicorn — for compose-up-only flows
#   (e.g. demo-instances) that don't run a separate migrate step.
# Either way, if migrations fail the container exits non-zero (set -e) so
# the failure is observable, not silent.
CMD ["sh", "-c", "set -e; [ -f /app/plugins/plugins.json ] || cp /app/plugins/plugins.json.dist /app/plugins/plugins.json; if [ \"${RUN_MIGRATIONS_ON_START:-false}\" = \"true\" ]; then echo '[entrypoint] RUN_MIGRATIONS_ON_START=true — running alembic upgrade heads'; alembic upgrade heads; fi; exec gunicorn --config gunicorn.conf.py 'vbwd.app:create_app()'"]
