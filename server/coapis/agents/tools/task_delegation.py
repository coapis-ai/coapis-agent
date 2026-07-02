# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
from __future__ import annotations
import asyncio, json, logging, os, time
from pathlib import Path
from typing import Any
from .registry import register_tool

logger = logging.getLogger(__name__)

TASK_DIR = Path(os.environ.get("COAPIS_TASK_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "tasks")))


def _ensure_dir():
    TASK_DIR.mkdir(parents=True, exist_ok=True)


def _load_tasks() -> dict[str, Any]:
    _ensure_dir()
    tf = TASK_DIR / "tasks.json"
    if tf.exists():
        try:
            return json.loads(tf.read_text())
        except Exception:
            pass
    return {"tasks": {}, "counter": 0}


def _save_tasks(data: dict[str, Any]):
    _ensure_dir()
    (TASK_DIR / "tasks.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


async def task_delegation(
    action: str = "create",
    task_id: str = "",
    title: str = "",
    description: str = "",
    assignee: str = "",
    priority: str = "normal",
    deadline: str = "",
    depends_on: str = "",
    status: str = "",
    result: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """任务分发与追踪。

    Args:
        action: 操作类型 (create/update/status/list/assign/cancel/dependencies)
        task_id: 任务 ID
        title: 任务标题
        description: 任务描述
        assignee: 分配给哪个 Agent
        priority: 优先级 (low/normal/high/urgent)
        deadline: 截止时间
        depends_on: 依赖的任务 ID（逗号分隔）
        status: 更新状态 (pending/running/done/failed/cancelled)
        result: 任务结果
        limit: 列表限制

    Returns:
        操作结果
    """
    data = _load_tasks()

    if action == "create":
        if not title.strip():
            return {"error": "title 不能为空"}
        data["counter"] = data.get("counter", 0) + 1
        tid = task_id.strip() if task_id.strip() else f"T-{data['counter']:04d}"
        depends = [d.strip() for d in depends_on.split(",") if d.strip()] if depends_on else []
        data["tasks"][tid] = {
            "title": title,
            "description": description,
            "assignee": assignee or "unassigned",
            "priority": priority,
            "deadline": deadline,
            "depends_on": depends,
            "status": "pending",
            "result": "",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_tasks(data)
        return {"action": "created", "task_id": tid, "title": title, "assignee": assignee or "unassigned"}

    elif action == "update":
        if not task_id.strip() or task_id not in data["tasks"]:
            return {"error": f"任务不存在: {task_id}"}
        t = data["tasks"][task_id]
        if status.strip():
            t["status"] = status
        if result.strip():
            t["result"] = result
        if title.strip():
            t["title"] = title
        if description.strip():
            t["description"] = description
        if priority.strip():
            t["priority"] = priority
        if deadline.strip():
            t["deadline"] = deadline
        t["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_tasks(data)
        return {"action": "updated", "task_id": task_id, "status": t["status"]}

    elif action == "status":
        if not task_id.strip() or task_id not in data["tasks"]:
            return {"error": f"任务不存在: {task_id}"}
        t = data["tasks"][task_id]
        return {"action": "status", "task_id": task_id, **t}

    elif action == "assign":
        if not task_id.strip() or task_id not in data["tasks"]:
            return {"error": f"任务不存在: {task_id}"}
        if not assignee.strip():
            return {"error": "assignee 不能为空"}
        data["tasks"][task_id]["assignee"] = assignee
        data["tasks"][task_id]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_tasks(data)
        return {"action": "assigned", "task_id": task_id, "assignee": assignee}

    elif action == "list":
        tasks = data.get("tasks", {})
        items = []
        for tid, t in tasks.items():
            items.append({"task_id": tid, "title": t["title"], "status": t["status"],
                          "assignee": t["assignee"], "priority": t["priority"],
                          "deadline": t.get("deadline", "")})
        # Sort by priority
        prio_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
        items.sort(key=lambda x: prio_order.get(x["priority"], 2))
        return {"action": "list", "count": len(items), "tasks": items[:limit]}

    elif action == "cancel":
        if not task_id.strip() or task_id not in data["tasks"]:
            return {"error": f"任务不存在: {task_id}"}
        data["tasks"][task_id]["status"] = "cancelled"
        data["tasks"][task_id]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_tasks(data)
        return {"action": "cancelled", "task_id": task_id}

    elif action == "dependencies":
        tasks = data.get("tasks", {})
        dep_graph = {}
        for tid, t in tasks.items():
            deps = t.get("depends_on", [])
            dep_graph[tid] = {
                "depends_on": deps,
                "blocked_by": [d for d in deps if d in tasks and tasks[d].get("status") not in ("done", "cancelled")],
                "status": t["status"],
            }
        return {"action": "dependencies", "graph": dep_graph}

    else:
        return {"error": f"未知操作: {action}，支持 create/update/status/list/assign/cancel/dependencies"}
