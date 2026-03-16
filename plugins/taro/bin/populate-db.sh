#!/bin/bash
# Populate Tarot Card Database
# ============================
# Populates the Tarot plugin database with 78 arcana cards.
# Runs the populate_arcanas.py script inside the backend API container via docker compose.
#
# Usage:
#   ./plugins/taro/bin/populate-db.sh           # Populate all arcana cards
#
# Requirements:
#   - docker compose running with api service
#   - PostgreSQL database running and migrated
#
# This script:
#   1. Checks that the backend API service is running
#   2. Runs the populate_arcanas.py script inside the api container
#   3. Populates the arcana table with 22 major and 56 minor cards
#   4. Associates cards with SVG image assets

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Determine script location and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR"/../../../.. && pwd)"

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Tarot Card Database Population        ║${NC}"
echo -e "${BLUE}║  Populate Arcana Table                 ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Check if docker compose is running and api service is available
if ! docker compose ps 2>/dev/null | grep -q "api.*Up"; then
    echo -e "${RED}✗ Error: api service is not running${NC}"
    echo ""
    echo "Please start the services first:"
    echo "  cd $PROJECT_ROOT/vbwd-backend"
    echo "  make up"
    exit 1
fi

echo -e "${YELLOW}[1/1] Populating arcana table with 78 tarot cards...${NC}"
echo ""

# Run the populate_arcanas.py script inside the api container
# The script is located at /app/plugins/taro/src/bin/populate_arcanas.py inside the container
docker compose exec -T api python /app/plugins/taro/src/bin/populate_arcanas.py

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║        Database Population Complete    ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${GREEN}✓ All 78 tarot cards populated${NC}"
    echo "  • 22 Major Arcana cards (0-21)"
    echo "  • 14 Cups cards (Ace-King)"
    echo "  • 14 Wands cards (Ace-King)"
    echo "  • 14 Swords cards (Ace-King)"
    echo "  • 14 Pentacles cards (Ace-King)"
    echo ""
    echo "Asset locations:"
    echo "  Backend: $SCRIPT_DIR/assets/arcana/"
    echo "  Frontend: $PROJECT_ROOT/vbwd-frontend/user/plugins/taro/assets/arcana/"
    echo ""
    exit 0
else
    echo ""
    echo -e "${RED}✗ Failed to populate arcana table${NC}"
    exit 1
fi
