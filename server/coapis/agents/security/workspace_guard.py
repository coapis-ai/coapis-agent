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
from ...constant import WORKING_DIR
from .audit_logger import AuditLogger, create_audit_event

logger = logging.getLogger(__name__)


# ── Fallback shell rules (used if PermissionManager not initialized) ──

FALLBACK_SHELL_WHITELIST: Dict[str, List[str]] = {
    "user": [
        # 文件浏览（* 表示允许任意参数）
        "ls *",
        "cat *", "head *", "tail *", "wc *", "grep *", "find *",
        "pwd", "date", "whoami",
        "echo *", "printf *",
        # 文件操作（限于工作区内，由 is_within_workspace 保护）
        "mkdir *",
        "touch *",
        "rm *",  # 工作区内允许删除
        "cp *",
        "mv *",
        "tree",
        # 文本处理
        "sort *", "uniq *", "cut *", "tr *", "sed *", "awk *",
        # 编程工具
        "python3 *", "python *",
        "node *", "npm *", "npx *", "pip3 *", "pip *",
        # 版本控制
        "git *",
        # 网络
        "curl *", "wget *",
        # 压缩解压
        "tar *", "zip *", "unzip *",
    ],
    "advanced": [
        # 文件浏览（* 表示允许任意参数）
        "ls *",
        "cat *", "head *", "tail *", "wc *", "grep *", "find *",
        "pwd", "date", "whoami", "id",
        "echo *", "printf *",
        # 文件操作
        "mkdir *",
        "touch *",
        "rm *", "rm -r", "rm -f",
        "cp *",
        "mv *",
        "tree",
        # 文本处理
        "sort *", "uniq *", "cut *", "tr *", "sed *", "awk *",
        # 编程工具（仅限脚本文件模式，禁止 -c/-e 内联执行）
        "python3 *.py", "python *.py",
        "node *.js", "npm *", "pip3 *", "pip *",
        # 版本控制
        "git *",
        # 网络
        "curl *", "wget *",
        # 系统管理
        "chmod *", "chown *",
        "docker", "docker *",
        "systemctl *", "service *",
        "apt *", "apt-get *", "yum *", "dnf *",
        "kill *", "pkill *",
        "tar *", "zip *", "unzip *",
        "crontab *",
    ],
    # admin: same as advanced — all commands go through
    # CommandRiskClassifier for CONFIRM/BLOCK level checks.
    "admin": [
        # 文件浏览
        "ls *",
        "cat *", "head *", "tail *", "wc *", "grep *", "find *",
        "pwd", "date", "whoami", "id",
        "echo *", "printf *",
        # 文件操作
        "mkdir *",
        "touch *",
        "rm *", "rm -r", "rm -f",
        "cp *",
        "mv *",
        "tree",
        # 文本处理
        "sort *", "uniq *", "cut *", "tr *", "sed *", "awk *",
        # 编程工具（仅限脚本文件模式，禁止 -c/-e 内联执行）
        "python3 *.py", "python *.py",
        "node *.js", "npm *", "pip3 *", "pip *",
        # 版本控制
        "git *",
        # 网络
        "curl *", "wget *",
        # 系统管理
        "chmod *", "chown *",
        "docker", "docker *",
        "systemctl *", "service *",
        "apt *", "apt-get *", "yum *", "dnf *",
        "kill *", "pkill *",
        "tar *", "zip *", "unzip *",
        "crontab *",
    ],
}

FALLBACK_SHELL_BLACKLIST: List[str] = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "mkfs.*",
    "dd if=",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "fdisk",
    "parted",
    "iptables",
    "nft",
]

FALLBACK_DANGEROUS_PATTERNS: List[str] = [
    r"rm\s+-[a-zA-Z]*f[a-zA-Z]*\s+(/|\~|/home|/root|/etc|/usr|/bin|/sbin)",
    r">\s*(/dev/|/etc/|/usr/|/bin/|/sbin/)",
    r"chmod\s+[0-7]*[7][0-7]*\s+(/|/etc/|/usr/|/bin/|/sbin/)",
    # P0: 禁止解释器内联执行（-c, -e, --eval）
    r"(python3?|node|ruby|perl|php)\s+(-c|--eval|-e)\s",
    # 禁止通过解释器模块执行命令
    r"python3?\s+-m\s+(subprocess|os|pty|shutil)",
    # 禁止通过 heredoc 绕过
    r"(python3?|node)\s+<<",
    # 禁止反弹 shell
    r"socket\.socket\s*\(",
    r"subprocess\.(call|run|Popen)\s*\(",
    r"os\.system\s*\(",
    r"os\.popen\s*\(",
    r"child_process",
    r"exec\s*\(",
    # 禁止将文件内容发送到外部
    r"curl\s+.*-d\s+@",
    r"curl\s+.*--data\s+@",
    r"wget\s+.*--post-file",
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
        """Get whitelist for role (fallback only)."""
        return FALLBACK_SHELL_WHITELIST.get(role, [])

    def _get_blacklist(self) -> List[str]:
        """Get blacklist (fallback only)."""
        return list(FALLBACK_SHELL_BLACKLIST)

    def _get_dangerous_pattern_strings(self) -> List[str]:
        """Get dangerous pattern strings (fallback only)."""
        return list(FALLBACK_DANGEROUS_PATTERNS)

    def is_within_workspace(self, target_path: str | Path, username: str | None = None) -> bool:
        """Check if target path is within the current user's workspace.

        Supports symlinked directories within workspace (e.g., workspace/files/
        -> workspaces/{username}/files/). The check passes if EITHER:
        1. The resolved path (following symlinks) is within workspace, OR
        2. The non-resolved path (before following symlinks) is within workspace

        Also allows access to global shared directories:
        - skill_pool: 全局技能池，所有用户可用

        Args:
            target_path: Path to check
            username: Override username (defaults to contextvar)

        Returns:
            True if path is within user's workspace or global shared dir, False otherwise
        """
        workspace_dir = get_current_workspace_dir()
        if workspace_dir is None:
            logger.warning(
                "WorkspaceGuard: workspace_dir not set in context. "
                "Path check skipped."
            )
            return True  # Allow if workspace not configured

        try:
            ws = Path(workspace_dir).expanduser().resolve()
            target_resolved = Path(target_path).expanduser().resolve()

            # Check 1: Resolved path (follows symlinks) within workspace
            try:
                target_resolved.relative_to(ws)
                return True
            except ValueError:
                pass

            # Check 2: Non-resolved path (before following symlinks) within workspace
            try:
                target_unresolved = Path(target_path).expanduser()
                target_unresolved.relative_to(ws)
                return True
            except ValueError:
                pass

            # Check 3: Global shared directories (skill_pool)
            # 全局技能池对所有用户开放
            skill_pool_dir = WORKING_DIR / "skill_pool"
            try:
                target_resolved.relative_to(skill_pool_dir.resolve())
                return True
            except ValueError:
                pass

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

        # Always use fallback (PermissionManager shell methods removed)
        return self._is_command_allowed_fallback(command, role)

    # Flags that enable inline code execution in interpreters — always blocked
    _INTERPRETER_INLINE_FLAGS: frozenset[str] = frozenset({
        "-c", "-e", "-E", "-i", "-I",
        "--command", "--eval", "--execute", "--interactive",
    })

    def _is_command_allowed_fallback(self, command: str, role: str) -> bool:
        """Fallback command check using prefix+args semantic matching.

        Whitelist entries follow these conventions:
        - ``"ls"``        → base command only, no args
        - ``"ls *"``      → base command + any arguments allowed
        - ``"python3 *.py"`` → base command + file arguments only
                             (flags like -c/-e are blocked)

        The old fnmatch-based approach had two problems:
        1. ``python3 *.py`` matched ``python3 -c os.system(...)`` (should block)
        2. ``python3 *.py`` did NOT match ``python3 setup.py install`` (should allow)

        This rewrite uses semantic argument classification:
        - Wildcard entries (``base *``): any args allowed
        - File-pattern entries (``base *.ext``): args must be files/paths, flags blocked
        - Base-only entries (``base``): no args allowed
        """
        cmd_stripped = command.strip()
        if not cmd_stripped:
            return False

        # ── 1. Check blacklist first ──
        for blacklist_pattern in self._get_blacklist():
            if fnmatch.fnmatch(cmd_stripped, blacklist_pattern):
                logger.warning(
                    "WorkspaceGuard: blacklisted command blocked. "
                    "role=%s, command=%s",
                    role, command[:100],
                )
                return False

        # ── 2. Check dangerous patterns (regex-based) ──
        for pattern in self._compiled_dangerous:
            if pattern.search(cmd_stripped):
                logger.warning(
                    "WorkspaceGuard: dangerous pattern detected. "
                    "role=%s, command=%s",
                    role, command[:100],
                )
                return False

        # ── 3. Whitelist matching (prefix + args) ──
        tokens = cmd_stripped.split()
        base_cmd = tokens[0] if tokens else ""
        args = tokens[1:] if len(tokens) > 1 else []

        allowed_commands = self._get_whitelist(role)

        for allowed in allowed_commands:
            allowed_tokens = allowed.split()
            allowed_base = allowed_tokens[0]

            # 3a. Base command must match
            if not fnmatch.fnmatch(base_cmd, allowed_base):
                continue

            allowed_tail = allowed_tokens[1:]  # everything after base

            # 3b. Base-only entry (e.g. "ls", "cat", "pwd") → no args allowed
            if not allowed_tail:
                if not args:
                    return True
                # Has args but whitelist says base-only → reject
                continue

            # 3c. Wildcard entry (e.g. "docker *", "curl *", "git") → any args OK
            if allowed_tail == ["*"]:
                return True

            # 3d. File-pattern entry (e.g. "python3 *.py", "node *.js")
            #     → args must contain at least one file path; inline flags blocked
            if self._is_file_pattern_entry(allowed_tail):
                if args and self._args_are_files_only(args):
                    return True
                continue

            # 3e. Fallback: full-string fnmatch for complex patterns
            if fnmatch.fnmatch(cmd_stripped, allowed):
                return True

        logger.warning(
            "WorkspaceGuard: command not in whitelist. "
            "role=%s, command=%s",
            role, command[:100],
        )
        return False

    @classmethod
    def _is_file_pattern_entry(cls, allowed_tail: list[str]) -> bool:
        """Return True if the whitelist tail is a file-matching pattern like '*.py'."""
        if len(allowed_tail) == 1:
            pat = allowed_tail[0]
            # Patterns like "*.py", "*.js", "*.sh" are file patterns
            if pat.startswith("*") and "." in pat:
                return True
        return False

    @classmethod
    def _args_are_files_only(cls, args: list[str]) -> bool:
        """Check that all arguments are file paths / flags that are safe.

        Rejects:
        - Inline execution flags: -c, -e, --eval, -i, etc.
        - Piped/redirect operators: |, >, >>
        - Flags that take code strings: -c "code"
        - File paths outside the user's workspace
        """
        if not args:
            return True

        workspace = get_current_workspace_dir()

        for arg in args:
            # Block pipe/redirect operators
            if arg in ("|", ">", ">>", "<", "&&", "||"):
                return False

            # Check if this is a flag (starts with -)
            if arg.startswith("-"):
                # Single-dash short flags: extract the letter(s) after -
                if arg.startswith("--"):
                    # Long flag: --eval, --command, --interactive, etc.
                    flag_name = arg.split("=", 1)[0]
                    if flag_name in cls._INTERPRETER_INLINE_FLAGS:
                        return False
                else:
                    # Short flags: -c, -e, -i, -E, -I (possibly bundled: -ce)
                    flag_chars = arg[1:].split("=", 1)[0]
                    for ch in flag_chars:
                        if ch in ("c", "e", "E", "i", "I"):
                            return False
            else:
                # Non-flag argument: validate it's within workspace
                # Reject absolute paths (including ~/) when no workspace configured
                arg_path = Path(arg).expanduser()
                if arg_path.is_absolute():
                    if workspace:
                        try:
                            resolved = arg_path.resolve()
                            resolved.relative_to(Path(workspace).resolve())
                        except ValueError:
                            logger.warning(
                                "WorkspaceGuard: script path outside workspace blocked. "
                                "arg=%s, workspace=%s",
                                arg, workspace,
                            )
                            return False
                    else:
                        # No workspace configured — reject absolute paths entirely
                        logger.warning(
                            "WorkspaceGuard: absolute path rejected without workspace. "
                            "arg=%s",
                            arg,
                        )
                        return False

        return True

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
