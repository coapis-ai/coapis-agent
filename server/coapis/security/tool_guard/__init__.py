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
