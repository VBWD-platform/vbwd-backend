FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    git \
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

# Plugin packages (opt-in, pip-based) — installed from git as pip wheels into
# site-packages as the `plugins.<name>` namespace, merged with /app/plugins via
# the pkgutil-extended plugins/__init__.py. The build only does this when the
# deploy workflow has written a non-empty plugins-requirements.txt into the build
# context; otherwise it is a no-op and the legacy clone+COPY model is used as-is.
# A BuildKit secret (id=git_token) supplies a token for private plugin repos and
# is never written to a persisted layer.
RUN --mount=type=secret,id=git_token \
    if [ -s plugins-requirements.txt ]; then \
      echo "[build] installing plugin packages from plugins-requirements.txt"; \
      TOKEN="$(cat /run/secrets/git_token 2>/dev/null || true)"; \
      if [ -n "$TOKEN" ]; then \
        git config --global url."https://x-access-token:${TOKEN}@github.com/".insteadOf "https://github.com/"; \
      fi; \
      pip install --no-cache-dir -r plugins-requirements.txt; \
      rm -f /root/.gitconfig; \
    else \
      echo "[build] no plugins-requirements.txt — using plugins present under ./plugins (clone model)"; \
    fi

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
# Plugin runtime deps: plugins are bind-mounted at runtime (not COPYd into the
# image), so any plugin-local requirements.txt is installed here at start. This
# is plugin-agnostic — it installs whatever plugins are present, naming none.
CMD ["sh", "-c", "set -e; [ -f /app/plugins/plugins.json ] || cp /app/plugins/plugins.json.dist /app/plugins/plugins.json; for r in /app/plugins/*/requirements.txt; do [ -f \"$r\" ] && { echo \"[entrypoint] installing plugin deps: $r\"; pip install --no-cache-dir -r \"$r\"; }; done; if [ \"${RUN_MIGRATIONS_ON_START:-false}\" = \"true\" ]; then echo '[entrypoint] RUN_MIGRATIONS_ON_START=true — running alembic upgrade heads'; alembic upgrade heads; fi; exec gunicorn --config gunicorn.conf.py 'vbwd.app:create_app()'"]
