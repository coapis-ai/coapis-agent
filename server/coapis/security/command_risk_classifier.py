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

"""Command Risk Classifier — three-level command classification.

Classifies shell commands into:
- AUTO:     directly execute (ls, cat, git status, etc.)
- CONFIRM:  require user approval via ApprovalCard (rm, kill, docker, etc.)
- BLOCK:    hard-reject without approval (rm -rf /, fork bomb, etc.)
- DENIED:   role lacks permission (user trying shell, user trying rm)

Usage::

    classifier = CommandRiskClassifier()
    result = classifier.classify(
        tool_name="execute_shell_command",
        command="rm -rf /tmp/cache",
        role="advanced",
        exec_level="STRICT",
    )
    print(result.risk_level)  # CONFIRM
    print(result.timeout_seconds)  # 60
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class CommandRiskLevel(str, Enum):
    """Three-level command risk classification."""
    AUTO = "auto"           # 🟢  Directly execute
    CONFIRM = "confirm"     # 🟡  Require user approval
    BLOCK = "block"         # 🔴  Hard-reject
    DENIED = "denied"       # 🔴  Role lacks permission


class CommandCategory(str, Enum):
    """Command operation categories."""
    FILE_BROWSE = "file_browse"
    FILE_CREATE = "file_create"
    FILE_DELETE = "file_delete"
    FILE_MOVE_COPY = "file_move_copy"
    TEXT_PROCESS = "text_process"
    PERMISSION = "permission"
    PROCESS_MGMT = "process_mgmt"
    SERVICE_MGMT = "service_mgmt"
    PACKAGE_MGMT = "package_mgmt"
    CONTAINER = "container"
    NETWORK_READONLY = "network_readonly"
    NETWORK_UPLOAD = "network_upload"
    CODE_EXEC_SCRIPT = "code_exec_script"
    CODE_EXEC_INLINE = "code_exec_inline"
    VERSION_CONTROL_READONLY = "version_control_readonly"
    VERSION_CONTROL_WRITE = "version_control_write"
    ARCHIVE = "archive"
    DANGEROUS = "dangerous"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CommandClassification:
    """Result of command risk classification."""
    risk_level: CommandRiskLevel
    command_category: CommandCategory
    timeout_seconds: int
    reason: str


# ── Default timeout config ──
DEFAULT_CONFIRM_TIMEOUT = 60
HIGH_RISK_CONFIRM_TIMEOUT = 30

# ── Role × CommandCategory permission matrix ──
# None = DENIED (role cannot use this category)
# CommandRiskLevel.AUTO = directly execute
# CommandRiskLevel.CONFIRM = require approval
ROLE_CATEGORY_PERMISSIONS: Dict[str, Dict[CommandCategory, Optional[CommandRiskLevel]]] = {
    "user": {
        CommandCategory.FILE_BROWSE: CommandRiskLevel.AUTO,
        CommandCategory.FILE_CREATE: CommandRiskLevel.AUTO,
        CommandCategory.FILE_DELETE: None,          # DENIED
        CommandCategory.FILE_MOVE_COPY: CommandRiskLevel.AUTO,
        CommandCategory.TEXT_PROCESS: CommandRiskLevel.AUTO,
        CommandCategory.PERMISSION: None,           # DENIED
        CommandCategory.PROCESS_MGMT: None,         # DENIED
        CommandCategory.SERVICE_MGMT: None,         # DENIED
        CommandCategory.PACKAGE_MGMT: None,         # DENIED
        CommandCategory.CONTAINER: None,            # DENIED
        CommandCategory.NETWORK_READONLY: CommandRiskLevel.AUTO,
        CommandCategory.NETWORK_UPLOAD: None,       # DENIED
        CommandCategory.CODE_EXEC_SCRIPT: CommandRiskLevel.AUTO,
        CommandCategory.CODE_EXEC_INLINE: CommandRiskLevel.BLOCK,
        CommandCategory.VERSION_CONTROL_READONLY: CommandRiskLevel.AUTO,
        CommandCategory.VERSION_CONTROL_WRITE: CommandRiskLevel.AUTO,
        CommandCategory.ARCHIVE: None,              # DENIED
        CommandCategory.DANGEROUS: CommandRiskLevel.BLOCK,
    },
    "advanced": {
        CommandCategory.FILE_BROWSE: CommandRiskLevel.AUTO,
        CommandCategory.FILE_CREATE: CommandRiskLevel.AUTO,
        CommandCategory.FILE_DELETE: CommandRiskLevel.CONFIRM,
        CommandCategory.FILE_MOVE_COPY: CommandRiskLevel.CONFIRM,
        CommandCategory.TEXT_PROCESS: CommandRiskLevel.AUTO,
        CommandCategory.PERMISSION: CommandRiskLevel.CONFIRM,
        CommandCategory.PROCESS_MGMT: CommandRiskLevel.CONFIRM,
        CommandCategory.SERVICE_MGMT: CommandRiskLevel.CONFIRM,
        CommandCategory.PACKAGE_MGMT: CommandRiskLevel.CONFIRM,
        CommandCategory.CONTAINER: CommandRiskLevel.CONFIRM,
        CommandCategory.NETWORK_READONLY: CommandRiskLevel.AUTO,
        CommandCategory.NETWORK_UPLOAD: CommandRiskLevel.BLOCK,
        CommandCategory.CODE_EXEC_SCRIPT: CommandRiskLevel.AUTO,
        CommandCategory.CODE_EXEC_INLINE: CommandRiskLevel.BLOCK,
        CommandCategory.VERSION_CONTROL_READONLY: CommandRiskLevel.AUTO,
        CommandCategory.VERSION_CONTROL_WRITE: CommandRiskLevel.CONFIRM,
        CommandCategory.ARCHIVE: CommandRiskLevel.AUTO,
        CommandCategory.DANGEROUS: CommandRiskLevel.BLOCK,
    },
    "admin": {
        CommandCategory.FILE_BROWSE: CommandRiskLevel.AUTO,
        CommandCategory.FILE_CREATE: CommandRiskLevel.AUTO,
        CommandCategory.FILE_DELETE: CommandRiskLevel.CONFIRM,
        CommandCategory.FILE_MOVE_COPY: CommandRiskLevel.CONFIRM,
        CommandCategory.TEXT_PROCESS: CommandRiskLevel.AUTO,
        CommandCategory.PERMISSION: CommandRiskLevel.CONFIRM,
        CommandCategory.PROCESS_MGMT: CommandRiskLevel.CONFIRM,
        CommandCategory.SERVICE_MGMT: CommandRiskLevel.CONFIRM,
        CommandCategory.PACKAGE_MGMT: CommandRiskLevel.CONFIRM,
        CommandCategory.CONTAINER: CommandRiskLevel.CONFIRM,
        CommandCategory.NETWORK_READONLY: CommandRiskLevel.AUTO,
        CommandCategory.NETWORK_UPLOAD: CommandRiskLevel.BLOCK,
        CommandCategory.CODE_EXEC_SCRIPT: CommandRiskLevel.AUTO,
        CommandCategory.CODE_EXEC_INLINE: CommandRiskLevel.CONFIRM,
        CommandCategory.VERSION_CONTROL_READONLY: CommandRiskLevel.AUTO,
        CommandCategory.VERSION_CONTROL_WRITE: CommandRiskLevel.CONFIRM,
        CommandCategory.ARCHIVE: CommandRiskLevel.AUTO,
        CommandCategory.DANGEROUS: CommandRiskLevel.BLOCK,
    },
}

# ── Command → Category mapping (order matters, first match wins) ──
_COMMAND_PATTERNS: List[Tuple[CommandCategory, str, str]] = [
    # FILE BROWSE (must be command prefix — match start of command only)
    (CommandCategory.FILE_BROWSE, r"^\s*(ls|dir|tree|pwd|stat|du|df)\b", "file browse"),

    # FILE CREATE
    (CommandCategory.FILE_CREATE, r"^\s*(mkdir|touch|tee)\b", "file create"),

    # TEXT PROCESS (must be command prefix)
    (CommandCategory.TEXT_PROCESS, r"^\s*(sort|uniq|cut|tr|sed|awk|wc|head|tail|cat|grep|find|echo|printf)\b", "text process"),

    # DANGEROUS (hard-block patterns, checked first)
    (CommandCategory.DANGEROUS, r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+/", "rm -rf /"),
    (CommandCategory.DANGEROUS, r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+~", "rm -rf ~"),
    (CommandCategory.DANGEROUS, r"\bmkfs\b", "mkfs"),
    (CommandCategory.DANGEROUS, r"\bdd\s+.*of=\/dev\/", "dd to device"),
    (CommandCategory.DANGEROUS, r"\bshutdown\b", "shutdown"),
    (CommandCategory.DANGEROUS, r"\breboot\b", "reboot"),
    (CommandCategory.DANGEROUS, r"\bhalt\b", "halt"),
    (CommandCategory.DANGEROUS, r"\bpoweroff\b", "poweroff"),
    (CommandCategory.DANGEROUS, r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (CommandCategory.DANGEROUS, r"\b(curl|wget)\b.*\|.*\b(bash|sh|zsh)\b", "curl|bash"),
    (CommandCategory.DANGEROUS, r"\/dev\/(tcp|udp)\/", "reverse shell"),
    (CommandCategory.DANGEROUS, r"\bnc\s+.*-e\s*\S+", "nc reverse shell"),
    (CommandCategory.DANGEROUS, r"\bsocat\s+.*EXEC:", "socat reverse shell"),

    # NETWORK (data upload — checked before general network)
    (CommandCategory.NETWORK_UPLOAD, r"curl\s+.*(-d|--data)\s+@", "curl data upload"),
    (CommandCategory.NETWORK_UPLOAD, r"curl\s+.*(-d|--data)\s", "curl data upload"),
    (CommandCategory.NETWORK_UPLOAD, r"wget\s+.*--post-file", "wget data upload"),

    # PRIVILEGE ESCALATION (sudo/su — treat as dangerous for non-admin)
    (CommandCategory.DANGEROUS, r"\bsudo\b", "sudo"),
    (CommandCategory.DANGEROUS, r"\bsu\b(?!\w)", "su"),

    # FILE DELETE
    (CommandCategory.FILE_DELETE, r"\brm\b", "rm"),
    (CommandCategory.FILE_DELETE, r"\bdel\b", "del (Windows)"),
    (CommandCategory.FILE_DELETE, r"\bRemove-Item\b", "Remove-Item"),

    # PROCESS MANAGEMENT
    (CommandCategory.PROCESS_MGMT, r"\bkill\b", "kill"),
    (CommandCategory.PROCESS_MGMT, r"\bpkill\b", "pkill"),
    (CommandCategory.PROCESS_MGMT, r"\bkillall\b", "killall"),

    # SERVICE MANAGEMENT
    (CommandCategory.SERVICE_MGMT, r"\bsystemctl\b", "systemctl"),
    (CommandCategory.SERVICE_MGMT, r"\bservice\b", "service"),
    (CommandCategory.SERVICE_MGMT, r"\bcrontab\b", "crontab"),

    # CONTAINER
    (CommandCategory.CONTAINER, r"\bdocker\b", "docker"),

    # PACKAGE MANAGEMENT
    (CommandCategory.PACKAGE_MGMT, r"\bapt(-get)?\b", "apt"),
    (CommandCategory.PACKAGE_MGMT, r"\byum\b", "yum"),
    (CommandCategory.PACKAGE_MGMT, r"\bdnf\b", "dnf"),
    (CommandCategory.PACKAGE_MGMT, r"\bpip3?\s+install\b", "pip install"),
    (CommandCategory.PACKAGE_MGMT, r"\bnpm\s+install\b", "npm install"),
    (CommandCategory.PACKAGE_MGMT, r"\bnpm\s+i\b", "npm install"),

    # PERMISSION
    (CommandCategory.PERMISSION, r"\bchmod\b", "chmod"),
    (CommandCategory.PERMISSION, r"\bchown\b", "chown"),

    # FILE MOVE/COPY
    (CommandCategory.FILE_MOVE_COPY, r"\bmv\b", "mv"),
    (CommandCategory.FILE_MOVE_COPY, r"\bcp\b", "cp"),

    # CODE EXEC (inline — before script)
    (CommandCategory.CODE_EXEC_INLINE, r"(python3?|node|ruby|perl|php)\s+(-c|--eval|-e)\s", "interpreter inline"),

    # CODE EXEC (script — safe)
    (CommandCategory.CODE_EXEC_SCRIPT, r"(python3?|node)\s+\S+\.(py|js)", "script execution"),
    (CommandCategory.CODE_EXEC_SCRIPT, r"\bnpm\b(?!\s+install)", "npm"),
    (CommandCategory.CODE_EXEC_SCRIPT, r"\bpip3?\b(?!\s+install)", "pip"),

    # VERSION CONTROL
    (CommandCategory.VERSION_CONTROL_WRITE, r"\bgit\s+(push|commit|merge|rebase|reset)\b", "git write"),
    (CommandCategory.VERSION_CONTROL_READONLY, r"\bgit\b", "git read-only"),

    # ARCHIVE
    (CommandCategory.ARCHIVE, r"\b(tar|zip|unzip)\b", "archive"),

    # NETWORK (readonly)
    (CommandCategory.NETWORK_READONLY, r"\bcurl\b", "curl read-only"),
    (CommandCategory.NETWORK_READONLY, r"\bwget\b", "wget read-only"),
]

# ── High-risk confirm commands (shorter timeout) ──
_HIGH_RISK_CONFIRM_COMMANDS: Set[CommandCategory] = {
    CommandCategory.PROCESS_MGMT,
    CommandCategory.SERVICE_MGMT,
    CommandCategory.PERMISSION,
}

# ── Non-shell tools that don't need classification ──
_NON_SHELL_TOOLS: Set[str] = {
    "read_file", "write_file", "edit_file", "append_file",
    "grep_search", "glob_search", "get_current_time",
    "set_user_timezone", "get_token_usage", "view_image",
    "view_video", "send_file_to_user", "desktop_screenshot",
    "memory_search", "browser_use",
}


class CommandRiskClassifier:
    """Three-level command risk classifier.

    Classifies shell commands based on:
    1. Role permissions (user/advanced/admin)
    2. Command patterns (regex matching)
    3. Execution context (tool name, parameters)
    """

    def __init__(
        self,
        *,
        confirm_timeout: int = DEFAULT_CONFIRM_TIMEOUT,
        high_risk_confirm_timeout: int = HIGH_RISK_CONFIRM_TIMEOUT,
    ) -> None:
        self._confirm_timeout = confirm_timeout
        self._high_risk_confirm_timeout = high_risk_confirm_timeout
        self._compiled_patterns = [
            (cat, re.compile(pat, re.IGNORECASE), desc)
            for cat, pat, desc in _COMMAND_PATTERNS
        ]

    def classify(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        role: str,
        *,
        command: Optional[str] = None,
    ) -> CommandClassification:
        """Classify a tool call's risk level.

        Parameters
        ----------
        tool_name:
            Name of the tool being called (e.g. "execute_shell_command").
        tool_input:
            Parameters dict from the LLM tool call.
        role:
            User role (user/advanced/admin).
        command:
            Shell command string. If None, extracted from tool_input["command"].
        """
        # Non-shell tools → AUTO (no classification needed)
        if tool_name in _NON_SHELL_TOOLS:
            return CommandClassification(
                risk_level=CommandRiskLevel.AUTO,
                command_category=CommandCategory.UNKNOWN,
                timeout_seconds=0,
                reason="Non-shell tool, no classification needed",
            )

        # Extract command
        if command is None:
            command = tool_input.get("command", "")
        if not command:
            return CommandClassification(
                risk_level=CommandRiskLevel.AUTO,
                command_category=CommandCategory.UNKNOWN,
                timeout_seconds=0,
                reason="Empty command, treating as AUTO",
            )

        # Classify command category
        category = self._classify_command(command)

        # Look up role × category permission
        role_perms = ROLE_CATEGORY_PERMISSIONS.get(role, {})
        risk_level = role_perms.get(category)

        # If category not in role perms → DENIED
        if risk_level is None:
            return CommandClassification(
                risk_level=CommandRiskLevel.DENIED,
                command_category=category,
                timeout_seconds=0,
                reason=f"Role '{role}' does not have permission for '{category.value}'",
            )

        # Determine timeout
        timeout = 0
        if risk_level == CommandRiskLevel.CONFIRM:
            if category in _HIGH_RISK_CONFIRM_COMMANDS:
                timeout = self._high_risk_confirm_timeout
            else:
                timeout = self._confirm_timeout

        # Build reason
        reason = self._build_reason(risk_level, category, role)

        return CommandClassification(
            risk_level=risk_level,
            command_category=category,
            timeout_seconds=timeout,
            reason=reason,
        )

    def _classify_command(self, command: str) -> CommandCategory:
        """Classify a command string into a category."""
        for category, pattern, desc in self._compiled_patterns:
            if pattern.search(command):
                return category
        return CommandCategory.UNKNOWN

    def _build_reason(
        self,
        risk_level: CommandRiskLevel,
        category: CommandCategory,
        role: str,
    ) -> str:
        """Build a human-readable reason string."""
        if risk_level == CommandRiskLevel.DENIED:
            return f"Role '{role}' does not have permission for '{category.value}' commands"
        if risk_level == CommandRiskLevel.BLOCK:
            return f"Command category '{category.value}' is blocked for security"
        if risk_level == CommandRiskLevel.CONFIRM:
            return f"Command category '{category.value}' requires user confirmation"
        return f"Command category '{category.value}' is safe to execute automatically"
