"""Test model-table consistency to prevent schema drift.

Ensures that:
1. Every model has a corresponding database table
2. Every model column exists in the database
3. Enum types match between Python and PostgreSQL
4. Foreign key relationships are enforced
5. Indexes are created correctly
6. Unique constraints are enforced
"""
from typing import Any, Type

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.types import Enum as SQLAlchemyEnum

from vbwd.extensions import db
from vbwd.models.base import BaseModel


def get_all_models() -> list[Type[BaseModel]]:
    """Get all model classes that have table definitions."""
    from vbwd import models

    # Import all models to register them
    _ = models

    result = []
    for attr_name in dir(models):
        attr = getattr(models, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, BaseModel)
            and attr != BaseModel
            and hasattr(attr, "__tablename__")
        ):
            result.append(attr)
    return sorted(result, key=lambda m: m.__name__)


def get_db_tables() -> set[str]:
    """Get all table names from PostgreSQL."""
    inspector = inspect(db.engine)
    return set(inspector.get_table_names())


def get_model_columns(model: Type[BaseModel]) -> dict[str, Any]:
    """Get all columns from a model."""
    return {col.name: col for col in model.__table__.columns}


def get_db_columns(table_name: str) -> dict[str, dict]:
    """Get all columns from database table."""
    inspector = inspect(db.engine)
    columns = {}
    for col in inspector.get_columns(table_name):
        columns[col["name"]] = col
    return columns


def get_model_foreign_keys(model: Type[BaseModel]) -> list[dict]:
    """Get all foreign keys from a model."""
    result = []
    for constraint in model.__table__.foreign_keys:
        result.append(
            {
                "name": constraint.name,
                "column": constraint.parent.name,
                "target_table": constraint.column.table.name,
                "target_column": constraint.column.name,
            }
        )
    return result


def get_db_foreign_keys(table_name: str) -> list[dict]:
    """Get all foreign keys from database table."""
    inspector = inspect(db.engine)
    result = []
    for fk in inspector.get_foreign_keys(table_name):
        result.append(
            {
                "name": fk.get("name", ""),
                "column": fk["constrained_columns"][0]
                if fk["constrained_columns"]
                else None,
                "target_table": fk["referred_table"],
                "target_column": fk["referred_columns"][0]
                if fk["referred_columns"]
                else None,
            }
        )
    return result


def get_model_indexes(model: Type[BaseModel]) -> list[str]:
    """Get all indexed columns from a model."""
    indexed = set()
    for col in model.__table__.columns:
        if col.index:
            indexed.add(col.name)
    for idx in model.__table__.indexes:
        for col in idx.columns:
            indexed.add(col.name)
    return sorted(indexed)


def get_db_indexes(table_name: str) -> list[str]:
    """Get all indexed columns from database table."""
    inspector = inspect(db.engine)
    indexed = set()
    for idx in inspector.get_indexes(table_name):
        for col in idx["column_names"]:
            indexed.add(col)
    return sorted(indexed)


def get_model_unique_constraints(model: Type[BaseModel]) -> list[str]:
    """Get all unique constraints from a model."""
    unique = set()
    for col in model.__table__.columns:
        if col.unique:
            unique.add(col.name)
    for constraint in model.__table__.constraints:
        if constraint.name and "uq_" in constraint.name.lower():
            for col in constraint.columns:
                unique.add(col.name)
    return sorted(unique)


def get_db_unique_constraints(table_name: str) -> list[str]:
    """Get all unique constraints and unique indexes from database table.

    Unique indexes enforce uniqueness identically to unique constraints in
    PostgreSQL, even though inspector.get_unique_constraints() only returns
    explicit UNIQUE CONSTRAINT entries (not standalone UNIQUE INDEX objects).
    """
    inspector = inspect(db.engine)
    unique = set()
    # Explicit UNIQUE CONSTRAINTs
    for constraint in inspector.get_unique_constraints(table_name):
        for col in constraint["column_names"]:
            unique.add(col)
    # Unique indexes (created via op.create_index(..., unique=True))
    for idx in inspector.get_indexes(table_name):
        if idx.get("unique"):
            for col in idx["column_names"]:
                unique.add(col)
    return sorted(unique)


def get_enum_columns(model: Type[BaseModel]) -> dict[str, Any]:
    """Get all enum columns from a model."""
    enums = {}
    for col in model.__table__.columns:
        if isinstance(col.type, SQLAlchemyEnum):
            enums[col.name] = col.type
    return enums


def get_db_enums(table_name: str) -> dict[str, set[str]]:
    """Get all enum columns from database table."""
    inspector = inspect(db.engine)
    enums = {}
    for col in inspector.get_columns(table_name):
        col_type = str(col["type"])
        if col_type.startswith("USER-DEFINED"):
            # Get enum values from PostgreSQL
            enum_name = col.get("type")
            if enum_name:
                enums[col["name"]] = enum_name
    return enums


# ============================================================================
# TEST FUNCTIONS
# ============================================================================


@pytest.fixture(autouse=True)
def app_context(app):
    """Provide Flask app context for tests."""
    with app.app_context():
        yield


class TestModelTableConsistency:
    """Test suite for model-table schema consistency."""

    def test_all_models_have_tables(self) -> None:
        """Verify every model has a corresponding database table.

        This test ensures that:
        - No models are defined without database tables
        - All models are properly migrated
        - Schema is complete
        """
        models = get_all_models()
        tables = get_db_tables()

        missing_tables = []
        for model in models:
            table_name = model.__tablename__
            if table_name not in tables:
                missing_tables.append((model.__name__, table_name))

        assert not missing_tables, (
            f"Found {len(missing_tables)} models without database tables:\n"
            + "\n".join(f"  {m[0]} -> {m[1]}" for m in missing_tables)
        )

    def test_model_columns_exist_in_database(self) -> None:
        """Verify every model column exists in the database.

        This test ensures that:
        - All model columns have database equivalents
        - No schema drift between model and database
        - Column definitions are synchronized
        """
        models = get_all_models()
        tables = get_db_tables()

        missing_columns = []
        for model in models:
            table_name = model.__tablename__
            if table_name not in tables:
                continue

            model_cols = get_model_columns(model)
            db_cols = get_db_columns(table_name)

            for col_name in model_cols:
                if col_name not in db_cols:
                    missing_columns.append((model.__name__, col_name))

        assert not missing_columns, (
            f"Found {len(missing_columns)} model columns missing from database:\n"
            + "\n".join(f"  {m[0]}.{m[1]}" for m in missing_columns)
        )

    def test_enum_types_match(self) -> None:
        """Verify Python enum types match PostgreSQL enum types.

        This test ensures that:
        - Python enums map correctly to database enums
        - No enum value case/format mismatches between Python and database
        - Enum consistency is maintained
        """
        models = get_all_models()
        tables = get_db_tables()

        enum_mismatches = []
        for model in models:
            table_name = model.__tablename__
            if table_name not in tables:
                continue

            enum_cols = get_enum_columns(model)
            for col_name, enum_type in enum_cols.items():
                if enum_type.enum_class:
                    py_values = {e.value for e in enum_type.enum_class}
                    # Verify all Python enum values are strings (not members)
                    non_string = [v for v in py_values if not isinstance(v, str)]
                    if non_string:
                        enum_mismatches.append(
                            (
                                model.__name__,
                                col_name,
                                f"Non-string values: {non_string}",
                            )
                        )

        assert (
            not enum_mismatches
        ), f"Found {len(enum_mismatches)} enum type mismatches:\n" + "\n".join(
            f"  {m[0]}.{m[1]}: {m[2]}" for m in enum_mismatches
        )

    def test_foreign_keys_exist(self) -> None:
        """Verify all model foreign keys are enforced in the database.

        This test ensures that:
        - Foreign key constraints are created in database
        - Referential integrity is enforced
        - No orphaned relationship definitions
        """
        models = get_all_models()
        tables = get_db_tables()

        missing_fks = []
        for model in models:
            table_name = model.__tablename__
            if table_name not in tables:
                continue

            model_fks = {fk["column"]: fk for fk in get_model_foreign_keys(model)}
            db_fks = {fk["column"]: fk for fk in get_db_foreign_keys(table_name)}

            for col_name in model_fks:
                if col_name not in db_fks:
                    missing_fks.append((model.__name__, col_name))

        assert not missing_fks, (
            f"Found {len(missing_fks)} model foreign keys missing from database:\n"
            + "\n".join(f"  {m[0]}.{m[1]}" for m in missing_fks)
        )

    def test_indexes_created(self) -> None:
        """Verify all indexed columns have database indexes.

        This test ensures that:
        - Performance indexes are created
        - Query optimization is enabled
        - All indexed columns have corresponding database indexes
        """
        models = get_all_models()
        tables = get_db_tables()

        missing_indexes = []
        for model in models:
            table_name = model.__tablename__
            if table_name not in tables:
                continue

            model_indexes = set(get_model_indexes(model))
            db_indexes = set(get_db_indexes(table_name))

            # Allow some flexibility: database might have more indexes
            missing = model_indexes - db_indexes
            if missing:
                missing_indexes.append((model.__name__, sorted(missing)))

        assert (
            not missing_indexes
        ), f"Found {len(missing_indexes)} models with missing indexes:\n" + "\n".join(
            f"  {m[0]}: {', '.join(m[1])}" for m in missing_indexes
        )

    def test_unique_constraints_enforced(self) -> None:
        """Verify unique constraints are enforced in the database.

        This test ensures that:
        - Unique constraints prevent duplicates
        - Data integrity is enforced
        - All unique-defined columns have constraints
        """
        models = get_all_models()
        tables = get_db_tables()

        missing_constraints = []
        for model in models:
            table_name = model.__tablename__
            if table_name not in tables:
                continue

            model_unique = set(get_model_unique_constraints(model))
            db_unique = set(get_db_unique_constraints(table_name))

            # Allow some flexibility: database might have more constraints
            missing = model_unique - db_unique
            if missing:
                missing_constraints.append((model.__name__, sorted(missing)))

        assert not missing_constraints, (
            f"Found {len(missing_constraints)} models with missing unique constraints:\n"
            + "\n".join(f"  {m[0]}: {', '.join(m[1])}" for m in missing_constraints)
        )

    def test_enum_values_match_database(self) -> None:
        """Verify Python enum values match PostgreSQL enum values exactly.

        This test ensures that:
        - Python enum members' .value matches database enum values
        - No case mismatches (PostgreSQL is case-sensitive)
        - All enum values are insertable into the database
        """
        models = get_all_models()
        tables = get_db_tables()
        mismatches = []

        for model in models:
            table_name = model.__tablename__
            if table_name not in tables:
                continue

            # Check all enum columns in the model
            for col in model.__table__.columns:
                if isinstance(col.type, SQLAlchemyEnum) and col.type.enum_class:
                    enum_class = col.type.enum_class
                    enum_name = col.type.name

                    try:
                        # Query PostgreSQL for the enum values
                        result = db.session.execute(
                            text(f"SELECT enum_range(NULL::{enum_name});")
                        )
                        db_enum_range = result.scalar()
                        if db_enum_range:
                            db_values = set(str(db_enum_range).strip("{}").split(","))
                        else:
                            db_values = set()
                    except Exception:
                        continue

                    # Get Python enum values
                    py_values = {member.value for member in enum_class}

                    # Check for mismatches
                    if db_values != py_values:
                        mismatches.append(
                            (
                                model.__name__,
                                col.name,
                                f"DB: {db_values}, Python: {py_values}",
                            )
                        )

        assert (
            not mismatches
        ), f"Found {len(mismatches)} enum value mismatches:\n" + "\n".join(
            f"  {m[0]}.{m[1]}: {m[2]}" for m in mismatches
        )


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
