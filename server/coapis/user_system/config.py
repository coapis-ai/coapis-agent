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

"""User system configuration - all strategies are configurable via env vars.

Environment variables (prefix: COAPIS_USER_):
- USER_SYSTEM_ENABLED: bool = False
- POINTS_LOGIN_DAILY: int = 5
- POINTS_FIRST_LOGIN: int = 20
- POINTS_CHAT_PER_SESSION: int = 2
- POINTS_AGENT_CREATE: int = 10
- POINTS_SKILL_CREATE: int = 15
- POINTS_MCP_CONFIG: int = 5
- POINTS_DOC_IMPORT: int = 3
- POINTS_WEEKLY_STREAK: int = 30
- POINTS_MONTHLY_STREAK: int = 100
- POINTS_DAILY_CAP: int = 50
- TOKEN_QUOTA_L0: int = 100000
- TOKEN_QUOTA_L1: int = 1000000
- TOKEN_QUOTA_L2: int = 5000000
- TOKEN_QUOTA_L3: int = 20000000
- TOKEN_QUOTA_L4: int = -1 (unlimited)
- RATE_LIMIT_L0: int = 10
- RATE_LIMIT_L1: int = 10
- RATE_LIMIT_L2: int = 50
- RATE_LIMIT_L3: int = 200
- RATE_LIMIT_L4: int = 1000
- LOCAL_MODEL_FREE_TOKENS: bool = True
- TOKEN_QUOTA_HARD_LIMIT: bool = False (soft limit by default)
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from ..constant import EnvVarLoader


class UserSystemConfig:
    """Configurable user system settings. All values read from env at init."""

    _instance: Optional["UserSystemConfig"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        prefix = "COAPIS_USER_"
        # Master switch
        self.enabled = EnvVarLoader.get_bool("COAPIS_USER_SYSTEM_ENABLED", False)

        # Points config
        self.points_login_daily = EnvVarLoader.get_int(
            f"{prefix}POINTS_LOGIN_DAILY", 5
        )
        self.points_first_login = EnvVarLoader.get_int(
            f"{prefix}POINTS_FIRST_LOGIN", 20
        )
        self.points_chat = EnvVarLoader.get_int(
            f"{prefix}POINTS_CHAT_PER_SESSION", 2
        )
        self.points_agent_create = EnvVarLoader.get_int(
            f"{prefix}POINTS_AGENT_CREATE", 10
        )
        self.points_skill_create = EnvVarLoader.get_int(
            f"{prefix}POINTS_SKILL_CREATE", 15
        )
        self.points_mcp_config = EnvVarLoader.get_int(
            f"{prefix}POINTS_MCP_CONFIG", 5
        )
        self.points_doc_import = EnvVarLoader.get_int(
            f"{prefix}POINTS_DOC_IMPORT", 3
        )
        self.points_weekly_streak = EnvVarLoader.get_int(
            f"{prefix}POINTS_WEEKLY_STREAK", 30
        )
        self.points_monthly_streak = EnvVarLoader.get_int(
            f"{prefix}POINTS_MONTHLY_STREAK", 100
        )
        self.points_daily_cap = EnvVarLoader.get_int(
            f"{prefix}POINTS_DAILY_CAP", 50
        )

        # Token quota per level
        self.token_quota_l0 = EnvVarLoader.get_int(
            f"{prefix}TOKEN_QUOTA_L0", 100_000
        )
        self.token_quota_l1 = EnvVarLoader.get_int(
            f"{prefix}TOKEN_QUOTA_L1", 1_000_000
        )
        self.token_quota_l2 = EnvVarLoader.get_int(
            f"{prefix}TOKEN_QUOTA_L2", 5_000_000
        )
        self.token_quota_l3 = EnvVarLoader.get_int(
            f"{prefix}TOKEN_QUOTA_L3", 20_000_000
        )
        self.token_quota_l4 = EnvVarLoader.get_int(
            f"{prefix}TOKEN_QUOTA_L4", -1
        )

        # Rate limits per level (requests per 60 seconds)
        self.rate_limit_l0 = EnvVarLoader.get_int(
            f"{prefix}RATE_LIMIT_L0", 120
        )
        self.rate_limit_l1 = EnvVarLoader.get_int(
            f"{prefix}RATE_LIMIT_L1", 120
        )
        self.rate_limit_l2 = EnvVarLoader.get_int(
            f"{prefix}RATE_LIMIT_L2", 50
        )
        self.rate_limit_l3 = EnvVarLoader.get_int(
            f"{prefix}RATE_LIMIT_L3", 200
        )
        self.rate_limit_l4 = EnvVarLoader.get_int(
            f"{prefix}RATE_LIMIT_L4", 1000
        )

        # Special settings
        self.local_model_free_tokens = EnvVarLoader.get_bool(
            f"{prefix}LOCAL_MODEL_FREE_TOKENS", True
        )
        self.token_quota_hard_limit = EnvVarLoader.get_bool(
            f"{prefix}TOKEN_QUOTA_HARD_LIMIT", False
        )

    @property
    def token_quotas(self) -> Dict[int, int]:
        """Return dict of level -> monthly token quota."""
        return {
            0: self.token_quota_l0,
            1: self.token_quota_l1,
            2: self.token_quota_l2,
            3: self.token_quota_l3,
            4: self.token_quota_l4,
        }

    @property
    def rate_limits(self) -> Dict[int, int]:
        """Return dict of level -> rate limit (req/s)."""
        return {
            0: self.rate_limit_l0,
            1: self.rate_limit_l1,
            2: self.rate_limit_l2,
            3: self.rate_limit_l3,
            4: self.rate_limit_l4,
        }

    @property
    def point_rules(self) -> List[Dict[str, Any]]:
        """Return list of point earning rules."""
        return [
            {"source": "first_login", "amount": self.points_first_login,
             "description": "首次登录奖励", "cap": False},
            {"source": "daily_login", "amount": self.points_login_daily,
             "description": "每日登录奖励", "cap": True},
            {"source": "chat", "amount": self.points_chat,
             "description": "每次有效对话", "cap": True},
            {"source": "create_agent", "amount": self.points_agent_create,
             "description": "创建Agent", "cap": False},
            {"source": "create_skill", "amount": self.points_skill_create,
             "description": "创建技能", "cap": False},
            {"source": "mcp_config", "amount": self.points_mcp_config,
             "description": "配置MCP工具", "cap": True},
            {"source": "doc_import", "amount": self.points_doc_import,
             "description": "导入文档(每篇)", "cap": True},
            {"source": "weekly_streak", "amount": self.points_weekly_streak,
             "description": "连续登录7天", "cap": False},
            {"source": "monthly_streak", "amount": self.points_monthly_streak,
             "description": "连续登录30天", "cap": False},
        ]

    def get_token_quota(self, level: int) -> int:
        """Get monthly token quota for a given level."""
        return self.token_quotas.get(level, self.token_quota_l1)

    def get_rate_limit(self, level: int) -> int:
        """Get rate limit for a given level."""
        return self.rate_limits.get(level, self.rate_limit_l1)

    def to_dict(self) -> Dict[str, Any]:
        """Export config as dict for API response."""
        return {
            "enabled": self.enabled,
            "point_rules": self.point_rules,
            "points_daily_cap": self.points_daily_cap,
            "token_quotas": self.token_quotas,
            "rate_limits": self.rate_limits,
            "local_model_free_tokens": self.local_model_free_tokens,
            "token_quota_hard_limit": self.token_quota_hard_limit,
        }


def get_config() -> UserSystemConfig:
    """Get or create the singleton config instance."""
    return UserSystemConfig()
