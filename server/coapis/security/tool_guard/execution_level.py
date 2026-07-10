# -*- coding: utf-8 -*-
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

"""Tool execution security levels for CoApis agent.

Defines different approval strategies for tool execution:
- STRICT: All tools require approval
- SMART: Low-risk tools auto-allowed, medium+ require approval
- AUTO: Only guarded_tools require approval (backward compatible)
- OFF: Tool guard completely disabled
"""
from __future__ import annotations

from enum import Enum


class ToolExecutionLevel(str, Enum):
    """Tool execution security level.

    Controls when tools require user approval before execution.
    """

    STRICT = "strict"
    """All tools require approval (highest security).

    Use case: Production environments, high-security deployments.
    Behavior: Even INFO-level findings trigger approval flow.
    """

    SMART = "smart"
    """Low-risk tools auto-allowed, medium+ require approval (recommended).

    Use case: Balanced security and productivity (default recommended).
    Behavior:
        - INFO/LOW severity: auto-allow
        - MEDIUM/HIGH/CRITICAL severity: require approval
    """

    AUTO = "auto"
    """Only explicitly guarded tools require approval (backward compatible).

    Use case: Current behavior, legacy compatibility.
    Behavior: Only tools in guarded_tools list are checked.
    """

    OFF = "off"
    """Tool guard completely disabled (no protection).

    Use case: Development/testing, fully trusted environments.
    Behavior: All tools execute immediately without any checks.
    """

    @classmethod
    def from_config(cls, value: str | None) -> "ToolExecutionLevel":
        """Parse execution level from config string.

        Args:
            value: Config value (case-insensitive)

        Returns:
            ToolExecutionLevel enum value, defaults to AUTO if invalid
        """
        if not value:
            return cls.AUTO

        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.AUTO

    def requires_approval_for_all_tools(self) -> bool:
        """Check if this level requires approval for all tools."""
        return self == ToolExecutionLevel.STRICT

    def is_disabled(self) -> bool:
        """Check if tool guard is completely disabled."""
        return self == ToolExecutionLevel.OFF

    def is_smart_mode(self) -> bool:
        """Check if using smart risk-based approval."""
        return self == ToolExecutionLevel.SMART


# ── Role-based default execution levels ─────────────────────────────
# When agent config does not specify approval_level, the user's role
# determines the default security policy.

ROLE_DEFAULT_EXECUTION_LEVEL: dict[str, ToolExecutionLevel] = {
    "user": ToolExecutionLevel.AUTO,
    "advanced": ToolExecutionLevel.SMART,
    "admin": ToolExecutionLevel.AUTO,
    "superadmin": ToolExecutionLevel.OFF,
}


def get_effective_execution_level(
    config_level: ToolExecutionLevel | None,
    user_role: str,
) -> ToolExecutionLevel:
    """Resolve the effective execution level considering both config and role.

    Priority:
    1. Explicit config (approval_level in agent.json) — highest priority
    2. Role-based default from ROLE_DEFAULT_EXECUTION_LEVEL
    3. Fallback: AUTO
    """
    # If config explicitly sets a non-AUTO level, honor it
    if config_level and config_level != ToolExecutionLevel.AUTO:
        return config_level

    # Otherwise use role-based default
    return ROLE_DEFAULT_EXECUTION_LEVEL.get(user_role, ToolExecutionLevel.AUTO)
