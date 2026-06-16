"""Migration coverage for the S97.1 ``vbwd_llm_connection`` table.

Verifies ``20260615_1100_llm_connection`` is reversible (up -> down -> up) and
resolves standalone (a pure core table, no plugin FK). Runs against a throwaway
database so it never touches the shared test DB.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text


def _admin_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/postgres"


@pytest.fixture
def throwaway_db():
    admin_url = _admin_url()
    db_name = f"llm_conn_mig_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    try:
        yield target_url
    finally:
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
            "20260615_1100_llm_connection.py",
        )
    )
    spec = importlib.util.spec_from_file_location("llm_conn_migration", path)
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


def _has_table(url: str) -> bool:
    engine = create_engine(url)
    try:
        return "vbwd_llm_connection" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_upgrade_creates_table_with_columns(throwaway_db):
    _run(throwaway_db, "upgrade")
    assert _has_table(throwaway_db)

    engine = create_engine(throwaway_db)
    try:
        columns = {
            col["name"] for col in inspect(engine).get_columns("vbwd_llm_connection")
        }
    finally:
        engine.dispose()
    for expected in {
        "slug",
        "connection_name",
        "api_endpoint",
        "api_key",
        "model",
        "provider",
        "is_active",
        "is_default",
        "last_active_at",
    }:
        assert expected in columns


def test_up_down_up_is_reversible(throwaway_db):
    _run(throwaway_db, "upgrade")
    assert _has_table(throwaway_db)
    _run(throwaway_db, "downgrade")
    assert not _has_table(throwaway_db)
    _run(throwaway_db, "upgrade")
    assert _has_table(throwaway_db)
