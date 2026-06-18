"""Sandboxed tool executor with timeout, output truncation, and rate limiting."""

import asyncio
import collections
import logging
import os
import time
from typing import Any, Callable, Optional
from .tool_sandbox import ToolSandbox

logger = logging.getLogger(__name__)

# Per-user rate limit: max tool calls per sliding window
_RATE_LIMIT_MAX = int(os.environ.get("COAPIS_RATE_LIMIT_MAX", "30"))
_RATE_LIMIT_WINDOW = float(os.environ.get("COAPIS_RATE_LIMIT_WINDOW", "60"))

# Tools that are allowed to execute
ALLOWED_TOOLS = frozenset({
    "read_file", "write_file", "edit_file",
    "grep_search", "glob_search",
    "execute_shell_command",
    "get_current_time", "set_user_timezone",
    "get_token_usage",
    "view_image",
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
    """Execute tools in a sandboxed environment.

    Provides:
    - Tool whitelist enforcement
    - Path validation for file tools
    - Command validation for shell tools
    - Execution timeout
    - Output truncation
    - Per-user rate limiting (sliding window)
    """

    # Class-level sliding window: {username: deque[timestamp]}
    _rate_windows: dict[str, collections.deque] = {}

    def __init__(
        self,
        username: str,
        workspace_dir: str,
        max_output_bytes: int = 1024 * 1024,  # 1MB
        execution_timeout: int = 30,  # seconds
    ):
        self.username = username
        self.workspace_dir = workspace_dir
        self.sandbox = ToolSandbox(username, workspace_dir)
        self.max_output_bytes = max_output_bytes
        self.execution_timeout = execution_timeout

    def _check_rate_limit(self) -> bool:
        """Check if user exceeds per-user rate limit. Returns True if OK."""
        now = time.monotonic()
        window = self._rate_windows.setdefault(
            self.username, collections.deque()
        )
        # Evict old entries outside the sliding window
        while window and (now - window[0]) > _RATE_LIMIT_WINDOW:
            window.popleft()
        if len(window) >= _RATE_LIMIT_MAX:
            return False
        window.append(now)
        return True

    async def execute_tool(
        self,
        tool_name: str,
        tool_func: Callable,
        **kwargs,
    ) -> Any:
        """Execute a tool with sandbox checks.

        Args:
            tool_name: Name of the tool
            tool_func: Async callable to execute
            **kwargs: Tool arguments

        Returns:
            Tool execution result

        Raises:
            PermissionError: If tool is not allowed or arguments are invalid
            TimeoutError: If execution exceeds timeout
        """
        # 0. Per-user rate limit check
        if not self._check_rate_limit():
            raise PermissionError(
                f"Rate limit exceeded: {_RATE_LIMIT_MAX} tool calls "
                f"per {_RATE_LIMIT_WINDOW}s window for user '{self.username}'"
            )

        # 1. Tool whitelist check
        if tool_name not in ALLOWED_TOOLS:
            raise PermissionError(f"Tool '{tool_name}' not in allowed list")

        # 2. Argument validation
        self._validate_arguments(tool_name, kwargs)

        # 3. Execute with timeout
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._run_tool(tool_func, **kwargs),
                timeout=self.execution_timeout,
            )
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t0
            logger.warning(
                "Tool %s timed out after %.1fs for user %s",
                tool_name, elapsed, self.username,
            )
            raise TimeoutError(
                f"Tool '{tool_name}' exceeded {self.execution_timeout}s timeout"
            )

        elapsed = time.monotonic() - t0
        logger.debug(
            "Tool %s executed in %.1fs for user %s",
            tool_name, elapsed, self.username,
        )

        # 4. Output truncation
        return self._truncate_output(result)

    def _validate_arguments(self, tool_name: str, kwargs: dict):
        """Validate tool arguments against sandbox rules."""
        if tool_name in PATH_TOOLS:
            path = (
                kwargs.get("file_path")
                or kwargs.get("path")
                or kwargs.get("image_path")
                or kwargs.get("file_path")
                or ""
            )
            if path:
                result = self.sandbox.check_path(path)
                if not result.allowed:
                    raise PermissionError(
                        f"Path access denied for '{tool_name}': {result.reason}"
                    )

        if tool_name in COMMAND_TOOLS:
            command = kwargs.get("command", "")
            if command:
                result = self.sandbox.check_command(command)
                if not result.allowed:
                    raise PermissionError(
                        f"Command denied for '{tool_name}': {result.reason}"
                    )

    async def _run_tool(self, func: Callable, **kwargs) -> Any:
        """Run the tool function."""
        if asyncio.iscoroutinefunction(func):
            return await func(**kwargs)
        else:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: func(**kwargs))

    def _truncate_output(self, result: Any) -> Any:
        """Truncate oversized output."""
        if isinstance(result, str):
            encoded = result.encode("utf-8", errors="replace")
            if len(encoded) > self.max_output_bytes:
                truncated = encoded[: self.max_output_bytes].decode(
                    "utf-8", errors="replace"
                )
                return truncated + f"\n... [truncated at {self.max_output_bytes} bytes]"
        return result
