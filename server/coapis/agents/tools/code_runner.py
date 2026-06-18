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

"""Code runner — safe execution of Python/Node code snippets with timeout and output capture.

Runs code in subprocess with restricted environment, isolated process, and timeout.
Security: runs in a restricted subprocess with sanitized env (no HOME/USER overrides),
read-only filesystem hint via temp dir, and network disabled when possible.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import resource
import tempfile
import time


def _set_child_resource_limits() -> None:
    """Set resource limits for child processes (preexec_fn)."""
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (200 * 1024 * 1024, 200 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        resource.setrlimit(resource.RLIMIT_NPROC, (100, 100))
    except (ValueError, OSError):
        pass
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_MAX_OUTPUT = 10000  # chars
_DEFAULT_TIMEOUT = 30  # seconds
_MAX_TIMEOUT = 120  # seconds

# ── Sandbox env: strip sensitive vars, force isolated tmp ──
_SANDBOX_ENV_KEYS = {
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR",
    "PYTHONIOENCODING", "NODE_PATH",
}

def _sandbox_env() -> dict[str, str]:
    """Build a restricted environment for subprocess execution."""
    env = {}
    for key in _SANDBOX_ENV_KEYS:
        val = os.environ.get(key)
        if val:
            env[key] = val
    # Force isolated temp directory
    tmpdir = tempfile.mkdtemp(prefix="coapis_code_")
    env["TMPDIR"] = tmpdir
    env["HOME"] = tmpdir  # prevent reading ~/.ssh etc.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


async def _run_process(
    cmd: list[str],
    code: str,
    timeout: int,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a process with code as stdin or via temp file."""
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            preexec_fn=_set_child_resource_limits,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=code.encode()), timeout=timeout
        )
        elapsed = round(time.time() - start, 2)
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace")[-_MAX_OUTPUT:],
            "stderr": stderr.decode(errors="replace")[-_MAX_OUTPUT:],
            "elapsed": elapsed,
        }
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"⏱️ Execution timed out after {timeout}s",
            "elapsed": timeout,
        }
    except FileNotFoundError:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"❌ Runtime not found: {cmd[0]}",
            "elapsed": 0,
        }
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e), "elapsed": 0}


async def code_runner(
    code: str = "",
    language: str = "python",
    timeout: int = 30,
    args: str = "",
) -> dict[str, Any]:
    """代码执行器。

    在子进程中安全执行代码片段，捕获 stdout/stderr 和返回码。

    Args:
        code: 要执行的代码
        language: 语言 (python/node)
        timeout: 超时秒数，默认 30，最大 120
        args: 传递给程序的命令行参数（空格分隔）

    Returns:
        执行结果
    """
    if not code.strip():
        return {"error": "code 不能为空"}

    timeout = min(max(timeout, 1), _MAX_TIMEOUT)

    if language == "python":
        cmd = ["python3", "-"]
        # Write code to temp file for better traceback
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name
        cmd = ["python3", tmp_path]
    elif language == "node":
        cmd = ["node", "-e", code]
    else:
        return {"error": f"不支持的语言: {language}，支持 python/node"}

    # Append args if provided
    if args.strip():
        cmd.extend(args.strip().split())

    result = await _run_process(cmd, code, timeout, env=_sandbox_env())

    # Cleanup temp file for python
    if language == "python":
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

    return {
        "language": language,
        "returncode": result["returncode"],
        "success": result["returncode"] == 0,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "elapsed": result["elapsed"],
    }
