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

"""Structured memory manager tool — JSON-indexed long-term memory.

Provides CRUD operations (add / search / remove / list) on a JSON-backed
memory index stored in ``memory/`` inside the current workspace.

Complements the existing ``memory_search`` tool (semantic search over
MEMORY.md) with structured key-value storage and fuzzy text search.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# ── Storage ───────────────────────────────────────────────────────────

_MEMORY_DIR = "memory"
_MEMORY_INDEX = "memory_index.json"


def _memory_dir() -> Path:
    """Return the absolute path to the memory directory."""
    from ...config.context import get_current_workspace_dir
    ws = get_current_workspace_dir()
    base = Path(ws) if ws else Path.cwd()
    return base / _MEMORY_DIR


def _index_path() -> Path:
    return _memory_dir() / _MEMORY_INDEX


def _load_index() -> list[dict[str, Any]]:
    """Load the memory index from disk."""
    path = _index_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.warning("Failed to load memory index: %s", e)
        return []


def _save_index(entries: list[dict[str, Any]]) -> None:
    """Persist the memory index to disk."""
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Tool implementation ───────────────────────────────────────────────

@register_tool(
    name="memory_manager",
    description="结构化长期记忆管理。支持 add/search/remove/list 操作，JSON 索引存储。支持分类标签(tags)和重要度评分(score)。",
    category="builtin",
    tags=["memory", "knowledge"],
    scene="core"
)
async def memory_manager(
    action: str = "list",
    key: str = "",
    content: str = "",
    category: str = "general",
    tags: str = "",
    score: float = 5.0,
    query: str = "",
    entry_id: str = "",
    limit: int = 10,
    min_score: float = 0.0,
) -> dict[str, Any]:
    """结构化长期记忆管理。

    与 memory_search（语义搜索 MEMORY.md）互补：
    - memory_search 适合大段文本的语义检索
    - memory_manager 适合精确的键值存储和模糊搜索

    Args:
        action: 操作类型 (add/search/remove/list)
        key: 记忆条目的标题/关键词（add 时必填）
        content: 记忆内容（add 时必填）
        category: 分类标签（add 时可选，默认 general）
            常用分类：project/user/decision/technical/meeting/preference/bug/idea
        tags: 领域标签，逗号分隔（add 时可选）
            示例：python,docker,security 或 产品设计,用户体验,定价策略
        score: 重要度评分 1-10（add 时可选，默认 5.0）
            1=低重要度  5=一般  8=重要  10=关键决策
        query: 搜索关键词（search 时必填）
        entry_id: 条目 ID（remove 时必填）
        limit: 搜索/列表最大返回数，默认 10
        min_score: 搜索/列表时的最低重要度过滤，默认 0（不过滤）

    Returns:
        操作结果
    """
    entries = _load_index()
    now = datetime.now().isoformat()

    if action == "add":
        if not key.strip():
            return {"error": "key 不能为空"}
        if not content.strip():
            return {"error": "content 不能为空"}

        entry = {
            "id": str(uuid.uuid4())[:8],
            "key": key.strip(),
            "content": content.strip(),
            "category": category.strip() or "general",
            "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags.strip() else [],
            "score": max(1.0, min(10.0, float(score))),
            "created_at": now,
            "updated_at": now,
        }
        entries.append(entry)
        _save_index(entries)
        return {
            "message": f"✅ 已添加记忆：{key.strip()}",
            "entry": entry,
            "total": len(entries),
        }

    elif action == "search":
        if not query.strip():
            return {"error": "搜索关键词不能为空"}

        query_lower = query.strip().lower()
        scored = []
        for e in entries:
            # Filter by min_score
            if e.get("score", 5.0) < min_score:
                continue
            fuzz = _fuzzy_score(query_lower, e)
            if fuzz > 0:
                # Boost score by importance: final = fuzz * (1 + importance/20)
                importance = e.get("score", 5.0)
                final = fuzz * (1 + importance / 20)
                scored.append((final, e))
        scored.sort(key=lambda x: -x[0])
        results = [e for _, e in scored[:limit]]

        return {
            "results": results,
            "count": len(results),
            "query": query.strip(),
            "total": len(entries),
        }

    elif action == "remove":
        if not entry_id.strip():
            return {"error": "entry_id 不能为空"}

        target = None
        for e in entries:
            if e["id"] == entry_id.strip() or e["id"].startswith(entry_id.strip()):
                target = e
                break

        if not target:
            return {"error": f"未找到条目: {entry_id}"}

        entries = [e for e in entries if e["id"] != target["id"]]
        _save_index(entries)
        return {
            "message": f"🗑️ 已删除记忆：{target['key']}",
            "total": len(entries),
        }

    elif action == "list":
        # Optional filters
        filtered = entries
        if category.strip() and category.strip() != "general":
            filtered = [e for e in filtered if e.get("category") == category.strip()]
        if min_score > 0:
            filtered = [e for e in filtered if e.get("score", 5.0) >= min_score]

        # Sort by score desc, then updated_at desc
        filtered.sort(
            key=lambda e: (e.get("score", 5.0), e.get("updated_at", "")),
            reverse=True,
        )
        results = filtered[:limit]

        return {
            "results": results,
            "count": len(results),
            "total": len(entries),
            "category": category if category.strip() else "all",
            "min_score": min_score,
        }

    else:
        return {"error": f"未知操作: {action}，支持 add/search/remove/list"}


# ── Fuzzy search helper ───────────────────────────────────────────────

def _fuzzy_score(query: str, entry: dict) -> int:
    """Score an entry against a query. Higher = better match. 0 = no match."""
    score = 0
    key_lower = entry.get("key", "").lower()
    content_lower = entry.get("content", "").lower()
    cat_lower = entry.get("category", "").lower()
    entry_tags = [t.lower() for t in entry.get("tags", [])]

    # Exact key match
    if query == key_lower:
        score += 100
    # Key contains query
    elif query in key_lower:
        score += 50
    # All query words in key
    elif all(w in key_lower for w in query.split()):
        score += 30

    # Content match
    if query in content_lower:
        score += 20

    # Category match
    if query in cat_lower:
        score += 10

    # Tags match (strong signal — tags describe domain/type)
    for tag in entry_tags:
        if query in tag or tag in query:
            score += 15
        elif any(w in tag for w in query.split() if len(w) >= 2):
            score += 8

    # Individual word matches in content
    for word in query.split():
        if len(word) >= 2 and word in content_lower:
            score += 5

    return score
