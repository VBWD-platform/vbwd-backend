"""Migration coverage for renaming the access-level join (S94 Slice 5).

``vbwd_user_user_access_levels`` -> ``vbwd_user_access_level_rel``, with its
PK/FK constraints renamed in lock-step; survives up -> down -> up. Runs against
a throwaway database.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

OLD = "vbwd_user_user_access_levels"
NEW = "vbwd_user_access_level_rel"


def _admin_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/postgres"


def _table_exists(engine, name) -> bool:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = :t AND table_schema = 'public'"
            ),
            {"t": name},
        ).fetchall()
    return len(rows) > 0


def _constraint_names(engine, table) -> set:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT con.conname FROM pg_constraint con "
                "JOIN pg_class rel ON rel.oid = con.conrelid "
                "WHERE rel.relname = :t"
            ),
            {"t": table},
        ).fetchall()
    return {row[0] for row in rows}


@pytest.fixture
def throwaway_db():
    admin_url = _admin_url()
    db_name = f"rename_al_join_mig_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    target_engine = create_engine(target_url)
    with target_engine.connect() as conn:
        conn.execute(text("CREATE TABLE vbwd_user (id uuid PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE vbwd_user_access_level (id uuid PRIMARY KEY)"))
        conn.execute(
            text(
                f"CREATE TABLE {OLD} ("
                "  user_id uuid NOT NULL REFERENCES vbwd_user(id),"
                "  user_access_level_id uuid NOT NULL "
                "    REFERENCES vbwd_user_access_level(id),"
                "  PRIMARY KEY (user_id, user_access_level_id)"
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
            "20260616_1500_rename_access_level_join.py",
        )
    )
    spec = importlib.util.spec_from_file_location("rename_al_join_migration", path)
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
        assert _table_exists(engine, OLD)

        _run(throwaway_db, "upgrade")
        assert _table_exists(engine, NEW)
        assert not _table_exists(engine, OLD)
        names = _constraint_names(engine, NEW)
        assert f"{NEW}_pkey" in names
        assert f"{NEW}_user_id_fkey" in names
        assert f"{NEW}_user_access_level_id_fkey" in names
        # No constraint kept the legacy prefix.
        assert not any(n.startswith(OLD) for n in names)

        _run(throwaway_db, "downgrade")
        assert _table_exists(engine, OLD)
        assert not _table_exists(engine, NEW)

        _run(throwaway_db, "upgrade")
        assert _table_exists(engine, NEW)
    finally:
        engine.dispose()
