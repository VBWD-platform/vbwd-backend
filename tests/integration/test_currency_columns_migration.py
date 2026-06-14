"""Migration coverage for the S84 ``vbwd_currency`` column change.

Verifies the ``20260613_1000_currency_drop_flags_widen_rate`` migration:
- drops ``is_active`` and ``is_default`` from ``vbwd_currency``;
- widens ``exchange_rate`` from ``Numeric(10, 6)`` to ``Numeric(18, 8)``;
- is reversible (up → down → up), where ``down`` re-adds the two columns
  nullable and narrows the rate back.

Runs against a throwaway database with just the pre-migration
``vbwd_currency`` shape so it never touches the shared test DB.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text


def _admin_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/postgres"


def _columns(engine) -> dict:
    """Return {column_name: (data_type, numeric_precision, numeric_scale)}."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, data_type, numeric_precision, numeric_scale "
                "FROM information_schema.columns "
                "WHERE table_name = 'vbwd_currency'"
            )
        ).fetchall()
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


@pytest.fixture
def throwaway_db():
    admin_url = _admin_url()
    db_name = f"curr_flags_mig_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    target_engine = create_engine(target_url)
    with target_engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE vbwd_currency ("
                "  id uuid PRIMARY KEY,"
                "  code varchar(3) NOT NULL,"
                "  name varchar(100) NOT NULL,"
                "  symbol varchar(10) NOT NULL,"
                "  exchange_rate numeric(10, 6) NOT NULL DEFAULT 1.0,"
                "  is_default boolean NOT NULL DEFAULT false,"
                "  is_active boolean NOT NULL DEFAULT true,"
                "  decimal_places integer NOT NULL DEFAULT 2"
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
            "20260613_1000_currency_drop_flags_widen_rate.py",
        )
    )
    spec = importlib.util.spec_from_file_location("curr_flags_migration", path)
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


def test_columns_present_before_migration(throwaway_db):
    engine = create_engine(throwaway_db)
    try:
        columns = _columns(engine)
        assert "is_active" in columns
        assert "is_default" in columns
        assert columns["exchange_rate"][1] == 10  # precision
        assert columns["exchange_rate"][2] == 6  # scale
    finally:
        engine.dispose()


def test_upgrade_drops_flags_and_widens_rate(throwaway_db):
    _run(throwaway_db, "upgrade")

    engine = create_engine(throwaway_db)
    try:
        columns = _columns(engine)
        assert "is_active" not in columns
        assert "is_default" not in columns
        assert columns["exchange_rate"][1] == 18  # widened precision
        assert columns["exchange_rate"][2] == 8  # widened scale
    finally:
        engine.dispose()


def test_up_down_up_is_reversible(throwaway_db):
    _run(throwaway_db, "upgrade")
    _run(throwaway_db, "downgrade")

    engine = create_engine(throwaway_db)
    try:
        columns = _columns(engine)
        assert "is_active" in columns
        assert "is_default" in columns
        assert columns["exchange_rate"][1] == 10  # narrowed back
        assert columns["exchange_rate"][2] == 6
    finally:
        engine.dispose()

    _run(throwaway_db, "upgrade")

    engine = create_engine(throwaway_db)
    try:
        columns = _columns(engine)
        assert "is_active" not in columns
        assert "is_default" not in columns
        assert columns["exchange_rate"][1] == 18
    finally:
        engine.dispose()
