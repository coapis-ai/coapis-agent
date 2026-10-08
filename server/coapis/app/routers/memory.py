# -*- coding: utf-8 -*-
"""Memory API — unified ledger + timeline read endpoints.

Endpoints (design: tech_docs/记忆系统整合设计方案.md §5.3):
- ``GET /api/memory/entries``       — ledger listing (scope/category/importance filters)
- ``GET /api/memory/timeline``      — timeline listing (signal_type filter, paginated)
- ``GET /api/memory/timeline/recent`` — trailing-window feed for the chat panel
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ...foundation.memory_repository import ScopeType
from ...foundation.repository_factory import RepositoryFactory
from ..auth import get_current_user

router = APIRouter(prefix="/memory", tags=["memory"])


class PageResponse(BaseModel):
    items: list[dict]
    total: int
    limit: int
    offset: int


class RecentResponse(BaseModel):
    items: list[dict]


@router.get("/entries", response_model=PageResponse)
async def list_memory_entries(
    user: dict = Depends(get_current_user),
    scope: ScopeType = Query(default=ScopeType.USER),
    category: str | None = Query(default=None),
    workspace_id: str | None = Query(
        default=None, description="Filter by workspace (org-shared memory)."),
    min_importance: float = Query(default=0.0, ge=0.0, le=1.0),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PageResponse:
    """Ledger listing for the signed-in user (user scope by default)."""
    # Memory subsystem keys users by username (workspace naming, REME).
    user_id = str(user.get("username") or user.get("id") or "")
    repo = RepositoryFactory.get_memory_repository()
    entries = repo.list_entries(
        scope=scope,
        user_id=user_id,
        workspace_id=workspace_id,
        category=category,
        q=q,
        limit=limit,
        offset=offset,
    )
    total = repo.count(
        scope=scope, user_id=user_id, workspace_id=workspace_id,
        category=category, q=q)
    items = [
        e.to_dict()
        for e in entries
        if (e.importance or 0.0) >= min_importance
    ]
    # NOTE: min_importance filters post-query; total reflects the pre-filter
    # count. Acceptable for v1 (importance floor rarely binds at default 0).
    return PageResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/timeline", response_model=PageResponse)
async def list_memory_timeline(
    user: dict = Depends(get_current_user),
    signal_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PageResponse:
    """Timeline listing for the signed-in user, newest first."""
    user_id = str(user.get("username") or user.get("id") or "")
    repo = RepositoryFactory.get_memory_timeline_repository()
    items, total = repo.query(
        user_id=user_id,
        signal_type=signal_type,
        limit=limit,
        offset=offset,
    )
    return PageResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/timeline/recent", response_model=RecentResponse)
async def recent_memory_timeline(
    user: dict = Depends(get_current_user),
    hours: int = Query(default=24, ge=1, le=24 * 30),
    limit: int = Query(default=100, ge=1, le=500),
) -> RecentResponse:
    """Trailing-window timeline feed (chat-panel 'what we talked about')."""
    user_id = str(user.get("username") or user.get("id") or "")
    repo = RepositoryFactory.get_memory_timeline_repository()
    items = repo.recent(user_id=user_id, hours=hours, limit=limit)
    return RecentResponse(items=items)
