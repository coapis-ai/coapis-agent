"""Tool execution sandbox - cross-platform path and command validation."""

import os
import re
from pathlib import Path
from typing import Optional, Set
from dataclasses import dataclass


@dataclass
class SandboxResult:
    allowed: bool
    reason: str = ""
    resolved_path: Optional[str] = None


class ToolSandbox:
    """Cross-platform tool execution sandbox.

    Validates file paths and shell commands before execution.
    Works on Linux, macOS, and Windows.
    """

    # Blocked path patterns (regex)
    BLOCKED_PATTERNS = [
        r"\.\./\.\./\.\.",
        r"/etc/passwd",
        r"/etc/shadow",
        r"/root/",
        r"/home/[^/]+/\.ssh",
        r"\.env$",
        r"secret",
        r"private.*key",
    ]

    # Dangerous command patterns
    DANGEROUS_COMMANDS = [
        "rm -rf /",
        "dd if=",
        "mkfs",
        ":(){ :|:& };:",
        "chmod 777 /",
        "wget",
        "curl.*|sh",
        "python -c.*import os",
        "nc -",
        "netcat",
        "telnet",
        "rm -rf /*",
        "rm -rf ~",
        "mv / ",
    ]

    def __init__(self, username: str, workspace_dir: str):
        self.username = username
        self.workspace_dir = Path(workspace_dir).resolve()
        self.allowed_dirs = self._build_allowed_dirs()

    def _build_allowed_dirs(self) -> Set[Path]:
        """Build set of allowed directories."""
        dirs = {
            self.workspace_dir,
            self.workspace_dir / "files",
            self.workspace_dir / "chats",
        }
        # Temp directory — per-user, under workspace/files/tmp
        dirs.add(self.workspace_dir / "files" / "tmp")
        return dirs

    def check_path(self, path: str, operation: str = "read") -> SandboxResult:
        """Check if a file path is allowed.

        Args:
            path: File path to validate
            operation: read/write/execute

        Returns:
            SandboxResult with allowed status and reason
        """
        try:
            resolved = Path(path).resolve()
        except (OSError, ValueError) as e:
            return SandboxResult(allowed=False, reason=f"Invalid path: {e}")

        path_str = str(resolved)

        # Check blocked patterns
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, path_str, re.IGNORECASE):
                return SandboxResult(
                    allowed=False,
                    reason=f"Blocked pattern: {pattern}",
                )

        # Check if path is within allowed directories
        for allowed_dir in self.allowed_dirs:
            try:
                resolved.relative_to(allowed_dir)
                return SandboxResult(allowed=True, resolved_path=path_str)
            except ValueError:
                continue

        return SandboxResult(
            allowed=False,
            reason=f"Path {path_str} not in any allowed directory",
        )

    def check_command(self, command: str) -> SandboxResult:
        """Check if a shell command is safe.

        Args:
            command: Shell command to validate

        Returns:
            SandboxResult with allowed status and reason
        """
        cmd_lower = command.lower().strip()

        # Check dangerous patterns
        for dangerous in self.DANGEROUS_COMMANDS:
            if dangerous in cmd_lower:
                return SandboxResult(
                    allowed=False,
                    reason=f"Dangerous command pattern: {dangerous}",
                )

        # Check path traversal
        if "../" in command and any(
            sensitive in command for sensitive in ["/etc", "/root", "/home"]
        ):
            return SandboxResult(
                allowed=False,
                reason="Path traversal detected in command",
            )

        return SandboxResult(allowed=True)
