"""Migration coverage for renaming the admin-role tables (S94 Slice 4).

Verifies the ``20260616_1400_rename_admin_role`` migration renames the three
System-B RBAC tables (``vbwd_role`` → ``vbwd_admin_role``,
``vbwd_role_permissions`` → ``vbwd_admin_role_permissions``,
``vbwd_user_roles`` → ``vbwd_user_admin_role``) AND their PK / FK / index
constraint names to the new prefix, that the FK to ``vbwd_permission`` survives,
and that the whole thing survives up → down → up.

Runs against a throwaway database so it never touches the shared test DB.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

OLD_TABLES = ("vbwd_role", "vbwd_role_permissions", "vbwd_user_roles")
NEW_TABLES = (
    "vbwd_admin_role",
    "vbwd_admin_role_permissions",
    "vbwd_user_admin_role",
)

# Postgres auto-generated names BEFORE the rename.
OLD_NAMES = {
    "vbwd_role": {
        "pk": "vbwd_role_pkey",
        "indexes": {"ix_vbwd_role_name", "ix_vbwd_role_slug"},
        "fks": set(),
    },
    "vbwd_role_permissions": {
        "pk": "vbwd_role_permissions_pkey",
        "indexes": set(),
        "fks": {
            "vbwd_role_permissions_role_id_fkey",
            "vbwd_role_permissions_permission_id_fkey",
        },
    },
    "vbwd_user_roles": {
        "pk": "vbwd_user_roles_pkey",
        "indexes": set(),
        "fks": {
            "vbwd_user_roles_user_id_fkey",
            "vbwd_user_roles_role_id_fkey",
        },
    },
}

# Names AFTER the rename (new prefix).
NEW_NAMES = {
    "vbwd_admin_role": {
        "pk": "vbwd_admin_role_pkey",
        "indexes": {"ix_vbwd_admin_role_name", "ix_vbwd_admin_role_slug"},
        "fks": set(),
    },
    "vbwd_admin_role_permissions": {
        "pk": "vbwd_admin_role_permissions_pkey",
        "indexes": set(),
        "fks": {
            "vbwd_admin_role_permissions_role_id_fkey",
            "vbwd_admin_role_permissions_permission_id_fkey",
        },
    },
    "vbwd_user_admin_role": {
        "pk": "vbwd_user_admin_role_pkey",
        "indexes": set(),
        "fks": {
            "vbwd_user_admin_role_user_id_fkey",
            "vbwd_user_admin_role_role_id_fkey",
        },
    },
}


def _admin_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/postgres"


def _table_exists(engine, table: str) -> bool:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = :t AND table_schema = 'public'"
            ),
            {"t": table},
        ).fetchall()
    return len(rows) > 0


def _constraint_names(engine, table: str, contype: str) -> set:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = cast(:t AS regclass) AND contype = :c"
            ),
            {"t": table, "c": contype},
        ).fetchall()
    return {row[0] for row in rows}


def _index_names(engine, table: str) -> set:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename = :t"),
            {"t": table},
        ).fetchall()
    return {row[0] for row in rows}


def _fk_target_tables(engine, table: str) -> set:
    """Return the set of tables that ``table`` has FKs pointing to."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT cast(confrelid AS regclass)::text FROM pg_constraint "
                "WHERE conrelid = cast(:t AS regclass) AND contype = 'f'"
            ),
            {"t": table},
        ).fetchall()
    return {row[0] for row in rows}


@pytest.fixture
def throwaway_db():
    """Empty DB pre-loaded with the pre-migration System-B RBAC tables
    (``vbwd_role`` / ``vbwd_role_permissions`` / ``vbwd_user_roles``) plus the
    ``vbwd_permission`` + ``vbwd_user`` tables they reference; dropped after."""
    admin_url = _admin_url()
    db_name = f"rename_role_mig_{uuid.uuid4().hex[:10]}"
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
                "CREATE TABLE vbwd_role ("
                "  name varchar(100) NOT NULL,"
                "  slug varchar(100) NOT NULL,"
                "  description varchar(500),"
                "  is_system boolean NOT NULL DEFAULT false,"
                "  id uuid PRIMARY KEY,"
                "  created_at timestamp NOT NULL DEFAULT now(),"
                "  updated_at timestamp NOT NULL DEFAULT now(),"
                "  version integer NOT NULL DEFAULT 1"
                ")"
            )
        )
        conn.execute(text("CREATE UNIQUE INDEX ix_vbwd_role_name ON vbwd_role (name)"))
        conn.execute(text("CREATE UNIQUE INDEX ix_vbwd_role_slug ON vbwd_role (slug)"))
        conn.execute(
            text(
                "CREATE TABLE vbwd_role_permissions ("
                "  role_id uuid NOT NULL REFERENCES vbwd_role(id),"
                "  permission_id uuid NOT NULL REFERENCES vbwd_permission(id),"
                "  PRIMARY KEY (role_id, permission_id)"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE vbwd_user_roles ("
                "  user_id uuid NOT NULL REFERENCES vbwd_user(id),"
                "  role_id uuid NOT NULL REFERENCES vbwd_role(id),"
                "  PRIMARY KEY (user_id, role_id)"
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
            "20260616_1400_rename_admin_role.py",
        )
    )
    spec = importlib.util.spec_from_file_location("rename_admin_role_migration", path)
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


def _assert_names(engine, expected: dict) -> None:
    for table, names in expected.items():
        assert _constraint_names(engine, table, "p") == {names["pk"]}
        assert _constraint_names(engine, table, "f") == names["fks"]
        if names["indexes"]:
            # PK index shares the pk name; assert the explicit indexes are present.
            assert names["indexes"].issubset(_index_names(engine, table))


def test_up_down_up_round_trip(throwaway_db):
    engine = create_engine(throwaway_db)
    try:
        # pre-migration: old tables + names present, new tables absent
        for table in OLD_TABLES:
            assert _table_exists(engine, table)
        for table in NEW_TABLES:
            assert not _table_exists(engine, table)
        _assert_names(engine, OLD_NAMES)

        _run(throwaway_db, "upgrade")
        for table in OLD_TABLES:
            assert not _table_exists(engine, table)
        for table in NEW_TABLES:
            assert _table_exists(engine, table)
        _assert_names(engine, NEW_NAMES)
        # FK to vbwd_permission survives the rename
        assert "vbwd_permission" in _fk_target_tables(
            engine, "vbwd_admin_role_permissions"
        )
        assert "vbwd_admin_role" in _fk_target_tables(
            engine, "vbwd_admin_role_permissions"
        )
        assert "vbwd_admin_role" in _fk_target_tables(engine, "vbwd_user_admin_role")

        _run(throwaway_db, "downgrade")
        for table in OLD_TABLES:
            assert _table_exists(engine, table)
        for table in NEW_TABLES:
            assert not _table_exists(engine, table)
        _assert_names(engine, OLD_NAMES)

        _run(throwaway_db, "upgrade")
        for table in NEW_TABLES:
            assert _table_exists(engine, table)
        _assert_names(engine, NEW_NAMES)
    finally:
        engine.dispose()
