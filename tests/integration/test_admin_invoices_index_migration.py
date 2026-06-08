"""S48.3 — core admin invoice list: index the sort column, up/down/up clean.

GET /api/v1/admin/invoices/ always sorts by ``created_at DESC``; ``status`` and
``user_id`` are already indexed on the model, but ``created_at`` is not. This
core migration adds ``ix_vbwd_user_invoice_created_at``.

Runs the migration's ``upgrade`` / ``downgrade`` directly against the live
integration connection and asserts the index appears, disappears, reappears —
proving it is reversible and idempotent-safe.
"""
import importlib.util
import re
from pathlib import Path

import pytest
from sqlalchemy import inspect

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND_ROOT / "alembic/versions/20260608_inv_admin_idx.py"

ALEMBIC_VERSION_NUM_MAXLEN = 32
TABLE = "vbwd_user_invoice"
EXPECTED_INDEX_COLUMNS = {("created_at",)}


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
    spec = importlib.util.spec_from_file_location("inv_admin_idx", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _index_column_sets(connection):
    indexes = inspect(connection).get_indexes(TABLE)
    return {tuple(index["column_names"]) for index in indexes}


def test_migration_revision_well_formed():
    src = MIGRATION.read_text()
    revision = re.search(r'^revision = "([^"]+)"', src, re.M).group(1)
    down = re.search(r'^down_revision = "([^"]+)"', src, re.M).group(1)
    assert revision == "20260608_inv_admin_idx"
    assert len(revision) <= ALEMBIC_VERSION_NUM_MAXLEN
    # Anchors on the prior core head (core migrations resolve standalone).
    assert down == "20260608_1000_remove_user_role"


def test_migration_up_down_up_creates_created_at_index(app):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from vbwd.extensions import db

    module = _load_migration()
    with app.app_context():
        connection = db.session.connection()
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            # The live DB already has the migration applied (it's at head), so
            # start from a known-down state, then exercise up/down/up.
            module.downgrade()
            after_down = _index_column_sets(connection)
            assert not (EXPECTED_INDEX_COLUMNS & after_down)

            module.upgrade()
            after_up = _index_column_sets(connection)
            assert EXPECTED_INDEX_COLUMNS <= after_up

            module.downgrade()
            after_down_again = _index_column_sets(connection)
            assert not (EXPECTED_INDEX_COLUMNS & after_down_again)

            module.upgrade()
            after_up_again = _index_column_sets(connection)
            assert EXPECTED_INDEX_COLUMNS <= after_up_again

        db.session.rollback()
