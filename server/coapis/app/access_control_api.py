# -*- coding: utf-8 -*-
"""AccessControl API — 统一访问控制 REST 端点。

端点：
- GET  /api/access-control/summary        — 所有频道 ACL 摘要
- GET  /api/access-control/{channel}      — 频道 ACL 详情
- POST /api/access-control/{channel}/whitelist     — 添加白名单
- DELETE /api/access-control/{channel}/whitelist/{user_id} — 移除白名单
- POST /api/access-control/{channel}/blacklist     — 添加黑名单
- DELETE /api/access-control/{channel}/blacklist/{user_id} — 移除黑名单
- GET  /api/access-control/pending        — 所有待审批列表
- POST /api/access-control/{channel}/pending/{user_id}/approve — 批准
- POST /api/access-control/{channel}/pending/{user_id}/reject  — 拒绝
- POST /api/access-control/{channel}/migrate  — 从旧 allow_from 迁移
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .access_control import get_access_control_store
from .permissions.decorators import require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/access-control", tags=["access-control"])


def _workspace_dir(request: Request, username: str) -> Path:
    """获取用户 workspace 目录路径。"""
    from ..constant import WORKSPACES_DIR
    return WORKSPACES_DIR / username


def _get_store(request: Request, username: str):
    """获取用户的 AccessControlStore。"""
    ws_dir = _workspace_dir(request, username)
    if not ws_dir.exists():
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    return get_access_control_store(ws_dir)


def _get_username(request: Request) -> str:
    """从 request state 获取当前用户名。"""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return username


# ── Request models ──────────────────────────────────────────────

class UserRemarkRequest(BaseModel):
    user_id: str
    remark: str = ""


class MigrateRequest(BaseModel):
    allow_from: List[str]


# ── 摘要和详情 ─────────────────────────────────────────────────

@router.get("/summary")
@require_role("admin")
async def get_summary(request: Request):
    """获取所有频道的 ACL 摘要。"""
    username = _get_username(request)
    store = _get_store(request, username)
    return {"username": username, "channels": store.get_summary()}


@router.get("/{channel}")
@require_role("admin")
async def get_channel_detail(request: Request, channel: str):
    """获取单个频道的完整 ACL 详情。"""
    username = _get_username(request)
    store = _get_store(request, username)
    return {"username": username, "channel": channel, "acl": store.get_channel_detail(channel)}


# ── 白名单管理 ─────────────────────────────────────────────────

@router.post("/{channel}/whitelist")
@require_role("admin")
async def add_whitelist(request: Request, channel: str, body: UserRemarkRequest):
    """添加用户到白名单。"""
    username = _get_username(request)
    store = _get_store(request, username)
    store.add_to_whitelist(channel, body.user_id, body.remark)
    return {"ok": True, "action": "added_to_whitelist", "user_id": body.user_id, "channel": channel}


@router.delete("/{channel}/whitelist/{user_id}")
@require_role("admin")
async def remove_whitelist(request: Request, channel: str, user_id: str):
    """从白名单移除用户。"""
    username = _get_username(request)
    store = _get_store(request, username)
    store.remove_from_whitelist(channel, user_id)
    return {"ok": True, "action": "removed_from_whitelist", "user_id": user_id, "channel": channel}


# ── 黑名单管理 ─────────────────────────────────────────────────

@router.post("/{channel}/blacklist")
@require_role("admin")
async def add_blacklist(request: Request, channel: str, body: UserRemarkRequest):
    """添加用户到黑名单。"""
    username = _get_username(request)
    store = _get_store(request, username)
    store.add_to_blacklist(channel, body.user_id, body.remark)
    return {"ok": True, "action": "added_to_blacklist", "user_id": body.user_id, "channel": channel}


@router.delete("/{channel}/blacklist/{user_id}")
@require_role("admin")
async def remove_blacklist(request: Request, channel: str, user_id: str):
    """从黑名单移除用户。"""
    username = _get_username(request)
    store = _get_store(request, username)
    store.remove_from_blacklist(channel, user_id)
    return {"ok": True, "action": "removed_from_blacklist", "user_id": user_id, "channel": channel}


# ── 待审批管理 ─────────────────────────────────────────────────

@router.get("/pending/list")
@require_role("admin")
async def get_pending(request: Request):
    """获取所有待审批列表。"""
    username = _get_username(request)
    store = _get_store(request, username)
    return {"username": username, "pending": store.get_all_pending()}


@router.post("/{channel}/pending/{user_id}/approve")
@require_role("admin")
async def approve_pending(request: Request, channel: str, user_id: str, body: Optional[UserRemarkRequest] = None):
    """批准待审批用户，加入白名单。"""
    username = _get_username(request)
    store = _get_store(request, username)
    remark = body.remark if body else ""
    ok = store.approve_pending(channel, user_id, remark)
    if not ok:
        raise HTTPException(status_code=404, detail="Pending entry not found")
    return {"ok": True, "action": "approved", "user_id": user_id, "channel": channel}


@router.post("/{channel}/pending/{user_id}/reject")
@require_role("admin")
async def reject_pending(request: Request, channel: str, user_id: str, body: Optional[UserRemarkRequest] = None):
    """拒绝待审批用户，加入黑名单。"""
    username = _get_username(request)
    store = _get_store(request, username)
    remark = body.remark if body else ""
    ok = store.reject_pending(channel, user_id, remark)
    if not ok:
        raise HTTPException(status_code=404, detail="Pending entry not found")
    return {"ok": True, "action": "rejected", "user_id": user_id, "channel": channel}


# ── 迁移 ──────────────────────────────────────────────────────

@router.post("/{channel}/migrate")
@require_role("admin")
async def migrate_allow_from(request: Request, channel: str, body: MigrateRequest):
    """从旧 allow_from 配置迁移到白名单。"""
    username = _get_username(request)
    store = _get_store(request, username)
    store.import_allow_from(channel, set(body.allow_from))
    return {"ok": True, "action": "migrated", "channel": channel, "count": len(body.allow_from)}
