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

"""Cron scheduler — manage system crontab entries (add/list/remove/enable/disable).

Wraps crontab CLI for safe scheduled task management.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

_TIMEOUT = 15
_MARKER_START = "# [CoApis-"
_MARKER_END = "]"  # closes marker comment


async def _run_cmd(
    cmd: list[str], stdin: str = "", timeout: int = _TIMEOUT
) -> dict[str, Any]:
    """Run a shell command."""
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin.encode() if stdin else None), timeout=timeout
        )
        elapsed = round(time.time() - start, 2)
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "elapsed": elapsed,
        }
    except asyncio.TimeoutError:
        return {"returncode": -1, "stdout": "", "stderr": f"Timeout after {timeout}s", "elapsed": timeout}
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": "Command not found", "elapsed": 0}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e), "elapsed": 0}


def _parse_crontab_line(line: str) -> dict[str, Any] | None:
    """Parse a crontab line into structured data."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Match: minute hour day month weekday command
    m = re.match(
        r"^(\S+\s+\S+\s+\S+\s+\S+\s+\S+)\s+(.+)$", line
    )
    if not m:
        return None

    schedule = m.group(1).strip()
    command = m.group(2).strip()

    # Check if it's a CoApis managed entry
    managed = command.startswith(_MARKER_START)

    return {
        "schedule": schedule,
        "command": command,
        "managed": managed,
        "enabled": not line.startswith("#"),
    }


def _make_entry(
    name: str, schedule: str, command: str, enabled: bool = True
) -> str:
    """Create a crontab entry with CoApis marker."""
    line = f"{schedule} {_MARKER_START}{name}{_MARKER_END} {command}"
    if not enabled:
        line = f"# {line}"
    return line


@register_tool(
    name="cron_scheduler",
    description="定时任务管理：基于系统 crontab 创建/列表/暂停/恢复/删除定时任务。",
    category="builtin",
    tags=["cron", "scheduling", "automation"],
    scene="ops"
)
async def cron_scheduler(
    action: str = "list",
    name: str = "",
    schedule: str = "",
    command: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    """定时任务管理。

    基于系统 crontab 管理定时任务，所有 CoApis 任务都有标记便于管理。

    Args:
        action: 操作类型 (list/add/remove/enable/disable/show)
        name: 任务名称（add/remove/enable/disable 时必填）
        schedule: cron 调度表达式（add 时必填，如 "*/5 * * * *" 每5分钟）
        command: 要执行的命令（add 时必填）
        enabled: 是否启用，默认 True

    Returns:
        操作结果
    """
    if action == "list":
        # Read current crontab
        r = await _run_cmd(["crontab", "-l"])
        entries = []
        if r["returncode"] == 0:
            for line in r["stdout"].split("\n"):
                parsed = _parse_crontab_line(line)
                if parsed and parsed["managed"]:
                    entries.append(parsed)
        return {
            "action": "list",
            "entries": entries,
            "count": len(entries),
            "success": True,
        }

    elif action == "add":
        if not name.strip():
            return {"error": "name 不能为空"}
        if not schedule.strip():
            return {"error": "schedule 不能为空（如 */5 * * * *）"}
        if not command.strip():
            return {"error": "command 不能为空"}

        # Read existing crontab
        r = await _run_cmd(["crontab", "-l"])
        existing_lines = []
        if r["returncode"] == 0:
            existing_lines = r["stdout"].split("\n")

        # Check for duplicate name
        marker = f"{_MARKER_START}{name.strip()}{_MARKER_END}"
        for line in existing_lines:
            if marker in line:
                return {"error": f"任务 '{name}' 已存在，请先 remove 再重新添加"}

        # Remove empty trailing line
        while existing_lines and not existing_lines[-1].strip():
            existing_lines.pop()

        # Add new entry
        new_entry = _make_entry(name.strip(), schedule.strip(), command.strip(), enabled)
        existing_lines.append(new_entry)

        new_crontab = "\n".join(existing_lines) + "\n"
        r2 = await _run_cmd(["crontab", "-"], stdin=new_crontab)
        return {
            "action": "add",
            "success": r2["returncode"] == 0,
            "name": name.strip(),
            "schedule": schedule.strip(),
            "command": command.strip(),
            "enabled": enabled,
            "error": r2["stderr"].strip() if r2["returncode"] != 0 else "",
        }

    elif action == "remove":
        if not name.strip():
            return {"error": "name 不能为空"}

        r = await _run_cmd(["crontab", "-l"])
        if r["returncode"] != 0:
            return {"error": "无法读取 crontab"}

        marker = f"{_MARKER_START}{name.strip()}{_MARKER_END}"
        new_lines = []
        found = False
        for line in r["stdout"].split("\n"):
            if marker in line:
                found = True
                continue
            new_lines.append(line)

        if not found:
            return {"error": f"未找到任务 '{name}'"}

        new_crontab = "\n".join(new_lines)
        r2 = await _run_cmd(["crontab", "-"], stdin=new_crontab)
        return {
            "action": "remove",
            "success": r2["returncode"] == 0,
            "name": name.strip(),
            "error": r2["stderr"].strip() if r2["returncode"] != 0 else "",
        }

    elif action in ("enable", "disable"):
        if not name.strip():
            return {"error": "name 不能为空"}

        r = await _run_cmd(["crontab", "-l"])
        if r["returncode"] != 0:
            return {"error": "无法读取 crontab"}

        marker = f"{_MARKER_START}{name.strip()}{_MARKER_END}"
        new_lines = []
        found = False
        for line in r["stdout"].split("\n"):
            if marker in line:
                found = True
                # Parse and recreate with new state
                parsed = _parse_crontab_line(line)
                if parsed:
                    new_entry = _make_entry(
                        name.strip(),
                        parsed["schedule"],
                        parsed["command"],
                        enabled=(action == "enable"),
                    )
                    new_lines.append(new_entry)
                    continue
            new_lines.append(line)

        if not found:
            return {"error": f"未找到任务 '{name}'"}

        new_crontab = "\n".join(new_lines)
        r2 = await _run_cmd(["crontab", "-"], stdin=new_crontab)
        return {
            "action": action,
            "success": r2["returncode"] == 0,
            "name": name.strip(),
            "enabled": (action == "enable"),
            "error": r2["stderr"].strip() if r2["returncode"] != 0 else "",
        }

    elif action == "show":
        if not name.strip():
            return {"error": "name 不能为空"}

        r = await _run_cmd(["crontab", "-l"])
        if r["returncode"] != 0:
            return {"error": "无法读取 crontab"}

        marker = f"{_MARKER_START}{name.strip()}{_MARKER_END}"
        for line in r["stdout"].split("\n"):
            if marker in line:
                parsed = _parse_crontab_line(line)
                return {
                    "action": "show",
                    "success": True,
                    "entry": parsed,
                }

        return {"error": f"未找到任务 '{name}'"}

    else:
        return {"error": f"未知操作: {action}，支持 list/add/remove/enable/disable/show"}
