# -*- coding: utf-8 -*-
"""
Cleanup API routes — storage overview, manual cleanup, rules management.

Endpoints:
  GET  /api/cleanup/overview   — hot/warm/cold size breakdown
  POST /api/cleanup/run        — execute full cleanup
  POST /api/cleanup/run/{type} — execute single cleanup task
  GET  /api/cleanup/rules      — current cleanup rules
  PUT  /api/cleanup/rules      — update cleanup rules
  GET  /api/cleanup/history    — cleanup log history
  GET  /api/cleanup/archived   — search archived messages
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .cleanup import CleanupEngine, DEFAULT_RULES, get_cleanup_engine
from .permissions.decorators import require_permission

router = APIRouter(prefix="/cleanup", tags=["cleanup"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_workspace(request: Request) -> Path:
    """Resolve current user's workspace directory."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from ..constant import WORKSPACES_DIR
    ws_dir = WORKSPACES_DIR / username
    if not ws_dir.exists():
        raise HTTPException(status_code=404, detail=f"Workspace not found for user {username}")
    return ws_dir


def _get_engine(request: Request) -> CleanupEngine:
    ws_dir = _get_user_workspace(request)
    return get_cleanup_engine(ws_dir)


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class CleanupRunRequest(BaseModel):
    data_types: Optional[list[str]] = Field(
        default=None,
        description="Specific data types to clean. None = all.",
    )
    user_id: str = Field(default="manual")


class RulesUpdateRequest(BaseModel):
    rules: Dict[str, Dict[str, int]] = Field(
        ...,
        description="Cleanup rules map. Keys: chat_messages, sessions, dialog_logs, tool_results, browser_cache",
    )


class ArchivedQueryRequest(BaseModel):
    chat_id: Optional[str] = None
    before: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/overview")
@require_permission("backup:read")
async def storage_overview(request: Request) -> dict:
    """Get storage overview with hot/warm/cold breakdown."""
    engine = _get_engine(request)
    try:
        return engine.get_storage_overview()
    finally:
        engine.close()


@router.post("/run")
@require_permission("backup:write")
async def run_cleanup(request: Request, body: CleanupRunRequest = CleanupRunRequest()) -> dict:
    """Execute full cleanup. Returns per-type stats."""
    engine = _get_engine(request)
    try:
        results = engine.run_full_cleanup(user_id=body.user_id)
        total_freed = sum(r.bytes_freed for r in results)
        total_items = sum(r.items_archived + r.items_deleted for r in results)
        return {
            "status": "ok",
            "total_items_processed": total_items,
            "total_bytes_freed": total_freed,
            "results": [
                {
                    "data_type": r.data_type,
                    "items_archived": r.items_archived,
                    "items_deleted": r.items_deleted,
                    "bytes_freed": r.bytes_freed,
                    "details": r.details,
                }
                for r in results
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        engine.close()


@router.post("/run/{data_type}")
@require_permission("backup:write")
async def run_cleanup_single(request: Request, data_type: str) -> dict:
    """Execute a single cleanup task by data type."""
    engine = _get_engine(request)
    try:
        method_map = {
            "chat_messages": lambda: engine.archive_chat_messages("", "manual", []),
            "sessions": engine.archive_expired_sessions,
            "dialog_logs": engine.compress_old_dialogs,
            "tool_results": engine.cleanup_tool_results,
            "browser_cache": engine.cleanup_browser_cache,
        }
        if data_type not in method_map:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown data_type: {data_type}. Valid: {list(method_map.keys())}",
            )
        result = method_map[data_type]()
        return {
            "status": "ok",
            "data_type": result.data_type,
            "items_archived": result.items_archived,
            "items_deleted": result.items_deleted,
            "bytes_freed": result.bytes_freed,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        engine.close()


@router.get("/rules")
@require_permission("backup:read")
async def get_rules(request: Request) -> dict:
    """Get current cleanup rules."""
    engine = _get_engine(request)
    try:
        return {
            "rules": engine.rules,
            "defaults": DEFAULT_RULES,
        }
    finally:
        engine.close()


@router.put("/rules")
@require_permission("backup:write")
async def update_rules(request: Request, body: RulesUpdateRequest) -> dict:
    """Update cleanup rules."""
    engine = _get_engine(request)
    try:
        # Validate keys
        valid_keys = set(DEFAULT_RULES.keys())
        for key in body.rules:
            if key not in valid_keys:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown rule key: {key}. Valid: {sorted(valid_keys)}",
                )
        engine.save_rules(body.rules)
        return {"status": "ok", "rules": engine.rules}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        engine.close()


@router.get("/history")
@require_permission("backup:read")
async def cleanup_history(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """Get cleanup execution history."""
    engine = _get_engine(request)
    try:
        return {"history": engine.get_cleanup_history(limit=limit)}
    finally:
        engine.close()


@router.post("/archived")
@require_permission("backup:read")
async def search_archived(request: Request, body: ArchivedQueryRequest) -> dict:
    """Search archived messages."""
    engine = _get_engine(request)
    try:
        if not body.chat_id:
            raise HTTPException(status_code=400, detail="chat_id is required")
        messages = engine.get_archived_messages(
            chat_id=body.chat_id,
            before=body.before,
            limit=body.limit,
        )
        return {"messages": messages, "count": len(messages)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        engine.close()
