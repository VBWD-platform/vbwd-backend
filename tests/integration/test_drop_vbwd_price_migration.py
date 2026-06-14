"""S85.1a — the CORE ``vbwd_price`` table-drop migration is up/down/up clean.

Runs the ``20260613_1100_drop_vbwd_price`` migration against a throwaway
database seeded with the pre-migration ``vbwd_currency`` + ``vbwd_price`` shape
(so it never touches the shared test DB):

- ``upgrade`` drops ``vbwd_price``;
- ``downgrade`` recreates the bare ``vbwd_price`` table (mirroring its original
  columns, including the ``vbwd_currency`` FK) — but NOT any cross-plugin FK;
- the migration is reversible (up → down → up).
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text


def _admin_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/postgres"


def _table_exists(engine, table: str) -> bool:
    return inspect(engine).has_table(table)


@pytest.fixture
def throwaway_db():
    admin_url = _admin_url()
    db_name = f"drop_price_mig_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    target_engine = create_engine(target_url)
    with target_engine.connect() as conn:
        # Minimal pre-migration shape: vbwd_currency (FK target) + vbwd_price.
        conn.execute(
            text(
                "CREATE TABLE vbwd_currency ("
                "  id uuid PRIMARY KEY,"
                "  code varchar(3) NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE vbwd_price ("
                "  price_float double precision NOT NULL,"
                "  price_decimal numeric(10, 2) NOT NULL,"
                "  currency_id uuid NOT NULL REFERENCES vbwd_currency(id),"
                "  taxes jsonb,"
                "  gross_amount numeric(10, 2) NOT NULL,"
                "  net_amount numeric(10, 2) NOT NULL,"
                "  description varchar(255),"
                "  id uuid PRIMARY KEY,"
                "  created_at timestamp NOT NULL,"
                "  updated_at timestamp NOT NULL,"
                "  version integer NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX ix_vbwd_price_currency_id " "ON vbwd_price (currency_id)"
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
            here, "..", "..", "alembic", "versions", "20260613_1100_drop_vbwd_price.py"
        )
    )
    spec = importlib.util.spec_from_file_location("drop_vbwd_price_migration", path)
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


def test_table_present_before_migration(throwaway_db):
    engine = create_engine(throwaway_db)
    try:
        assert _table_exists(engine, "vbwd_price")
    finally:
        engine.dispose()


def test_upgrade_drops_vbwd_price(throwaway_db):
    _run(throwaway_db, "upgrade")
    engine = create_engine(throwaway_db)
    try:
        assert not _table_exists(engine, "vbwd_price")
    finally:
        engine.dispose()


def test_up_down_up_is_reversible(throwaway_db):
    _run(throwaway_db, "upgrade")
    _run(throwaway_db, "downgrade")
    engine = create_engine(throwaway_db)
    try:
        assert _table_exists(engine, "vbwd_price"), "downgrade must recreate the table"
        # The down recreation does NOT re-add a cross-plugin FK.
        fks = inspect(engine).get_foreign_keys("vbwd_price")
        referred = {fk["referred_table"] for fk in fks}
        assert "subscription_tarif_plan" not in referred
    finally:
        engine.dispose()

    _run(throwaway_db, "upgrade")
    engine = create_engine(throwaway_db)
    try:
        assert not _table_exists(engine, "vbwd_price")
    finally:
        engine.dispose()
