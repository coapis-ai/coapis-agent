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

"""TODO tool — session-level task list management.

Provides add / update / remove / complete / list operations on a JSON-backed
task list stored at ``files/.todo.json`` inside the current workspace.

Designed for multi-step tasks (3+ steps) where the Agent needs to track
progress.  Complements the Plan module (macro) with micro-level execution
tracking.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# ── Path helpers ──────────────────────────────────────────────────────

_TODO_FILENAME = ".todo.json"


def _todo_path() -> Path:
    """Return the absolute path to the TODO file in the current workspace."""
    from ...config.context import get_current_workspace_dir
    ws = get_current_workspace_dir()
    if ws:
        return Path(ws) / _TODO_FILENAME
    # Fallback: current working directory
    return Path.cwd() / _TODO_FILENAME


def _load_todos() -> list[dict[str, Any]]:
    """Load the TODO list from disk. Returns empty list on any error."""
    path = _todo_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.warning("Failed to load TODO list: %s", e)
        return []


def _save_todos(todos: list[dict[str, Any]]) -> None:
    """Persist the TODO list to disk."""
    path = _todo_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(todos, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Schema ────────────────────────────────────────────────────────────

TODO_TOOL_SCHEMA = {
    "name": "todo_tool",
    "description": (
        "管理当前会话的任务清单。用于3步以上的复杂任务，或用户一次性给出多个任务时。\n"
        "支持的操作：add（添加）、update（更新）、remove（删除）、complete（完成）、list（查看）。\n"
        "每次操作后返回当前完整清单和摘要。"
    ),
    "parameters": {
        "action": {
            "type": "string",
            "enum": ["add", "update", "remove", "complete", "list"],
            "description": "操作类型",
        },
        "task_id": {
            "type": "string",
            "description": "任务ID（update/remove/complete 时必填）",
        },
        "content": {
            "type": "string",
            "description": "任务内容（add 时必填，update 时可选）",
        },
        "priority": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "优先级（add/update 时可选，默认 medium）",
        },
    },
}


# ── Tool implementation ───────────────────────────────────────────────

@register_tool(
    name="todo_tool",
    description="管理当前会话的任务清单。支持 add/update/remove/complete/list 操作。",
    category="builtin",
    tags=["task", "todo"],
    scene="core"
)
async def todo_tool(
    action: str = "list",
    task_id: str = "",
    content: str = "",
    priority: str = "medium",
) -> dict[str, Any]:
    """管理当前会话的任务清单。

    Args:
        action: 操作类型 (add/update/remove/complete/list)
        task_id: 任务ID（update/remove/complete 时必填）
        content: 任务内容（add 时必填）
        priority: 优先级 (low/medium/high)，默认 medium

    Returns:
        操作结果 + 当前完整清单
    """
    todos = _load_todos()
    now = datetime.now().isoformat()

    if action == "add":
        if not content.strip():
            return {"error": "任务内容不能为空"}

        new_task = {
            "id": str(uuid.uuid4())[:8],
            "content": content.strip(),
            "priority": priority if priority in ("low", "medium", "high") else "medium",
            "status": "todo",
            "created_at": now,
            "updated_at": now,
        }
        todos.append(new_task)
        _save_todos(todos)
        return _build_response(f"✅ 已添加任务：{content.strip()}", todos)

    elif action == "update":
        task = _find_task(todos, task_id)
        if not task:
            return {"error": f"未找到任务 {task_id}"}

        if content.strip():
            task["content"] = content.strip()
        if priority in ("low", "medium", "high"):
            task["priority"] = priority
        task["updated_at"] = now
        _save_todos(todos)
        return _build_response(f"📝 已更新任务 {task_id}", todos)

    elif action == "remove":
        task = _find_task(todos, task_id)
        if not task:
            return {"error": f"未找到任务 {task_id}"}

        todos = [t for t in todos if t["id"] != task_id]
        _save_todos(todos)
        return _build_response(f"🗑️ 已删除任务：{task['content']}", todos)

    elif action == "complete":
        task = _find_task(todos, task_id)
        if not task:
            return {"error": f"未找到任务 {task_id}"}

        task["status"] = "done"
        task["updated_at"] = now
        _save_todos(todos)
        return _build_response(f"✅ 已完成任务：{task['content']}", todos)

    elif action == "list":
        return _build_response("📋 当前任务清单", todos)

    else:
        return {"error": f"未知操作：{action}，支持 add/update/remove/complete/list"}


# ── Helpers ───────────────────────────────────────────────────────────

def _find_task(todos: list[dict], task_id: str) -> dict | None:
    """Find a task by ID (prefix match supported)."""
    if not task_id:
        return None
    for t in todos:
        if t["id"] == task_id or t["id"].startswith(task_id):
            return t
    return None


def _build_response(message: str, todos: list[dict]) -> dict:
    """Build a structured response with message + current list + summary."""
    total = len(todos)
    done = sum(1 for t in todos if t["status"] == "done")
    pending = total - done

    # Sort by priority: high > medium > low
    priority_order = {"high": 0, "medium": 1, "low": 2}
    sorted_todos = sorted(
        todos,
        key=lambda t: (
            0 if t["status"] == "todo" else 1,
            priority_order.get(t.get("priority", "medium"), 1),
        ),
    )

    return {
        "message": message,
        "summary": {
            "total": total,
            "done": done,
            "pending": pending,
            "progress": f"{done}/{total}" if total > 0 else "0/0",
        },
        "todos": sorted_todos,
    }
