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

"""Notes tool — lightweight session-level note taking.

Complements memory_manager (long-term structured memory) with fast,
ephemeral notes for the current working context.
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


def _notes_path() -> Path:
    """Path to the session notes file."""
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws) / ".notes.json"
    except Exception:
        pass
    return Path.cwd() / ".notes.json"


def _load_notes() -> list[dict[str, Any]]:
    """Load notes from disk."""
    path = _notes_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_notes(notes: list[dict[str, Any]]) -> None:
    """Persist notes to disk."""
    path = _notes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(notes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@register_tool(
    name="notes",
    description="轻量级会话笔记：快速记录/查找/删除临时笔记，与 memory_manager（长期记忆）互补。",
    category="builtin",
    tags=["notes", "session", "temporary"],
    scene="data"
)
async def notes(
    action: str = "list",
    content: str = "",
    query: str = "",
    note_id: str = "",
    tag: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """轻量级会话笔记。

    与 memory_manager 的区别：
    - memory_manager: 长期结构化记忆，带 category/tags/score，永久保存
    - notes: 会话级临时笔记，轻量快速，适合当前工作上下文

    Args:
        action: 操作类型 (add/list/search/delete/clear)
        content: 笔记内容（add 时必填）
        query: 搜索关键词（search 时必填）
        note_id: 笔记 ID（delete 时必填）
        tag: 标签过滤（list/search 时可选）
        limit: 最大返回数，默认 20

    Returns:
        操作结果
    """
    notes_list = _load_notes()
    now = datetime.now().isoformat()

    if action == "add":
        if not content.strip():
            return {"error": "笔记内容不能为空"}

        entry = {
            "id": str(uuid.uuid4())[:6],
            "content": content.strip(),
            "tag": tag.strip() or "",
            "created_at": now,
        }
        notes_list.append(entry)
        _save_notes(notes_list)
        return {
            "message": f"✅ 已记录笔记: {content.strip()[:50]}...",
            "note": entry,
            "total": len(notes_list),
        }

    elif action == "list":
        filtered = notes_list
        if tag.strip():
            filtered = [n for n in notes_list if n.get("tag") == tag.strip()]
        filtered = filtered[-limit:]  # Latest first (tail)
        filtered.reverse()

        return {
            "results": filtered,
            "count": len(filtered),
            "total": len(notes_list),
            "tag": tag.strip() or "all",
        }

    elif action == "search":
        if not query.strip():
            return {"error": "搜索关键词不能为空"}

        query_lower = query.strip().lower()
        results = []
        for n in reversed(notes_list):  # Search latest first
            if query_lower in n.get("content", "").lower():
                results.append(n)
                if len(results) >= limit:
                    break

        return {
            "results": results,
            "count": len(results),
            "query": query.strip(),
            "total": len(notes_list),
        }

    elif action == "delete":
        if not note_id.strip():
            return {"error": "note_id 不能为空"}

        target = None
        for n in notes_list:
            if n["id"] == note_id.strip() or n["id"].startswith(note_id.strip()):
                target = n
                break

        if not target:
            return {"error": f"未找到笔记: {note_id}"}

        notes_list = [n for n in notes_list if n["id"] != target["id"]]
        _save_notes(notes_list)
        return {
            "message": f"🗑️ 已删除笔记: {target['content'][:50]}...",
            "total": len(notes_list),
        }

    elif action == "clear":
        count = len(notes_list)
        _save_notes([])
        return {
            "message": f"🧹 已清空 {count} 条笔记",
            "total": 0,
        }

    else:
        return {"error": f"未知操作: {action}，支持 add/list/search/delete/clear"}
