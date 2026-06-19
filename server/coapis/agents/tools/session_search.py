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

"""Session search tool — search historical conversations across multiple sources.

Searches JSONL history files, workspace chat JSON, and markdown memory files
to help agents find relevant past context.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# Max file size to scan (5MB)
_MAX_FILE_SIZE = 5 * 1024 * 1024
# Max results per source
_MAX_PER_SOURCE = 20


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


def _search_jsonl_files(query: str, limit: int) -> list[dict]:
    """Search JSONL history files (debug_history.jsonl, etc.)."""
    results = []
    workspace = _get_workspace()

    # Look for JSONL files in workspace and common locations
    search_paths = [
        workspace / "debug_history.jsonl",
        workspace / "history.jsonl",
        workspace / "chat_history.jsonl",
        workspace / "sessions",
    ]

    # Also scan for any .jsonl files
    for jsonl_file in workspace.glob("*.jsonl"):
        if jsonl_file not in search_paths:
            search_paths.append(jsonl_file)

    for path in search_paths:
        if path.is_file() and path.suffix == ".jsonl":
            if path.stat().st_size > _MAX_FILE_SIZE:
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line_no, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        # Extract text content
                        text = _extract_text(msg)
                        if _matches_query(query, text):
                            results.append({
                                "source": str(path.name),
                                "line": line_no,
                                "role": msg.get("role", msg.get("name", "")),
                                "content": _truncate(text, 200),
                                "timestamp": msg.get("timestamp", msg.get("time", "")),
                            })
                            if len(results) >= limit:
                                break
            except Exception as e:
                logger.debug(f"Error reading {path}: {e}")

    return results[:limit]


def _search_workspace_chats(query: str, limit: int) -> list[dict]:
    """Search workspace chats.json files."""
    results = []
    workspace = _get_workspace()

    for chats_file in workspace.glob("*/chats.json"):
        if chats_file.stat().st_size > _MAX_FILE_SIZE:
            continue
        try:
            data = json.loads(chats_file.read_text(encoding="utf-8"))
            chats = data.get("chats", [])
            for chat in chats:
                messages = chat.get("messages", [])
                chat_id = chat.get("id", "")
                chat_name = chat.get("name", chat.get("title", ""))
                for msg in messages:
                    text = _extract_text(msg)
                    if _matches_query(query, text):
                        results.append({
                            "source": f"chats/{chats_file.parent.name}",
                            "chat_id": chat_id,
                            "chat_name": chat_name,
                            "role": msg.get("role", ""),
                            "content": _truncate(text, 200),
                            "timestamp": msg.get("timestamp", ""),
                        })
                        if len(results) >= limit:
                            break
                if len(results) >= limit:
                    break
        except Exception as e:
            logger.debug(f"Error reading {chats_file}: {e}")

    return results[:limit]


def _search_memory_files(query: str, limit: int) -> list[dict]:
    """Search memory markdown files."""
    results = []
    workspace = _get_workspace()

    memory_files = list(workspace.glob("memory/*.md"))
    memory_main = workspace / "MEMORY.md"
    if memory_main.exists():
        memory_files.insert(0, memory_main)

    for md_file in memory_files:
        if md_file.stat().st_size > _MAX_FILE_SIZE:
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            lines = content.split("\n")
            for line_no, line in enumerate(lines, 1):
                line_stripped = line.strip()
                if not line_stripped or line_stripped.startswith("#"):
                    continue
                if _matches_query(query, line_stripped):
                    # Get context: surrounding lines
                    start = max(0, line_no - 2)
                    end = min(len(lines), line_no + 2)
                    context = "\n".join(lines[start:end])
                    results.append({
                        "source": f"memory/{md_file.name}",
                        "line": line_no,
                        "content": _truncate(context, 300),
                        "timestamp": _extract_date_from_filename(md_file.name),
                    })
                    if len(results) >= limit:
                        break
        except Exception as e:
            logger.debug(f"Error reading {md_file}: {e}")

    return results[:limit]


def _extract_text(msg: dict) -> str:
    """Extract readable text from a message dict."""
    # Try common fields
    for field in ("content", "text", "message", "summary"):
        val = msg.get(field)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, list):
            # Handle content blocks
            parts = []
            for block in val:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        parts.append(f"[tool:{block.get('name', '')}]")
                elif isinstance(block, str):
                    parts.append(block)
            if parts:
                return " ".join(parts)
    return ""


def _matches_query(query: str, text: str) -> bool:
    """Check if text matches the query (case-insensitive substring match)."""
    if not query or not text:
        return False
    query_lower = query.lower()
    text_lower = text.lower()
    # All query words must appear
    return all(w in text_lower for w in query_lower.split())


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _extract_date_from_filename(filename: str) -> str:
    """Try to extract date from filename like 2026-06-11.md."""
    if len(filename) >= 10:
        try:
            datetime.strptime(filename[:10], "%Y-%m-%d")
            return filename[:10]
        except ValueError:
            pass
    return ""


@register_tool(
    name="session_search",
    description="搜索历史会话和记忆文件。支持关键词搜索 JSONL 历史、workspace 聊天记录、memory markdown 文件。",
    category="builtin",
    tags=["search", "history", "memory"],
    scene="coding"
)
async def session_search(
    query: str = "",
    limit: int = 10,
    source: str = "all",
) -> dict[str, Any]:
    """搜索历史会话和记忆文件。

    搜索范围：
    - JSONL 历史文件（debug_history.jsonl 等）
    - Workspace 聊天记录（chats.json）
    - Memory markdown 文件（MEMORY.md, memory/*.md）

    Args:
        query: 搜索关键词（支持多词，空格分隔为 AND 逻辑）
        limit: 最大返回结果数，默认 10
        source: 搜索来源 (all/jsonl/chats/memory)，默认 all

    Returns:
        搜索结果列表
    """
    if not query.strip():
        return {"error": "搜索关键词不能为空"}

    results = []
    sources_searched = []

    if source in ("all", "jsonl"):
        jsonl_results = _search_jsonl_files(query.strip(), limit)
        results.extend(jsonl_results)
        sources_searched.append(f"jsonl({len(jsonl_results)})")

    if source in ("all", "chats"):
        chat_results = _search_workspace_chats(query.strip(), limit)
        results.extend(chat_results)
        sources_searched.append(f"chats({len(chat_results)})")

    if source in ("all", "memory"):
        memory_results = _search_memory_files(query.strip(), limit)
        results.extend(memory_results)
        sources_searched.append(f"memory({len(memory_results)})")

    # Sort by relevance (more query words matched = higher rank)
    query_words = query.strip().lower().split()

    def _rank(r: dict) -> tuple:
        text = r.get("content", "").lower()
        matches = sum(1 for w in query_words if w in text)
        return (-matches, r.get("timestamp", ""))

    results.sort(key=_rank)
    results = results[:limit]

    return {
        "results": results,
        "count": len(results),
        "query": query.strip(),
        "sources": ", ".join(sources_searched),
    }
