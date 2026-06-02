"""Alembic environment configuration.

Intentionally plugin-agnostic: plugin models are discovered dynamically
by scanning each plugin's src/models/ directory and importing every
module found there.  This registers all SQLAlchemy model classes into
db.Model.metadata without naming any specific plugin in this file.
"""
from logging.config import fileConfig
import sys
import os
import importlib
import pkgutil

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import text

from alembic import context

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vbwd.config import get_database_url
from vbwd.extensions import db

# Import core models so their tables are visible to autogenerate
import vbwd.models  # noqa: F401  — side-effect: registers all core model classes

# Dynamically import every model module from every plugin's src/models/ directory.
# No plugin names are hard-coded here; new plugins are picked up automatically.
_plugins_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "plugins"))
for _plugin in sorted(os.listdir(_plugins_dir)):
    _plugin_dir = os.path.join(_plugins_dir, _plugin)
    if not os.path.isdir(_plugin_dir) or _plugin.startswith((".", "_")):
        continue
    # Scan both conventions: src/models/ (old) and plugin_id/models/ (new)
    for _subdir in ["src/models", f"{_plugin}/models"]:
        _models_dir = os.path.join(_plugin_dir, _subdir)
        if not os.path.isdir(_models_dir):
            continue
        _import_prefix = _subdir.replace("/", ".")
        for _, _module_name, _is_pkg in pkgutil.iter_modules([_models_dir]):
            if not _is_pkg:
                importlib.import_module(f"plugins.{_plugin}.{_import_prefix}.{_module_name}")

# Alembic config object
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Dynamically discover plugin migration directories (agnostic — no hardcoded plugins)
_version_locations = [os.path.join(os.path.dirname(__file__), "versions")]
for _plugin in sorted(os.listdir(_plugins_dir)):
    _migrations_dir = os.path.join(_plugins_dir, _plugin, "migrations", "versions")
    if os.path.isdir(_migrations_dir):
        _version_locations.append(_migrations_dir)
config.set_main_option("version_locations", ":".join(_version_locations))

# Inject the runtime database URL
config.set_main_option("sqlalchemy.url", get_database_url())

# All tables — core and plugin — are now registered in this metadata
target_metadata = db.Model.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # Alembic's version table defaults to version_num VARCHAR(32). Some
        # date-prefixed plugin revision ids exceed 32 chars, which truncates on
        # write to a fresh DB. Widen the column up front so any revision id
        # fits. Idempotent across every DB shape (fresh, narrow, already-wide)
        # and — like the rest of this file — names no specific plugin.
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version ("
                "version_num VARCHAR(255) NOT NULL "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE alembic_version "
                "ALTER COLUMN version_num TYPE VARCHAR(255)"
            )
        )
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
