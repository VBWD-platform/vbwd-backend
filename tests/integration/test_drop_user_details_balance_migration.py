"""Migration coverage for dropping ``vbwd_user_details.balance`` (S94 Slice 1).

Verifies the ``20260616_1200_drop_balance`` migration removes the dead column,
that its downgrade re-adds it (``Numeric(10,2) NOT NULL DEFAULT 0.00``), and
that the whole thing survives up → down → up.

Runs against a throwaway database so it never touches the shared test DB or its
alembic version table.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

TABLE = "vbwd_user_details"
COLUMN = "balance"


def _admin_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/postgres"


def _has_column(engine) -> bool:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": TABLE, "c": COLUMN},
        ).fetchall()
    return len(rows) > 0


@pytest.fixture
def throwaway_db():
    """Empty DB with a minimal ``vbwd_user_details`` table that still has the
    ``balance`` column (the pre-migration shape); dropped afterwards."""
    admin_url = _admin_url()
    db_name = f"drop_balance_mig_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    target_engine = create_engine(target_url)
    with target_engine.connect() as conn:
        conn.execute(
            text(
                f"CREATE TABLE {TABLE} ("
                "  id uuid PRIMARY KEY,"
                f"  {COLUMN} numeric(10,2) NOT NULL DEFAULT 0.00"
                ")"
            )
        )
        conn.commit()
    try:
        yield target_url
    finally:
        target_engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin_engine.dispose()


def _load_migration():
    import importlib.util

    here = os.path.dirname(__file__)
    path = os.path.abspath(
        os.path.join(
            here,
            "..",
            "..",
            "alembic",
            "versions",
            "20260616_1200_drop_user_details_balance.py",
        )
    )
    spec = importlib.util.spec_from_file_location("drop_balance_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(url: str, direction: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    module = _load_migration()
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            migration_context = MigrationContext.configure(connection)
            with Operations.context(migration_context):
                getattr(module, direction)()
            connection.commit()
    finally:
        engine.dispose()


def test_up_down_up_round_trip(throwaway_db):
    engine = create_engine(throwaway_db)
    try:
        assert _has_column(engine) is True  # pre-migration shape

        _run(throwaway_db, "upgrade")
        assert _has_column(engine) is False  # dropped

        _run(throwaway_db, "downgrade")
        assert _has_column(engine) is True  # re-added

        _run(throwaway_db, "upgrade")
        assert _has_column(engine) is False  # dropped again
    finally:
        engine.dispose()
