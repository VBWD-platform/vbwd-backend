"""Migration coverage for the core ``GUEST`` enum value (S86.1 D-core).

Verifies the ``20260613_1300_add_guest_role`` migration adds ``GUEST`` to
the native Postgres ``userrole`` enum, is idempotent (up/down/up), and that
its downgrade is the documented no-op (Postgres cannot drop an enum value).

Runs against a throwaway database so it never touches the shared test DB or
its alembic version table.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text


def _admin_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/postgres"


def _enum_values(engine) -> set:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT e.enumlabel FROM pg_enum e "
                "JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'userrole'"
            )
        ).fetchall()
    return {row[0] for row in rows}


@pytest.fixture
def throwaway_db():
    """Create an empty database with just the ``userrole`` enum, yield its
    URL, and drop it afterwards."""
    admin_url = _admin_url()
    db_name = f"guest_role_mig_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    target_engine = create_engine(target_url)
    with target_engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TYPE userrole AS ENUM "
                "('SUPER_ADMIN', 'ADMIN', 'USER', 'VENDOR', 'BOT')"
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
    """Load the migration module by file path (its name starts with a digit
    so it isn't importable as a dotted module)."""
    import importlib.util

    here = os.path.dirname(__file__)
    path = os.path.abspath(
        os.path.join(
            here,
            "..",
            "..",
            "alembic",
            "versions",
            "20260613_1300_add_guest_role.py",
        )
    )
    spec = importlib.util.spec_from_file_location("guest_role_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration_upgrade(url: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    module = _load_migration()
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            migration_context = MigrationContext.configure(connection)
            with Operations.context(migration_context):
                module.upgrade()
    finally:
        engine.dispose()


def test_guest_value_absent_before_migration(throwaway_db):
    engine = create_engine(throwaway_db)
    try:
        assert "GUEST" not in _enum_values(engine)
    finally:
        engine.dispose()


def test_migration_adds_guest_value_and_is_idempotent(throwaway_db):
    _run_migration_upgrade(throwaway_db)

    engine = create_engine(throwaway_db)
    try:
        assert "GUEST" in _enum_values(engine)
    finally:
        engine.dispose()

    # up → (down is a no-op) → up again must not raise (IF NOT EXISTS).
    _load_migration().downgrade()  # documented no-op
    _run_migration_upgrade(throwaway_db)

    engine = create_engine(throwaway_db)
    try:
        assert "GUEST" in _enum_values(engine)
    finally:
        engine.dispose()
