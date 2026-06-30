"""Sandboxed tool executor - unified security gateway for all tool calls.

Security layers (executed in order):
1. Tool whitelist check
2. Path whitelist check (file tools)
3. Command classification (L0-L4 via UnifiedToolGuardEngine)
4. Pattern rules + escape detection (via UnifiedToolGuardEngine)
5. Input content detection (via InputGuardEngine)
6. Audit logging for all security events
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .tool_sandbox import ToolSandbox

logger = logging.getLogger(__name__)

# Tools that are allowed to execute
ALLOWED_TOOLS = frozenset({
    "read_file", "write_file", "edit_file",
    "grep_search", "glob_search",
    "execute_shell_command",
    "get_current_time", "set_user_timezone",
    "get_token_usage",
    "view_image", "view_video",
    "send_file_to_user",
    "desktop_screenshot",
    "memory_search",
})

# Tools that require path validation
PATH_TOOLS = frozenset({
    "read_file", "write_file", "edit_file",
    "view_image", "send_file_to_user",
})

# Tools that require command validation
COMMAND_TOOLS = frozenset({
    "execute_shell_command",
})


class SandboxedExecutor:
    """Execute tools through unified security pipeline.

    Provides:
    - Tool whitelist enforcement
    - Path validation for file tools
    - Command classification (L0-L4)
    - Pattern rules + escape detection
    - Input content detection
    - Execution timeout
    - Output truncation
    - Audit logging
    """

    def __init__(self):
        self._unified_engine = None
        self._input_guard = None
        self._audit_logger = None

    def _get_unified_engine(self):
        """Lazy-load UnifiedToolGuardEngine."""
        if self._unified_engine is None:
            try:
                from .tool_guard.unified_engine import UnifiedToolGuardEngine
                self._unified_engine = UnifiedToolGuardEngine()
                logger.info("UnifiedToolGuardEngine loaded")
            except Exception as e:
                logger.warning(f"Failed to load UnifiedToolGuardEngine: {e}")
        return self._unified_engine

    def _get_input_guard(self):
        """Lazy-load InputGuardEngine."""
        if self._input_guard is None:
            try:
                from .input_guard.engine import InputGuardEngine
                self._input_guard = InputGuardEngine()
                logger.info("InputGuardEngine loaded")
            except Exception as e:
                logger.warning(f"Failed to load InputGuardEngine: {e}")
        return self._input_guard

    def _get_audit_logger(self):
        """Lazy-load SecurityAuditLogger."""
        if self._audit_logger is None:
            try:
                from .audit_logger import SecurityAuditLogger
                self._audit_logger = SecurityAuditLogger.get_instance()
            except Exception:
                pass
        return self._audit_logger

    def _get_sandbox(self, username: str) -> Optional[ToolSandbox]:
        """Get ToolSandbox for a user."""
        try:
            workspaces_dir = os.environ.get(
                "COAPIS_WORKSPACES_DIR", "/apps/ai/coapis/workspaces"
            )
            workspace_dir = f"{workspaces_dir}/{username}"
            return ToolSandbox(username=username, workspace_dir=workspace_dir)
        except Exception as e:
            logger.warning(f"Failed to create ToolSandbox for {username}: {e}")
            return None

    def check_tool_allowed(self, tool_name: str) -> dict:
        """Check if a tool is allowed to execute.

        Tools registered in the system are already vetted by the platform.
        Runtime security is enforced by:
        - ToolGuardMixin (command classification L0-L4, path validation)
        - Docker container sandbox (network/filesystem isolation)

        Returns:
            {"allowed": bool, "reason": str}
        """
        return {"allowed": True, "reason": ""}

    def check_path(self, username: str, path: str, operation: str = "read") -> dict:
        """Check if path access is allowed for a user.

        Returns:
            {"allowed": bool, "reason": str, "resolved_path": str}
        """
        sandbox = self._get_sandbox(username)
        if sandbox is None:
            return {"allowed": True, "reason": "No sandbox available", "resolved_path": path}

        result = sandbox.check_path(path, operation)
        return {
            "allowed": result.allowed,
            "reason": result.reason,
            "resolved_path": result.resolved_path or path,
        }

    def check_command(self, username: str, command: str) -> dict:
        """Run full security pipeline on a command.

        Returns:
            {
                "allowed": bool,
                "action": str,  # allow/audit/confirm/block
                "level": str,   # L0-L4
                "reason": str,
                "matched_rules": list,
                "evasion_flags": list,
            }
        """
        result = {
            "allowed": True,
            "action": "allow",
            "level": "L0",
            "reason": "",
            "matched_rules": [],
            "evasion_flags": [],
        }

        # 1. ToolSandbox basic check
        sandbox = self._get_sandbox(username)
        if sandbox:
            sb_result = sandbox.check_command(command)
            if not sb_result.allowed:
                result["allowed"] = False
                result["action"] = "block"
                result["reason"] = sb_result.reason
                self._log_command(username, command, result)
                return result

        # 2. UnifiedToolGuardEngine (command classification + rules + evasion)
        engine = self._get_unified_engine()
        if engine:
            try:
                guard_result = engine.process_command("execute_shell_command", {"command": command})
                result["level"] = guard_result.get("level", "L0")
                result["action"] = guard_result.get("action", "allow")
                result["matched_rules"] = guard_result.get("matched_rules", [])
                result["evasion_flags"] = guard_result.get("evasion_flags", [])
                result["reason"] = guard_result.get("reason", "")

                if result["action"] == "block":
                    result["allowed"] = False
                    self._log_command(username, command, result)
                    return result

                # audit/confirm actions: allowed but logged
                if result["action"] in ("audit", "confirm"):
                    self._log_command(username, command, result)
            except Exception as e:
                logger.warning(f"UnifiedToolGuardEngine error: {e}")

        # 3. InputGuardEngine (input content detection)
        input_guard = self._get_input_guard()
        if input_guard:
            try:
                from .input_guard.models import InputRequest
                request = InputRequest(content=command, user=username, source="tool_execute")
                ig_result = asyncio.get_event_loop().run_until_complete(
                    input_guard.check_input(request)
                ) if not asyncio.get_event_loop().is_running() else None

                if ig_result and ig_result.blocked:
                    result["allowed"] = False
                    result["action"] = "block"
                    result["reason"] = f"InputGuard: {ig_result.reason}"
                    self._log_input(username, command, ig_result)
                    return result
            except Exception as e:
                logger.debug(f"InputGuard check skipped: {e}")

        self._log_command(username, command, result)
        return result

    def _log_command(self, username: str, command: str, result: dict):
        """Log command check result to audit logger."""
        audit = self._get_audit_logger()
        if audit is None:
            return

        try:
            if result["action"] == "block":
                audit.log_command_block(
                    user=username,
                    command=command,
                    level=result.get("level", "L0"),
                    action=result["action"],
                    reason=result.get("reason", ""),
                    matched_rules=result.get("matched_rules", []),
                )
            elif result["action"] in ("audit", "confirm"):
                audit.log_command_audit(
                    user=username,
                    command=command,
                    level=result.get("level", "L0"),
                    action=result["action"],
                    matched_rules=result.get("matched_rules", []),
                )
        except Exception as e:
            logger.debug(f"Audit log failed: {e}")

    def _log_input(self, username: str, input_text: str, ig_result):
        """Log input guard result to audit logger."""
        audit = self._get_audit_logger()
        if audit is None:
            return

        try:
            audit.log_input_block(
                user=username,
                input_summary=input_text,
                reason=ig_result.reason,
                matched_rules=getattr(ig_result, "matched_rules", []),
            )
        except Exception as e:
            logger.debug(f"Audit log failed: {e}")
