# -*- coding: utf-8 -*-
"""Engine management for the unified data layer.

Single global ``Engine`` + ``sessionmaker``, lazily created.

URL resolution (preserves the D-7 / D-8 / D-9 rules from ``db_settings``):

* ``COAPIS_DATABASE_URL`` with a ``postgresql://`` scheme → enterprise
  PostgreSQL (mapped to the ``psycopg2`` driver);
* everything else → community SQLite: the variable is validated by
  :func:`coapis.foundation.db_settings.resolve_db_path` (SQLite-only,
  relative paths resolved under the data dir), falling back to
  ``<DATA>/system/coapis.db``.

SQLite connection pragmas (WAL + busy_timeout + FK) are applied on every
new DBAPI connection, so any pooled connection is safe for concurrent
readers/writers. A ``QueuePool`` (SQLAlchemy default for file SQLite) is
used rather than a single shared connection, because the app is
multi-threaded (event loop + thread pool + background tasks) and a single
DBAPI connection is not safe for concurrent use.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_lock = threading.Lock()
_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None
_explicit_url: Optional[str] = None  # set via init_engine() (tests/bootstrap)

_PG_SCHEMES = (
    "postgresql",
    "postgres",
    "postgresql+psycopg2",
    "postgresql+psycopg",
    "postgresql+asyncpg",
)


def build_database_url() -> str:
    """Resolve the SQLAlchemy database URL.

    An URL passed explicitly via :func:`init_engine` always wins (test /
    bootstrap scenario). Otherwise the environment is consulted.
    """
    if _explicit_url is not None:
        return _explicit_url

    raw = (os.environ.get("COAPIS_DATABASE_URL") or "").strip()
    if raw:
        scheme = raw.split("://", 1)[0].lower()
        if scheme in _PG_SCHEMES:
            # Enterprise PostgreSQL.
            if scheme in ("postgresql", "postgres"):
                raw = "postgresql+psycopg2://" + raw.split("://", 1)[1]
            return raw
        # Community: sqlite://... (validated below) or a bare path is
        # rejected by resolve_db_path.

    # Community SQLite — full D-7/D-8/D-9 validation.
    from ..db_settings import resolve_db_path

    return f"sqlite:///{resolve_db_path()}"


def _create_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()
        return engine

    # PostgreSQL (enterprise).
    return create_engine(url, pool_size=5, max_overflow=10, **kwargs)


def get_engine() -> Engine:
    """Return the global engine, creating it on first use."""
    global _engine, _session_factory
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = _create_engine(build_database_url())
                _session_factory = sessionmaker(
                    bind=_engine, expire_on_commit=False, autoflush=False
                )
    return _engine


def get_session_factory() -> "sessionmaker[Session]":
    """Return the global session factory (engine created if needed)."""
    get_engine()
    assert _session_factory is not None
    return _session_factory


def init_engine(url: str) -> Engine:
    """Create/replace the global engine with an explicit URL.

    Intended for tests and explicit bootstrap; the URL is remembered so
    Alembic (``env.py``) resolves the same database.
    """
    global _engine, _session_factory, _explicit_url
    with _lock:
        _explicit_url = url
        if _engine is not None:
            _engine.dispose()
        _engine = _create_engine(url)
        _session_factory = sessionmaker(
            bind=_engine, expire_on_commit=False, autoflush=False
        )
    return _engine


def reset_engine() -> None:
    """Dispose the global engine and clear the explicit URL (tests)."""
    global _engine, _session_factory, _explicit_url
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _session_factory = None
        _explicit_url = None


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Transactional session: commit on success, rollback on error.

    Repositories call one method == one session == one transaction, so
    concurrent calls never interleave writes inside a single transaction.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
