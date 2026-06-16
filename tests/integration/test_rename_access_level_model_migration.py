"""Migration coverage for renaming the AccessLevel model tables (S94 Slice 6a).

``vbwd_user_access_level`` -> ``vbwd_access_level`` and
``vbwd_user_access_level_permissions`` -> ``vbwd_access_level_permissions``,
with PK / FK / index constraints renamed in lock-step. The user-join FK on
``vbwd_user_access_level_rel`` follows the renamed table automatically. Survives
up -> down -> up. Runs against a throwaway database.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

OLD = "vbwd_user_access_level"
NEW = "vbwd_access_level"
OLD_PERMS = "vbwd_user_access_level_permissions"
NEW_PERMS = "vbwd_access_level_permissions"
REL = "vbwd_user_access_level_rel"


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


def _index_names(engine, table) -> set:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename = :t"),
            {"t": table},
        ).fetchall()
    return {row[0] for row in rows}


@pytest.fixture
def throwaway_db():
    admin_url = _admin_url()
    db_name = f"rename_al_model_mig_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    target_engine = create_engine(target_url)
    with target_engine.connect() as conn:
        conn.execute(text("CREATE TABLE vbwd_user (id uuid PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE vbwd_permission (id uuid PRIMARY KEY)"))
        conn.execute(
            text(
                f"CREATE TABLE {OLD} ("
                "  id uuid PRIMARY KEY,"
                "  name varchar(100) NOT NULL,"
                "  slug varchar(100) NOT NULL,"
                "  linked_plan_slug varchar(100)"
                ")"
            )
        )
        conn.execute(text(f"CREATE UNIQUE INDEX ix_{OLD}_name ON {OLD} (name)"))
        conn.execute(text(f"CREATE UNIQUE INDEX ix_{OLD}_slug ON {OLD} (slug)"))
        conn.execute(
            text(
                f"CREATE INDEX ix_{OLD}_linked_plan_slug "
                f"ON {OLD} (linked_plan_slug)"
            )
        )
        conn.execute(
            text(
                f"CREATE TABLE {OLD_PERMS} ("
                "  user_access_level_id uuid NOT NULL "
                f"    REFERENCES {OLD}(id),"
                "  permission_id uuid NOT NULL REFERENCES vbwd_permission(id),"
                "  PRIMARY KEY (user_access_level_id, permission_id)"
                ")"
            )
        )
        conn.execute(
            text(
                f"CREATE TABLE {REL} ("
                "  user_id uuid NOT NULL REFERENCES vbwd_user(id),"
                "  user_access_level_id uuid NOT NULL "
                f"    REFERENCES {OLD}(id),"
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
            "20260616_1600_rename_access_level_model.py",
        )
    )
    spec = importlib.util.spec_from_file_location("rename_al_model_migration", path)
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


def _rel_fk_target(engine) -> str:
    """Return the table the rel.user_access_level_id FK points at."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT confrel.relname FROM pg_constraint con "
                "JOIN pg_class rel ON rel.oid = con.conrelid "
                "JOIN pg_class confrel ON confrel.oid = con.confrelid "
                "WHERE rel.relname = :t AND con.contype = 'f' "
                "  AND confrel.relname IN (:old, :new)"
            ),
            {"t": REL, "old": OLD, "new": NEW},
        ).fetchone()
    return row[0] if row else ""


def test_up_down_up_round_trip(throwaway_db):
    engine = create_engine(throwaway_db)
    try:
        assert _table_exists(engine, OLD)
        assert _rel_fk_target(engine) == OLD

        _run(throwaway_db, "upgrade")
        assert _table_exists(engine, NEW)
        assert not _table_exists(engine, OLD)
        assert _table_exists(engine, NEW_PERMS)
        assert not _table_exists(engine, OLD_PERMS)

        cons = _constraint_names(engine, NEW)
        assert f"{NEW}_pkey" in cons
        assert not any(c.startswith(OLD) for c in cons)

        idx = _index_names(engine, NEW)
        assert f"ix_{NEW}_name" in idx
        assert f"ix_{NEW}_slug" in idx
        assert f"ix_{NEW}_linked_plan_slug" in idx
        assert not any(i.startswith(f"ix_{OLD}") for i in idx)

        perm_cons = _constraint_names(engine, NEW_PERMS)
        assert f"{NEW_PERMS}_pkey" in perm_cons
        assert f"{NEW_PERMS}_user_access_level_id_fkey" in perm_cons
        assert f"{NEW_PERMS}_permission_id_fkey" in perm_cons
        assert not any(c.startswith(OLD_PERMS) for c in perm_cons)

        # The rel FK now points at the renamed table (handled by rename_table).
        assert _rel_fk_target(engine) == NEW

        _run(throwaway_db, "downgrade")
        assert _table_exists(engine, OLD)
        assert not _table_exists(engine, NEW)
        assert _rel_fk_target(engine) == OLD

        _run(throwaway_db, "upgrade")
        assert _table_exists(engine, NEW)
    finally:
        engine.dispose()
