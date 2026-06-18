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

"""Base classes for control command handlers.

Control commands are high-priority commands like /stop that require
immediate response and special handling outside the normal agent flow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from ...channels.base import BaseChannel
    from ...workspace import Workspace


@dataclass
class ControlContext:
    """Context for control command execution.

    Attributes:
        workspace: Current workspace instance (for task_tracker, etc.)
        payload: Original message payload (native dict or AgentRequest)
        channel: Channel instance
        session_id: Normalized session ID (e.g. "console:user1")
        user_id: User ID from request
        agent_id: Agent ID for permission checks
        role: User role for permission gating (user/advanced/admin)
        args: Parsed command arguments (command-specific)
    """

    workspace: "Workspace"
    payload: Any
    channel: "BaseChannel"
    session_id: str
    user_id: str
    agent_id: str
    role: str = "user"
    args: Dict[str, Any] = field(default_factory=dict)


class BaseControlCommandHandler(ABC):
    """Abstract base class for control command handlers.

    Subclasses implement specific commands (e.g. /stop, /pause).

    Example:
        class StopCommandHandler(BaseControlCommandHandler):
            command_name = "/stop"

            async def handle(self, context: ControlContext) -> str:
                # Implementation
                return "Task stopped"
    """

    command_name: str = ""

    @abstractmethod
    async def handle(self, context: ControlContext) -> str:
        """Handle the control command.

        Args:
            context: Control command context

        Returns:
            Response text to send to user

        Raises:
            Exception: If command execution fails
        """
        raise NotImplementedError
