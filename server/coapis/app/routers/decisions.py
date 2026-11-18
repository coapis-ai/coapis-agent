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
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import text

from ..permissions import require_perm
from ...decision.config import POSTS
from ...decision.ledger_contract import LEDGER_OUTCOME_CODES

logger = logging.getLogger(__name__)

router = APIRouter(tags=["decisions"])

_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50
# 台账里的 source = 岗位名（gateway 用 purpose 落账）+ 验收回灌的 "outcome"。
# 原先硬写五岗，plan_review / tool_gate / intent 的行存在却筛不出来——
# 治理页上"六岗配置"有六个岗，筛选项只有五个，对账口径天生缺角。
_SOURCES = tuple(sorted(set(POSTS) | {"outcome"}))
# 人工改判的合法码与写侧共用一张表：台账早已不止 hit/miss/pending，
# 白名单窄一格，管理员想把误写的 applied 纠成 vetoed 就会被 400 挡回。
_OUTCOMES = tuple(LEDGER_OUTCOME_CODES)

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
    """行 -> dict。台账的时间列是 created_at（float epoch），原样交给前端格式化。"""
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)


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

    **命中率有两把尺子**（v1.2.47）：``hit``/``miss``/``pending`` 是全行
    口径，规则直判、闸门关闭的行也算在里面，量的是这个岗位立项闸整体准不
    准；``hit_judged``/``miss_judged``/``pending_judged`` 只统计真问过判官
    的行，才是判官自己的战绩。plan_gate 实测 111 行里只有 3 行真判，两个
    口径差一个数量级，混着算就是"判官命中率 75%"那种假账。顶层 ``pending``
    汇总块再把待回执分成"合法等回填"与"收口失效"（尺子是
    ledger_contract.PENDING_EXPECTED_SOURCES，写账侧同一个）。

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
    from coapis.decision.gateway import JUDGED_LAYERS
    from coapis.decision.ledger_contract import PENDING_EXPECTED_SOURCES

    judged_set = ",".join(f"'{x}'" for x in JUDGED_LAYERS)
    sql = text(
        "SELECT source, "
        "COUNT(*) AS n, "
        # 真判断次数：规则/闸门/开关关闭这类"压根不需要判"的行不是判断。
        # 混在一起计数会被巡检噪声灌满，看不出判官有没有发生作用。
        f"SUM(CASE WHEN hit_layer IN ({judged_set}) THEN 1 ELSE 0 END) AS judged, "
        "SUM(CASE WHEN hit_layer='llm' THEN 1 ELSE 0 END) AS llm, "
        f"SUM(CASE WHEN hit_layer IN ({degraded}) THEN 1 ELSE 0 END) AS degraded, "
        "SUM(CASE WHEN hit_layer='timeout' THEN 1 ELSE 0 END) AS timeouts, "
        "SUM(CASE WHEN hit_layer='no_model' THEN 1 ELSE 0 END) AS no_model, "
        "ROUND(CAST(AVG(latency_ms) AS NUMERIC), 0) AS avg_ms, "
        "MAX(latency_ms) AS max_ms, "
        "ROUND(CAST(SUM(cost) AS NUMERIC), 4) AS cost, "
        "SUM(tokens) AS tokens, "
        # 两把尺子分开记（v1.2.47）：不带后缀的是全行口径——规则直判的
        # 对错也算进去，量的是"立项闸准不准"；带 judged 后缀的只统计真
        # 问过判官的行，量的才是"判官准不准"。plan_gate 实测 111 行里只有
        # 3 行 hit_layer=llm，两个口径差一个数量级，混在一起算必然错。
        "SUM(CASE WHEN outcome='hit' THEN 1 ELSE 0 END) AS hit, "
        "SUM(CASE WHEN outcome='miss' THEN 1 ELSE 0 END) AS miss, "
        "SUM(CASE WHEN outcome='pending' THEN 1 ELSE 0 END) AS pending, "
        f"SUM(CASE WHEN outcome='hit' AND hit_layer IN ({judged_set}) "
        "THEN 1 ELSE 0 END) AS hit_judged, "
        f"SUM(CASE WHEN outcome='miss' AND hit_layer IN ({judged_set}) "
        "THEN 1 ELSE 0 END) AS miss_judged, "
        f"SUM(CASE WHEN outcome='pending' AND hit_layer IN ({judged_set}) "
        "THEN 1 ELSE 0 END) AS pending_judged "
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
            # 总数 = 台账全部行（含未配置判官的直判行）：D-A 之后 no_model 不算
            # 一次判断，所以"真判次数"另用 by_source.judged 看。把总数收窄成
            # 真判数会让"判断总数"在没配判官时恒为 0，页面看不出系统发生了什么。
            total_n = session.execute(
                text(f"SELECT COUNT(*) FROM decision_events WHERE {clause}"),
                params,
            ).scalar() or 0
    except Exception as exc:  # pragma: no cover
        logger.warning("[Decisions] 统计读取失败: %s", exc)
        return {"days": days, "total": 0, "cost": 0.0, "by_source": [],
                "error": str(exc)}
    # 收场口径（v1.2.47）：只有 PENDING_EXPECTED_SOURCES 里的岗位停在 pending
    # 才算合法（等验收回填）。其余岗位一旦 pending 就是收口失效——v1.2.45
    # 那批"永远 pending"的假账正是这么混进台账的，单列 anomaly 当哨兵，
    # 别让它再藏在总数里。
    expected_sources = sorted(PENDING_EXPECTED_SOURCES)
    pending_total = sum(int(r._mapping.get("pending") or 0) for r in rows)
    pending_expected = sum(
        int(r._mapping.get("pending") or 0)
        for r in rows
        if (r._mapping.get("source") or "") in PENDING_EXPECTED_SOURCES
    )

    return {
        "days": days,
        "total": int(total_n),
        "cost": float(total_cost or 0),
        "by_source": [dict(r._mapping) for r in rows],
        "pending": {
            "total": pending_total,
            "expected": pending_expected,
            "anomaly": pending_total - pending_expected,
            "expected_sources": expected_sources,
        },
    }


@router.get("/judge-health")
def judge_health(
    request: Request,
    days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    """判官健康只读卡（B3 · 收尾方案 v1 §6.1）：供给侧 + 台账侧一屏看穿。

    为什么单独一个端点：判官的问题从来不是"判了几次"，而是"为什么没判"。
    供给侧说"槽位里是谁、它凭什么能判"；台账侧按**弃权原因码**分桶说
    "沉默都为什么沉默"。两者并排，管理员才能一眼看出该配模型、该开闸、
    还是该修上游。只读，不改任何配置。
    """
    me, role = _identity(request)
    from coapis.decision.config import get_hub_config
    from coapis.decision.gateway import JUDGED_LAYERS
    from coapis.decision.judge_reasons import REASON_TEXT, parse_code
    from coapis.decision.resolver import availability_key, judge_capability_ok

    cfg = get_hub_config()
    slot_provider = str(getattr(cfg, "judge_provider_id", "") or "")
    slot_model = str(getattr(cfg, "judge_model", "") or "")

    supply: dict[str, Any] = {
        "slot_provider_id": slot_provider,
        "slot_model": slot_model,
        "availability_key": availability_key(slot_provider, slot_model),
        "capability_dispatch": bool(getattr(cfg, "judge_capability_dispatch", False)),
        "probe_enabled": bool(getattr(cfg, "judge_probe_enabled", False)),
        "min_prompt_tokens": int(getattr(cfg, "judge_min_prompt_tokens", 2048) or 2048),
        "capable": None,
        "capability_reason": "",
        "capability": {},
    }
    if slot_provider and slot_model:
        ok, code = judge_capability_ok(
            slot_provider, slot_model,
            min_prompt_tokens=supply["min_prompt_tokens"],
        )
        supply["capable"] = bool(ok)
        supply["capability_reason"] = "" if ok else code
        try:
            from coapis.providers.provider_manager import ProviderManager

            prov = ProviderManager.get_instance().get_provider(slot_provider)
            if prov is not None:
                supply["capability"] = prov.judge_capability(slot_model)
        except Exception:  # noqa: BLE001 - 读不到底牌不影响卡片出数
            supply["capability"] = {}

    # 台账侧：按弃权原因码分桶（reason 列形状 = [码] 人话）。
    # 码的解析在 SQL 里做（substr+instr），Python 侧再过滤一次形状，
    # 保证"旧账无码行"归入 untagged 而不是消失。
    # “真判”口径 = 判官模型给出结论的两层（llm / llm_session）。
    # 网关里那组 JUDGED_LAYERS 把 timeout/transport/parse 也算成“问过模型”，
    # 那是给 /stats 用的（“问到过”≠“判成了”）；这张卡回答“为什么没判成”，
    # 所以超时/传输/解析失败**都算弃权**，一起进分桶。
    judged_set = "'llm','llm_session'"  # noqa: E501
    where = ["created_at >= (strftime('%s','now') - :win_sec)"]
    params: dict[str, Any] = {"win_sec": int(days) * 86400}
    if role != "admin":
        where.append("user_id = :me")
        params["me"] = me
    clause = " AND ".join(where)
    abstain: list[dict[str, Any]] = []
    total_judged = 0
    total_rows = 0
    try:
        from coapis.foundation.db.engine import get_session

        with get_session() as session:
            rows = session.execute(
                text(
                    "SELECT CASE WHEN substr(reason,1,1)='[' AND instr(reason,']')>2 "
                    "THEN substr(reason, 2, instr(reason,']') - 2) ELSE '' END AS code, "
                    "COUNT(*) AS n "
                    f"FROM decision_events WHERE {clause} "
                    f"AND hit_layer NOT IN ({judged_set}) "
                    "GROUP BY code ORDER BY n DESC"
                ),
                params,
            ).all()
            abstain = [
                {
                    "code": str(r._mapping.get("code") or "") or "untagged",
                    "text": REASON_TEXT.get(str(r._mapping.get("code") or ""), "无原因码（旧账）"),
                    "count": int(r._mapping.get("n") or 0),
                }
                for r in rows
            ]
            total_judged = int(session.execute(
                text(f"SELECT COUNT(*) FROM decision_events WHERE {clause} "
                     f"AND hit_layer IN ({judged_set})"),
                params,
            ).scalar() or 0)
            total_rows = int(session.execute(
                text(f"SELECT COUNT(*) FROM decision_events WHERE {clause}"),
                params,
            ).scalar() or 0)
    except Exception as exc:  # pragma: no cover
        logger.warning("[Decisions] 判官健康读数失败: %s", exc)
        return {"days": days, "supply": supply, "abstain": [],
                "judged": 0, "rows": 0, "error": str(exc)}

    # 原因码必须全部来自码表（判"台账铺码是否完整"用得上）
    known = [a for a in abstain if a["code"] in REASON_TEXT]
    return {
        "days": days,
        "supply": supply,
        "abstain": abstain,
        "judged": total_judged,
        "rows": total_rows,
        "untagged": int(sum(a["count"] for a in abstain if a["code"] == "untagged")),
        "coded_ratio": round(
            sum(a["count"] for a in known) / max(1, total_rows - total_judged), 3,
        ),
    }


@router.post("/{event_id}/rating")
def rate_decision(
    event_id: str,
    request: Request,
    rating: int = Query(..., ge=-1, le=1, description="1 准 / 0 不准 / -1 撤销"),
    outcome: Optional[str] = Query(None, description="outcome 码，见 LEDGER_OUTCOME_CODES"),
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
    # 判断模型的解析唯一归 resolver，且**只认判官槽位**（D-A 2026-11-05 拍板：
    # 判官没配就是没有判官，不借会话激活模型）。面板显示的空判官 = 真实运行
    # 状态：判官此时不上岗，五岗全部按规则直判。
    from coapis.decision.resolver import get_judge_provider_config
    from coapis.decision import get_hub_config

    hub = get_hub_config()
    try:
        slot = get_judge_provider_config(hub, user_id=me, agent_id=agent_id) or {}
    except Exception:  # pragma: no cover - 槽位解析失败时只报配置
        slot = {}
    return {
        # 全字段视图：页面要能看见"当前生效的每一项"，不做单位换算、读写同名
        "config": hub.full_view(),
        # decision_hub：管理端读取的那一节（与落盘段同名，前端只认这一节）
        "decision_hub": hub.full_view(),
        "judge": {
            "provider_id": str(slot.get("provider_id") or ""),
            "model": str(slot.get("model") or ""),
            # 命中层：judge_slot(判官槽位) / decision_slot(模型管理里的决策模型
            # 槽位) / agent_default / global_default。面板写清"当前生效的是谁、
            # 从哪来"，用户就不会拿会话激活模型去猜判官是谁（v16 B7）。
            "source": str(slot.get("source") or ""),
            "configured": bool(slot.get("provider_id") and slot.get("model")),
        },
        "agent_id": agent_id,
        "sources": list(_SOURCES),
    }


@router.put(
    "/config",
    # v19 P2-3 闸门：**六岗配置是治理项，不是人人可改的运行参数**。
    # 原先任何登录用户 POST /decisions/config 都能把判官总开关关掉、把
    # 技能岗位预算改成 1——改的是**整台部署**的判断行为（落盘
    # decision_hub.json 全局生效），却连一次审计都不记。
    # 权限矩阵里 "judge" 模块默认只有 admin 有 audit（模块缺席 = 拒绝，
    # fail-closed），非管理员改配置直接 403，由管理员在权限页显式授权。
    dependencies=[Depends(require_perm("judge:audit"))],
)
def put_config(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """改判官配置：落盘到部署级配置文件（重启后仍生效）并立即生效。

    只认 :mod:`coapis.decision.config` 认识的键，未知键拒收——不再制造
    "配置写了没人读"的死字段（v14 §0.3 的教训）。落盘位置是
    ``WORKING_DIR/config/decision_hub.json`` 单一真相，读取侧
    ``get_hub_config()`` 直接压过环境变量，页面改完下一轮判断就生效。
    """
    from coapis.decision import normalize_hub_keys
    from coapis.decision.config import (
        HUB_KEY_ALIASES,
        POST_KEY_ALIASES,
        DecisionHubConfig,
        save_hub_section,
    )

    known = set(DecisionHubConfig.known_keys())
    body = body or {}
    # 只筛掉不认识的键；键名收敛交给写入侧统一做（别名归一 + 全名落盘），
    # 读取侧与落盘段同名，两处不会各认一套键名。岗位开关走平铺别名
    # （``plan_gate_enabled`` 这类），不在别名表里会被当未知键静默拒收——
    # 页面开关点了等于没点。
    accepted = {
        k: v
        for k, v in body.items()
        if k in known or k in HUB_KEY_ALIASES or k in POST_KEY_ALIASES
    }
    unknown = sorted(set(body) - set(accepted))
    if not accepted:
        raise HTTPException(status_code=400, detail="没有可识别的配置项")
    try:
        cfg = save_hub_section(accepted)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"保存失败: {exc}") from exc
    # checked 回传全字段生效值（越界值已夹取），供前端核对真正生效的每一项
    return {"ok": True, "decision_hub": accepted,
            "ignored": unknown, "checked": cfg.full_view()}


@router.get("/loop-gates")
def loop_gate_stats(
    request: Request,
    days: int = Query(7, ge=1, le=90, description="统计窗口（天）"),
    chat_id: Optional[str] = Query(None, description="按会话过滤"),
    recent_limit: int = Query(20, ge=1, le=200, description="最近触发行数"),
) -> dict[str, Any]:
    """循环闸触发对账：按门分桶 + 白话说明 + 最近触发行。

    数据源是台账岗位 ``loop_gate``。闸码存在 ``payload.purpose`` ——
    ``purpose`` **不是 decision_events 的列**（实测列签名里没有它，
    契约层只能经 payload 把它带进台账），所以这里按行取回、在 Python 侧
    聚合，不写方言相关的 json_extract。

    计数口径：默认每次触发明细一行（``ledger_every`` = 1），
    ``hits`` 就是台账行数本身 = 真实触发次数；若运维把节流粒度调大，
    ``hits`` 会按行数 × 粒度还原，响应里的 ``counting_note`` 会说明。

    十门零值补齐——"从没触发"与"没数据"必须分得开（v15 定下的口径）。
    非管理员只见自己触发的闸（与 /decisions 同口径）。
    """
    from coapis.agents.loop_gates import GATE_CODES, GATE_LABELS, ledger_every

    me, role = _identity(request)
    # created_at 是 epoch 秒（Float 列，实测 dev 库全为 real）。
    # 用 datetime 参数比较=拿数字和文本比，SQLite 里 real 恒小于 text，
    # 窗口过滤会把**全部真实行**筛掉（端点恒 0 行的真因）。
    since = time.time() - float(days) * 86400.0

    sql = (
        "SELECT event_id, created_at, action, reason, chat_id, turn, "
        "user_id FROM decision_events "
        "WHERE source = 'loop_gate' AND created_at >= :since"
    )
    params: dict[str, Any] = {"since": since, "_cap": 5000}
    if role != "admin":
        sql += " AND user_id = :me"
        params["me"] = me
    if chat_id:
        sql += " AND chat_id = :chat_id"
        params["chat_id"] = chat_id
    sql += " ORDER BY created_at DESC, event_id DESC LIMIT :_cap"

    buckets: dict[str, dict[str, Any]] = {
        code: {
            "gate": code,
            "label": GATE_LABELS.get(code, code),
            "rows": 0,
            "hits": 0,
            "actions": {},
            "last_at": None,
        }
        for code in GATE_CODES
    }
    unknown: dict[str, int] = {}
    picked: list[dict[str, Any]] = []
    total_rows = 0

    try:
        from coapis.foundation.db.engine import get_session

        with get_session() as session:
            fetched = session.execute(text(sql), params).all()
    except Exception as exc:  # pragma: no cover - 库坏了不该拖垮前端
        logger.warning("[Decisions] 循环闸台账读取失败: %s", exc)
        return {
            "days": days,
            "gates": list(buckets.values()),
            "total_rows": 0,
            "total_hits": 0,
            "active_gates": 0,
            "unknown_gates": {},
            "recent": [],
            "ledger_every": ledger_every(),
            "enabled": _loop_gate_enabled_flag(),
            "error": str(exc),
        }

    for event_id, created_at, action, reason, cid, turn, uid in fetched:
        total_rows += 1
        gate = _lg_gate_of(reason)
        stamp = _lg_iso(created_at)
        row = {
            "event_id": str(event_id or ""),
            "created_at": stamp,
            "gate": gate,
            "action": str(action or ""),
            "reason": str(reason or ""),
            "chat_id": str(cid or ""),
            "turn": int(turn or 0),
            "user_id": str(uid or ""),
        }
        bucket = buckets.get(gate)
        if bucket is None:
            # 未登记闸码必须显式暴露，不能静默吞掉
            unknown[gate] = unknown.get(gate, 0) + 1
        else:
            bucket["rows"] += 1
            key = str(action or "observe")
            bucket["actions"][key] = int(bucket["actions"].get(key, 0)) + 1
            if stamp and (not bucket["last_at"] or stamp > bucket["last_at"]):
                bucket["last_at"] = stamp
        if len(picked) < recent_limit:
            picked.append(row)

    every = ledger_every()
    gates = sorted(
        buckets.values(),
        key=lambda item: (-int(item["rows"]), str(item["gate"])),
    )
    for item in gates:
        item["hits"] = int(item["rows"]) * every

    return {
        "days": days,
        "gates": gates,
        "total_rows": total_rows,
        "total_hits": total_rows * every,
        "active_gates": sum(1 for g in gates if g["rows"] > 0),
        "unknown_gates": unknown,
        "recent": picked,
        "ledger_every": every,
        "counting_note": (
            "hits = 台账行数 × ledger_every；默认 ledger_every=1，"
            "即 hits 就是真实触发次数"
        ),
        "enabled": _loop_gate_enabled_flag(),
    }


def _lg_gate_of(reason: Any) -> str:
    """闸码取法：读 reason 的 `[闸码]` 前缀（闸链写入时带的格式）。

    台账表没有 purpose/payload 列（`_LEDGER_COLUMNS` 权威清单里没有），
    闸码唯一活着的地方就是 reason 前缀——这是实测后的取舍，不是猜测。
    解析不出前缀返回空串，由端点计入 unknown_gates 显式暴露。
    """
    text_ = str(reason or "").strip()
    if not text_.startswith("["):
        return ""
    end = text_.find("]")
    if end <= 1:
        return ""
    return text_[1:end].strip()


def _lg_iso(value: Any) -> str:
    """时间列统一转 ISO 文本。

    台账的 created_at 是 epoch 秒（Float 列）；历史行里也见过文本时间。
    这里两种都归一成 ISO，页面读到的时间必须可比、可读。
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, float)):
        if value <= 0:
            return ""
        try:
            return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError, TypeError):
            return ""
    return str(value)


def _loop_gate_enabled_flag() -> dict[str, Any]:
    """闸开关与阈值现状（阈值配置化后必须让页面看见当前值）。

    显示的是 :meth:`GateThresholds.effective` 的**生效值**（hub > env > 默认），
    不是纯 env 读数——否则页面报一套、闸里跑另一套，调参时必然对着假数字猜。
    """
    try:
        from coapis.agents.loop_gates import GateThresholds
        from coapis.decision.config import get_hub_config

        cfg = GateThresholds.effective(get_hub_config())
        return {
            "round_budget": int(cfg.round_budget),
            # 旧字段保持布尔语义（页面在用），新字段给出三态档位。
            "stop_phrase": cfg.stop_phrase_mode != "off",
            "stop_phrase_mode": str(cfg.stop_phrase_mode),
            "dedup": int(cfg.exact_dedup),
            "empty_streak": int(cfg.empty_streak),
            "session_warn": int(cfg.session_warn),
            "stagnation_similarity": int(cfg.stagnation_similarity),
            "stagnation_force_exit": int(cfg.stagnation_force_exit),
            "dup_global": int(cfg.dup_global),
            "fail_streak": int(cfg.fail_streak),
            "fail_cooldown_s": int(cfg.fail_cooldown_s),
        }
    except Exception:  # pragma: no cover
        return {}
