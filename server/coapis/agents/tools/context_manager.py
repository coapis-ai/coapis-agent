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

"""Context manager — maintain working context across multi-turn conversations.

Tracks open files, current task, and pending items so the agent
doesn't lose state between conversation turns.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)


def _ctx_path() -> Path:
    """Path to the context file."""
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws) / ".context.json"
    except Exception:
        pass
    return Path.cwd() / ".context.json"


def _load_ctx() -> dict[str, Any]:
    """Load context from disk."""
    path = _ctx_path()
    if not path.exists():
        return _default_ctx()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Merge with defaults for missing keys
        defaults = _default_ctx()
        defaults.update(data)
        return defaults
    except Exception:
        return _default_ctx()


def _save_ctx(ctx: dict[str, Any]) -> None:
    """Persist context to disk."""
    path = _ctx_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ctx["updated_at"] = datetime.now().isoformat()
    path.write_text(
        json.dumps(ctx, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _default_ctx() -> dict[str, Any]:
    return {
        "current_task": "",
        "task_description": "",
        "open_files": [],
        "pending_items": [],
        "key_decisions": [],
        "created_at": datetime.now().isoformat(),
        "updated_at": "",
    }


async def context_manager(
    action: str = "get",
    key: str = "",
    value: str = "",
) -> dict[str, Any]:
    """工作上下文管理。

    支持的 key：
    - current_task: 当前任务名称
    - task_description: 任务详细描述
    - open_files: 打开的文件列表（value 用逗号分隔）
    - pending_items: 待办事项（value 用逗号分隔，每次追加）
    - key_decisions: 关键决策记录（value 用逗号分隔，每次追加）

    Args:
        action: 操作类型 (set/get/list/clear)
        key: 上下文键名
        value: 上下文值

    Returns:
        操作结果
    """
    ctx = _load_ctx()

    if action == "set":
        if not key.strip():
            return {"error": "key 不能为空"}

        key = key.strip()
        value = value.strip()

        if key == "current_task":
            ctx["current_task"] = value
        elif key == "task_description":
            ctx["task_description"] = value
        elif key == "open_files":
            files = [f.strip() for f in value.split(",") if f.strip()]
            # Append to existing list (deduplicate)
            existing = ctx.get("open_files", [])
            for f in files:
                if f not in existing:
                    existing.append(f)
            ctx["open_files"] = existing
        elif key == "pending_items":
            items = [i.strip() for i in value.split(",") if i.strip()]
            existing = ctx.get("pending_items", [])
            for item in items:
                if item not in existing:
                    existing.append(item)
            ctx["pending_items"] = existing
        elif key == "key_decisions":
            decisions = [d.strip() for d in value.split(",") if d.strip()]
            existing = ctx.get("key_decisions", [])
            for d in decisions:
                existing.append(d)
            ctx["key_decisions"] = existing
        else:
            # Allow arbitrary keys
            ctx[key] = value

        _save_ctx(ctx)
        return {
            "message": f"✅ 已设置: {key} = {value[:100]}",
            "key": key,
            "total_keys": len(ctx),
        }

    elif action == "get":
        if key.strip():
            key = key.strip()
            val = ctx.get(key, "")
            if isinstance(val, list):
                return {"key": key, "value": val, "count": len(val)}
            return {"key": key, "value": val}
        else:
            # Return all context (summary)
            return {
                "current_task": ctx.get("current_task", ""),
                "task_description": ctx.get("task_description", ""),
                "open_files": ctx.get("open_files", []),
                "pending_items": ctx.get("pending_items", []),
                "key_decisions": ctx.get("key_decisions", []),
                "updated_at": ctx.get("updated_at", ""),
            }

    elif action == "list":
        results = []
        for k, v in ctx.items():
            if k.startswith("_") or k in ("created_at", "updated_at"):
                continue
            if isinstance(v, list):
                results.append({"key": k, "type": "list", "count": len(v), "value": v})
            else:
                results.append({"key": k, "type": "string", "value": v})
        return {
            "results": results,
            "count": len(results),
            "updated_at": ctx.get("updated_at", ""),
        }

    elif action == "clear":
        if key.strip():
            key = key.strip()
            if key in ctx and key not in ("created_at", "updated_at"):
                old = ctx[key]
                ctx[key] = [] if isinstance(old, list) else ""
                _save_ctx(ctx)
                return {"message": f"🧹 已清空: {key}"}
            return {"error": f"未找到 key: {key}"}
        else:
            _save_ctx(_default_ctx())
            return {"message": "🧹 已清空所有上下文"}

    else:
        return {"error": f"未知操作: {action}，支持 set/get/list/clear"}
