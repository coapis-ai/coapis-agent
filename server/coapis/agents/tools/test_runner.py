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

"""Test runner — run tests (pytest/unittest/npm) and capture output/coverage.

Wraps common test runners, captures structured results.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_TIMEOUT = 120  # seconds


def _get_workspace() -> Path:
    """Get workspace directory."""
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws)
    except Exception:
        pass
    return Path.cwd()


def _detect_runner(project_dir: Path) -> str:
    """Auto-detect test runner based on project files."""
    if (project_dir / "package.json").exists():
        return "npm"
    if (project_dir / "pyproject.toml").exists() or (project_dir / "setup.py").exists():
        # Prefer pytest
        try:
            r = asyncio.get_event_loop().run_until_complete(
                _run_cmd(["pytest", "--version"], str(project_dir))
            )
            if r.get("returncode") == 0:
                return "pytest"
        except Exception:
            pass
        return "unittest"
    if (project_dir / "pom.xml").exists():
        return "maven"
    if (project_dir / "go.mod").exists():
        return "go"
    return "unknown"


async def _run_cmd(
    cmd: list[str], cwd: str, timeout: int = _TIMEOUT
) -> dict[str, Any]:
    """Run a shell command with timeout and capture output."""
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ},
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        elapsed = round(time.time() - start, 2)
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace")[-8000:],
            "stderr": stderr.decode(errors="replace")[-4000:],
            "elapsed": elapsed,
        }
    except asyncio.TimeoutError:
        return {"returncode": -1, "stdout": "", "stderr": f"Timeout after {timeout}s", "elapsed": timeout}
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": f"Command not found: {cmd[0]}", "elapsed": 0}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e), "elapsed": 0}


def _parse_pytest_output(output: str) -> dict[str, Any]:
    """Parse pytest summary line."""
    result: dict[str, Any] = {}
    for line in output.split("\n"):
        line = line.strip()
        # "3 passed, 1 failed in 2.5s"
        if " passed" in line or " failed" in line:
            parts = line.split(" in ")
            if len(parts) >= 1:
                result["summary"] = parts[0]
            if len(parts) >= 2:
                result["time"] = parts[1]
        elif line.startswith("="):
            result["separator"] = line
    return result


def _parse_npm_output(output: str) -> dict[str, Any]:
    """Parse npm test output."""
    result: dict[str, Any] = {}
    for line in output.split("\n"):
        line = line.strip()
        if "passing" in line or "failing" in line:
            result.setdefault("summary", []).append(line)
    return result


async def test_runner(
    target: str = "",
    runner: str = "",
    args: str = "",
    timeout: int = 60,
    coverage: bool = False,
) -> dict[str, Any]:
    """测试运行器。

    自动检测或指定测试框架，运行测试并返回结构化结果。

    Args:
        target: 测试文件/目录（如 tests/, tests/test_api.py, -k test_login）
        runner: 指定运行器（pytest/unittest/npm/maven/go），留空自动检测
        args: 额外参数（空格分隔）
        timeout: 超时秒数，默认 60
        coverage: 是否收集覆盖率（仅 pytest 支持）

    Returns:
        测试结果
    """
    project_dir = _get_workspace()

    # Auto-detect runner
    if not runner.strip():
        runner = _detect_runner(project_dir)

    cmd: list[str] = []
    extra = args.strip().split() if args.strip() else []

    if runner == "pytest":
        cmd = ["python3", "-m", "pytest"]
        if coverage:
            cmd.extend(["--cov", "--cov-report=term-missing"])
        if target.strip():
            cmd.extend(target.strip().split())
        cmd.extend(extra)
    elif runner == "unittest":
        cmd = ["python3", "-m", "pytest"]
        if target.strip():
            cmd.extend(target.strip().split())
        else:
            cmd.append(".")
        cmd.extend(extra)
    elif runner == "npm":
        cmd = ["npm", "test"]
        if target.strip():
            cmd.extend(["--", target.strip()])
        cmd.extend(extra)
    elif runner == "maven":
        cmd = ["mvn", "test"]
        if target.strip():
            cmd.extend(["-Dtest=" + target.strip()])
        cmd.extend(extra)
    elif runner == "go":
        cmd = ["go", "test", "-v"]
        if target.strip():
            cmd.extend(target.strip().split())
        cmd.extend(extra)
    else:
        return {"error": f"无法自动检测测试运行器，请通过 runner 参数指定 (pytest/unittest/npm/maven/go)"}

    result = await _run_cmd(cmd, str(project_dir), timeout=timeout)

    # Parse output
    parsed: dict[str, Any] = {}
    if runner == "pytest":
        parsed = _parse_pytest_output(result["stdout"])
    elif runner == "npm":
        parsed = _parse_npm_output(result["stdout"])

    return {
        "runner": runner,
        "command": " ".join(cmd),
        "returncode": result["returncode"],
        "success": result["returncode"] == 0,
        "elapsed": result["elapsed"],
        "parsed": parsed,
        "stdout": result["stdout"][-3000:] if result["stdout"] else "",
        "stderr": result["stderr"][-2000:] if result["stderr"] else "",
    }
