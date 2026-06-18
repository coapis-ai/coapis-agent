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

"""
Pre-tool-call guard framework for CoApis.

Scans tool execution parameters **before** the agent invokes a tool,
looking for dangerous patterns such as command injection, data
exfiltration, or access to sensitive files.

Architecture
~~~~~~~~~~~~

The guard framework mirrors the skill-scanner's extensible design:

* **BaseToolGuardian** – abstract interface every guardian must implement.
* **RuleBasedToolGuardian** – YAML regex-signature matching on parameter
  values (fast, line-based).
* **ToolGuardEngine** – orchestrator that runs all registered guardians
  and aggregates findings into a :class:`ToolGuardResult`.

Only rule-based detection is shipped today.  The :class:`BaseToolGuardian`
interface is intentionally kept thin so that new engines (LLM-as-a-judge,
semantic analysis, …) can be plugged in without changes to the
orchestrator.

Quick start::

    from coapis.security.tool_guard import ToolGuardEngine

    engine = ToolGuardEngine()
    result = engine.guard("execute_shell_command", {"command": "rm -rf /"})
    if not result.is_safe:
        print(f"WARN: {result.max_severity.value} findings")
"""
from __future__ import annotations

from .models import (
    TOOL_GUARD_DENIED_MARK,
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)
from .engine import ToolGuardEngine
from .guardians import BaseToolGuardian
from .guardians.file_guardian import FilePathToolGuardian
from .guardians.rule_guardian import RuleBasedToolGuardian

__all__ = [
    "TOOL_GUARD_DENIED_MARK",
    "GuardFinding",
    "GuardSeverity",
    "GuardThreatCategory",
    "BaseToolGuardian",
    "FilePathToolGuardian",
    "RuleBasedToolGuardian",
    "ToolGuardEngine",
    "ToolGuardResult",
]
