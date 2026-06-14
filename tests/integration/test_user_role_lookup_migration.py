"""Migration coverage for the ``vbwd_user_role`` lookup table (role FK).

Verifies the ``20260613_1500_user_role_lookup`` migration against a throwaway
database that starts in the OLD shape (native ``userrole`` enum + a
``vbwd_user`` row), so it never touches the shared test DB:

  * upgrade creates + seeds the lookup table, converts ``role`` to a varchar FK
    preserving the existing value, and drops the native enum type,
  * the conversion is value-preserving (the pre-existing ADMIN user keeps ADMIN),
  * up -> down -> up is clean and idempotent (the seed uses ON CONFLICT).
"""
import importlib.util
import os
import uuid

import pytest
from sqlalchemy import create_engine, text


def _admin_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/postgres"


def _load_migration():
    here = os.path.dirname(__file__)
    path = os.path.abspath(
        os.path.join(
            here,
            "..",
            "..",
            "alembic",
            "versions",
            "20260613_1500_user_role_lookup_table.py",
        )
    )
    spec = importlib.util.spec_from_file_location("user_role_lookup_migration", path)
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
            with connection.begin():
                migration_context = MigrationContext.configure(connection)
                with Operations.context(migration_context):
                    getattr(module, direction)()
    finally:
        engine.dispose()


@pytest.fixture
def legacy_db():
    """Throwaway DB in the pre-migration shape: native ``userrole`` enum and a
    ``vbwd_user`` table holding one ADMIN row."""
    admin_url = _admin_url()
    db_name = f"role_lookup_mig_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    target_engine = create_engine(target_url)
    with target_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TYPE userrole AS ENUM "
                "('SUPER_ADMIN', 'ADMIN', 'USER', 'VENDOR', 'BOT', 'GUEST')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE vbwd_user ("
                "  id uuid PRIMARY KEY,"
                "  email varchar(255) NOT NULL,"
                "  role userrole NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO vbwd_user (id, email, role) "
                "VALUES (:id, 'admin@example.com', 'ADMIN')"
            ),
            {"id": str(uuid.uuid4())},
        )
    target_engine.dispose()
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


def _enum_type_exists(engine) -> bool:
    with engine.connect() as conn:
        found = conn.execute(
            text("SELECT 1 FROM pg_type WHERE typname = 'userrole'")
        ).scalar()
    return found is not None


def _lookup_rows(engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, name FROM vbwd_user_role")).fetchall()
    return {row[0]: row[1] for row in rows}


def _admin_user_role(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT role FROM vbwd_user WHERE email = 'admin@example.com'")
        ).scalar()


def test_upgrade_creates_lookup_converts_role_and_drops_enum(legacy_db):
    _run(legacy_db, "upgrade")

    engine = create_engine(legacy_db)
    try:
        assert _lookup_rows(engine) == {
            "SUPER_ADMIN": "Super Admin",
            "ADMIN": "Admin",
            "USER": "User",
            "VENDOR": "Vendor",
            "BOT": "Bot",
            "GUEST": "Guest",
        }
        # Existing value preserved through the type conversion.
        assert _admin_user_role(engine) == "ADMIN"
        # Native enum type is gone.
        assert _enum_type_exists(engine) is False
    finally:
        engine.dispose()


def test_up_down_up_is_clean(legacy_db):
    _run(legacy_db, "upgrade")
    _run(legacy_db, "downgrade")

    engine = create_engine(legacy_db)
    try:
        # Downgrade restored the native enum and the user value survived.
        assert _enum_type_exists(engine) is True
        assert _admin_user_role(engine) == "ADMIN"
    finally:
        engine.dispose()

    _run(legacy_db, "upgrade")

    engine = create_engine(legacy_db)
    try:
        assert len(_lookup_rows(engine)) == 6
        assert _admin_user_role(engine) == "ADMIN"
        assert _enum_type_exists(engine) is False
    finally:
        engine.dispose()
