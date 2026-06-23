# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
