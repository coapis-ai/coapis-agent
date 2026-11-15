# -*- coding: utf-8 -*-
"""B5-B/B5-C · 治理只读端点（事件联合视图 + 沙箱状态）。

两个端点，全部**只读**：

``GET /api/governance/events``
    治理事件联合视图。``kind`` 可重复传（``?kind=judge&kind=approval``），
    取值必须是 :data:`coapis.governance.events.EVENT_KINDS` 里的词。
    判定逻辑零 here —— 全部在 ``governance/events.py`` 那张表里。

``GET /api/governance/sandbox-status``
    沙箱能力实测报告（内核 / user namespace / bwrap 自测）+ 当前档位。
    探测在治理页按需跑，不在热路径跑。

身份与可见性（口径与 /api/decisions 一致，读 request.state，零 DB）：

* 管理员：看全部，可按 ``user`` 收窄；
* 普通用户：强制只看自己的事件。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from ...governance.events import EVENT_KINDS, list_events
from ...security.env_probe import probe, read_probe_report
from ...security.sandboxed_shell import sandbox_mode, sandbox_net_mode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/governance", tags=["governance"])


def _identity(request: Request) -> tuple[str, str]:
    """取网关注入的身份（口径与 decisions 端点一致）。"""
    state = request.state
    username = str(getattr(state, "username", "") or "")
    role = str(getattr(state, "role", "") or "").lower()
    return username, role


def _is_admin(role: str) -> bool:
    return role in ("admin", "administrator", "superadmin")


@router.get("/events", summary="治理事件联合视图（只读）")
async def governance_events(
    request: Request,
    kind: list[str] = Query(
        default_factory=list,
        description="事件类别，可重复传：judge/tool/tool_denied/approval/"
        "memory/file_version/sandbox_denied/config",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    days: Optional[float] = Query(
        default=None,
        ge=0,
        description="只回看最近 N 天（含小数）；不传=不限",
    ),
    user: Optional[str] = Query(
        default=None,
        description="管理员可按用户收窄；普通用户忽略此参数",
    ),
) -> dict:
    username, role = _identity(request)
    if not username:
        raise HTTPException(status_code=401, detail="未识别到身份")

    # 作用域：非管理员强制只看自己
    scoped_user = user if (_is_admin(role) and user) else (None if _is_admin(role) else username)

    bad = sorted(set(kind) - set(EVENT_KINDS))
    if bad:
        raise HTTPException(
            status_code=400,
            detail=(
                "未知的事件类别: %s。可用: %s"
                % (", ".join(bad), ", ".join(EVENT_KINDS))
            ),
        )

    since_ts = None
    if days:
        import time

        since_ts = time.time() - days * 86400

    # 读审计链尾部 + 三张表 —— 线程池里跑，别卡事件循环
    result = await run_in_threadpool(
        list_events,
        kinds=list(kind) if kind else None,
        limit=limit,
        username=scoped_user,
        since_ts=since_ts,
    )
    result["role"] = role
    result["scope"] = scoped_user or "all"
    return result


@router.get("/sandbox-status", summary="沙箱能力实测报告（只读）")
async def governance_sandbox_status(
    request: Request,
    refresh: bool = Query(
        default=False,
        description="true=强制重探（会起一次 bwrap 自测子进程）",
    ),
) -> dict:
    username, role = _identity(request)
    if not username:
        raise HTTPException(status_code=401, detail="未识别到身份")

    report = None
    if refresh:
        if not _is_admin(role):
            raise HTTPException(status_code=403, detail="重探沙箱能力仅管理员可用")
        report = await run_in_threadpool(probe, force=True)
    else:
        report = read_probe_report()

    return {
        "mode": sandbox_mode(),
        "net": sandbox_net_mode(),
        "probed": report is not None,
        "probe": report,
        "hint": (
            "probed=false 表示还没探过；带 ?refresh=true 由管理员触发一次实测。"
            if report is None
            else None
        ),
    }
