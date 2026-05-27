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

# Migrations are NOT run here (S03) — they live in a separate one-shot
# `vbwd_migrate` compose service / `make migrate` step, so a hung or failed
# migration cannot block container readiness or strand a rollout mid-deploy.
# This CMD only ensures `plugins.json` exists and launches gunicorn.
CMD ["sh", "-c", "[ -f /app/plugins/plugins.json ] || cp /app/plugins/plugins.json.dist /app/plugins/plugins.json && gunicorn --config gunicorn.conf.py 'vbwd.app:create_app()'"]
