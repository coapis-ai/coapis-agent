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
