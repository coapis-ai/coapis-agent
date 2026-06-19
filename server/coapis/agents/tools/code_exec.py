# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""Code execution — unified tool for running tests and code snippets.

Merges test_runner + code_runner into a single tool via action parameter.
Capabilities: run pytest/unittest/npm tests, execute Python/Node code snippets.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import resource
import tempfile
import time
from pathlib import Path
from typing import Any

from .registry import register_tool


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

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 10000
_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 120

# ── Sandbox env ──
_SANDBOX_ENV_KEYS = {
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR",
    "PYTHONIOENCODING", "NODE_PATH",
}


def _sandbox_env() -> dict[str, str]:
    env = {}
    for key in _SANDBOX_ENV_KEYS:
        val = os.environ.get(key)
        if val:
            env[key] = val
    tmpdir = tempfile.mkdtemp(prefix="coapis_code_")
    env["TMPDIR"] = tmpdir
    env["HOME"] = tmpdir
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _get_workspace() -> Path:
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws)
    except Exception:
        pass
    return Path.cwd()


async def _run_cmd(
    cmd: list[str], cwd: str, timeout: int = 120,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env or {**os.environ},
            preexec_fn=_set_child_resource_limits,
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
        try:
            proc.kill()
        except Exception:
            pass
        return {"returncode": -1, "stdout": "", "stderr": f"Timeout after {timeout}s", "elapsed": timeout}
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": f"Command not found: {cmd[0]}", "elapsed": 0}


def _detect_runner(project_dir: Path) -> str:
    if (project_dir / "package.json").exists():
        return "npm"
    if (project_dir / "pyproject.toml").exists() or (project_dir / "setup.py").exists():
        return "pytest"
    if (project_dir / "pom.xml").exists():
        return "maven"
    if (project_dir / "go.mod").exists():
        return "go"
    return "unknown"


# ── Test runner internals ──

async def _run_pytest(project_dir: str, target: str, args: str, timeout: int) -> dict[str, Any]:
    cmd = ["python3", "-m", "pytest", "--tb=short", "-q"]
    if target.strip():
        cmd.append(target.strip())
    if args.strip():
        cmd.extend(args.strip().split())
    return await _run_cmd(cmd, project_dir, timeout)


async def _run_unittest(project_dir: str, target: str, args: str, timeout: int) -> dict[str, Any]:
    cmd = ["python3", "-m", "unittest"]
    if target.strip():
        cmd.append(target.strip())
    if args.strip():
        cmd.extend(args.strip().split())
    return await _run_cmd(cmd, project_dir, timeout)


async def _run_npm_test(project_dir: str, args: str, timeout: int) -> dict[str, Any]:
    cmd = ["npm", "test"]
    if args.strip():
        cmd.extend(args.strip().split())
    return await _run_cmd(cmd, project_dir, timeout)


# ── Code runner internals ──

async def _run_code_snippet(code: str, language: str, timeout: int) -> dict[str, Any]:
    env = _sandbox_env()
    start = time.time()

    if language == "python":
        cmd = ["python3", "-c", code]
    elif language == "javascript":
        cmd = ["node", "-e", code]
    else:
        return {"error": f"不支持的语言: {language}，支持 python/javascript"}

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            preexec_fn=_set_child_resource_limits,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
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
        return {"returncode": -1, "stdout": "", "stderr": f"Timeout after {timeout}s", "elapsed": timeout}


async def _run_code_file(file_path: str, args: list[str], timeout: int) -> dict[str, Any]:
    env = _sandbox_env()
    fp = Path(file_path)
    if not fp.is_absolute():
        fp = _get_workspace() / fp
    if not fp.exists():
        return {"error": f"文件不存在: {file_path}"}

    suffix = fp.suffix.lower()
    if suffix == ".py":
        cmd = ["python3", str(fp)] + args
    elif suffix in (".js", ".mjs"):
        cmd = ["node", str(fp)] + args
    elif suffix == ".sh":
        cmd = ["bash", str(fp)] + args
    else:
        return {"error": f"不支持的文件类型: {suffix}"}

    return await _run_cmd(cmd, str(fp.parent), timeout, env=env)


@register_tool(
    name="code_exec",
    description="代码执行：运行测试套件（pytest/unittest/npm）或执行代码片段（Python/Node），支持沙箱隔离。test_runner + code_runner 合并。",
    category="builtin",
    tags=["code", "exec", "test", "run"],
    scene="coding",
)
async def code_exec(
    action: str = "run_test",
    code: str = "",
    language: str = "python",
    file_path: str = "",
    target: str = "",
    args: str = "",
    timeout: int = _DEFAULT_TIMEOUT,
    **kwargs: Any,
) -> dict[str, Any]:
    """代码执行统一工具。

    Args:
        action: 操作类型:
            - run_test: 运行测试套件
            - run_code: 执行代码片段
            - run_file: 执行代码文件
            - detect: 检测项目测试框架
        code: 代码片段（run_code 时使用）
        language: 语言 (python/javascript)
        file_path: 文件路径（run_file 时使用）
        target: 测试目标（文件/模块/类）
        args: 附加参数
        timeout: 超时秒数

    Returns:
        执行结果
    """
    timeout = min(timeout, _MAX_TIMEOUT)

    if action == "run_test":
        project_dir = str(_get_workspace())
        runner = _detect_runner(Path(project_dir))
        args_str = args or ""
        target_str = target or ""

        if runner == "pytest":
            result = await _run_pytest(project_dir, target_str, args_str, timeout)
        elif runner == "unittest":
            result = await _run_unittest(project_dir, target_str, args_str, timeout)
        elif runner == "npm":
            result = await _run_npm_test(project_dir, args_str, timeout)
        else:
            return {"error": f"未检测到测试框架（需要 pytest/unittest/npm）", "detected": runner}

        result["runner"] = runner
        result["action"] = "run_test"
        result["success"] = result.get("returncode") == 0
        return result

    elif action == "run_code":
        if not code.strip():
            return {"error": "code 不能为空"}
        result = await _run_code_snippet(code, language, timeout)
        result["action"] = "run_code"
        result["language"] = language
        result["success"] = result.get("returncode") == 0
        return result

    elif action == "run_file":
        if not file_path.strip():
            return {"error": "file_path 不能为空"}
        extra_args = args.split() if args.strip() else []
        result = await _run_code_file(file_path, extra_args, timeout)
        result["action"] = "run_file"
        result["file_path"] = file_path
        result["success"] = result.get("returncode") == 0
        return result

    elif action == "detect":
        project_dir = _get_workspace()
        runner = _detect_runner(project_dir)
        return {
            "action": "detect",
            "project_dir": str(project_dir),
            "detected_runner": runner,
            "has_pytest": (project_dir / "pyproject.toml").exists() or (project_dir / "setup.py").exists(),
            "has_package_json": (project_dir / "package.json").exists(),
        }

    else:
        return {"error": f"未知操作: {action}，支持 run_test/run_code/run_file/detect"}


# ── Aliases for backward compatibility ──
test_runner = code_exec
code_runner = code_exec
