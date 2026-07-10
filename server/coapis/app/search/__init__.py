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

"""Global search module - unified search across skills, files, and conversations.

Provides:
- Unified search API across multiple data sources
- Search skills by name, description, category
- Search files by name, path, content
- Search conversations by message content
- Relevance scoring and ranking
- Pagination support
"""

import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)


class SearchResult:
    """A single search result."""

    def __init__(
        self,
        source: str,
        item_id: str,
        title: str,
        snippet: str = "",
        score: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.source = source  # "skill", "file", "conversation"
        self.item_id = item_id
        self.title = title
        self.snippet = snippet
        self.score = score
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "item_id": self.item_id,
            "title": self.title,
            "snippet": self.snippet,
            "score": round(self.score, 3),
            "metadata": self.metadata,
        }


class SearchIndex:
    """In-memory search index for skills, files, and conversations."""

    def __init__(self):
        self._skills: Dict[str, Dict[str, Any]] = {}
        self._files: Dict[str, Dict[str, Any]] = {}
        self._conversations: Dict[str, Dict[str, Any]] = {}

    def index_skill(self, skill_id: str, name: str, description: str, category: str = ""):
        """Add a skill to the search index."""
        self._skills[skill_id] = {
            "name": name,
            "description": description,
            "category": category,
            "indexed_at": datetime.utcnow(),
        }

    def index_file(self, file_id: str, path: str, size: int = 0):
        """Add a file to the search index."""
        self._files[file_id] = {
            "path": path,
            "name": path.split("/")[-1],
            "size": size,
            "indexed_at": datetime.utcnow(),
        }

    def index_conversation(self, conv_id: str, title: str, message_count: int = 0):
        """Add a conversation to the search index."""
        self._conversations[conv_id] = {
            "title": title,
            "message_count": message_count,
            "indexed_at": datetime.utcnow(),
        }

    def remove_skill(self, skill_id: str):
        """Remove a skill from the index."""
        self._skills.pop(skill_id, None)

    def remove_file(self, file_id: str):
        """Remove a file from the index."""
        self._files.pop(file_id, None)

    def remove_conversation(self, conv_id: str):
        """Remove a conversation from the index."""
        self._conversations.pop(conv_id, None)


def _calculate_score(query: str, text: str) -> Tuple[float, str]:
    """Calculate relevance score and extract snippet.

    Returns:
        (score, snippet)
    """
    if not query or not text:
        return 0.0, ""

    query_lower = query.lower()
    text_lower = text.lower()
    query_words = re.split(r'\s+', query_lower.strip())

    score = 0.0

    # Exact match (highest priority)
    if query_lower in text_lower:
        score += 10.0

    # Word matches
    for word in query_words:
        if len(word) < 2:
            continue
        count = text_lower.count(word)
        score += count * 2.0

    # Title/Name match (bonus)
    if query_lower in text_lower[:50]:  # First 50 chars (likely title)
        score += 5.0

    # Extract snippet
    snippet = ""
    if score > 0:
        # Find best matching context
        best_pos = -1
        for word in query_words:
            pos = text_lower.find(word)
            if pos != -1:
                best_pos = pos
                break

        if best_pos >= 0:
            start = max(0, best_pos - 50)
            end = min(len(text), best_pos + 100)
            snippet = text[start:end]
            if start > 0:
                snippet = "..." + snippet
            if end < len(text):
                snippet = snippet + "..."

    return score, snippet


class GlobalSearchManager:
    """Manages global search across all data sources."""

    def __init__(self):
        self._index = SearchIndex()

    def search(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[SearchResult]:
        """Search across all sources.

        Args:
            query: Search query
            sources: List of sources to search ("skill", "file", "conversation"). None = all.
            limit: Max results to return
            offset: Pagination offset

        Returns:
            List of search results sorted by score
        """
        if not sources:
            sources = ["skill", "file", "conversation"]

        results: List[SearchResult] = []

        # Search skills
        if "skill" in sources:
            for skill_id, skill_data in self._index._skills.items():
                text = f"{skill_data['name']} {skill_data['description']} {skill_data['category']}"
                score, snippet = _calculate_score(query, text)
                if score > 0:
                    results.append(SearchResult(
                        source="skill",
                        item_id=skill_id,
                        title=skill_data["name"],
                        snippet=snippet,
                        score=score,
                        metadata={"category": skill_data["category"]},
                    ))

        # Search files
        if "file" in sources:
            for file_id, file_data in self._index._files.items():
                text = f"{file_data['name']} {file_data['path']}"
                score, snippet = _calculate_score(query, text)
                if score > 0:
                    results.append(SearchResult(
                        source="file",
                        item_id=file_id,
                        title=file_data["name"],
                        snippet=snippet,
                        score=score,
                        metadata={"path": file_data["path"], "size": file_data["size"]},
                    ))

        # Search conversations
        if "conversation" in sources:
            for conv_id, conv_data in self._index._conversations.items():
                text = conv_data["title"]
                score, snippet = _calculate_score(query, text)
                if score > 0:
                    results.append(SearchResult(
                        source="conversation",
                        item_id=conv_id,
                        title=conv_data["title"],
                        snippet=snippet,
                        score=score,
                        metadata={"message_count": conv_data["message_count"]},
                    ))

        # Sort by score (descending)
        results.sort(key=lambda r: r.score, reverse=True)

        # Pagination
        return results[offset: offset + limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get search index statistics."""
        return {
            "skills_indexed": len(self._index._skills),
            "files_indexed": len(self._index._files),
            "conversations_indexed": len(self._index._conversations),
        }


# Global search manager
search_manager = GlobalSearchManager()


# ---- API Router ----

router = APIRouter(prefix="/search", tags=["Search"])


@router.get("")
async def search(
    q: str,
    sources: Optional[str] = None,  # Comma-separated: skill,file,conversation
    limit: int = 50,
    offset: int = 0,
):
    """Perform global search.

    Args:
        q: Search query (required)
        sources: Comma-separated list of sources to search. Default: all.
        limit: Max results (default: 50)
        offset: Pagination offset (default: 0)
    """
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters")

    source_list = None
    if sources:
        source_list = [s.strip() for s in sources.split(",") if s.strip()]
        valid_sources = {"skill", "file", "conversation"}
        if not source_list.issubset(valid_sources):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sources. Valid: {', '.join(sorted(valid_sources))}",
            )

    results = search_manager.search(
        query=q.strip(),
        sources=source_list,
        limit=limit,
        offset=offset,
    )

    # Group by source
    grouped: Dict[str, List[Dict]] = {}
    for r in results:
        d = r.to_dict()
        grouped.setdefault(r.source, []).append(d)

    return {
        "query": q,
        "total_results": len(results),
        "results": results[:limit],
        "grouped": grouped,
        "stats": search_manager.get_stats(),
    }


@router.get("/stats")
async def get_search_stats():
    """Get search index statistics."""
    return search_manager.get_stats()


@router.post("/index/skill")
async def index_skill(request: Request):
    """Manually index a skill (for admin/maintenance)."""
    body = await request.json()
    skill_id = body.get("skill_id")
    name = body.get("name")
    description = body.get("description", "")
    category = body.get("category", "")

    if not skill_id or not name:
        raise HTTPException(status_code=400, detail="skill_id and name are required")

    search_manager._index.index_skill(skill_id, name, description, category)
    return {"ok": True}


@router.post("/index/file")
async def index_file(request: Request):
    """Manually index a file."""
    body = await request.json()
    file_id = body.get("file_id")
    path = body.get("path")
    size = body.get("size", 0)

    if not file_id or not path:
        raise HTTPException(status_code=400, detail="file_id and path are required")

    search_manager._index.index_file(file_id, path, size)
    return {"ok": True}


@router.post("/index/conversation")
async def index_conversation(request: Request):
    """Manually index a conversation."""
    body = await request.json()
    conv_id = body.get("conv_id")
    title = body.get("title")
    message_count = body.get("message_count", 0)

    if not conv_id or not title:
        raise HTTPException(status_code=400, detail="conv_id and title are required")

    search_manager._index.index_conversation(conv_id, title, message_count)
    return {"ok": True}


@router.delete("/index/{source}/{item_id}")
async def remove_from_index(source: str, item_id: str):
    """Remove an item from the search index."""
    if source == "skill":
        search_manager._index.remove_skill(item_id)
    elif source == "file":
        search_manager._index.remove_file(item_id)
    elif source == "conversation":
        search_manager._index.remove_conversation(item_id)
    else:
        raise HTTPException(status_code=400, detail=f"Invalid source: {source}")

    return {"ok": True}
