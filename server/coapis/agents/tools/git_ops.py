# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Git operations — wrap common git commands for safe, structured use."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

_TIMEOUT = 30


def _get_workspace() -> Path:
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws)
    except Exception:
        pass
    return Path.cwd()


async def _run_git(args: list[str], cwd: str, timeout: int = _TIMEOUT) -> dict[str, Any]:
    cmd = ["git"] + args
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        elapsed = round(time.time() - start, 2)
        return {"returncode": proc.returncode,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
                "elapsed": elapsed}
    except asyncio.TimeoutError:
        return {"returncode": -1, "stdout": "", "stderr": f"Timeout after {timeout}s", "elapsed": timeout}
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": "git not found", "elapsed": 0}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e), "elapsed": 0}


@register_tool(
    name="git_ops",
    description="Git 操作：status/diff/log/commit/branch/merge/stash/add/push/pull/fetch。",
    category="builtin",
    tags=["git", "version-control", "ops"],
    scene="general"
)
async def git_ops(
    action: str = "status",
    message: str = "",
    branch: str = "",
    ref: str = "",
    paths: str = "",
    count: int = 10,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Git 操作。

    Args:
        action: 操作类型 (status/diff/log/commit/branch/merge/stash/add/push/pull/fetch/log_clean)
        message: commit 信息
        branch: 分支名
        ref: 引用/标签名
        paths: 文件路径（逗号分隔）
        count: log 条数，默认 10
        dry_run: 预览模式
    """
    cwd = str(_get_workspace())

    if action == "status":
        r = await _run_git(["status", "--short"], cwd)
        return {"action": "status", "success": r["returncode"] == 0,
                "output": r["stdout"].strip() or "(clean working tree)",
                "error": r["stderr"].strip() if r["returncode"] != 0 else ""}

    elif action == "diff":
        r = await _run_git(["diff", "--stat"], cwd)
        r2 = await _run_git(["diff"], cwd)
        return {"action": "diff", "success": r["returncode"] == 0,
                "stat": r["stdout"].strip() or "(no changes)",
                "diff": r2["stdout"][-5000:] if r2["stdout"] else ""}

    elif action == "log":
        args = ["log", "--oneline", f"-{count}"]
        if ref.strip():
            args.append(ref.strip())
        if paths.strip():
            args.extend(["--", paths.strip()])
        r = await _run_git(args, cwd)
        entries = []
        for line in r["stdout"].strip().split("\n"):
            if not line.strip():
                continue
            parts = line.strip().split(" ", 1)
            entries.append({"hash": parts[0] if parts else "",
                           "message": parts[1] if len(parts) > 1 else ""})
        return {"action": "log", "success": r["returncode"] == 0,
                "entries": entries, "count": len(entries)}

    elif action == "commit":
        if not message.strip():
            return {"error": "commit message 不能为空"}
        if paths.strip():
            path_list = [p.strip() for p in paths.split(",") if p.strip()]
            if path_list:
                add_r = await _run_git(["add"] + path_list, cwd)
                if add_r["returncode"] != 0:
                    return {"error": f"git add failed: {add_r['stderr']}"}
        else:
            await _run_git(["add", "-A"], cwd)
        if dry_run:
            r = await _run_git(["diff", "--cached", "--stat"], cwd)
            return {"action": "commit", "dry_run": True,
                    "would_commit": r["stdout"].strip() or "(nothing to commit)",
                    "message": message.strip()}
        r = await _run_git(["commit", "-m", message.strip()], cwd)
        return {"action": "commit", "success": r["returncode"] == 0,
                "output": r["stdout"].strip(), "message": message.strip(),
                "error": r["stderr"].strip() if r["returncode"] != 0 else ""}

    elif action == "branch":
        if branch.strip():
            r = await _run_git(["checkout", "-b", branch.strip()], cwd)
            return {"action": "branch", "success": r["returncode"] == 0,
                    "branch": branch.strip(), "created": r["returncode"] == 0,
                    "error": r["stderr"].strip() if r["returncode"] != 0 else ""}
        else:
            r = await _run_git(["branch", "-a"], cwd)
            branches = []
            for line in r["stdout"].strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                is_current = line.startswith("*")
                name = line.lstrip("* ").strip()
                if name.startswith("remotes/origin/"):
                    continue
                branches.append({"name": name, "current": is_current})
            return {"action": "branch", "success": r["returncode"] == 0,
                    "branches": branches, "count": len(branches)}

    elif action == "merge":
        if not branch.strip():
            return {"error": "branch 不能为空"}
        r = await _run_git(["merge", branch.strip()], cwd)
        return {"action": "merge", "success": r["returncode"] == 0,
                "branch": branch.strip(), "output": r["stdout"].strip(),
                "error": r["stderr"].strip() if r["returncode"] != 0 else ""}

    elif action == "stash":
        r = await _run_git(["stash"], cwd)
        return {"action": "stash", "success": r["returncode"] == 0,
                "output": r["stdout"].strip(),
                "error": r["stderr"].strip() if r["returncode"] != 0 else ""}

    elif action == "add":
        if not paths.strip():
            return {"error": "paths 不能为空"}
        path_list = [p.strip() for p in paths.split(",") if p.strip()]
        r = await _run_git(["add"] + path_list, cwd)
        return {"action": "add", "success": r["returncode"] == 0,
                "paths": path_list,
                "error": r["stderr"].strip() if r["returncode"] != 0 else ""}

    elif action == "push":
        r = await _run_git(["push"], cwd)
        return {"action": "push", "success": r["returncode"] == 0,
                "output": r["stdout"].strip(),
                "error": r["stderr"].strip() if r["returncode"] != 0 else ""}

    elif action == "pull":
        r = await _run_git(["pull"], cwd)
        return {"action": "pull", "success": r["returncode"] == 0,
                "output": r["stdout"].strip(),
                "error": r["stderr"].strip() if r["returncode"] != 0 else ""}

    elif action == "fetch":
        r = await _run_git(["fetch"], cwd)
        return {"action": "fetch", "success": r["returncode"] == 0,
                "output": r["stdout"].strip(),
                "error": r["stderr"].strip() if r["returncode"] != 0 else ""}

    elif action == "log_clean":
        r = await _run_git(["log", "--oneline", "--all", f"-{count}",
                           "--format=%H|%s|%ai"], cwd)
        entries = []
        for line in r["stdout"].strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 2)
            entries.append({"hash": parts[0] if parts else "",
                           "message": parts[1] if len(parts) > 1 else "",
                           "date": parts[2] if len(parts) > 2 else ""})
        return {"action": "log_clean", "success": r["returncode"] == 0,
                "entries": entries, "count": len(entries)}
    else:
        return {"error": f"未知操作: {action}，支持 status/diff/log/commit/branch/merge/stash/add/push/pull/fetch/log_clean"}
