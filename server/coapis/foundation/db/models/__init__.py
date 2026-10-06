# -*- coding: utf-8 -*-
"""Unified data-layer models (all 18 community tables).

Importing this package registers every model on ``Base.metadata`` —
required by Alembic autogenerate and ``create_all``.

The two B-tier runtime tables (:class:`TokenUsageDaily`,
:class:`PermissionsConfig`) were historically created only via the legacy
raw-DDL path; since T2 (Alembic single source of truth) they are part of
the ORM metadata so a fresh database built with ``alembic upgrade head``
alone contains every community table.
"""

from .eval import AgentRun, AgentTask, AgentTrajectory
from .external import ExternalBinding, ExternalSystem
from .files import FileRecord
from .memory import Memory
from .memory_timeline import MemoryTimeline
from .runtime import PermissionsConfig, TokenUsageDaily
from .scene import Scene, Tag, UserSceneSettings
from .state import MigrationState
from .usage import PointTransaction, TokenUsage
from .user import ApiKey, AuditLog, User, UserPreference, UserSetting

__all__ = [
    "AgentRun",
    "AgentTask",
    "AgentTrajectory",
    "ApiKey",
    "AuditLog",
    "ExternalBinding",
    "ExternalSystem",
    "FileRecord",
    "Memory",
    "MemoryTimeline",
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
