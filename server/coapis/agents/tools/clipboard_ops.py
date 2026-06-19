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

"""Clipboard operations — read/write system clipboard (Linux/Mac).

Wraps xclip/xsel/pbcopy/pbpaste for cross-platform clipboard access.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_MAX_CLIPBOARD = 50000  # chars


def _get_clipboard_tools() -> dict[str, list[str]]:
    """Detect available clipboard tools."""
    system = platform.system().lower()
    tools = {}
    if system == "linux":
        if shutil.which("xclip"):
            tools["read"] = ["xclip", "-selection", "clipboard", "-o"]
            tools["write"] = ["xclip", "-selection", "clipboard"]
        elif shutil.which("xsel"):
            tools["read"] = ["xsel", "--clipboard", "--output"]
            tools["write"] = ["xsel", "--clipboard", "--input"]
    elif system == "darwin":
        tools["read"] = ["pbpaste"]
        tools["write"] = ["pbcopy"]
    return tools


async def _run_cmd(cmd: list[str], stdin: str = "", timeout: int = _TIMEOUT) -> dict[str, Any]:
    start = __import__("time").time()
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
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace")[:_MAX_CLIPBOARD],
            "stderr": stderr.decode(errors="replace"),
        }
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": f"Command not found: {cmd[0]}"}
    except asyncio.TimeoutError:
        return {"returncode": -1, "stdout": "", "stderr": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e)}


@register_tool(
    name="clipboard_ops",
    description="剪贴板操作：读取/写入系统剪贴板（支持 Linux xclip/xsel 和 Mac pbcopy/pbpaste）。",
    category="builtin",
    tags=["clipboard", "system", "utility"],
    scene="core"
)
async def clipboard_ops(
    action: str = "read",
    text: str = "",
) -> dict[str, Any]:
    """剪贴板操作。

    Args:
        action: 操作类型 (read/write)
        text: 要写入剪贴板的文本

    Returns:
        操作结果
    """
    tools = _get_clipboard_tools()
    if not tools:
        return {
            "error": "未找到剪贴板工具",
            "hint": "Linux: 安装 xclip 或 xsel (apt install xclip)，Mac: 自带 pbcopy/pbpaste",
        }

    if action == "read":
        r = await _run_cmd(tools["read"])
        if r["returncode"] != 0:
            return {"error": f"读取剪贴板失败: {r['stderr']}", "content": ""}
        content = r["stdout"]
        return {
            "action": "read",
            "content": content,
            "length": len(content),
            "truncated": len(content) >= _MAX_CLIPBOARD,
        }

    elif action == "write":
        if not text.strip():
            return {"error": "text 不能为空"}
        r = await _run_cmd(tools["write"], stdin=text)
        if r["returncode"] != 0:
            return {"error": f"写入剪贴板失败: {r['stderr']}"}
        return {
            "action": "write",
            "success": True,
            "length": len(text),
        }

    else:
        return {"error": f"未知操作: {action}，支持 read/write"}
