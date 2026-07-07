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

"""Memory management module for CoApis agents."""

from typing import TYPE_CHECKING

from .agent_md_manager import AgentMdManager
from .base_memory_manager import BaseMemoryManager

try:
    from .reme_light_memory_manager import ReMeLightMemoryManager
except ImportError:
    ReMeLightMemoryManager = None  # type: ignore[assignment,misc]

# Proactive symbols are lazily re-exported via __getattr__ at runtime to
# avoid circular imports (proactive -> react_agent -> agents.memory loop).
# The TYPE_CHECKING block below satisfies static analysis tools (pylint, mypy).
if TYPE_CHECKING:  # pragma: no cover
    from .proactive import (
        ProactiveConfig,
        ProactiveQueryResult,
        ProactiveTask,
        enable_proactive_for_session,
        extract_content,
        generate_proactive_response,
        proactive_configs,
        proactive_tasks,
        proactive_trigger_loop,
    )

# pylint: disable=undefined-all-variable
__all__ = [
    "AgentMdManager",
    "BaseMemoryManager",
    "ReMeLightMemoryManager",
    # proactive symbols resolved lazily at runtime via __getattr__
    "ProactiveConfig",
    "ProactiveTask",
    "ProactiveQueryResult",
    "enable_proactive_for_session",
    "proactive_trigger_loop",
    "proactive_tasks",
    "proactive_configs",
    "generate_proactive_response",
    "extract_content",
]

_PROACTIVE_EXPORTS = {
    "ProactiveConfig",
    "ProactiveTask",
    "ProactiveQueryResult",
    "enable_proactive_for_session",
    "proactive_trigger_loop",
    "proactive_tasks",
    "proactive_configs",
    "generate_proactive_response",
    "extract_content",
}


def __getattr__(name: str):
    if name in _PROACTIVE_EXPORTS:
        from . import proactive as _proactive  # noqa: PLC0415

        return getattr(_proactive, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
