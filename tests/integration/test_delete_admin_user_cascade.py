"""Migration coverage for the ``ON DELETE CASCADE`` fix on the three core FKs
that point at ``vbwd_user``.

Deleting a SUPER_ADMIN / ADMIN user via ``DELETE /api/v1/admin/users/<id>``
raised an unhandled ``IntegrityError`` (HTTP 500). ``UserRepository.delete``
runs a single ``DELETE FROM vbwd_user`` and relies on the database FK cascade,
but three core join / usage tables referenced ``vbwd_user.id`` with the default
``NO ACTION`` and blocked the delete at statement-end:

  * ``vbwd_user_admin_role.user_id``       (the admin-specific blocker),
  * ``vbwd_user_access_level_rel.user_id``,
  * ``vbwd_feature_usage.user_id``.

A plain USER deletes cleanly only because it has no row in
``vbwd_user_admin_role``.

Runs the ``20260711_1000_user_fk_ondelete_cascade`` migration directly against a
throwaway database (mirroring ``test_api_key_migration``) so it never touches
the shared test DB or its alembic version table, and is immune to migration-
state left behind by sibling suites. It asserts:

  * BEFORE the migration a delete of a referenced user is blocked (the 500),
  * AFTER ``upgrade`` the same delete cascades and the child rows are gone,
  * the migration is reversible: ``down`` restores ``NO ACTION`` (delete blocked
    again) and ``up`` re-enables the cascade.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

# Minimal pre-migration schema: vbwd_user plus the three child tables, each
# with a plain (NO ACTION) FK to vbwd_user.id — exactly the state the migration
# has to fix.
_PRE_MIGRATION_DDL = (
    'CREATE TABLE "vbwd_user" (id UUID PRIMARY KEY)',
    'CREATE TABLE "vbwd_user_admin_role" ('
    "  user_id UUID NOT NULL REFERENCES vbwd_user(id),"
    "  role_id UUID NOT NULL,"
    "  PRIMARY KEY (user_id, role_id))",
    'CREATE TABLE "vbwd_user_access_level_rel" ('
    "  user_id UUID NOT NULL REFERENCES vbwd_user(id),"
    "  user_access_level_id UUID NOT NULL,"
    "  PRIMARY KEY (user_id, user_access_level_id))",
    'CREATE TABLE "vbwd_feature_usage" ('
    "  id UUID PRIMARY KEY,"
    "  user_id UUID NOT NULL REFERENCES vbwd_user(id),"
    "  feature_name VARCHAR(100) NOT NULL,"
    "  usage_count INTEGER NOT NULL DEFAULT 0,"
    "  period_start TIMESTAMP NOT NULL)",
)


def _admin_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/postgres"


@pytest.fixture
def throwaway_db():
    """A fresh DB holding the minimal pre-migration schema; dropped afterwards."""
    admin_url = _admin_url()
    db_name = f"user_fk_cascade_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    target_engine = create_engine(target_url)
    with target_engine.connect() as conn:
        for statement in _PRE_MIGRATION_DDL:
            conn.execute(text(statement))
        conn.commit()
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
            "20260711_1000_user_fk_ondelete_cascade.py",
        )
    )
    spec = importlib.util.spec_from_file_location("user_fk_cascade_migration", path)
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


def _seed_admin_with_child_rows(url: str):
    """Insert a user plus one row in each of the three child tables."""
    engine = create_engine(url)
    user_id = uuid.uuid4()
    try:
        with engine.connect() as conn:
            conn.execute(
                text('INSERT INTO "vbwd_user" (id) VALUES (:uid)'), {"uid": user_id}
            )
            conn.execute(
                text(
                    'INSERT INTO "vbwd_user_admin_role" (user_id, role_id) '
                    "VALUES (:uid, :rid)"
                ),
                {"uid": user_id, "rid": uuid.uuid4()},
            )
            conn.execute(
                text(
                    'INSERT INTO "vbwd_user_access_level_rel" '
                    "(user_id, user_access_level_id) VALUES (:uid, :lid)"
                ),
                {"uid": user_id, "lid": uuid.uuid4()},
            )
            conn.execute(
                text(
                    'INSERT INTO "vbwd_feature_usage" '
                    "(id, user_id, feature_name, usage_count, period_start) "
                    "VALUES (:id, :uid, 'cascade_feature', 1, now())"
                ),
                {"id": uuid.uuid4(), "uid": user_id},
            )
            conn.commit()
    finally:
        engine.dispose()
    return user_id


def _delete_user(url: str, user_id) -> None:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(
                text('DELETE FROM "vbwd_user" WHERE id = :uid'), {"uid": user_id}
            )
            conn.commit()
    finally:
        engine.dispose()


def _child_row_counts(url: str, user_id) -> dict:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return {
                table: conn.execute(
                    text(f'SELECT count(*) FROM "{table}" WHERE user_id = :uid'),
                    {"uid": user_id},
                ).scalar()
                for table in (
                    "vbwd_user_admin_role",
                    "vbwd_user_access_level_rel",
                    "vbwd_feature_usage",
                )
            }
    finally:
        engine.dispose()


def test_delete_is_blocked_before_migration(throwaway_db):
    """Reproduces the production 500: pre-migration the FK blocks the delete."""
    user_id = _seed_admin_with_child_rows(throwaway_db)
    with pytest.raises(IntegrityError):
        _delete_user(throwaway_db, user_id)


def test_delete_cascades_after_migration(throwaway_db):
    _run(throwaway_db, "upgrade")

    user_id = _seed_admin_with_child_rows(throwaway_db)
    assert _child_row_counts(throwaway_db, user_id) == {
        "vbwd_user_admin_role": 1,
        "vbwd_user_access_level_rel": 1,
        "vbwd_feature_usage": 1,
    }

    _delete_user(throwaway_db, user_id)  # no IntegrityError — the fix.

    assert _child_row_counts(throwaway_db, user_id) == {
        "vbwd_user_admin_role": 0,
        "vbwd_user_access_level_rel": 0,
        "vbwd_feature_usage": 0,
    }


def test_migration_up_down_up_is_reversible(throwaway_db):
    _run(throwaway_db, "upgrade")
    # Down restores NO ACTION: the delete is blocked again.
    _run(throwaway_db, "downgrade")
    user_id = _seed_admin_with_child_rows(throwaway_db)
    with pytest.raises(IntegrityError):
        _delete_user(throwaway_db, user_id)

    # Up re-enables the cascade.
    _run(throwaway_db, "upgrade")
    _delete_user(throwaway_db, user_id)
    assert _child_row_counts(throwaway_db, user_id) == {
        "vbwd_user_admin_role": 0,
        "vbwd_user_access_level_rel": 0,
        "vbwd_feature_usage": 0,
    }
