# -*- coding: utf-8 -*-
"""审批意图台账写入/读取（B2 · 方案 v1 §4 验收 5）。

队列回答"现在要不要批"，本模块回答"批过什么、谁批的、怎么收的场"。

红线（与台账写入契约同一纪律）：
* **旁路** —— ``record_intent`` 永不抛异常、永不阻塞审批主链；写失败只
  debug 日志。审批是用户等着的东西，台账是事后复盘的东西，谁也不能让
  用户等一次数据库故障。
* **一行到底** —— 入队写一行，裁决**更新**同一行（不追加），于是
  "入队了几张卡 / 收场了几张卡 / 超时几张"三个数天然对得上。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: ``why`` 列长度上限（列约定 500，与判官原因码同尺子）。
_WHY_MAX = 500


def _row_to_dict(row: Any) -> dict[str, Any]:
    try:
        return row.to_dict()
    except Exception:  # pragma: no cover - defensive
        return {}


def record_intent(
    pending: Any,
    *,
    decision: str = "",
    outcome: str = "",
    decided_by: str = "",
    decide_source: str = "",
    why: str = "",
) -> bool:
    """入队登记（``decision``/``outcome`` 留空）或收场落账（覆盖同一行）。

    ``decision`` = 用户做了什么动作；``outcome`` = 系统是否采纳。两件事
    分列是刻意的：身份校验拒绝的未遂选择，此前只能记成"用户拒绝"，
    而用户明明点了批准 —— 台账不能歪曲用户行为。

    永不抛异常；返回是否入账。
    """
    try:
        from ...foundation.db import get_session
        from ...foundation.db.models.approval import (
            VALID_DECIDE_SOURCES,
            VALID_INTENT_DECISIONS,
            ApprovalIntent,
        )

        request_id = str(getattr(pending, "request_id", "") or "")
        if not request_id:
            return False
        # 词表自检：越界的裁决值照写，但留痕（读侧会看到它，比静默丢弃好查）
        if decision and decision not in VALID_INTENT_DECISIONS:
            logger.warning(
                "intent ledger: 未知裁决值 %s（request_id=%s）",
                decision,
                request_id,
            )
        if decide_source and decide_source not in VALID_DECIDE_SOURCES:
            logger.debug(
                "intent ledger: 未知收场通道 %s（request_id=%s）",
                decide_source,
                request_id,
            )
        now = _now()
        with get_session() as s:
            row = s.get(ApprovalIntent, request_id)
            if row is None:
                row = ApprovalIntent(request_id=request_id)
                s.add(row)
            # 身份字段：入队时写死，裁决时不覆盖（收场不能改写请求的归属）
            if not row.created_at:
                row.session_id = str(getattr(pending, "session_id", "") or "")
                row.root_session_id = str(
                    getattr(pending, "root_session_id", "") or ""
                )
                row.user_id = str(getattr(pending, "user_id", "") or "")
                row.agent_id = str(getattr(pending, "agent_id", "") or "")
                row.channel = str(getattr(pending, "channel", "") or "")
                row.tool_name = str(getattr(pending, "tool_name", "") or "")
                row.severity = str(getattr(pending, "severity", "") or "")
                row.findings_count = int(
                    getattr(pending, "findings_count", 0) or 0
                )
                row.timeout_seconds = float(
                    getattr(pending, "timeout_seconds", 0.0) or 0.0
                )
                row.created_at = float(
                    getattr(pending, "created_at", 0.0) or now
                )
            if decision or outcome:
                if decision:
                    row.decision = decision
                row.outcome = str(outcome or "")
                row.decided_by = str(decided_by or "")
                row.decide_source = str(decide_source or "")
                row.why = (str(why or "")[:_WHY_MAX] or None)
                row.resolved_at = now
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("intent ledger write failed (ignored): %s", exc)
        return False


def list_intent_rows(
    session_id: str = "",
    *,
    user_id: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """已收场的审批意图（按会话/用户筛），最新的在前。

    只返回**已裁决**的行 —— 还在队列里等的行 decision 为空，不算意图。
    """
    return _query(session_id=session_id, user_id=user_id, limit=limit)


def list_timeout_rows(
    session_id: str = "",
    *,
    user_id: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """超时默认拒绝的审批（可统计、可追溯）。"""
    return _query(
        session_id=session_id,
        user_id=user_id,
        decision="timed_out",
        limit=limit,
    )


def intent_stats(
    *,
    since: float = 0.0,
    origin_not_test: bool = False,
) -> dict[str, Any]:
    """裁决分布计数（看板用；口径 = 已收场的行）。"""
    try:
        from sqlalchemy import func, select

        from ...foundation.db import get_session
        from ...foundation.db.models.approval import ApprovalIntent

        with get_session() as s:
            stmt = select(
                ApprovalIntent.decision,
                func.count(ApprovalIntent.request_id),
            ).group_by(ApprovalIntent.decision)
            if since > 0:
                stmt = stmt.where(ApprovalIntent.created_at >= since)
            rows = s.execute(stmt).all()
        out: dict[str, Any] = {
            "total": 0,
            "approved": 0,
            "denied": 0,
            "timed_out": 0,
            "system_cancelled": 0,
            "pending": 0,
            "by_source": {},
        }
        for decision, count in rows:
            out["total"] += int(count)
            key = str(decision or "")
            if key in out:
                out[key] += int(count)
            else:
                # 未登记的裁决值单独成桶，不掺进已知桶
                out.setdefault("unknown", 0)
                out["unknown"] += int(count)
        src_stmt = select(
            ApprovalIntent.decide_source,
            func.count(ApprovalIntent.request_id),
        ).where(ApprovalIntent.outcome != "")
        if since > 0:
            src_stmt = src_stmt.where(ApprovalIntent.created_at >= since)
        with get_session() as s:
            for src, count in s.execute(src_stmt.group_by(
                ApprovalIntent.decide_source
            )).all():
                out["by_source"][str(src or "unknown")] = int(count)
        return out
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("intent ledger stats failed (ignored): %s", exc)
        return {"total": 0, "error": "ledger_unavailable"}


def _query(
    *,
    session_id: str = "",
    user_id: str = "",
    decision: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    try:
        from sqlalchemy import select

        from ...foundation.db import get_session
        from ...foundation.db.models.approval import ApprovalIntent

        # "已收场" = outcome 非空（不是 decision 非空 —— 未遂选择也是收场，
        # 它的 decision 是用户的动作，outcome 是 refused:*）
        stmt = select(ApprovalIntent).where(ApprovalIntent.outcome != "")
        if session_id:
            stmt = stmt.where(ApprovalIntent.session_id == session_id)
        if user_id:
            stmt = stmt.where(ApprovalIntent.user_id == user_id)
        if decision is not None:
            stmt = stmt.where(ApprovalIntent.decision == decision)
        stmt = stmt.order_by(ApprovalIntent.created_at.desc()).limit(
            max(1, int(limit))
        )
        with get_session() as s:
            return [_row_to_dict(r) for r in s.execute(stmt).scalars().all()]
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("intent ledger query failed (ignored): %s", exc)
        return []


def sweep_orphaned_intents(grace_seconds: float = 90.0) -> int:
    """把上一辈子进程留下的未收场行收场掉（返回收场条数）。

    审批的 future 只活在进程内存里：进程一重启，DB 里那条 pending 行
    就永远不会有人再写它 —— 读侧会看到"还没收场"的僵尸行，统计超时率
    也被它压低。这里在维护循环里扫一次：``outcome`` 为空且早于 grace 的
    行，按超时收场，``decide_source`` 标 ``maintenance`` 以便和真实的
    用户超时区分开。

    grace（默认 90s）是为了不误伤本辈子刚入队、还在等人裁决的行。
    永不抛异常；失败返回 0。
    """
    try:
        from sqlalchemy import select

        from ...foundation.db import get_session
        from ...foundation.db.models.approval import ApprovalIntent

        now = _now()
        cutoff = now - max(0.0, float(grace_seconds))
        with get_session() as s:
            rows = s.execute(
                select(ApprovalIntent)
                .where(ApprovalIntent.outcome == "")
                .where(ApprovalIntent.created_at < cutoff)
            ).scalars().all()
            for row in rows:
                row.decision = "timed_out"
                row.outcome = "auto:abandoned_at_startup"
                row.decide_source = "maintenance"
                row.why = "进程重启后无人收场，由维护清扫按超时收场"
                row.resolved_at = now
            count = len(rows)
        if count:
            logger.info("intent ledger: 清扫未收场行 %d 条", count)
        return count
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("intent ledger sweep failed (ignored): %s", exc)
        return 0


def _now() -> float:
    import time

    return time.time()


__all__ = [
    "intent_stats",
    "list_intent_rows",
    "list_timeout_rows",
    "record_intent",
    "sweep_orphaned_intents",
]
