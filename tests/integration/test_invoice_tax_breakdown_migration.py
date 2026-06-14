"""S85.4 gap #1 — the CORE migration adds the per-rate tax columns to the
invoice line item and resolves plugin-free.

Adds ``net_amount``, ``tax_amount`` (``Numeric(10,2)``) and ``tax_breakdown``
(JSONB, default empty list) to ``vbwd_invoice_line_item``. Anchors on the core
chain's own prior head (no cross-plugin coupling), so it resolves on a
core-only install. Exercises ``upgrade`` / ``downgrade`` directly against the
live integration connection and asserts the columns appear, disappear,
reappear — proving it is reversible.
"""
import importlib.util
import re
from pathlib import Path

import pytest
from sqlalchemy import inspect

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND_ROOT / "alembic/versions/20260614_1000_inv_line_tax_bd.py"

ALEMBIC_VERSION_NUM_MAXLEN = 32
TABLE = "vbwd_invoice_line_item"
NEW_COLUMNS = {"net_amount", "tax_amount", "tax_breakdown"}


@pytest.fixture
def app():
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": get_database_url(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "RATELIMIT_ENABLED": False,
    }
    return create_app(test_config)


def _load_migration():
    spec = importlib.util.spec_from_file_location("inv_line_tax_breakdown", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _column_names(connection):
    return {column["name"] for column in inspect(connection).get_columns(TABLE)}


def test_migration_revision_well_formed():
    src = MIGRATION.read_text()
    revision = re.search(r'^revision = "([^"]+)"', src, re.M).group(1)
    down = re.search(r'^down_revision = "([^"]+)"', src, re.M).group(1)
    assert revision == "20260614_1000_inv_line_tax_bd"
    assert len(revision) <= ALEMBIC_VERSION_NUM_MAXLEN
    assert down == "20260613_1500_user_role_lookup"


def test_migration_resolves_plugin_free():
    src = MIGRATION.read_text()
    depends = re.search(r"^depends_on = (.+)$", src, re.M).group(1).strip()
    assert depends == "None"
    down = re.search(r'^down_revision = "([^"]+)"', src, re.M).group(1)
    assert not down.startswith("20260613_sub")


def test_migration_up_down_up_adds_tax_columns(app):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from vbwd.extensions import db

    module = _load_migration()
    with app.app_context():
        connection = db.session.connection()
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.downgrade()
            after_down = _column_names(connection)
            assert not (NEW_COLUMNS & after_down)

            module.upgrade()
            after_up = _column_names(connection)
            assert NEW_COLUMNS <= after_up

            module.downgrade()
            after_down_again = _column_names(connection)
            assert not (NEW_COLUMNS & after_down_again)

            module.upgrade()
            after_up_again = _column_names(connection)
            assert NEW_COLUMNS <= after_up_again

        db.session.rollback()
