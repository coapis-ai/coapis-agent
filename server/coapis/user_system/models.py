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

"""User system Pydantic models.

Simplified: no user levels, no points system.
Quota management is kept but level-based logic is removed.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# User models
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    """Request to create a new user."""
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    email: Optional[str] = None
    display_name: Optional[str] = None
    role: str = "user"  # user / advanced / admin
    muga_key: Optional[str] = None  # MuGA tenant key (UUID), auto-generated if not provided


class UserUpdate(BaseModel):
    """Request to update user profile."""
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    token_quota_monthly: Optional[int] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """User response (no sensitive data)."""
    id: int
    username: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    token_quota_monthly: int = 1_000_000
    token_used_monthly: int = 0
    role: str = "user"
    is_active: bool = True
    created_at: Optional[float] = None
    last_login_at: Optional[float] = None
    muga_key: Optional[str] = None  # MuGA tenant key (UUID) for user-isolated file space

    @property
    def token_remaining(self) -> int:
        return max(0, self.token_quota_monthly - self.token_used_monthly)


class UserListResponse(BaseModel):
    """Paginated user list."""
    users: List[UserResponse]
    total: int
    page: int = 1
    page_size: int = 20


# ---------------------------------------------------------------------------
# Token usage models
# ---------------------------------------------------------------------------

class TokenUsageRecord(BaseModel):
    """A single token usage record."""
    id: int
    user_id: int
    username: str
    agent_id: Optional[str] = None
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_cents: float = 0.0
    created_at: Optional[float] = None


class TokenUsageSummary(BaseModel):
    """Token usage summary for a user."""
    username: str
    quota_monthly: int
    used_monthly: int
    remaining: int
    usage_percent: float
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_cents: float = 0.0
    top_models: List[Dict[str, Any]] = []


class TokenUsageList(BaseModel):
    """Paginated token usage records."""
    records: List[TokenUsageRecord]
    total: int
    page: int = 1
    page_size: int = 50


class TokenRecordRequest(BaseModel):
    """Request to record token usage."""
    username: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    agent_id: Optional[str] = None


# ---------------------------------------------------------------------------
# User preferences models (个人设置)
# ---------------------------------------------------------------------------

class ChatDisplayConfig(BaseModel):
    """聊天显示配置."""
    hideToolCall: bool = True
    hideThought: bool = True
    userMarkdown: bool = True
    codeLineNumbers: bool = False
    codeFolding: bool = True
    autoExpandCode: bool = False


class UserSetting(BaseModel):
    """User setting key-value pair."""
    key: str
    value: Any


class UserSettingsList(BaseModel):
    """List of user settings."""
    settings: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# API Key models
# ---------------------------------------------------------------------------

class APIKeyCreate(BaseModel):
    """Request to create an API key."""
    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = Field(default_factory=list)


class APIKeyResponse(BaseModel):
    """API key response (with full key shown only on creation)."""
    id: int
    name: Optional[str] = None
    key_prefix: str
    scopes: List[str] = []
    created_at: Optional[float] = None
    last_used_at: Optional[float] = None
    full_key: Optional[str] = None  # Only populated on creation


class APIKeyList(BaseModel):
    """List of API keys."""
    keys: List[APIKeyResponse]
    total: int


# ---------------------------------------------------------------------------
# Audit log models
# ---------------------------------------------------------------------------

class AuditLog(BaseModel):
    """审计日志记录."""
    id: int
    user_id: int
    username: str
    action: str          # create_agent, update_model, login, etc.
    resource_type: str   # agent, model, skill, backup
    resource_id: str
    details: Dict[str, Any] = {}
    ip_address: str = ""
    user_agent: str = ""
    created_at: float = 0.0


class AuditLogCreate(BaseModel):
    """创建审计日志."""
    user_id: int
    username: str
    action: str
    resource_type: str
    resource_id: str
    details: Dict[str, Any] = {}
    ip_address: str = ""
    user_agent: str = ""


class AuditLogList(BaseModel):
    """分页审计日志列表."""
    logs: List[AuditLog]
    total: int
    page: int = 1
    page_size: int = 50


class AuditLogFilter(BaseModel):
    """审计日志筛选条件."""
    user_id: Optional[int] = None
    username: Optional[str] = None
    action: Optional[str] = None
    resource_type: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    page: int = 1
    page_size: int = 50
