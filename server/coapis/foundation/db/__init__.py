# -*- coding: utf-8 -*-
"""Unified data layer package (engine + declarative base).

Re-exports the public API so consumers can write
``from ..foundation.db import get_engine`` (previously this package
had no ``__init__.py`` — a namespace package — and those imports raised
ImportError at runtime, silently forcing every caller onto the JSON
file fallback).
"""

from .base import Base, BaseRow
from .engine import (
    build_database_url,
    get_engine,
    get_session,
    get_session_factory,
    init_engine,
    reset_engine,
)

__all__ = [
    "Base",
    "BaseRow",
    "build_database_url",
    "get_engine",
    "get_session",
    "get_session_factory",
    "init_engine",
    "reset_engine",
]
