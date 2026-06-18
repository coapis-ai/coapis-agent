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

"""ACP shared definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ...config.config import ACPAgentConfig, ACPConfig

__all__ = [
    "ACPAgentConfig",
    "ACPConfig",
    "ACPErrors",
    "ACPConfigurationError",
    "ACPTransportError",
    "ACPProtocolError",
    "ACPSessionError",
    "SuspendedPermission",
]


class ACPErrors(Exception):
    def __init__(self, message: str, *, agent: Optional[str] = None):
        super().__init__(message)
        self.agent = agent


class ACPConfigurationError(ACPErrors):
    pass


class ACPTransportError(ACPErrors):
    pass


class ACPProtocolError(ACPErrors):
    pass


class ACPSessionError(ACPErrors):
    pass


@dataclass
class SuspendedPermission:
    payload: dict[str, Any]
    options: list[dict[str, Any]]
    agent: str
    tool_name: str
    tool_kind: str
    target: str | None = None
    action: str | None = None
    summary: str | None = None
    command: str | None = None
    paths: list[str] = field(default_factory=list)
    requires_user_confirmation: bool = True
