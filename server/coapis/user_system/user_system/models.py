# -*- coding: utf-8 -*-
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

"""User system Pydantic models."""
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


class UserUpdate(BaseModel):
    """Request to update user profile."""
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    password: Optional[str] = None


class UserResponse(BaseModel):
    """User response (no sensitive data)."""
    id: int
    username: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    level: int = 0
    points: int = 0
    total_points_earned: int = 0
    total_points_spent: int = 0
    token_quota_monthly: int = 1_000_000
    token_used_monthly: int = 0
    role: str = "user"
    is_active: bool = True
    created_at: Optional[float] = None
    last_login_at: Optional[float] = None
    consecutive_login_days: int = 0

    @property
    def token_remaining(self) -> int:
        return max(0, self.token_quota_monthly - self.token_used_monthly)

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES.get(self.level, "Unknown")


class UserListResponse(BaseModel):
    """Paginated user list."""
    users: List[UserResponse]
    total: int
    page: int = 1
    page_size: int = 20


# ---------------------------------------------------------------------------
# Level definitions
# ---------------------------------------------------------------------------

LEVEL_THRESHOLDS = {
    0: 0,       # L0 - Visitor
    1: 100,     # L1 - User
    2: 500,     # L2 - Advanced
    3: 2000,    # L3 - Professional
    4: 5000,    # L4 - Enterprise
}

LEVEL_NAMES = {
    0: "Visitor",
    1: "User",
    2: "Advanced",
    3: "Professional",
    4: "Enterprise",
}

LEVEL_NAMES_ZH = {
    0: "访客",
    1: "用户",
    2: "进阶用户",
    3: "专业用户",
    4: "企业用户",
}


def get_level_for_points(points: int) -> int:
    """Calculate level based on total points earned."""
    level = 0
    for lvl, threshold in sorted(LEVEL_THRESHOLDS.items()):
        if points >= threshold:
            level = lvl
    return level


# ---------------------------------------------------------------------------
# Point transaction models
# ---------------------------------------------------------------------------

class PointTransaction(BaseModel):
    """A single point transaction record."""
    id: int
    user_id: int
    username: str
    type: str  # "earned" or "spent"
    amount: int
    source: str  # "login", "chat", "create_agent", etc.
    description: Optional[str] = None
    created_at: Optional[float] = None


class PointTransactionList(BaseModel):
    """Paginated point transactions."""
    transactions: List[PointTransaction]
    total: int
    page: int = 1
    page_size: int = 50


class PointAddRequest(BaseModel):
    """Request to add points manually."""
    username: str
    amount: int
    source: str = "manual"
    description: Optional[str] = None


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
# User settings models
# ---------------------------------------------------------------------------

class UserSetting(BaseModel):
    """A single user setting."""
    setting_key: str
    setting_value: Optional[str] = None


class UserSettingsList(BaseModel):
    """User settings."""
    username: str
    settings: Dict[str, str]


# ---------------------------------------------------------------------------
# API Key models
# ---------------------------------------------------------------------------

class APIKeyCreate(BaseModel):
    """Request to create an API key."""
    name: Optional[str] = None
    rate_limit: int = Field(default=10, ge=1, le=1000)
    quota_monthly: int = Field(default=1000, ge=1)
    expires_days: Optional[int] = None


class APIKeyResponse(BaseModel):
    """API key response."""
    id: int
    name: Optional[str] = None
    key_prefix: str
    rate_limit: int
    quota_monthly: int
    quota_used: int
    is_active: bool
    created_at: Optional[float] = None
    last_used_at: Optional[float] = None
    expires_at: Optional[float] = None


class APIKeyList(BaseModel):
    """List of API keys."""
    keys: List[APIKeyResponse]
    total: int


# ---------------------------------------------------------------------------
# Points config (for API response)
# ---------------------------------------------------------------------------

class PointsConfigResponse(BaseModel):
    """Current points configuration."""
    level_thresholds: Dict[int, int] = LEVEL_THRESHOLDS
    level_names: Dict[int, str] = LEVEL_NAMES
    level_names_zh: Dict[int, str] = LEVEL_NAMES_ZH
    point_rules: List[Dict[str, Any]] = []
