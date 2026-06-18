# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

"""User system module - configurable user management with points, tokens, and quotas.

This module is completely independent from existing CoApis functionality.
It is disabled by default (USER_SYSTEM_ENABLED=False) and can be enabled via env var.

Structure:
- database.py: SQLite persistence layer
- models.py: Pydantic data models
- config.py: Configurable strategy parameters
- service.py: Core business logic (users, points, tokens, quotas)
- middleware.py: Optional middleware (auth, quota, rate limit)
- routers/: API endpoints
"""
from .database import get_db, UserSystemDB
from .models import (
    UserCreate, UserUpdate, UserResponse, UserListResponse,
    PointTransaction, PointTransactionList, PointAddRequest,
    TokenUsageRecord, TokenUsageSummary, TokenUsageList, TokenRecordRequest,
    UserSetting, UserSettingsList,
    APIKeyCreate, APIKeyResponse, APIKeyList,
    PointsConfigResponse,
    LEVEL_THRESHOLDS, LEVEL_NAMES, LEVEL_NAMES_ZH,
    get_level_for_points,
)
from .config import get_config, UserSystemConfig

__all__ = [
    "get_db",
    "UserSystemDB",
    "get_config",
    "UserSystemConfig",
    "UserCreate", "UserUpdate", "UserResponse", "UserListResponse",
    "PointTransaction", "PointTransactionList", "PointAddRequest",
    "TokenUsageRecord", "TokenUsageSummary", "TokenUsageList", "TokenRecordRequest",
    "UserSetting", "UserSettingsList",
    "APIKeyCreate", "APIKeyResponse", "APIKeyList",
    "PointsConfigResponse",
    "LEVEL_THRESHOLDS", "LEVEL_NAMES", "LEVEL_NAMES_ZH",
    "get_level_for_points",
]
