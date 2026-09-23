# -*- coding: utf-8 -*-
"""Programmatic Alembic runner for the unified data layer.

``run_migrations()`` is the single entry point used by the factory at
startup: it runs ``alembic upgrade head`` against the database selected by
:func:`coapis.foundation.db.engine.build_database_url` (explicit test URL
> ``COAPIS_DATABASE_URL`` > community default).
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _alembic_config() -> Config:
    cfg = Config(str(_MIGRATIONS_DIR / "alembic.ini"))
    # Work regardless of CWD.
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return cfg


def run_migrations() -> None:
    """Upgrade the database schema to head (idempotent)."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    logger.info("alembic: schema upgraded to head")


def current_revision() -> str | None:
    """Return the current alembic revision (``None`` if un-stamped).

    Reuses the global engine/connection pool instead of opening a throwaway
    connection.
    """
    from alembic.runtime.migration import MigrationContext

    from .engine import get_engine

    with get_engine().connect() as conn:
        ctx = MigrationContext.configure(conn)
        return ctx.get_current_revision()
