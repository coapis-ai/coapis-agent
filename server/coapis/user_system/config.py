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

"""User system configuration - token quotas and rate limits.

Simplified: no user levels, no points system.
All level-based logic has been removed.

The user system is always enabled in the open-source version.
Environment variables (prefix: COAPIS_USER_):
- TOKEN_QUOTA_DEFAULT: int = 1000000 (monthly token quota per user)
- TOKEN_QUOTA_HARD_LIMIT: bool = False (soft limit by default)

Local models are always free of charge.
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
        # User system is always enabled in open-source version
        self.enabled = True

        # Token quota (unified, no per-level)
        self.default_token_quota = EnvVarLoader.get_int(
            f"{prefix}TOKEN_QUOTA_DEFAULT", 1_000_000
        )

        # Local models are always free of charge
        self.local_model_free_tokens = True

        # Special settings
        self.token_quota_hard_limit = EnvVarLoader.get_bool(
            f"{prefix}TOKEN_QUOTA_HARD_LIMIT", False
        )

    def get_token_quota(self, level: int = 0) -> int:
        """Return monthly token quota. Level parameter kept for backward compat but ignored."""
        return self.default_token_quota

    def to_dict(self) -> Dict[str, Any]:
        """Serialize config for API response."""
        return {
            "enabled": self.enabled,
            "default_token_quota": self.default_token_quota,
            "local_model_free_tokens": self.local_model_free_tokens,
            "token_quota_hard_limit": self.token_quota_hard_limit,
        }


# Singleton accessor
_config: Optional[UserSystemConfig] = None


def get_config() -> UserSystemConfig:
    """Get or create the singleton config."""
    global _config
    if _config is None:
        _config = UserSystemConfig()
    return _config
