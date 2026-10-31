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

"""判断中枢可见可控（v14 §5.2 / U 批）。

判官过去最大的问题不是"判得准不准"，是**没人知道它判没判**——台账
写进库里，前端一行都看不到。这一层只做两件事：把台账按会话/来源摊开，
把配置开关交到人手里。

Endpoints:
    GET    /decisions              — 台账列表（chat_id / source / turn 过滤，分页）
    GET    /decisions/stats        — 近 N 天逐来源战绩（判断/降级/超时/命中率/花费）
    POST   /decisions/{id}/rating  — 人给一次判断打分
    GET    /decisions/config       — 判官配置 + 当前生效的判断模型
    PUT    /decisions/config       — 改判官配置（落 agent.json，即时生效）

作用域：普通用户只看自己的行（台账 user_id == 登录名）；admin 看全部。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter(tags=["decisions"])

_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50
_SOURCES = ("plan_gate", "outcome", "skill_trigger", "advisor", "acceptance")
_OUTCOMES = ("hit", "miss", "pending")

# 台账里"判了但没走成"的层——词表必须与 gateway 写入侧逐字一致
# （LAYER_BREAKER="breaker_open"、LAYER_BUDGET="budget_cap"…）。
# 过去这里写的是 'breaker'/'budget'/'malformed'，台账里根本不存在这些值，
# 统计永远是 0，"判官有没有干活"的降级信号被抹平。
_DEGRADED = ("no_model", "breaker_open", "budget_cap", "timeout",
             "transport", "parse_fail", "not_chat", "error")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _identity(request: Request) -> tuple[str, str]:
    """(username, role)。无名氏按 user 处理——台账不给匿名开门。"""
    username = getattr(request.state, "username", None)
    if not username:
        info = getattr(request.state, "user_info", None)
        if isinstance(info, dict):
            username = info.get("username")
    role = str(getattr(request.state, "role", None) or "user")
    return str(username or "anonymous"), role


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    ts = data.get("ts")
    if hasattr(ts, "isoformat"):
        data["ts"] = ts.isoformat()
    elif ts is not None:
        data["ts"] = str(ts)
    return data


def _active_agent_id(request: Request, username: str) -> str:
    """会话当前智能体：请求头 > 查询参数 > 全局 active_agent > default。"""
    aid = request.headers.get("X-Agent-Id") or request.query_params.get("agent_id")
    if aid:
        return str(aid)
    try:
        from coapis.app.agent_context import get_active_agent_id

        return str(get_active_agent_id() or "default")
    except Exception:  # pragma: no cover - 上下文未就绪时退回 default
        return "default"


# --------------------------------------------------------------------------- #
# 台账
# --------------------------------------------------------------------------- #

@router.get("")
def list_decisions(
    request: Request,
    chat_id: Optional[str] = Query(None, description="按会话过滤"),
    source: Optional[str] = Query(None, description="按判断来源过滤"),
    turn: Optional[int] = Query(None, ge=0, description="按回合过滤"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """判断台账列表，最新在前。普通用户只见自己的行。"""
    me, role = _identity(request)
    where = ["1=1"]
    params: dict[str, Any] = {}
    if role != "admin":
        where.append("user_id = :me")
        params["me"] = me
    if chat_id:
        where.append("chat_id = :chat_id")
        params["chat_id"] = chat_id
    if source:
        where.append("source = :source")
        params["source"] = source
    if turn is not None:
        where.append("turn = :turn")
        params["turn"] = turn
    clause = " AND ".join(where)
    try:
        from coapis.foundation.db.engine import get_session

        with get_session() as session:
            total = session.execute(
                text(f"SELECT COUNT(*) FROM decision_events WHERE {clause}"),
                params,
            ).scalar() or 0
            rows = session.execute(
                text(
                    # 列名严格对齐台账真实表（19 列）与 bus._LEDGER_COLUMNS 写入侧，
                    # 不引用不存在的列——过去这里写了 ts/tokens_in/confidence 等
                    # 9 个幽灵列，真实库上整条查询直接抛错，台账恒空。
                    "SELECT event_id, created_at, user_id, agent_id, chat_id, "
                    "turn, source, complexity, action, judgment, reason, "
                    "hit_layer, model, latency_ms, cost, tokens, outcome, "
                    "rating, input_hash "
                    f"FROM decision_events WHERE {clause} "
                    "ORDER BY created_at DESC, event_id DESC "
                    "LIMIT :_limit OFFSET :_offset",
                ),
                {**params, "_limit": limit, "_offset": offset},
            ).all()
    except Exception as exc:  # pragma: no cover - 库坏了不该拖垮前端
        logger.warning("[Decisions] 台账读取失败: %s", exc)
        return {"items": [], "total": 0, "limit": limit, "offset": offset,
                "error": str(exc)}
    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/stats")
def decision_stats(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    chat_id: Optional[str] = Query(None),
) -> dict[str, Any]:
    """逐来源战绩：判断次数、真判断/降级/超时、耗时、花费、命中率。

    这组数字就是"判官到底有没有发生作用"的直接证据：``degraded`` 高
    说明阶梯在原地降级（多半是没配判断模型或超时太短），``llm`` 有数
    才说明真跑过大模型。
    """
    me, role = _identity(request)
    # created_at 是 float epoch（台账写入侧用 time.time()）。时间窗必须按
    # 秒比；原来按 datetime 字符串比幽灵列 'ts'，真实库上整条统计直接抛错。
    where = ["created_at >= (strftime('%s','now') - :win_sec)"]
    params: dict[str, Any] = {"win_sec": int(days) * 86400}
    if role != "admin":
        where.append("user_id = :me")
        params["me"] = me
    if chat_id:
        where.append("chat_id = :chat_id")
        params["chat_id"] = chat_id
    clause = " AND ".join(where)
    degraded = ",".join(f"'{x}'" for x in _DEGRADED)
    from coapis.decision.hub_acceptance import _NO_JUDGMENT_SOURCES
    no_judge = ",".join(f"'{x}'" for x in _NO_JUDGMENT_SOURCES)
    sql = text(
        "SELECT source, "
        "COUNT(*) AS n, "
        # 真判断次数：规则/闸门/开关关闭这类"压根不需要判"的行不是判断。
        # 混在一起计数会被巡检噪声灌满，看不出判官有没有发生作用。
        f"SUM(CASE WHEN hit_layer NOT IN ({no_judge}) THEN 1 ELSE 0 END) AS judged, "
        "SUM(CASE WHEN hit_layer='llm' THEN 1 ELSE 0 END) AS llm, "
        f"SUM(CASE WHEN hit_layer IN ({degraded}) THEN 1 ELSE 0 END) AS degraded, "
        "SUM(CASE WHEN hit_layer='timeout' THEN 1 ELSE 0 END) AS timeouts, "
        "SUM(CASE WHEN hit_layer='no_model' THEN 1 ELSE 0 END) AS no_model, "
        "ROUND(AVG(latency_ms), 0) AS avg_ms, "
        "MAX(latency_ms) AS max_ms, "
        "ROUND(SUM(cost), 4) AS cost, "
        "SUM(tokens) AS tokens, "
        "SUM(CASE WHEN outcome='hit' THEN 1 ELSE 0 END) AS hit, "
        "SUM(CASE WHEN outcome='miss' THEN 1 ELSE 0 END) AS miss, "
        "SUM(CASE WHEN outcome='pending' THEN 1 ELSE 0 END) AS pending "
        f"FROM decision_events WHERE {clause} "
        "GROUP BY source ORDER BY n DESC"
    )
    try:
        from coapis.foundation.db.engine import get_session

        with get_session() as session:
            rows = session.execute(sql, params).all()
            total_cost = session.execute(
                text(f"SELECT ROUND(SUM(cost), 4) FROM decision_events "
                     f"WHERE {clause}"),
                params,
            ).scalar() or 0
            total_n = session.execute(
                text(f"SELECT COUNT(*) FROM decision_events WHERE {clause}"),
                params,
            ).scalar() or 0
    except Exception as exc:  # pragma: no cover
        logger.warning("[Decisions] 统计读取失败: %s", exc)
        return {"days": days, "total": 0, "cost": 0.0, "by_source": [],
                "error": str(exc)}
    return {
        "days": days,
        "total": int(total_n),
        "cost": float(total_cost or 0),
        "by_source": [dict(r._mapping) for r in rows],
    }


@router.post("/{event_id}/rating")
def rate_decision(
    event_id: str,
    request: Request,
    rating: int = Query(..., ge=-1, le=1, description="1 准 / 0 不准 / -1 撤销"),
    outcome: Optional[str] = Query(None, description="hit|miss|pending"),
) -> dict[str, Any]:
    """给某一次判断打分（台账 ``rating`` 列的入口）。

    普通用户只能改自己的行——判官战绩不能被别人刷分。
    """
    me, role = _identity(request)
    if outcome is not None and outcome not in _OUTCOMES:
        raise HTTPException(status_code=400, detail="outcome 取值不对")
    sql = text(
        "UPDATE decision_events SET rating = :rating"
        + (", outcome = :outcome" if outcome else "")
        + " WHERE event_id = :_eid"
        + ("" if role == "admin" else " AND user_id = :me"),
    )
    params: dict[str, Any] = {"rating": int(rating), "_eid": event_id}
    if outcome:
        params["outcome"] = outcome
    if role != "admin":
        params["me"] = me
    try:
        from coapis.foundation.db.engine import get_session

        with get_session() as session:
            changed = session.execute(sql, params).rowcount
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not changed:
        raise HTTPException(status_code=404, detail="该判断记录不存在或不属于你")
    return {"ok": True, "event_id": event_id, "rating": int(rating),
            "outcome": outcome}


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #

@router.get("/config")
def get_config(request: Request) -> dict[str, Any]:
    """判官配置 + 当前生效的判断模型（面板必须显示"判官到底是谁"）。"""
    me, _role = _identity(request)
    agent_id = _active_agent_id(request, me)
    # 判断模型的解析唯一归 resolver（plan_gate 里的同名函数已删——
    # 两处各解一遍正是 v14 §0.3 抓到的"绕过配置"根因）
    from coapis.decision.resolver import get_judgment_provider_config
    from coapis.decision import get_hub_config

    hub = get_hub_config()
    try:
        slot = get_judgment_provider_config(me, agent_id) or {}
    except Exception:  # pragma: no cover - 槽位解析失败时只报配置
        slot = {}
    return {
        "config": hub.as_dict(),
        "judge": {
            "provider_id": str(slot.get("provider_id") or ""),
            "model": str(slot.get("model") or ""),
        },
        "agent_id": agent_id,
        "sources": list(_SOURCES),
    }


@router.put("/config")
def put_config(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """改判官配置，写进 agent.json 的 ``decision_hub`` 段（重启后仍生效）。

    只认 :mod:`coapis.decision.config` 认识的键，未知键拒收——不再制造
    "配置写了没人读"的死字段（v14 §0.3 的教训）。
    """
    from coapis.config import load_agent_config, save_agent_config
    from coapis.decision.config import DecisionHubConfig, reset_hub_config

    agent_id = _active_agent_id(request, _identity(request)[0])
    try:
        cfg = load_agent_config(agent_id)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=404, detail=f"智能体读不到: {exc}") from exc
    known = set(DecisionHubConfig.known_keys())
    body = body or {}
    payload = {k: v for k, v in body.items() if k in known}
    unknown = sorted(set(body) - known)
    if not payload:
        raise HTTPException(status_code=400, detail="没有可识别的配置项")
    merged = dict(getattr(cfg, "decision_hub", None) or {})
    merged.update(payload)
    try:
        cfg.decision_hub = merged
        save_agent_config(agent_id, cfg)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"保存失败: {exc}") from exc
    reset_hub_config()
    return {"ok": True, "agent_id": agent_id, "decision_hub": merged,
            "ignored": unknown}
