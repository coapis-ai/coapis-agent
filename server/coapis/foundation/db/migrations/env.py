# -*- coding: utf-8 -*-
"""Alembic environment for the unified data layer.

The database URL is resolved at runtime via
:func:`coapis.foundation.db.engine.build_database_url` (honours an
explicit URL set by ``init_engine`` for tests, then
``COAPIS_DATABASE_URL`` / the community default), so no hard-coded URL is
ever used here.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import the package so every model is registered on Base.metadata.
from coapis.foundation.db import models  # noqa: F401
from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import build_database_url

config = context.config

# Programmatic URL — overrides the placeholder in alembic.ini.
config.set_main_option("sqlalchemy.url", build_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (live connection)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
