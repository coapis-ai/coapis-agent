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

"""Workspace guard - path isolation and shell command enforcement.

Provides:
- Path boundary checks: ensure target paths stay within user's workspace
- Shell command whitelist/blacklist: role-based command filtering
- Zero-trust validation at tool execution layer

Shell permissions are loaded from PermissionManager config (permissions.json),
with hardcoded fallbacks if PermissionManager is not yet initialized.
"""
from __future__ import annotations

import fnmatch
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ...config.context import (
    get_current_username,
    get_current_user_role,
    get_current_workspace_dir,
)
from .audit_logger import AuditLogger, create_audit_event

logger = logging.getLogger(__name__)


# ── Fallback shell rules (used if PermissionManager not initialized) ──

FALLBACK_SHELL_WHITELIST: Dict[str, List[str]] = {
    "user": [
        "ls", "ls -la", "ls -l", "ls -a", "ls -1",
        "cat", "head", "tail", "wc", "grep", "find",
        "pwd", "date", "whoami", "id",
        "echo", "printf",
        "mkdir", "mkdir -p",
        "touch",
        "rm", "rm -rf",
        "cp", "cp -r",
        "mv",
        "tree",
        "sort", "uniq", "cut", "tr", "sed", "awk",
        "python3", "python", "node", "npm", "pip3", "pip",
        "git",
        "curl", "wget",
        "chmod", "chown",
    ],
    "advanced": [
        "ls", "ls *", "cat", "head", "tail", "wc", "grep", "find",
        "pwd", "date", "whoami", "id",
        "echo", "printf",
        "mkdir", "mkdir *",
        "touch",
        "rm", "rm *",
        "cp", "cp *",
        "mv",
        "tree",
        "sort", "uniq", "cut", "tr", "sed", "awk",
        "python3", "python", "node", "npm", "pip3", "pip",
        "git",
        "curl", "wget",
        "chmod", "chown",
        "docker", "docker-compose",
        "systemctl", "service",
        "apt", "apt-get", "yum", "dnf",
        "kill", "pkill",
        "tar", "zip", "unzip",
        "crontab",
    ],
    "admin": ["*"],
}

FALLBACK_SHELL_BLACKLIST: List[str] = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs.*",
    "dd if=",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "fdisk",
    "parted",
]

FALLBACK_DANGEROUS_PATTERNS: List[str] = [
    r"rm\s+-[a-zA-Z]*f[a-zA-Z]*\s+(/|\~|/home|/root|/etc|/usr|/bin|/sbin)",
    r">\s*(/dev/|/etc/|/usr/|/bin/|/sbin/)",
    r"chmod\s+[0-7]*[7][0-7]*\s+(/|/etc/|/usr/|/bin/|/sbin/)",
    # Pipe and redirect attacks
    r"\|\s*(bash|sh|zsh|csh|ksh|dash)",
    r"\|\s*(nc|ncat|netcat)\s+-[e]",
    r"\|\s*curl\s+",
    r"\|\s*wget\s+",
    r";\s*(rm|shutdown|reboot|halt|mkfs|dd|fdisk)",
    r"&&\s*(rm|shutdown|reboot|halt|mkfs|dd|fdisk)",
]


class WorkspaceGuard:
    """Zero-trust workspace isolation enforcer.

    Provides path boundary checks and shell command validation
    at the tool execution layer. Shell permissions are loaded from
    PermissionManager config with hardcoded fallbacks.
    """

    def __init__(self):
        self._compiled_dangerous: List[re.Pattern] = []
        self._reload_dangerous_patterns()

    def _get_permission_manager(self) -> Optional["PermissionManager"]:
        """Try to get PermissionManager instance.
        
        Returns None if not initialized (e.g., during early startup).
        """
        try:
            from ...app.permissions.manager import PermissionManager
            return PermissionManager.get_instance()
        except (RuntimeError, ImportError):
            return None

    def _reload_dangerous_patterns(self) -> None:
        """Compile dangerous pattern regexes."""
        patterns = self._get_dangerous_pattern_strings()
        self._compiled_dangerous = []
        for p in patterns:
            try:
                self._compiled_dangerous.append(re.compile(p))
            except re.error as e:
                logger.warning(f"WorkspaceGuard: invalid dangerous pattern '{p}': {e}")

    def _get_whitelist(self, role: str) -> List[str]:
        """Get whitelist for role, from PermissionManager or fallback."""
        pm = self._get_permission_manager()
        if pm is not None:
            return pm.get_shell_whitelist(role)
        return FALLBACK_SHELL_WHITELIST.get(role, [])

    def _get_blacklist(self) -> List[str]:
        """Get blacklist, from PermissionManager or fallback."""
        pm = self._get_permission_manager()
        if pm is not None:
            return pm.get_shell_blacklist()
        return list(FALLBACK_SHELL_BLACKLIST)

    def _get_dangerous_pattern_strings(self) -> List[str]:
        """Get dangerous pattern strings, from PermissionManager or fallback."""
        pm = self._get_permission_manager()
        if pm is not None:
            return pm.get_dangerous_patterns()
        return list(FALLBACK_DANGEROUS_PATTERNS)

    def is_within_workspace(self, target_path: str | Path, username: str | None = None) -> bool:
        """Check if target path is within the current user's workspace.

        Args:
            target_path: Path to check
            username: Override username (defaults to contextvar)

        Returns:
            True if path is within user's workspace, False otherwise

        Note:
        - Relative paths (e.g., "AGENTS.md", "MEMORY.md") are always allowed
        - Admin role bypasses workspace boundary checks
        - Absolute paths are checked against workspace boundary for non-admin users
        """
        # Admin role bypasses all path restrictions
        role = get_current_user_role()
        if role == "admin":
            return True

        # Relative paths are always allowed (they resolve within workspace)
        if not isinstance(target_path, Path):
            if not target_path.startswith(("/", "~")):
                return True

        workspace_dir = get_current_workspace_dir()
        if workspace_dir is None:
            logger.warning(
                "WorkspaceGuard: workspace_dir not set in context. "
                "Path check skipped."
            )
            return True  # Allow if workspace not configured

        try:
            target = Path(target_path).expanduser().resolve()
            ws = Path(workspace_dir).expanduser().resolve()

            try:
                target.relative_to(ws)
                return True
            except ValueError:
                return False
        except (OSError, RuntimeError) as e:
            logger.warning(
                f"WorkspaceGuard: failed to resolve path {target_path}: {e}"
            )
            return False

    def check_path(self, target_path: str | Path, operation: str = "read") -> Path:
        """Validate path and return resolved Path, or raise ValueError.

        Args:
            target_path: Path to validate
            operation: Operation type ("read", "write", "execute") for logging

        Returns:
            Resolved Path object

        Raises:
            ValueError: If path escapes workspace boundary
        """
        if not self.is_within_workspace(target_path):
            username = get_current_username() or "anonymous"
            resolved = Path(target_path).expanduser()
            workspace = get_current_workspace_dir() or Path("/")

            logger.warning(
                f"WorkspaceGuard: {operation} attempt outside workspace. "
                f"user={username}, path={resolved}, workspace={workspace}"
            )

            # Audit log
            ev = create_audit_event(
                event_type="path_check",
                tool_name="workspace_guard",
                target_path=str(target_path),
                result="denied",
                reason=f"路径越权: {target_path} 不在工作空间 {workspace} 内",
            )
            AuditLogger.log(ev)

            raise ValueError(
                f"路径越权: 目标路径 {target_path} 不在工作空间 {workspace} 内"
            )

        # Audit allowed path access
        ev = create_audit_event(
            event_type="path_check",
            tool_name="workspace_guard",
            target_path=str(target_path),
            result="allowed",
        )
        AuditLogger.log(ev)

        return Path(target_path).expanduser().resolve()

    def is_command_allowed(self, command: str, role: str | None = None) -> bool:
        """Check if shell command is allowed for the current user's role.

        Args:
            command: Shell command string
            role: Override role (defaults to contextvar)

        Returns:
            True if command is allowed, False otherwise
        """
        if role is None:
            role = get_current_user_role() or "user"

        # Use PermissionManager if available (supports hot-reload)
        pm = self._get_permission_manager()
        if pm is not None:
            return pm.is_shell_command_allowed(role, command)

        # Fallback: hardcoded rules
        return self._is_command_allowed_fallback(command, role)

    def _is_command_allowed_fallback(self, command: str, role: str) -> bool:
        """Fallback command check using hardcoded rules."""
        # Check whitelist first (admin wildcard takes precedence)
        allowed_commands = self._get_whitelist(role)

        # Admin wildcard — admin bypasses all restrictions
        if "*" in allowed_commands:
            return True

        # Check blacklist (non-admin roles only)
        for blacklist_pattern in self._get_blacklist():
            if fnmatch.fnmatch(command, blacklist_pattern):
                logger.warning(
                    f"WorkspaceGuard: blacklisted command blocked. "
                    f"role={role}, command={command[:100]}"
                )
                return False

        # Check dangerous patterns (non-admin roles only)
        for pattern in self._compiled_dangerous:
            if pattern.search(command):
                logger.warning(
                    f"WorkspaceGuard: dangerous pattern detected. "
                    f"role={role}, command={command[:100]}"
                )
                return False

        # Extract base command (first word)
        base_cmd = command.strip().split()[0] if command.strip() else ""

        # Check exact match or pattern match
        for allowed in allowed_commands:
            if fnmatch.fnmatch(base_cmd, allowed.split()[0]):
                return True

        logger.warning(
            f"WorkspaceGuard: command not in whitelist. "
            f"role={role}, command={command[:100]}"
        )
        return False

    def check_command(self, command: str) -> str:
        """Validate shell command and return sanitized version, or raise ValueError.

        Args:
            command: Shell command string

        Returns:
            Original command if allowed

        Raises:
            ValueError: If command is not allowed for current role
        """
        role = get_current_user_role() or "user"
        if not self.is_command_allowed(command, role):
            # Audit log
            ev = create_audit_event(
                event_type="command_check",
                tool_name="workspace_guard",
                command=command[:200],
                result="denied",
                reason=f"角色 {role} 不允许执行命令",
            )
            AuditLogger.log(ev)

            raise ValueError(
                f"命令越权: 角色 {role} 不允许执行命令 '{command[:100]}...'"
            )

        # Audit allowed command
        ev = create_audit_event(
            event_type="command_check",
            tool_name="workspace_guard",
            command=command[:200],
            result="allowed",
        )
        AuditLogger.log(ev)

        return command

    def reload_patterns(self) -> None:
        """Reload dangerous patterns from config (for hot-reload support)."""
        self._reload_dangerous_patterns()
        logger.info("WorkspaceGuard: dangerous patterns reloaded")


# Singleton instance
_guard: Optional[WorkspaceGuard] = None


def get_guard() -> WorkspaceGuard:
    """Get or create the WorkspaceGuard singleton."""
    global _guard
    if _guard is None:
        _guard = WorkspaceGuard()
    return _guard


def is_within_workspace(target_path: str | Path) -> bool:
    """Convenience function: check if path is within workspace."""
    return get_guard().is_within_workspace(target_path)


def check_path(target_path: str | Path, operation: str = "read") -> Path:
    """Convenience function: validate path or raise ValueError."""
    return get_guard().check_path(target_path, operation)


def is_command_allowed(command: str) -> bool:
    """Convenience function: check if command is allowed."""
    return get_guard().is_command_allowed(command)


def check_command(command: str) -> str:
    """Convenience function: validate command or raise ValueError."""
    return get_guard().check_command(command)
