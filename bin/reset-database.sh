#!/bin/bash
# Reset Database Script - DESTRUCTIVE OPERATION
# This script will completely reset the database, destroying all data
# Usage: ./bin/reset-database.sh [--skip-demo-data]
#
# What it does:
# 1. Drops and recreates the PostgreSQL database
# 2. Runs all Alembic migrations
# 3. Creates admin and test users
# 4. Optionally installs demo data

set -e

# Change to the directory containing this script's parent (vbwd-backend/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Default values
SKIP_DEMO_DATA=false
FORCE=false
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-AdminPass123@}"
TEST_EMAIL="${TEST_EMAIL:-test@example.com}"
TEST_PASSWORD="${TEST_PASSWORD:-TestPass123@}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-demo-data)
            SKIP_DEMO_DATA=true
            shift
            ;;
        --force|-f)
            FORCE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-demo-data    Skip demo data installation"
            echo "  --force, -f         Skip confirmation prompts (for automation)"
            echo "  --help, -h          Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  ADMIN_EMAIL         Admin email (default: admin@example.com)"
            echo "  ADMIN_PASSWORD      Admin password (default: AdminPass123@)"
            echo "  TEST_EMAIL          Test user email (default: test@example.com)"
            echo "  TEST_PASSWORD       Test user password (default: TestPass123@)"
            echo ""
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo -e "${YELLOW}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${YELLOW}║                  DATABASE RESET WARNING                        ║${NC}"
echo -e "${YELLOW}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${RED}⚠️  THIS WILL PERMANENTLY DELETE ALL DATABASE DATA ⚠️${NC}"
echo ""
echo "This script will:"
echo "  1. Drop the entire PostgreSQL database"
echo "  2. Recreate an empty database"
echo "  3. Run all migrations"
echo "  4. Create test users:"
echo "     - Admin: ${ADMIN_EMAIL}"
echo "     - User:  ${TEST_EMAIL}"

if [ "$SKIP_DEMO_DATA" = false ]; then
    echo "  5. Install demo data (tarif plans, demo users, invoices)"
else
    echo "  5. Skip demo data installation"
fi

echo ""
echo -e "${YELLOW}This operation CANNOT be undone!${NC}"
echo ""

if [ "$FORCE" = true ]; then
    echo -e "${YELLOW}--force flag set, skipping confirmation prompts.${NC}"
else
    read -p "Type 'RESET' to continue, or anything else to cancel: " CONFIRMATION

    if [ "$CONFIRMATION" != "RESET" ]; then
        echo -e "${GREEN}Operation cancelled. Database unchanged.${NC}"
        exit 0
    fi

    echo ""
    echo -e "${RED}Final confirmation required!${NC}"
    read -p "Are you absolutely sure? Type 'YES' to proceed: " FINAL_CONFIRMATION

    if [ "$FINAL_CONFIRMATION" != "YES" ]; then
        echo -e "${GREEN}Operation cancelled. Database unchanged.${NC}"
        exit 0
    fi
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           Starting Database Reset Process                      ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if containers are running
if ! docker compose ps | grep -q "postgres.*Up"; then
    echo -e "${RED}ERROR: PostgreSQL container is not running${NC}"
    echo "Start the containers first with: docker compose up -d"
    exit 1
fi

# Stop the API now — its CMD runs alembic on startup and would race with our migration step
echo "Stopping api service before reset..."
docker compose stop api

# Get database credentials from environment or defaults
DB_USER="${POSTGRES_USER:-vbwd}"
DB_PASSWORD="${POSTGRES_PASSWORD:-vbwd}"
DB_NAME="${POSTGRES_DB:-vbwd}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 1/5: Dropping existing database"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Terminate existing connections and drop database
docker compose exec -T postgres psql -U "$DB_USER" -d postgres << EOF
-- Terminate all connections to the database
SELECT pg_terminate_backend(pg_stat_activity.pid)
FROM pg_stat_activity
WHERE pg_stat_activity.datname = '$DB_NAME'
  AND pid <> pg_backend_pid();

-- Drop database if exists
DROP DATABASE IF EXISTS $DB_NAME;
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Database dropped successfully${NC}"
else
    echo -e "${RED}✗ Failed to drop database${NC}"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 2/5: Creating fresh database"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Create fresh database
docker compose exec -T postgres psql -U "$DB_USER" -d postgres << EOF
CREATE DATABASE $DB_NAME
    WITH OWNER = $DB_USER
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.utf8'
    LC_CTYPE = 'en_US.utf8'
    TEMPLATE = template0;
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Database created successfully${NC}"
else
    echo -e "${RED}✗ Failed to create database${NC}"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 3/5: Running database migrations"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Run migrations in a one-off container so there is no race with the api CMD startup
docker compose run --rm api alembic upgrade head

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Migrations completed successfully${NC}"
else
    echo -e "${RED}✗ Migrations failed${NC}"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 3b: Starting API service"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

docker compose start api

echo "Waiting for api to be ready..."
RETRIES=30
until docker compose exec -T api echo "ok" > /dev/null 2>&1; do
    RETRIES=$((RETRIES - 1))
    if [ $RETRIES -eq 0 ]; then
        echo -e "${RED}✗ API did not come back up in time${NC}"
        docker compose logs --tail=20 api
        exit 1
    fi
    sleep 2
done
echo -e "${GREEN}✓ API is ready${NC}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 4/5: Creating users"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Create admin user
echo "Creating admin user: ${ADMIN_EMAIL}"
docker compose exec -T api python /app/bin/create_admin.py \
    --email "${ADMIN_EMAIL}" --password "${ADMIN_PASSWORD}"

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Failed to create admin user${NC}"
    exit 1
fi

# Create test user
echo "Creating test user: ${TEST_EMAIL}"
docker compose exec -T api python /app/bin/create_user.py \
    --email "${TEST_EMAIL}" --password "${TEST_PASSWORD}"

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Failed to create test user${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Users created successfully${NC}"

# Install demo data if not skipped
if [ "$SKIP_DEMO_DATA" = false ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Step 5/5: Installing demo data"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if [ -f "./bin/install_demo_data.sh" ]; then
        ./bin/install_demo_data.sh
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓ Demo data installed successfully${NC}"
        else
            echo -e "${YELLOW}⚠ Demo data installation had some issues${NC}"
        fi
    else
        echo -e "${YELLOW}⚠ Demo data script not found, skipping${NC}"
    fi
else
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Step 5/5: Skipping demo data installation"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${YELLOW}✓ Demo data installation skipped${NC}"
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            Database Reset Completed Successfully              ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Summary:"
echo "  ✓ Database dropped and recreated"
echo "  ✓ Migrations applied"
echo "  ✓ Admin user created: ${ADMIN_EMAIL}"
echo "  ✓ Test user created:  ${TEST_EMAIL}"

if [ "$SKIP_DEMO_DATA" = false ]; then
    echo "  ✓ Demo data installed"
    echo ""
    echo "Demo Users:"
    echo "  user.free@demo.local / demo123 (Free plan)"
    echo "  user.pro@demo.local / demo123 (Pro plan)"
fi

echo ""
echo "Login Credentials:"
echo "  Admin: ${ADMIN_EMAIL} / ${ADMIN_PASSWORD}"
echo "  User:  ${TEST_EMAIL} / ${TEST_PASSWORD}"
echo ""
