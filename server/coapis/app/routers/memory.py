# -*- coding: utf-8 -*-
"""Memory API — unified ledger + timeline read endpoints.

Endpoints (design: tech_docs/记忆系统整合设计方案.md §5.3):
- ``GET /api/memory/entries``       — ledger listing (scope/category/importance filters)
- ``GET /api/memory/timeline``      — timeline listing (signal_type filter, paginated)
- ``GET /api/memory/timeline/recent`` — trailing-window feed for the chat panel

v3 知识沉淀（方案 2026-11-07 社区版知识沉淀 v3）:
- ``POST /api/memory/notes``                  — 聊天侧"记下来"（importance=1.0）
- ``GET  /api/memory/knowledge``              — 治理页列表（含已撤销）
- ``POST /api/memory/knowledge/{id}/undo``    — 撤销（软删）
- ``POST /api/memory/knowledge/{id}/restore`` — 恢复
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...foundation.memory_repository import ScopeType
from ...foundation.repository_factory import RepositoryFactory
from ..auth import get_current_user

logger = logging.getLogger(__name__)

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


# ── v3 知识沉淀：记下来 / 治理列表 / 撤销 ───────────────────────────


class NoteRequest(BaseModel):
    """"记下来"请求体（用户在聊天里显式要求沉淀）。"""

    content: str
    session_id: str = ""
    agent_id: str = ""
    category: str = "notes"


class NoteResponse(BaseModel):
    model_config = {"populate_by_name": True}

    ok: bool
    id: int | None = None
    detail: str = ""


class KnowledgeListResponse(BaseModel):
    model_config = {"populate_by_name": True}

    ok: bool = True
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    stats: dict[str, Any] = Field(default_factory=dict)


def _row_payload(row: Any) -> dict[str, Any]:
    """把仓库条目摊平成前端要的扁平字段。"""
    return {
        "id": row.id,
        "scope": str(row.scope),
        "user_id": row.user_id or "",
        "agent_id": row.agent_id or "",
        "session_id": row.session_id or "",
        "category": row.category,
        "title": row.title,
        "content": row.content,
        "importance": float(row.importance or 0.0),
        "source": row.source or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "deleted_at": row.deleted_at,
        "archived": row.deleted_at is not None,
    }


def _knowledge_repo() -> Any:
    return RepositoryFactory.get_memory_repository()


@router.post("/notes", response_model=NoteResponse)
async def create_memory_note(
    body: NoteRequest,
    user: dict = Depends(get_current_user),
) -> NoteResponse:
    """"记下来"：把这条内容作为 importance=1.0 的记忆落库。

    机器晋升（dream → scope=user, importance≈0.6）走的是统计门槛，用户没有
    入口把"这条有用"变成记忆 —— 旧审核台是唯一入口且必 500。这里给一个
    一步到位的通道：写 DB → 刷投影 → 立刻可被注入。
    """
    content = (body.content or "").strip()
    if len(content) < 2:
        raise HTTPException(status_code=400, detail="content too short")
    user_id = str(user.get("username") or user.get("id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="no user identity")

    from ...foundation.foundation_manager import get_foundation_manager

    fm = get_foundation_manager()
    new_id = fm.add_note(
        content=content,
        user_id=user_id,
        agent_id=(body.agent_id or None),
        session_id=(body.session_id or None),
        category=body.category or "notes",
    )
    if new_id is None:
        raise HTTPException(status_code=503, detail="memory store unavailable")
    logger.info("memory note created: user=%s id=%s len=%d", user_id, new_id, len(content))
    return NoteResponse(ok=True, id=new_id, detail="stored")


@router.get("/knowledge", response_model=KnowledgeListResponse)
async def list_knowledge(
    scope: str = Query("all", pattern="^(user|workspace|all)$"),
    include_archived: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
) -> KnowledgeListResponse:
    """知识沉淀列表（治理页数据源）：本人条目 + 共享层条目。

    ``include_archived`` 默认开：淘汰/撤销的记录必须可见，否则"事后撤销"
    变成"事后失忆"。
    """
    user_id = str(user.get("username") or user.get("id") or "")
    repo = _knowledge_repo()
    rows: list[dict[str, Any]] = []
    total = 0
    scopes = [None] if scope == "all" else [scope]
    for sc in scopes:
        rows.extend(repo.list_for_governance(
            user_id=user_id, scope=sc, include_archived=include_archived,
            limit=limit, offset=offset,
        ))
        total += repo.count_for_governance(user_id=user_id, scope=sc)
    rows.sort(key=lambda r: (-float(r.get("importance") or 0.0), -(r.get("created_at") or 0)))
    rows = rows[:limit]
    stats = repo.stats(user_id=user_id)
    return KnowledgeListResponse(ok=True, items=rows, total=total, stats=stats)


@router.post("/knowledge/{memory_id}/undo")
async def undo_knowledge(
    memory_id: int,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """撤销一条沉淀（软删）。撤销后既不进注入、也不进投影。

    权限：本人的条目本人撤；共享层条目只有管理员能撤（撤的是"共享"这个
    决定，条目本体留给原主）。
    """
    user_id = str(user.get("username") or user.get("id") or "")
    repo = _knowledge_repo()
    row = repo.get(memory_id, include_archived=True)
    if row is None:
        raise HTTPException(status_code=404, detail="memory not found")
    if row.user_id and row.user_id != user_id and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="not your memory entry")
    if not row.user_id and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="shared entries need admin")
    if not repo.delete(memory_id):
        raise HTTPException(status_code=410, detail="already revoked or gone")
    _refresh_projection()
    logger.info("knowledge revoked: user=%s id=%s", user_id, memory_id)
    return {"ok": True, "id": memory_id, "state": "revoked"}


@router.post("/knowledge/{memory_id}/restore")
async def restore_knowledge(
    memory_id: int,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """恢复一条被撤销的沉淀（撤销的撤销）。"""
    user_id = str(user.get("username") or user.get("id") or "")
    repo = _knowledge_repo()
    row = repo.get(memory_id, include_archived=True)
    if row is None:
        raise HTTPException(status_code=404, detail="memory not found")
    if row.user_id and row.user_id != user_id and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="not your memory entry")
    if not repo.restore(memory_id):
        raise HTTPException(status_code=409, detail="not revoked")
    _refresh_projection()
    logger.info("knowledge restored: user=%s id=%s", user_id, memory_id)
    return {"ok": True, "id": memory_id, "state": "active"}


def _refresh_projection() -> None:
    """刷新文件投影（失败不影响本次请求结果）。"""
    try:
        from ...foundation import knowledge_export

        knowledge_export.export_from_db()
    except Exception:
        logger.warning("knowledge projection refresh failed", exc_info=True)
