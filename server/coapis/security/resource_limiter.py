"""Resource limiter - cross-platform CPU/memory/disk/process limits.

Uses Python's resource module on Linux/macOS, with psutil fallback on Windows.
Pure Python, zero external dependencies (psutil optional on Windows only).
"""

import os
import sys
import logging
import asyncio
import subprocess
import tempfile
import shutil
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


def sandbox_mem_mb() -> int:
    """RLIMIT_AS (virtual address space) cap for sandboxed children, in MB.

    Read from env ``COAPIS_SANDBOX_MEM_MB``; ``0`` (the default) means
    **unlimited** (``RLIM_INFINITY``).

    Why configurable instead of one fixed number: RLIMIT_AS bounds *virtual
    address space*, and V8 (node) reserves far more virtual space than it
    ever touches. A tight cap makes node die at startup with "Cannot
    allocate a 536870912 byte reservation" even when the host has gigabytes
    free - the old 512 MB cap reproduced exactly that. Any fixed cap is a
    landmine for node workloads, so the default is unlimited and the real
    safety net is expected to live at container level (docker --memory /
    cgroup v2 memory.max), which bounds *resident* memory and is kind to V8.
    """
    raw = (os.environ.get("COAPIS_SANDBOX_MEM_MB") or "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        logger.warning("COAPIS_SANDBOX_MEM_MB=%r is not an integer; using unlimited", raw)
        return 0
    return value if value > 0 else 0


def sandbox_mem_bytes() -> int:
    """Sandbox RLIMIT_AS value in bytes; RLIM_INFINITY when unlimited.

    Falls back to a very large number when the ``resource`` module is
    unavailable (Windows); callers guard the setrlimit calls with try/except.
    """
    mb = sandbox_mem_mb()
    if mb > 0:
        return mb * 1024 * 1024
    return getattr(resource, "RLIM_INFINITY", (1 << 62) - 1)


# Try to import resource module (Linux/macOS only)
try:
    import resource
    HAS_RESOURCE = True
except ImportError:
    HAS_RESOURCE = False

# Try to import psutil (Windows fallback)
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


@dataclass
class ResourceLimits:
    """Resource limits configuration."""
    cpu_seconds: int = 10          # Max CPU time in seconds
    memory_mb: int = sandbox_mem_mb()  # Max memory in MB; 0 = unlimited
    file_size_mb: int = 10         # Max file size in MB
    max_processes: int = 50        # Max child processes
    max_open_files: int = 64       # Max open file descriptors
    wall_time_seconds: int = 30    # Max wall clock time


@dataclass
class ProcessResult:
    """Result of a resource-limited process execution."""
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    oom_killed: bool = False


class ResourceLimiter:
    """Cross-platform resource limiter.

    Sets resource limits before process execution to prevent:
    - CPU exhaustion (infinite loops)
    - Memory exhaustion (memory bombs)
    - Disk exhaustion (filling disk)
    - Process fork bombs

    Linux/macOS: Uses resource module (kernel-enforced)
    Windows: Uses subprocess creation flags (best-effort)
    """

    def __init__(self, limits: Optional[ResourceLimits] = None):
        self.limits = limits or ResourceLimits()
        self._platform = sys.platform

    def _set_unix_limits(self):
        """Set resource limits on Linux/macOS (kernel-enforced)."""
        if not HAS_RESOURCE:
            return

        # CPU time limit
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (self.limits.cpu_seconds, self.limits.cpu_seconds),
        )

        # Memory limit (virtual address space); 0 means unlimited
        mem_bytes = (
            resource.RLIM_INFINITY
            if self.limits.memory_mb <= 0
            else self.limits.memory_mb * 1024 * 1024
        )
        resource.setrlimit(
            resource.RLIMIT_AS,
            (mem_bytes, mem_bytes),
        )

        # File size limit
        fsize_bytes = self.limits.file_size_mb * 1024 * 1024
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (fsize_bytes, fsize_bytes),
        )

        # Max child processes
        resource.setrlimit(
            resource.RLIMIT_NPROC,
            (self.limits.max_processes, self.limits.max_processes),
        )

        # Max open files
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (self.limits.max_open_files, self.limits.max_open_files),
        )

        logger.debug(
            "Unix limits set: cpu=%ds mem=%dMB file=%dMB procs=%d",
            self.limits.cpu_seconds,
            self.limits.memory_mb,
            self.limits.file_size_mb,
            self.limits.max_processes,
        )

    async def run_limited(
        self,
        command: str,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> ProcessResult:
        """Execute a command with resource limits.

        Args:
            command: Shell command to execute
            cwd: Working directory (defaults to temp dir)
            env: Environment variables (defaults to filtered env)
            timeout: Wall clock timeout (defaults to limits.wall_time_seconds)

        Returns:
            ProcessResult with stdout, stderr, returncode
        """
        timeout = timeout or self.limits.wall_time_seconds

        # Create temp working directory if not specified
        temp_dir = None
        if cwd is None:
            temp_dir = tempfile.mkdtemp(prefix="sandbox_")
            cwd = temp_dir

        # Filter environment
        if env is None:
            env = self._filter_env()

        try:
            if self._platform == "win32":
                return await self._run_windows(command, cwd, env, timeout)
            else:
                return await self._run_unix(command, cwd, env, timeout)
        finally:
            # Clean up temp directory
            if temp_dir:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

    async def _run_unix(
        self,
        command: str,
        cwd: str,
        env: dict,
        timeout: int,
    ) -> ProcessResult:
        """Execute on Linux/macOS with resource limits."""
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            preexec_fn=self._set_unix_limits if HAS_RESOURCE else None,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            return ProcessResult(
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                returncode=proc.returncode or 0,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ProcessResult(
                stdout="",
                stderr=f"Process killed: exceeded {timeout}s timeout",
                returncode=-1,
                timed_out=True,
            )

    async def _run_windows(
        self,
        command: str,
        cwd: str,
        env: dict,
        timeout: int,
    ) -> ProcessResult:
        """Execute on Windows with best-effort limits."""
        # Windows uses CREATE_NEW_PROCESS_GROUP for isolation
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            creationflags=creation_flags,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            return ProcessResult(
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                returncode=proc.returncode or 0,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ProcessResult(
                stdout="",
                stderr=f"Process killed: exceeded {timeout}s timeout",
                returncode=-1,
                timed_out=True,
            )

    def _filter_env(self) -> dict:
        """Create a filtered environment with only safe variables."""
        safe_keys = {
            "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM",
            "SHELL", "TMPDIR", "TEMP", "TMP",
        }
        return {k: v for k, v in __import__("os").environ.items() if k in safe_keys}

    def get_limits_info(self) -> dict:
        """Get information about current resource limits."""
        info = {
            "platform": self._platform,
            "has_resource_module": HAS_RESOURCE,
            "has_psutil": HAS_PSUTIL,
            "configured": {
                "cpu_seconds": self.limits.cpu_seconds,
                "memory_mb": self.limits.memory_mb,
                "file_size_mb": self.limits.file_size_mb,
                "max_processes": self.limits.max_processes,
                "wall_time_seconds": self.limits.wall_time_seconds,
            },
        }

        # Read current limits on Unix
        if HAS_RESOURCE:
            try:
                info["current"] = {
                    "cpu": resource.getrlimit(resource.RLIMIT_CPU),
                    "memory": resource.getrlimit(resource.RLIMIT_AS),
                    "file_size": resource.getrlimit(resource.RLIMIT_FSIZE),
                    "nproc": resource.getrlimit(resource.RLIMIT_NPROC),
                }
            except Exception:
                pass

        return info
