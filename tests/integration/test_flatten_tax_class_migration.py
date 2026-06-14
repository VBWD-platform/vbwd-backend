"""Migration coverage for the S72.3 ``vbwd_tax_class`` flatten.

Verifies the ``20260613_1100_flatten_tax_class`` migration:
- adds a nullable ``tax_class VARCHAR(50)`` column to ``vbwd_tax``;
- data-migrates each tax's ``tax_class_id`` link to the referenced class
  ``code`` string;
- drops ``vbwd_tax.tax_class_id`` and the ``vbwd_tax_class`` table;
- is reversible (up → down → up), where ``down`` recreates ``vbwd_tax_class``,
  re-adds ``tax_class_id`` nullable, and drops the ``tax_class`` column (the
  original class rows / links are not restored — documented lossy).

Runs against a throwaway database with just the pre-migration tax shape so it
never touches the shared test DB.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text


def _admin_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/postgres"


def _tax_columns(engine) -> set:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'vbwd_tax'"
            )
        ).fetchall()
    return {row[0] for row in rows}


def _table_exists(engine, table_name: str) -> bool:
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM information_schema.tables " "WHERE table_name = :n"),
            {"n": table_name},
        ).first()
    return result is not None


@pytest.fixture
def throwaway_db():
    admin_url = _admin_url()
    db_name = f"flatten_tax_mig_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    target_engine = create_engine(target_url)
    class_id = str(uuid.uuid4())
    tax_with_class_id = str(uuid.uuid4())
    tax_without_class_id = str(uuid.uuid4())
    with target_engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE vbwd_tax_class ("
                "  id uuid PRIMARY KEY,"
                "  name varchar(100) NOT NULL,"
                "  code varchar(50) NOT NULL UNIQUE,"
                "  description text,"
                "  default_rate numeric(5, 2) NOT NULL DEFAULT 0,"
                "  is_default boolean NOT NULL DEFAULT false,"
                "  created_at timestamptz,"
                "  updated_at timestamptz,"
                "  version integer"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE vbwd_tax ("
                "  id uuid PRIMARY KEY,"
                "  name varchar(100) NOT NULL,"
                "  code varchar(50) NOT NULL UNIQUE,"
                "  description text,"
                "  rate numeric(5, 2) NOT NULL,"
                "  country_code varchar(2),"
                "  region_code varchar(10),"
                "  tax_class_id uuid REFERENCES vbwd_tax_class(id) "
                "    ON DELETE SET NULL,"
                "  is_active boolean NOT NULL DEFAULT true,"
                "  is_inclusive boolean NOT NULL DEFAULT false,"
                "  created_at timestamptz,"
                "  updated_at timestamptz,"
                "  version integer"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO vbwd_tax_class (id, name, code, default_rate) "
                "VALUES (:id, 'Standard', 'standard', 19)"
            ),
            {"id": class_id},
        )
        conn.execute(
            text(
                "INSERT INTO vbwd_tax "
                "(id, name, code, rate, tax_class_id) "
                "VALUES (:id, 'VAT DE', 'VAT_DE', 19, :class_id)"
            ),
            {"id": tax_with_class_id, "class_id": class_id},
        )
        conn.execute(
            text(
                "INSERT INTO vbwd_tax (id, name, code, rate, tax_class_id) "
                "VALUES (:id, 'No Class Tax', 'NO_CLASS', 7, NULL)"
            ),
            {"id": tax_without_class_id},
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
            "20260613_1100_flatten_tax_class.py",
        )
    )
    spec = importlib.util.spec_from_file_location("flatten_tax_migration", path)
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


def test_pre_migration_shape(throwaway_db):
    engine = create_engine(throwaway_db)
    try:
        assert _table_exists(engine, "vbwd_tax_class")
        columns = _tax_columns(engine)
        assert "tax_class_id" in columns
        assert "tax_class" not in columns
    finally:
        engine.dispose()


def test_upgrade_adds_label_drops_class(throwaway_db):
    _run(throwaway_db, "upgrade")

    engine = create_engine(throwaway_db)
    try:
        columns = _tax_columns(engine)
        assert "tax_class" in columns
        assert "tax_class_id" not in columns
        assert not _table_exists(engine, "vbwd_tax_class")
    finally:
        engine.dispose()


def test_upgrade_data_migrates_class_code_into_label(throwaway_db):
    _run(throwaway_db, "upgrade")

    engine = create_engine(throwaway_db)
    try:
        with engine.connect() as conn:
            linked = conn.execute(
                text("SELECT tax_class FROM vbwd_tax WHERE code = 'VAT_DE'")
            ).scalar()
            unlinked = conn.execute(
                text("SELECT tax_class FROM vbwd_tax WHERE code = 'NO_CLASS'")
            ).scalar()
        assert linked == "standard"
        assert unlinked is None
    finally:
        engine.dispose()


def test_up_down_up_is_reversible(throwaway_db):
    _run(throwaway_db, "upgrade")
    _run(throwaway_db, "downgrade")

    engine = create_engine(throwaway_db)
    try:
        assert _table_exists(engine, "vbwd_tax_class")
        columns = _tax_columns(engine)
        assert "tax_class_id" in columns
        assert "tax_class" not in columns
    finally:
        engine.dispose()

    _run(throwaway_db, "upgrade")

    engine = create_engine(throwaway_db)
    try:
        columns = _tax_columns(engine)
        assert "tax_class" in columns
        assert "tax_class_id" not in columns
        assert not _table_exists(engine, "vbwd_tax_class")
    finally:
        engine.dispose()
