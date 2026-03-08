#!/bin/bash
# Populate CMS Demo Data
# ======================
# Populates the CMS plugin database with demo styles, widgets, layouts, and pages.
# Runs the populate_cms.py script inside the backend API container via docker compose.
#
# Usage:
#   ./plugins/cms/bin/populate-db.sh
#
# Requirements:
#   - docker compose running with api service
#   - PostgreSQL database running and migrated (including cms_templates migration)
#
# This script creates:
#   - 10 CSS themes (5 light: clean/warm/cool/soft/paper, 5 dark: midnight/charcoal/forest/purple/carbon)
#   - 8 widgets: header-nav, footer-nav, hero-home1, hero-home2, cta-primary,
#                features-3col, pricing-2col, testimonials
#   - 4 layouts: home-v1, home-v2, landing, content-page
#   - 5 demo pages: home1, home2, landing2, landing3, about

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR"/../../.. && pwd)"

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  CMS Plugin — Demo Data Population    ║${NC}"
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

echo -e "${YELLOW}Populating CMS demo data...${NC}"
echo ""

docker compose exec -T api python /app/plugins/cms/src/bin/populate_cms.py

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   CMS Demo Data Population Complete   ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${GREEN}✓ Styles: 5 light + 5 dark themes${NC}"
    echo -e "${GREEN}✓ Widgets: 8 reusable content blocks${NC}"
    echo -e "${GREEN}✓ Layouts: home-v1, home-v2, landing, content-page${NC}"
    echo -e "${GREEN}✓ Pages: home1, home2, landing2, landing3, about${NC}"
    echo ""
    echo "View in admin: http://localhost:8081/admin/cms/styles"
    echo ""
    exit 0
else
    echo ""
    echo -e "${RED}✗ Failed to populate CMS demo data${NC}"
    exit 1
fi
