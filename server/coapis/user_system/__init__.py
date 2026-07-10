# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""User system module - configurable user management with tokens and quotas.

This module is completely independent from existing CoApis functionality.
The user system is always enabled in the open-source version.

Simplified: no user levels, no points system.

Structure:
- database.py: SQLite/JSON persistence layer
- models.py: Pydantic data models
- config.py: Configurable strategy parameters
- service.py: Core business logic (users, tokens, quotas)
- middleware.py: Optional middleware (quota, rate limit)
- points.py: Stub (removed)
- routers/: API endpoints
"""
from .database import get_db, UserSystemDB
from .models import (
    UserCreate, UserUpdate, UserResponse, UserListResponse,
    TokenUsageRecord, TokenUsageSummary, TokenUsageList, TokenRecordRequest,
    UserSetting, UserSettingsList,
    APIKeyCreate, APIKeyResponse, APIKeyList,
    AuditLog, AuditLogCreate, AuditLogList, AuditLogFilter,
)
from .config import get_config, UserSystemConfig

__all__ = [
    "get_db",
    "UserSystemDB",
    "get_config",
    "UserSystemConfig",
    "UserCreate", "UserUpdate", "UserResponse", "UserListResponse",
    "TokenUsageRecord", "TokenUsageSummary", "TokenUsageList", "TokenRecordRequest",
    "UserSetting", "UserSettingsList",
    "APIKeyCreate", "APIKeyResponse", "APIKeyList",
    "AuditLog", "AuditLogCreate", "AuditLogList", "AuditLogFilter",
]
