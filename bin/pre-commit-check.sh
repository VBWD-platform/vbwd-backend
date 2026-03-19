#!/bin/bash
#
# Pre-Commit Check Script
# =======================
# Runs all code quality checks before commit/push.
# Used by developers locally and GitHub Actions CI/CD.
#
# Usage:
#   ./bin/pre-commit-check.sh           # Run all checks (lint + unit + integration)
#   ./bin/pre-commit-check.sh --full    # Explicit full run (lint + unit + integration)
#   ./bin/pre-commit-check.sh --quick   # Skip integration tests
#   ./bin/pre-commit-check.sh --lint    # Only static analysis
#   ./bin/pre-commit-check.sh --unit    # Only unit tests
#   ./bin/pre-commit-check.sh --integration  # Only integration tests
#
# Exit Codes:
#   0 - All checks passed
#   1 - Static analysis failed
#   2 - Unit tests failed
#   3 - Integration tests failed
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Determine script location and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Change to project root
cd "$PROJECT_ROOT"

# Track results
LINT_RESULT=0
UNIT_RESULT=0
INTEGRATION_RESULT=0

# Parse arguments
RUN_LINT=true
RUN_UNIT=true
RUN_INTEGRATION=true
PLUGIN_NAME=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --full)
            RUN_LINT=true
            RUN_UNIT=true
            RUN_INTEGRATION=true
            shift
            ;;
        --quick)
            RUN_INTEGRATION=false
            shift
            ;;
        --lint)
            RUN_UNIT=false
            RUN_INTEGRATION=false
            shift
            ;;
        --unit)
            RUN_LINT=false
            RUN_INTEGRATION=false
            shift
            ;;
        --integration)
            RUN_LINT=false
            RUN_UNIT=false
            shift
            ;;
        --plugin)
            PLUGIN_NAME="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --quick              Skip integration tests"
            echo "  --lint               Only run static analysis"
            echo "  --unit               Only run unit tests"
            echo "  --integration        Only run integration tests"
            echo "  --plugin <name>      Run checks for a single plugin only"
            echo "  --help, -h           Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 --quick                    # All: lint + unit (skip integration)"
            echo "  $0 --plugin booking --quick    # Booking plugin only: lint + unit"
            echo "  $0 --plugin booking --unit     # Booking plugin only: unit tests"
            exit 0
            ;;
        *)
            shift
            ;;
    esac
done

# Set paths based on plugin scope
if [ -n "$PLUGIN_NAME" ]; then
    LINT_PATHS="plugins/$PLUGIN_NAME/"
    UNIT_PATHS="plugins/$PLUGIN_NAME/tests/unit/"
    INTEGRATION_PATHS="plugins/$PLUGIN_NAME/tests/integration/"
else
    LINT_PATHS="vbwd/ tests/"
    UNIT_PATHS="tests/unit/ plugins/*/tests/unit/"
    INTEGRATION_PATHS="tests/integration/ plugins/*/tests/integration/"
fi

# Detect environment (Docker, CI, or local)
IN_DOCKER=false
if [ -f /.dockerenv ] || grep -q docker /proc/1/cgroup 2>/dev/null; then
    IN_DOCKER=true
fi
# In CI (GitHub Actions), run commands directly — services are already running
if [ -n "$GITHUB_ACTIONS" ] || [ "$CI" = "true" ]; then
    IN_DOCKER=true
fi

# Helper function for section headers
print_header() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
}

# Helper function for success/failure messages
print_result() {
    if [ "$2" -eq 0 ]; then
        echo -e "${GREEN}[PASS]${NC} $1"
    else
        echo -e "${RED}[FAIL]${NC} $1"
    fi
}

# ============================================
# PART A: Static Code Analysis
# ============================================
run_static_analysis() {
    print_header "PART A: Static Code Analysis"

    local failed=0

    # A.1: Black - Code Formatter (check mode)
    echo -e "${YELLOW}[A.1] Running Black (code formatter check)...${NC}"
    if $IN_DOCKER; then
        black --check --diff $LINT_PATHS 2>&1 || failed=1
    else
        docker compose run --rm -T test black --check --diff $LINT_PATHS 2>&1 || failed=1
    fi
    print_result "Black formatter check" $failed

    if [ $failed -ne 0 ]; then
        echo -e "${YELLOW}  Tip: Run 'black vbwd/ tests/' to auto-fix formatting${NC}"
    fi

    # A.2: Flake8 - Code Sniffer (style checker)
    echo ""
    echo -e "${YELLOW}[A.2] Running Flake8 (code style checker)...${NC}"
    local flake_failed=0
    if $IN_DOCKER; then
        flake8 $LINT_PATHS --max-line-length=120 --extend-ignore=E203,W503 2>&1 || flake_failed=1
    else
        docker compose run --rm -T test flake8 $LINT_PATHS --max-line-length=120 --extend-ignore=E203,W503 2>&1 || flake_failed=1
    fi
    print_result "Flake8 style check" $flake_failed
    [ $flake_failed -ne 0 ] && failed=1

    # A.3: Mypy - Static Type Analyzer
    echo ""
    echo -e "${YELLOW}[A.3] Running Mypy (static type analyzer)...${NC}"
    local mypy_failed=0
    if $IN_DOCKER; then
        mypy $LINT_PATHS --ignore-missing-imports --no-error-summary 2>&1 || mypy_failed=1
    else
        docker compose run --rm -T test mypy $LINT_PATHS --ignore-missing-imports --no-error-summary 2>&1 || mypy_failed=1
    fi
    print_result "Mypy type check" $mypy_failed
    [ $mypy_failed -ne 0 ] && failed=1

    echo ""
    if [ $failed -eq 0 ]; then
        echo -e "${GREEN}Static analysis: ALL CHECKS PASSED${NC}"
    else
        echo -e "${RED}Static analysis: SOME CHECKS FAILED${NC}"
    fi

    return $failed
}

# ============================================
# PART B: Unit Tests
# ============================================
run_unit_tests() {
    print_header "PART B: Unit Tests"

    local failed=0

    echo -e "${YELLOW}Running unit tests with pytest (core + plugins)...${NC}"
    echo ""

    if $IN_DOCKER; then
        pytest $UNIT_PATHS -q --tb=line 2>&1
        local exit_code=$?
        # exit 5 = no tests collected (not a failure)
        [ $exit_code -ne 0 ] && [ $exit_code -ne 5 ] && failed=1
    else
        docker compose run --rm test bash -c "pytest $UNIT_PATHS -q --tb=line"
        local exit_code=$?
        [ $exit_code -ne 0 ] && [ $exit_code -ne 5 ] && failed=1
    fi

    echo ""
    print_result "Unit tests" $failed

    return $failed
}

# ============================================
# PART C: Integration Tests
# ============================================
run_integration_tests() {
    print_header "PART C: Integration Tests"

    local failed=0

    echo -e "${YELLOW}Running integration tests with real PostgreSQL (core + plugins)...${NC}"
    echo ""

    # Ensure services are running
    if ! $IN_DOCKER; then
        echo "Checking if services are running..."
        if ! docker compose ps | grep -q "api.*Up"; then
            echo -e "${YELLOW}Starting services...${NC}"
            docker compose up -d
            echo "Waiting for services to be ready..."
            sleep 5
        fi
    fi

    if $IN_DOCKER; then
        # Inside Docker, run directly (core + plugin integration tests)
        pytest $INTEGRATION_PATHS -q --tb=line 2>&1 || failed=1
    else
        # Outside Docker, use the test-integration service
        docker compose --profile test-integration run --rm test-integration \
            bash -c "pytest $INTEGRATION_PATHS -q --tb=line" 2>&1 || failed=1
    fi

    echo ""
    print_result "Integration tests" $failed

    return $failed
}

# ============================================
# Main Execution
# ============================================
main() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════╗"
    echo "║        PRE-COMMIT CHECK SCRIPT           ║"
    if [ -n "$PLUGIN_NAME" ]; then
    echo "║     plugin: $PLUGIN_NAME"
    else
    echo "║     vbwd-backend quality assurance       ║"
    fi
    echo "╚══════════════════════════════════════════╝"
    echo -e "${NC}"

    local start_time=$(date +%s)

    # Part A: Static Analysis
    if [ "$RUN_LINT" = true ]; then
        run_static_analysis || LINT_RESULT=1
    fi

    # Part B: Unit Tests
    if [ "$RUN_UNIT" = true ]; then
        run_unit_tests || UNIT_RESULT=1
    fi

    # Part C: Integration Tests
    if [ "$RUN_INTEGRATION" = true ]; then
        run_integration_tests || INTEGRATION_RESULT=1
    fi

    # ============================================
    # Summary
    # ============================================
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    print_header "SUMMARY"

    [ "$RUN_LINT" = true ] && print_result "Part A: Static Analysis" $LINT_RESULT
    [ "$RUN_UNIT" = true ] && print_result "Part B: Unit Tests" $UNIT_RESULT
    [ "$RUN_INTEGRATION" = true ] && print_result "Part C: Integration Tests" $INTEGRATION_RESULT

    echo ""
    echo "Duration: ${duration}s"
    echo ""

    # Determine exit code
    if [ $LINT_RESULT -ne 0 ]; then
        echo -e "${RED}FAILED: Static analysis errors must be fixed before commit${NC}"
        exit 1
    elif [ $UNIT_RESULT -ne 0 ]; then
        echo -e "${RED}FAILED: Unit tests must pass before commit${NC}"
        exit 2
    elif [ $INTEGRATION_RESULT -ne 0 ]; then
        echo -e "${RED}FAILED: Integration tests must pass before commit${NC}"
        exit 3
    else
        echo -e "${GREEN}SUCCESS: All checks passed! Ready to commit.${NC}"
        exit 0
    fi
}

# Run main function
main
