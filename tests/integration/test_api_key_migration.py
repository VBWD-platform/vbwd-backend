"""S52.0 — migration coverage for the core ``vbwd_api_key`` table.

Verifies the ``20260606_1000_create_api_key`` migration creates the table,
is reversible, and survives up → down → up against a throwaway database (so
it never touches the shared test DB or its alembic version table). The table
must exist with the expected columns and resolve with no plugins present.
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
    """Create an empty database with just the ``vbwd_user`` table (FK target),
    yield its URL, drop it afterwards."""
    admin_url = _admin_url()
    db_name = f"api_key_mig_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    target_engine = create_engine(target_url)
    with target_engine.connect() as conn:
        # Minimal FK target: the migration declares ON DELETE CASCADE → vbwd_user.id.
        conn.execute(text('CREATE TABLE "vbwd_user" (id UUID PRIMARY KEY)'))
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
            here, "..", "..", "alembic", "versions", "20260606_1000_create_api_key.py"
        )
    )
    spec = importlib.util.spec_from_file_location("api_key_migration", path)
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


def _has_table(url: str, table: str) -> bool:
    engine = create_engine(url)
    try:
        return inspect(engine).has_table(table)
    finally:
        engine.dispose()


def test_table_absent_before_migration(throwaway_db):
    assert not _has_table(throwaway_db, "vbwd_api_key")


def test_migration_creates_table_with_expected_columns(throwaway_db):
    _run(throwaway_db, "upgrade")

    assert _has_table(throwaway_db, "vbwd_api_key")
    engine = create_engine(throwaway_db)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("vbwd_api_key")}
    finally:
        engine.dispose()
    assert {
        "id",
        "user_id",
        "label",
        "key_hash",
        "key_prefix",
        "scopes",
        "ip_whitelist",
        "is_active",
        "created_by_user_id",
        "last_used_at",
    }.issubset(columns)


def test_migration_up_down_up_is_reversible(throwaway_db):
    _run(throwaway_db, "upgrade")
    _run(throwaway_db, "downgrade")
    assert not _has_table(throwaway_db, "vbwd_api_key")
    _run(throwaway_db, "upgrade")
    assert _has_table(throwaway_db, "vbwd_api_key")


def test_cascade_delete_removes_keys_with_owner(throwaway_db):
    _run(throwaway_db, "upgrade")
    engine = create_engine(throwaway_db)
    user_id = uuid.uuid4()
    key_id = uuid.uuid4()
    try:
        with engine.connect() as conn:
            conn.execute(
                text('INSERT INTO "vbwd_user" (id) VALUES (:uid)'), {"uid": user_id}
            )
            conn.execute(
                text(
                    'INSERT INTO "vbwd_api_key" '
                    "(id, user_id, label, key_hash, key_prefix, scopes, "
                    "ip_whitelist, is_active, created_at, updated_at, version) "
                    "VALUES (:id, :uid, 'k', :h, 'vbwdk_x', '[]'::jsonb, "
                    "'[]'::jsonb, true, now(), now(), 0)"
                ),
                {"id": key_id, "uid": user_id, "h": "a" * 64},
            )
            conn.execute(
                text('DELETE FROM "vbwd_user" WHERE id = :uid'), {"uid": user_id}
            )
            remaining = conn.execute(
                text('SELECT count(*) FROM "vbwd_api_key" WHERE id = :id'),
                {"id": key_id},
            ).scalar()
            conn.commit()
        assert remaining == 0
    finally:
        engine.dispose()
