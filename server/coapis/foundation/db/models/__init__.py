# -*- coding: utf-8 -*-
"""Unified data-layer models (all 15 community tables).

Importing this package registers every model on ``Base.metadata`` —
required by Alembic autogenerate and ``create_all``.

The two B-tier runtime tables (:class:`TokenUsageDaily`,
:class:`PermissionsConfig`) were historically created only via the legacy
raw-DDL path; since T2 (Alembic single source of truth) they are part of
the ORM metadata so a fresh database built with ``alembic upgrade head``
alone contains every community table.
"""

from .external import ExternalBinding, ExternalSystem
from .runtime import PermissionsConfig, TokenUsageDaily
from .scene import Scene, Tag, UserSceneSettings
from .state import MigrationState
from .usage import PointTransaction, TokenUsage
from .user import ApiKey, AuditLog, User, UserPreference, UserSetting

__all__ = [
    "ApiKey",
    "AuditLog",
    "ExternalBinding",
    "ExternalSystem",
    "MigrationState",
    "PermissionsConfig",
    "PointTransaction",
    "Scene",
    "Tag",
    "TokenUsage",
    "TokenUsageDaily",
    "User",
    "UserPreference",
    "UserSceneSettings",
    "UserSetting",
]
