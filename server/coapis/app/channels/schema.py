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

"""
Channel schema: channel type identifiers, routing (ChannelAddress),
and conversion protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@dataclass
class ChannelAddress:
    """
    Unified routing for send: kind + id + extra.
    Replaces ad-hoc meta keys (channel_id, user_id, session_webhook, etc.).
    """

    kind: str  # "dm" | "channel" | "webhook" | "console" | ...
    id: str
    extra: Optional[Dict[str, Any]] = None

    def to_handle(self) -> str:
        """String handle for to_handle (e.g. discord:ch:123)."""
        if self.extra and "to_handle" in self.extra:
            return str(self.extra["to_handle"])
        return f"{self.kind}:{self.id}"


# Built-in channel type identifiers. Plugin channels use arbitrary str keys.
BUILTIN_CHANNEL_TYPES = (
    "imessage",
    "discord",
    "dingtalk",
    "feishu",
    "qq",
    "telegram",
    "mqtt",
    "console",
    "voice",
    "sip",
    "xiaoyi",
)

# ChannelType is str to allow plugin channels; built-in set above.
ChannelType = str

# Default channel when none is specified (runner / config).
DEFAULT_CHANNEL: ChannelType = "console"


@runtime_checkable
class ChannelMessageConverter(Protocol):
    """
    Protocol for channel message conversion.
    Channels convert native payloads to AgentRequest and send responses.
    """

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """
        Convert this channel's native message payload to AgentRequest.
        Use runtime Message and Content types; no intermediate envelope.
        """

    async def send_response(
        self,
        to_handle: str,
        response: Any,
        meta: Optional[dict] = None,
    ) -> None:
        """Convert AgentResponse to channel reply and send."""
