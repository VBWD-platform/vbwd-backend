#!/bin/bash
# Populate Email Templates
# ========================
# Seeds the email_template table with default transactional email templates
# for all 8 built-in event types.
# Runs Alembic migrations first, then populate_email.py inside the backend API container.
#
# Behaviour: INSERT-only — existing templates (matched by event_type) are skipped.
# Safe to re-run at any time.
#
# Usage:
#   ./plugins/email/bin/populate-db.sh
#
# Requirements:
#   - docker compose running with api service
#   - PostgreSQL database running
#   - Required migration (applied automatically by this script):
#       20260314_create_email_template_table
#
# This script creates (if not already present):
#   - subscription.activated
#   - subscription.cancelled
#   - subscription.payment_failed
#   - subscription.renewed
#   - trial.started
#   - trial.expiring_soon
#   - user.registered
#   - user.password_reset

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR"/../../.. && pwd)"

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Email Plugin — Template Population   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

cd "$PROJECT_ROOT/vbwd-backend" 2>/dev/null || cd "$PROJECT_ROOT" 2>/dev/null

if ! docker compose ps 2>/dev/null | grep -q "api.*Up"; then
    echo -e "${RED}✗ Error: api service is not running${NC}"
    echo ""
    echo "Please start the services first:"
    echo "  cd $PROJECT_ROOT/vbwd-backend"
    echo "  make up"
    exit 1
fi

echo -e "${YELLOW}Step 1/2 — Running Alembic migrations...${NC}"
echo ""

docker compose exec -T api python -m alembic upgrade heads

if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}✗ Alembic migrations failed — aborting population${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 2/2 — Seeding default email templates (insert-only)...${NC}"
echo ""

docker compose exec -T api python /app/plugins/email/src/bin/populate_email.py

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  Email Template Population Complete   ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${GREEN}✓ 8 default templates seeded${NC}"
    echo -e "${GREEN}  (skipped any that already existed)${NC}"
    echo ""
    echo "  Admin: http://localhost:8081/admin/email/templates"
    echo ""
    exit 0
else
    echo ""
    echo -e "${RED}✗ Failed to populate email templates${NC}"
    exit 1
fi
