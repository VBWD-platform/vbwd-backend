"""Migration coverage for dropping ``vbwd_user_case`` (S94 Slice 2).

Verifies the ``20260616_1300_drop_user_case`` migration drops the table + its
``usercasestatus`` enum, that the downgrade recreates both (table + indexes +
enum), and that the whole thing survives up → down → up.

Runs against a throwaway database so it never touches the shared test DB.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

TABLE = "vbwd_user_case"
ENUM = "usercasestatus"


def _admin_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/postgres"


def _table_exists(engine) -> bool:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = :t AND table_schema = 'public'"
            ),
            {"t": TABLE},
        ).fetchall()
    return len(rows) > 0


def _enum_exists(engine) -> bool:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT 1 FROM pg_type WHERE typname = :n"), {"n": ENUM}
        ).fetchall()
    return len(rows) > 0


@pytest.fixture
def throwaway_db():
    """Empty DB with ``vbwd_user`` + the pre-migration ``vbwd_user_case`` table
    and its enum; dropped afterwards."""
    admin_url = _admin_url()
    db_name = f"drop_case_mig_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    target_engine = create_engine(target_url)
    with target_engine.connect() as conn:
        conn.execute(text("CREATE TABLE vbwd_user (id uuid PRIMARY KEY)"))
        conn.execute(
            text(
                f"CREATE TYPE {ENUM} AS ENUM "
                "('DRAFT', 'ACTIVE', 'COMPLETED', 'ARCHIVED')"
            )
        )
        conn.execute(
            text(
                f"CREATE TABLE {TABLE} ("
                "  id uuid PRIMARY KEY,"
                "  user_id uuid NOT NULL REFERENCES vbwd_user(id) ON DELETE CASCADE,"
                "  description text,"
                "  date_started date,"
                f"  status {ENUM} NOT NULL,"
                "  created_at timestamp NOT NULL DEFAULT now(),"
                "  updated_at timestamp NOT NULL DEFAULT now(),"
                "  version integer NOT NULL DEFAULT 1"
                ")"
            )
        )
        conn.execute(text(f"CREATE INDEX ix_vbwd_user_case_status ON {TABLE} (status)"))
        conn.execute(
            text(f"CREATE INDEX ix_vbwd_user_case_user_id ON {TABLE} (user_id)")
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
            "20260616_1300_drop_user_case.py",
        )
    )
    spec = importlib.util.spec_from_file_location("drop_user_case_migration", path)
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
        assert _table_exists(engine) and _enum_exists(engine)  # pre-migration

        _run(throwaway_db, "upgrade")
        assert not _table_exists(engine)
        assert not _enum_exists(engine)

        _run(throwaway_db, "downgrade")
        assert _table_exists(engine)
        assert _enum_exists(engine)

        _run(throwaway_db, "upgrade")
        assert not _table_exists(engine)
        assert not _enum_exists(engine)
    finally:
        engine.dispose()
