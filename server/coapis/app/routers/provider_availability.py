# -*- coding: utf-8 -*-
"""模型可用性台账接口（B1-B · 只读）。

**为什么单独一个路由**（实施方案 §5-B1）：判官弃权时台账里只写得到
"circuit breaker open"，运维看不到是 429、超时还是鉴权；聊天侧重试耗尽时
同样没有留下"为什么"。本路由把两份原因合成一处给人看。

**只读**：本路由不写任何状态；写由
``providers/provider_model_availability.py`` 在调用链里完成。
权限口径沿用判官台账（``judge:audit``，见 routers/decisions.py:323）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from ..permissions import require_perm
from ...providers.provider_model_availability import (
    AVAILABILITY_STATUSES,
    get_availability_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/providers",
    tags=["providers"],
    dependencies=[Depends(require_perm("judge:audit"))],
)


@router.get("/availability")
async def get_provider_model_availability(
    provider_id: str | None = Query(
        None,
        description="只看某个 provider（不传 = 全部）",
    ),
    include_ok: bool = Query(
        True,
        description="是否包含 status=ok 的条目（默认含，便于看到恢复）",
    ),
) -> dict:
    """读模型可用性台账（进程内观测数据）。

    数据口径：台账是**进程内**的（重启即清空），TTL 默认 1 小时
    （``COAPIS_AVAILABILITY_TTL`` 秒，非法值回默认）。所以它是"最近发生过
    什么"的观测面，不是长期审计账——长期账在判官台账 ``decision_events``。
    """
    provider_ids = [provider_id] if provider_id else None
    try:
        view = get_availability_store().snapshot(provider_ids).to_dict()
    except Exception as exc:  # 只读接口不因观测面抖动 500
        logger.warning("可用性台账读取失败: %s: %s", type(exc).__name__, exc)
        return {
            "items": [],
            "count": 0,
            "statuses": sorted(AVAILABILITY_STATUSES),
            "error": f"{type(exc).__name__}",
        }
    if not include_ok:
        view["items"] = [
            item for item in view["items"] if item.get("status") != "ok"
        ]
        view["count"] = len(view["items"])
    view["statuses"] = sorted(AVAILABILITY_STATUSES)
    return view
