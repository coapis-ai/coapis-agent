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
looking for dangerous shell commands, shell-evasion tricks, sensitive-file
targets, prompt-injection content and data-exfiltration shapes.

Architecture (C2–C5: one engine, one config source)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **UnifiedToolGuardEngine** – the single evaluator.  Layers, in order:
  access control (denied/guarded) → file-path layer → command classification
  + global pattern rules (shell only) → shell-evasion heuristics →
  cross-command rules.  It returns one of ``allow / audit / confirm / block``.
* **InputGuardEngine** – content detection (prompt injection, credential
  exfiltration) for *every* tool, run by the mixin before the layers above.
* **config_store** – resolves *the* YAML file
  (``{WORKING_DIR}/system/tool_guard.yaml``) that both the engine and the
  console read/write.

The legacy orchestrator (``ToolGuardEngine`` + ``RuleBasedToolGuardian`` +
``rules/dangerous_shell_commands.yaml``) was retired in C5: it read a second
config source and duplicated the rule set, which is how the "console switch
does nothing" and "builtin-rules always empty" defects happened.

Quick start::

    from coapis.security.tool_guard import get_unified_engine

    result = get_unified_engine().process_command(
        "execute_shell_command", {"command": "rm -rf /"}
    )
    if result["action"] == "block":
        print("blocked:", result["reason"])
"""
from __future__ import annotations

from .config_store import resolve_yaml_path
from .guardians import BaseToolGuardian
from .guardians.file_guardian import FilePathToolGuardian
from .models import (
    TOOL_GUARD_DENIED_MARK,
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)
from .unified_engine import (
    UnifiedToolGuardEngine,
    get_unified_engine,
    reset_engine,
)

__all__ = [
    "TOOL_GUARD_DENIED_MARK",
    "BaseToolGuardian",
    "FilePathToolGuardian",
    "GuardFinding",
    "GuardSeverity",
    "GuardThreatCategory",
    "ToolGuardResult",
    "UnifiedToolGuardEngine",
    "get_unified_engine",
    "reset_engine",
    "resolve_yaml_path",
]
