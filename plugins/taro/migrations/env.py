"""Alembic environment for taro plugin migrations.

Usage:
    cd vbwd-backend
    alembic -c plugins/taro/migrations/alembic.ini upgrade head
"""
from logging.config import fileConfig
import sys
import os

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Add parent directory to path for running from vbwd-backend root
current_dir = os.path.dirname(__file__)
vbwd_backend_root = os.path.abspath(os.path.join(current_dir, "../../.."))
sys.path.insert(0, vbwd_backend_root)

# Import config and models
from src.config import get_database_url
from src.extensions import db

# Import all Taro models so Alembic can detect them
from plugins.taro.src.models import (
    Arcana,
    TaroSession,
    TaroCardDraw,
)

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set SQLAlchemy URL from environment
config.set_main_option("sqlalchemy.url", get_database_url())

# Add your model's MetaData object here for 'autogenerate' support
target_metadata = db.Model.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
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
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
