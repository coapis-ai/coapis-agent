# -*- coding: utf-8 -*-
"""技能清单变更审计闸门（v19 §P2-3）。

**它治什么**（v19 实测清单里的原话）：技能清单现在人人可改，且改的是
manifest 的 ``enabled`` 字段——启用/停用/删除/保存一个技能，**下一轮的
触发行为当场就变了**，而台账上零痕迹。出问题无法回答"谁在什么时候把哪个
技能动了"，判官技能岗的效果也就永远对不上账。

**怎么做**：给所有需要 ``skills:write`` 的端点挂一个依赖——非 GET 调用
落一条治理台账（``source="skill_gate"``），记 谁 / 什么时候 / 哪个端点 /
哪个技能。写失败只记日志，**绝不影响技能操作本身**（与台账"记账不绑
判断"的同一条口径）。

开关：``decision_hub.skill_gate_audit``（默认开）。关闭后依赖直接返回。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from fastapi import Request

logger = logging.getLogger(__name__)

#: 审计行岗位名（台账 source/purpose 都用它，对账时按它筛）。
AUDIT_SOURCE = "skill_gate"

#: 写台账失败不抛——闸门只做记录，不拦操作。
_write_fail_logged = False


def _audit_enabled() -> bool:
    """闸门开关（配置读不到时按"开"处理：审计默认要有）。"""
    try:
        from ...decision.config import get_hub_config

        return bool(get_hub_config().skill_gate_audit)
    except Exception:  # noqa: BLE001 - 配置层异常不该让技能页 500
        return True


def _write_audit_row(
    *,
    action: str,
    method: str,
    path: str,
    skill_name: str,
    user_id: str,
    agent_id: str,
) -> None:
    try:
        from ...decision.ledger_contract import write_ledger

        write_ledger(
            source=AUDIT_SOURCE,
            purpose=AUDIT_SOURCE,
            action=action,
            chat_id="",
            turn=0,
            user_id=user_id,
            agent_id=agent_id,
            hit_layer="audit",
            reason=f"技能清单变更：{action} {method} {path}"
            + (f" 技能={skill_name}" if skill_name else ""),
            value={"method": method, "path": path, "skill": skill_name},
        )
    except Exception:  # noqa: BLE001 - 审计写不进台账不该弄坏技能操作
        global _write_fail_logged
        if not _write_fail_logged:
            _write_fail_logged = True
            logger.warning("[技能审计] 台账写入失败", exc_info=True)


def skill_gate_audit(action: str = "change") -> Callable[..., Any]:
    """FastAPI 依赖工厂：为一次技能清单变更记一行治理台账。

    用法（挂在本仓库所有 ``require_perm("skills:write")`` 端点上）：

        @router.post("/{skill_name}/enable",
                     dependencies=[Depends(require_perm("skills:write")),
                                  Depends(skill_gate_audit("enable"))])

    - **只记改动**：GET 请求直接放过（``skills:write`` 里混了几个只读端点，
      如 /hub/search、/workspaces，它们不改任何东西）。
    - **不拦操作**：本依赖永不抛 4xx/5xx；权限判定仍由 ``require_perm`` 负责。
    """

    async def _dependency(request: Request) -> None:
        if request.method == "GET":
            return
        if not _audit_enabled():
            return
        state = getattr(request, "state", None)
        user_id = str(getattr(state, "username", None) or "anonymous")
        agent_id = str(getattr(state, "agent_id", "") or "")
        path = str(request.url.path)
        skill_name = str(
            request.path_params.get("skill_name")
            or request.query_params.get("skill_name")
            or "",
        )
        # 台账写是同步 DB 活，丢后台线程——技能接口的响应时间不为审计买单。
        threading.Thread(
            target=_write_audit_row,
            kwargs={
                "action": action,
                "method": request.method,
                "path": path,
                "skill_name": skill_name,
                "user_id": user_id,
                "agent_id": agent_id,
            },
            daemon=True,
        ).start()

    return _dependency


__all__ = ["AUDIT_SOURCE", "skill_gate_audit"]
