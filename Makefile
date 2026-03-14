.PHONY: up down build test test-unit test-integration test-integration-keep-data test-coverage seed-test-data cleanup-test-data reset-demo populate-ghrm logs shell clean lint pre-commit pre-commit-quick

# Start all services
up:
	docker compose up -d

# Start with rebuild
up-build:
	docker compose up -d --build

# Stop services
down:
	docker compose down

# Build containers
build:
	docker compose build

# Run all tests (unit tests with SQLite)
test:
	docker compose run --rm test pytest tests/unit/ plugins/ --ignore=tests/integration -v

# Run unit tests only
test-unit:
	docker compose run --rm test pytest tests/unit/ plugins/ -v

# Run integration tests with real PostgreSQL and HTTP requests
# Requires: services running (make up)
test-integration:
	docker compose --profile test-integration run --rm test-integration pytest tests/integration/ -v

# Run integration tests and keep test data for debugging
test-integration-keep-data:
	TEST_DATA_CLEANUP=false docker compose --profile test-integration run --rm test-integration pytest tests/integration/ -v

# Seed test data manually (requires TEST_DATA_SEED=true)
seed-test-data:
	TEST_DATA_SEED=true docker compose exec api flask seed-test-data

# Cleanup test data manually (requires TEST_DATA_CLEANUP=true)
cleanup-test-data:
	TEST_DATA_CLEANUP=true docker compose exec api flask cleanup-test-data

# Reset database to clean demo state (3 plans, 2 addons, 3 token bundles)
reset-demo:
	docker compose exec api flask --app "src:create_app()" reset-demo --yes

# Populate GHRM CMS data (layouts, widgets, pages) — idempotent, safe to re-run
populate-ghrm:
	./plugins/ghrm/bin/populate-db.sh

# Run tests with coverage
test-coverage:
	docker compose run --rm test pytest --cov=src --cov-report=term-missing

# Run all tests (unit + integration)
test-all: test test-integration

# View logs
logs:
	docker compose logs -f

# Shell access to API container
shell:
	docker compose exec api bash

# Clean up
clean:
	docker compose down -v
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Static code analysis only (black, flake8, mypy)
lint:
	./bin/pre-commit-check.sh --lint

# Full pre-commit check (lint + unit + integration)
pre-commit:
	./bin/pre-commit-check.sh

# Quick pre-commit check (lint + unit, skip integration)
pre-commit-quick:
	./bin/pre-commit-check.sh --quick
