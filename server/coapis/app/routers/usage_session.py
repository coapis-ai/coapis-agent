"""会话用量视图（B2 · PRD P0-2）。

背景：旧版只有按天/按 provider 的汇总（/api/token-usage/*），没有会话级视图，
于是"一次会话花了多少、哪一轮花的、第几轮被打断"全都查不到；再叠上 B1 之前的
用量缺失，会话页的成本角标恒为 0。本模块把逐轮台账聚合成会话级视图：只读，
不碰写入侧，不新增页（PRD 定的是接进现有会话资源面板）。

口径：
- 会话主键用台账列 session_id；台账里 chat_id 是"一轮一行"，逐轮明细按它给。
- 用量与金额直接来自 token_usage 逐轮行（B1 起才有真值），金额由 provider
  定价算实；读不到单价记 0 并给理由码。
- 理由码是**读时派生**（表里没有第二套 zero_reason 列，避免第二套真相）：
    usage_missing   —— tokens 与金额全 0：上游没回 usage
    pricing_missing —— 有 tokens 无金额：定价表读不到
  命名与 decision/ledger_contract.py 的 ZERO_* 同源。
- 归属：管理员看全部；普通用户只能看自己的行（台账 user_id/username 两列都认，
  因为历史行里两者都出现过）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text

from ...token_usage.db_writer import _engine
from ..permissions.decorators import require_permission
from .chats import _get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/usage", tags=["Usage"])

# 零成本理由码（与 decision/ledger_contract.py 的 ZERO_* 同源，不另立枚举）
REASON_USAGE_MISSING = "usage_missing"
REASON_PRICING_MISSING = "pricing_missing"


def zero_reason_for(tokens: int, cost_cents: float) -> str | None:
    """零成本理由码（读时派生，见模块 docstring）。"""
    if tokens <= 0 and cost_cents <= 0:
        return REASON_USAGE_MISSING
    if tokens > 0 and cost_cents <= 0:
        return REASON_PRICING_MISSING
    return None


def scope_values(username: str, is_admin: bool) -> tuple[str, ...]:
    """台账归属过滤值；管理员返回空元组表示不限归属。"""
    return () if is_admin else (username,)


def _scalar_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _scalar_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _distinct_csv(value: object) -> list[str]:
    return sorted({p for p in str(value or "").split(",") if p})


@router.get("/by-session/{session_id}")
@require_permission("chat:history")
async def get_usage_by_session(
    request: Request,
    session_id: str,
    chat_id: str | None = Query(
        default=None,
        description="只看某一轮（chat_id）时传入",
    ),
    turns_limit: int = Query(
        default=50,
        ge=1,
        le=500,
        description="逐轮明细最多返回多少条",
    ),
) -> dict:
    """会话级用量视图：总量 + 按轮聚合 + 逐轮明细（含零成本理由码）。"""
    engine = _engine()
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="数据库不可用，用量台账读不到",
        )

    username, is_admin = _get_current_user(request)
    scopes = scope_values(username, is_admin)

    where = ["session_id = :sid"]
    params: dict = {"sid": session_id}
    if scopes:
        where.append("user_id IN :uids")
        params["uids"] = scopes
    if chat_id:
        where.append("chat_id = :cid")
        params["cid"] = chat_id
    clause = " AND ".join(where)

    with engine.connect() as conn:
        agg = conn.execute(
            text(
                "SELECT COUNT(*) AS calls,"
                " COALESCE(SUM(input_tokens),0) AS input_tokens,"
                " COALESCE(SUM(output_tokens),0) AS output_tokens,"
                " COALESCE(SUM(total_tokens),0) AS total_tokens,"
                " COALESCE(SUM(cost_cents),0) AS cost_cents,"
                " COALESCE(SUM(CASE WHEN stream_interrupted = 1 THEN 1 ELSE 0 END),0)"
                " AS interrupted_turns,"
                " COALESCE(SUM(CASE WHEN total_tokens > 0 THEN 1 ELSE 0 END),0)"
                " AS calls_with_usage,"
                " COALESCE(SUM(CASE WHEN COALESCE(latency_ms,0) > 0 THEN 1 ELSE 0 END),0)"
                " AS calls_with_latency,"
                " MIN(created_at) AS first_at, MAX(created_at) AS last_at"
                f" FROM token_usage WHERE {clause}",
            ),
            params,
        ).mappings().first()

        by_chat_rows = conn.execute(
            text(
                "SELECT chat_id,"
                " COUNT(*) AS turns,"
                " COALESCE(SUM(input_tokens),0) AS input_tokens,"
                " COALESCE(SUM(output_tokens),0) AS output_tokens,"
                " COALESCE(SUM(total_tokens),0) AS total_tokens,"
                " COALESCE(SUM(cost_cents),0) AS cost_cents,"
                " COALESCE(SUM(CASE WHEN stream_interrupted = 1 THEN 1 ELSE 0 END),0)"
                " AS interrupted,"
                " GROUP_CONCAT(DISTINCT provider_id) AS providers,"
                " GROUP_CONCAT(DISTINCT model) AS models,"
                " MIN(created_at) AS first_at, MAX(created_at) AS last_at"
                f" FROM token_usage WHERE {clause}"
                " GROUP BY chat_id ORDER BY MAX(created_at) DESC",
            ),
            params,
        ).mappings().all()

        turn_rows = conn.execute(
            text(
                "SELECT turn_index, chat_id, api_call_id, provider_id, model,"
                " input_tokens, output_tokens, total_tokens, cost_cents,"
                " latency_ms, stream_interrupted, created_at"
                f" FROM token_usage WHERE {clause}"
                " ORDER BY created_at DESC LIMIT :lim",
            ),
            {**params, "lim": int(turns_limit)},
        ).mappings().all()

    total_tokens = _scalar_int((agg or {}).get("total_tokens"))
    total_cost = _scalar_float((agg or {}).get("cost_cents"))

    by_chat = []
    for row in by_chat_rows:
        tokens = _scalar_int(row["total_tokens"])
        cost = _scalar_float(row["cost_cents"])
        by_chat.append(
            {
                "chat_id": row["chat_id"],
                "turns": _scalar_int(row["turns"]),
                "input_tokens": _scalar_int(row["input_tokens"]),
                "output_tokens": _scalar_int(row["output_tokens"]),
                "total_tokens": tokens,
                "cost_cents": cost,
                "interrupted_turns": _scalar_int(row["interrupted"]),
                "providers": _distinct_csv(row["providers"]),
                "models": _distinct_csv(row["models"]),
                "zero_cost_reason": zero_reason_for(tokens, cost),
                "first_at": row["first_at"],
                "last_at": row["last_at"],
            },
        )

    turns = [
        {
            "turn_index": r["turn_index"],
            "chat_id": r["chat_id"],
            "api_call_id": r["api_call_id"],
            "provider_id": r["provider_id"],
            "model": r["model"],
            "input_tokens": _scalar_int(r["input_tokens"]),
            "output_tokens": _scalar_int(r["output_tokens"]),
            "total_tokens": _scalar_int(r["total_tokens"]),
            "cost_cents": _scalar_float(r["cost_cents"]),
            "latency_ms": r["latency_ms"],
            "stream_interrupted": (
                bool(r["stream_interrupted"])
                if r["stream_interrupted"] is not None
                else None
            ),
            "zero_cost_reason": zero_reason_for(
                _scalar_int(r["total_tokens"]),
                _scalar_float(r["cost_cents"]),
            ),
            "created_at": r["created_at"],
        }
        for r in turn_rows
    ]

    return {
        "session_id": session_id,
        "scoped_admin": bool(is_admin),
        "totals": {
            "calls": _scalar_int((agg or {}).get("calls")),
            "input_tokens": _scalar_int((agg or {}).get("input_tokens")),
            "output_tokens": _scalar_int((agg or {}).get("output_tokens")),
            "total_tokens": total_tokens,
            "cost_cents": total_cost,
            "interrupted_turns": _scalar_int((agg or {}).get("interrupted_turns")),
            "calls_with_usage": _scalar_int((agg or {}).get("calls_with_usage")),
            "calls_with_latency": _scalar_int(
                (agg or {}).get("calls_with_latency"),
            ),
            "zero_cost_reason": zero_reason_for(total_tokens, total_cost),
            "first_at": (agg or {}).get("first_at"),
            "last_at": (agg or {}).get("last_at"),
        },
        "by_chat": by_chat,
        "turns": turns,
    }
