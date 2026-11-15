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

"""检查点接口（B5-A 最小版）。

三个口：列表（只读）、预览（只读、不落盘）、恢复（破坏性，必须显式授权）。

鉴权沿用决策台那套（``app/routers/decisions.py::_identity``）：身份从网关
注入的 ``request.state`` 取，**不认任何自报身份的头**。作用域硬隔离——
非管理员只能看/动自己的检查点，传别人的用户名直接 403。

功能开关 ``COAPIS_CHECKPOINTS_ENABLED`` 默认关。**关闭时不静默**：
列表 404、动作 503，detail 都写清楚怎么开启。

路由注册由父代理统一做（本文件不注册）::

    from ..routers.checkpoints import router as checkpoints_router
    app.include_router(checkpoints_router, prefix="/api",
                       dependencies=authing)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ...checkpoints import (
    CheckpointIntegrityError,
    CheckpointNotFoundError,
    CheckpointPathError,
    CheckpointService,
    ConfirmRequiredError,
    ScopeForbiddenError,
    TooManyFilesError,
    BlobMissingError,
    checkpoints_enabled,
    checkpoints_flag,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checkpoints", tags=["checkpoints"])

_DISABLED_HINT = (
    "检查点功能未启用（%s）。要启用：给后端进程设环境变量 "
    "COAPIS_CHECKPOINTS_ENABLED=true 并重启服务。" % checkpoints_flag()
)


# --------------------------------------------------------------------------- #
# 身份 / 开关
# --------------------------------------------------------------------------- #


def _identity(request: Request) -> tuple[str, str]:
    """取调用者身份。照 decisions.py：只认网关注入的 request.state。"""
    username = getattr(request.state, "username", None)
    if not username:
        info = getattr(request.state, "user_info", None)
        if isinstance(info, dict):
            username = info.get("username")
    role = str(getattr(request.state, "role", None) or "user")
    return str(username or "anonymous"), role


def _require_enabled() -> None:
    if checkpoints_enabled():
        return
    raise HTTPException(status_code=404, detail=_DISABLED_HINT)


def _require_enabled_action() -> None:
    """动作类接口在功能未启用时给 503（明确"服务未开启"，不是"没数据"）。"""
    if checkpoints_enabled():
        return
    raise HTTPException(status_code=503, detail=_DISABLED_HINT)


def _scope(user: str, role: str, target: Optional[str]) -> str:
    """作用域：非管理员只能是自己。"""
    if not target or str(target).strip() in ("", "me", user):
        return user
    if role != "admin":
        raise HTTPException(
            status_code=403,
            detail="只能查看/操作自己的检查点（要查他人需管理员身份）",
        )
    return str(target).strip()


def _service(username: str) -> CheckpointService:
    try:
        return CheckpointService(username)
    except CheckpointPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ScopeForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# 请求体
# --------------------------------------------------------------------------- #


class PreviewRequest(BaseModel):
    """预览请求（只读）。"""

    checkpoint_id: str = Field(..., description="要回滚到的检查点 id")
    user: Optional[str] = Field(
        None, description="管理员查他人时指定；非管理员忽略此字段"
    )


class RestoreRequest(BaseModel):
    """恢复请求（破坏性）。``confirm`` 必须显式为 true。"""

    checkpoint_id: str = Field(..., description="要回滚到的检查点 id")
    confirm: bool = Field(False, description="显式授权；false 直接 400")
    session: Optional[str] = Field(None, description="留底检查点归属的会话")
    user: Optional[str] = Field(
        None, description="管理员操作他人时指定；非管理员忽略此字段"
    )


# --------------------------------------------------------------------------- #
# 接口
# --------------------------------------------------------------------------- #


@router.get("")
def list_checkpoints(
    request: Request,
    session: Optional[str] = Query(None, description="按会话过滤"),
    user: Optional[str] = Query(None, description="管理员查他人"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """列出检查点（只读）。非管理员只看自己的。"""
    _require_enabled()
    username, role = _identity(request)
    scope = _scope(username, role, user)
    svc = _service(scope)
    try:
        items = svc.list_checkpoints(session=session, limit=limit)
    except CheckpointPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "username": scope,
        "enabled": True,
        "session_filter": session,
        "count": len(items),
        "items": [c.to_summary() for c in items],
    }


@router.post("/preview")
def preview_restore(
    request: Request, body: PreviewRequest = Body(...)
) -> dict[str, Any]:
    """回滚预览：返回将回滚的文件清单 + 哈希差异。**绝不落盘**。"""
    _require_enabled_action()
    username, role = _identity(request)
    scope = _scope(username, role, body.user)
    svc = _service(scope)
    try:
        plan = svc.preview_restore(body.checkpoint_id)
    except CheckpointNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CheckpointPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = plan.to_dict()
    payload["dry_run"] = True
    payload["wrote_to_disk"] = False
    return payload


@router.post("/restore")
def restore_checkpoint(
    request: Request, body: RestoreRequest = Body(...)
) -> dict[str, Any]:
    """执行回滚。无 ``confirm: true`` 一律 400；恢复前自动生成留底检查点。"""
    _require_enabled_action()
    username, role = _identity(request)
    scope = _scope(username, role, body.user)
    if body.confirm is not True:
        raise HTTPException(
            status_code=400,
            detail=(
                "恢复是破坏性操作，必须显式授权：请求体带 \"confirm\": true。"
                "建议先调 POST /api/checkpoints/preview 看待改清单。"
            ),
        )
    svc = _service(scope)
    try:
        outcome = svc.restore(
            body.checkpoint_id, confirm=True, session=body.session
        )
    except ConfirmRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CheckpointNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (CheckpointIntegrityError, BlobMissingError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TooManyFilesError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except CheckpointPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    out = outcome.to_dict()
    out["username"] = scope
    return out
