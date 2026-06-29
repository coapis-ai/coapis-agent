"""Process isolator - subprocess isolation with temp dirs and env filtering.

Executes tool commands in isolated subprocesses with:
- Temporary working directory (cleaned after execution)
- Environment variable filtering
- Output truncation
- Timeout enforcement

Pure Python, zero external dependencies.
"""

import asyncio
import os
import sys
import shutil
import tempfile
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Set

logger = logging.getLogger(__name__)


@dataclass
class IsolatedResult:
    """Result of an isolated process execution."""
    stdout: str
    stderr: str
    returncode: int
    working_dir: str
    timed_out: bool = False
    output_truncated: bool = False


class ProcessIsolator:
    """Execute commands in isolated subprocess environments.

    Each execution gets:
    - Its own temporary working directory
    - Filtered environment variables (no secrets leaking)
    - Output size limits
    - Wall clock timeout
    """

    # Only strictly necessary variables. Removed to prevent info leakage:
    # HOME → reveals user home path; USER/SHELL → reveals identity;
    # TMPDIR/TEMP/TMP → can be abused for symlink attacks.
    SAFE_ENV_KEYS: frozenset[str] = frozenset({
        "PATH",       # Required: find executables (git, python3, etc.)
        "LANG",       # Required: correct locale/encoding
        "LC_ALL",     # Required: locale override
        "TERM",       # Required: terminal capability queries
    })

    # Maximum length for any single env var value (anti-injection)
    _MAX_ENV_VALUE_LEN = 4096

    def __init__(
        self,
        base_workspace: str,
        max_output_bytes: int = 1024 * 1024,  # 1MB
        timeout: int = 30,
        allowed_env_keys: Optional[Set[str]] = None,
    ):
        self.base_workspace = base_workspace
        self.max_output_bytes = max_output_bytes
        self.timeout = timeout
        self.allowed_env_keys = allowed_env_keys or self.SAFE_ENV_KEYS

    async def execute(
        self,
        command: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> IsolatedResult:
        """Execute a command in an isolated environment.

        Args:
            command: Shell command to execute
            cwd: Working directory (creates temp if None)
            env: Additional environment variables

        Returns:
            IsolatedResult with output and metadata
        """
        # Create isolated working directory — under workspace/files/tmp
        temp_dir = None
        if cwd is None:
            tmp_base = Path(self.base_workspace) / "files" / "tmp"
            tmp_base.mkdir(parents=True, exist_ok=True)
            temp_dir = tempfile.mkdtemp(prefix="isolated_", dir=str(tmp_base))
            cwd = temp_dir

        # Build filtered environment
        exec_env = self._build_env(env)

        try:
            return await self._run_process(command, cwd, exec_env)
        finally:
            # Clean up temp directory
            if temp_dir:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

    async def _run_process(
        self,
        command: str,
        cwd: str,
        env: Dict[str, str],
    ) -> IsolatedResult:
        """Run the subprocess with timeout."""
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        try:
            raw_stdout, raw_stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return IsolatedResult(
                stdout="",
                stderr=f"Process killed: exceeded {self.timeout}s timeout",
                returncode=-1,
                working_dir=cwd,
                timed_out=True,
            )

        # Decode and truncate output
        stdout = raw_stdout.decode(errors="replace")
        stderr = raw_stderr.decode(errors="replace")
        output_truncated = False

        if len(stdout.encode()) > self.max_output_bytes:
            stdout = stdout[:self.max_output_bytes]
            stdout += f"\n... [truncated at {self.max_output_bytes} bytes]"
            output_truncated = True

        if len(stderr.encode()) > self.max_output_bytes:
            stderr = stderr[:self.max_output_bytes]
            stderr += f"\n... [truncated at {self.max_output_bytes} bytes]"
            output_truncated = True

        return IsolatedResult(
            stdout=stdout,
            stderr=stderr,
            returncode=proc.returncode or 0,
            working_dir=cwd,
            output_truncated=output_truncated,
        )

    def _build_env(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Build filtered environment variables with value sanitization.

        Only whitelisted keys are included. Values are truncated to
        ``_MAX_ENV_VALUE_LEN`` to prevent injection via oversized values.
        Null bytes are stripped from all values.
        """
        env = {}
        for key in self.allowed_env_keys:
            val = os.environ.get(key)
            if val is not None:
                env[key] = self._sanitize_env_value(val)

        # Add extra variables (also sanitized)
        if extra:
            for k, v in extra.items():
                env[k] = self._sanitize_env_value(v)

        return env

    @classmethod
    def _sanitize_env_value(cls, value: str) -> str:
        """Strip null bytes and truncate overly long values."""
        # Remove null bytes (potential injection vector in shell)
        value = value.replace("\x00", "")
        # Truncate to prevent memory abuse
        if len(value) > cls._MAX_ENV_VALUE_LEN:
            value = value[:cls._MAX_ENV_VALUE_LEN]
        return value

    def create_workspace_copy(self, prefix: str = "isolated_") -> str:
        """Create a temporary copy of the workspace for isolation."""
        tmp_base = Path(self.base_workspace) / "files" / "tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix=prefix, dir=str(tmp_base))
        try:
            # Copy essential files (not the entire workspace)
            for item in os.listdir(self.base_workspace):
                src = os.path.join(self.base_workspace, item)
                dst = os.path.join(temp_dir, item)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                elif os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
        except Exception as e:
            logger.warning("Failed to copy workspace: %s", e)
        return temp_dir

    def get_stats(self) -> dict:
        """Get isolator statistics."""
        return {
            "base_workspace": self.base_workspace,
            "max_output_bytes": self.max_output_bytes,
            "timeout": self.timeout,
            "allowed_env_keys": len(self.allowed_env_keys),
        }
