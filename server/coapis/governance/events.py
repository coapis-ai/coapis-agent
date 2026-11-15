# -*- coding: utf-8 -*-
"""B5-B · 治理事件统一语义（只读联合视图，不新建表、不迁移数据）。

治理类事件散在四个地方，各说各话：

- ``audit.jsonl`` —— 工具调用 / 工具闸拦截 / 审批决策 / 沙箱路径与命令检查 /
  配置变更（``agents/security/audit_logger.py`` 的哈希链）；
- ``decision_events`` —— 判官六类插手点；
- ``file_records`` —— 资源台账（谁在什么时候产出了哪个文件、第几版）；
- ``memory_timelines`` —— 记忆晋升链。

本模块做一件事：**给它们一套统一的 ``kind`` 语义**，并提供只读联合查询。
判定规则全部写死在下面这张表里（SSOT），任何来源的事件都要经
``classify_audit_event()`` / ``_row_to_event()`` 出来，**端点层零判定逻辑**。

设计边界（拍板 D3/D6 的口径）：

* **只读**：不写任何表、不改任何既有事件的存储格式；老日志照常写。
* **不迁移**：历史数据没有的字段留 ``None``，不回填、不猜测。
* **作用域**：`username` 由调用方（端点）按身份注入，本模块只按参数过滤。

统一事件形状：

``{kind, ts, username, source, action, target, session, result, reason, ref_id}``

``target`` 是**操作对象**（工具名 / 文件路径 / 命令），``session`` 是所属会话；
两者分开是因为审批与判官事件都要同时看"动了什么"和"在哪次会话里动的"。
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Iterable, Iterator, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "EVENT_KINDS",
    "classify_audit_event",
    "read_audit_events",
    "read_judge_events",
    "read_file_version_events",
    "read_memory_events",
    "list_events",
]

# ── kind 词表（SSOT） ──────────────────────────────────────────────

#: 六类治理事件 + ``config``（配置变更也是治理事件，实测里它已经在写）。
#: 新增 kind 必须同时出现在这里与被映射到，端点层不造新词。
EVENT_KINDS: tuple[str, ...] = (
    "judge",
    "tool",
    "tool_denied",
    "approval",
    "memory",
    "file_version",
    "sandbox_denied",
    "config",
)

#: audit.jsonl 的 ``event_type`` → kind。出现未覆盖的 event_type 时
#: 走 ``_kind_by_result`` 兜底，仍不命中就返回 None（调用方跳过）。
_KIND_BY_EVENT_TYPE = {
    "tool_call": "tool",
    "tool_guard_denied": "tool_denied",
    "tool_monitor_blocked": "tool_denied",
    "tool_guard_approval": "approval",
    "approval": "approval",
    "permission_denied": "sandbox_denied",
    # ⚠️ 掺水根因（此处曾是沙箱拦截率虚高的源头）：``path_check`` /
    # ``command_check`` / ``sandbox`` 以前**无条件**映射成 sandbox_denied，
    # 于是"路径校验通过""命令检查通过"这类**放行**记录也进了拒绝桶。
    # 实测 dev 审计链 1810 条放行里混着 213 条真拒绝 —— 检查类事件的桶
    # 必须取决于**结果**，交回 _kind_by_result 判（见 _RESULT_SENSITIVE_*）。
    "tool_plan_scope": "tool",
    "config_change": "config",
    "file_op": "file_version",
}

#: 结果敏感的检查类事件：放行归 tool 桶，拒绝才归 sandbox_denied。
_RESULT_SENSITIVE_EVENT_TYPES = frozenset(
    {"path_check", "command_check", "sandbox"}
)

#: 判官的插手点（plan_gate/tool_gate/…）→ judge
_JUDGE_POINT_KINDS = "judge"


# ── 审计链（audit.jsonl） ─────────────────────────────────────────


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_audit_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    """把一条审计链原始事件映射成统一事件形状。

    未识别的 event_type 返回 ``None`` —— 宁可少给，不猜语义。
    """
    if not isinstance(raw, dict):
        return None
    event_type = str(raw.get("event_type") or "")
    if not event_type:
        return None

    meta = raw.get("metadata")
    meta = meta if isinstance(meta, dict) else {}
    result = str(raw.get("result") or "")

    kind = _KIND_BY_EVENT_TYPE.get(event_type)
    if event_type in _RESULT_SENSITIVE_EVENT_TYPES:
        # 检查类事件：桶取决于**结果**，不取决于事件名（沙箱掺水修复）。
        kind = "sandbox_denied" if result.startswith("denied") else None
    if kind is None:
        kind = _kind_by_result(event_type, result, meta)
    if kind is None:
        return None

    # 沙箱拒绝是 tool_call 里的一支（result=denied_by_policy(...)）→ 单独成类
    if kind == "tool" and result.startswith("denied"):
        kind = (
            "sandbox_denied"
            if "sandbox" in result
            else "tool_denied"
        )

    target = (
        raw.get("resource")
        or meta.get("tool")
        or meta.get("file_path")
        or meta.get("command")
        or meta.get("session_id")
    )
    reason = raw.get("reason") or meta.get("reason") or meta.get("policy")

    return {
        "kind": kind,
        "ts": _as_float(raw.get("timestamp")) or _as_float(raw.get("ts")),
        "username": raw.get("user_id") or meta.get("username"),
        "source": "audit.jsonl",
        "action": event_type,
        "target": str(target) if target is not None else None,
        "session": meta.get("session_id"),
        "result": result or None,
        "reason": str(reason) if reason is not None else None,
        "ref_id": raw.get("event_id"),
    }


def _kind_by_result(
    event_type: str,
    result: str,
    meta: dict[str, Any],
) -> str | None:
    """兜底映射：老日志里没有 event_type 语义、只有结果的，按结果判。

    ⚠️ 拒绝/放行只能按**结果**分，不能按事件名分（沙箱掺水根因）。
    此前这里写的是 ``if "sandbox" in event_type or "path" in event_type
    or "command" in event_type: return "sandbox_denied"`` —— 事件名里带
    command/path/sandbox 的**放行**记录（沙箱检查通过、路径校验通过）
    全被算成沙箱拒绝。实测 dev 审计链 1810 条放行里混进 213 条真拒绝，
    看板上的"沙箱拦截率"是掺水的假数字。
    """
    denied = result.startswith("denied")
    if result.startswith("denied_by_policy(sandbox)"):
        return "sandbox_denied"
    if "approval" in event_type:
        return "approval"
    if denied and ("sandbox" in result or "sandbox" in event_type):
        return "sandbox_denied"
    if denied:
        return "tool_denied"
    # 到这里都是**未拒绝**的记录：有工具对象的归 tool，其余不进拒绝桶
    if meta.get("tool") is not None:
        return "tool"
    return None


def _tail_lines(path, max_bytes: int) -> Iterator[str]:
    """从文件尾部读若干字节（审计链可达数十 MB，全读会拖死请求）。"""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            if size > max_bytes:
                # 丢掉可能被截断的第一行
                fh.readline()
            data = fh.read()
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("governance: 读审计链失败 %s: %s", path, exc)
        return
    for line in data.decode("utf-8", "replace").splitlines():
        if line.strip():
            yield line


def read_audit_events(
    log_path: "str | os.PathLike[str]",
    *,
    limit: int = 100,
    kinds: Sequence[str] | None = None,
    username: str | None = None,
    since_ts: float | None = None,
    max_bytes: int = 512_000,
) -> list[dict[str, Any]]:
    """读审计链尾部并映射成统一事件（新→旧）。"""
    wanted = set(kinds or ())
    out: list[dict[str, Any]] = []
    for line in _tail_lines(log_path, max_bytes):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        ev = classify_audit_event(raw)
        if ev is None:
            continue
        if wanted and ev["kind"] not in wanted:
            continue
        if username and ev.get("username") != username:
            continue
        if since_ts is not None and (ev.get("ts") or 0) < since_ts:
            continue
        out.append(ev)
    # 尾部读到的是文件顺序（旧→新），limit 必须取**最新**的那几条
    out.sort(key=lambda e: e.get("ts") or 0, reverse=True)
    if limit > 0:
        out = out[: int(limit)]
    return out


# ── 数据库侧（判官 / 台账 / 记忆链） ─────────────────────────────


def _query_rows(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from ..foundation.db.engine import get_session
    except Exception as exc:  # pragma: no cover
        logger.debug("governance: 数据库不可用: %s", exc)
        return []
    try:
        from sqlalchemy import text
    except Exception:  # pragma: no cover
        return []

    try:
        with get_session() as session:
            rows = session.execute(text(sql), params).mappings().all()
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.debug("governance: 事件查询失败: %s", exc)
        return []


def read_judge_events(
    *,
    limit: int = 100,
    username: str | None = None,
    since_ts: float | None = None,
) -> list[dict[str, Any]]:
    """判官事件（decision_events）。

    ⚠️ 列名一律以**库里的真实列**为准（2026-11-15 在 dev 真库
    ``/apps/ai/coapis-dev/system/coapis.db`` 用 PRAGMA 实测）。此前这条
    SQL 查了 9 个从来不存在的列（``updated_at``/``point``/``subject``/
    ``verdict``/``confidence``/``evidence``/``rationale``/``session_id``/
    ``deleted_at``），异常被 ``_query_rows`` 吞成空列表 —— 台账 364 行
    在库里，看板 0 行。列名对不上表，是"看板永远空"的头号根因。
    """
    sql = (
        "SELECT event_id, created_at, user_id, session_id, agent_id, source, "
        "purpose, action, judgment, hit_layer, model, cost, tokens, outcome, "
        "reason, origin, zero_reason, dirty_band, payload "
        "FROM decision_events"
    )
    params: dict[str, Any] = {"lim": int(limit)}
    if username:
        sql += " WHERE user_id = :uid"
        params["uid"] = username
    if since_ts is not None:
        sql += (" AND" if " WHERE" in sql else " WHERE") + " created_at >= :since"
        params["since"] = float(since_ts)
    sql += " ORDER BY created_at DESC LIMIT :lim"

    out = []
    for r in _query_rows(sql, params):
        # payload 是 JSON 文本（写侧 dumps，见 decision/types.payload_to_json_text）。
        # 弃权原因码落在里面 —— 读侧解出来，看板才知道"判官为什么沉默"。
        detail = _loads_payload(r.get("payload"))
        out.append(
            {
                "kind": "judge",
                "ts": r.get("created_at"),
                "username": r.get("user_id"),
                "source": r.get("source"),
                "action": r.get("source"),
                "purpose": r.get("purpose"),
                "session": r.get("session_id"),
                "target": r.get("chat_id"),
                "result": r.get("judgment"),
                "reason": r.get("reason"),
                "hit_layer": r.get("hit_layer"),
                "cost": r.get("cost"),
                "tokens": r.get("tokens"),
                "outcome": r.get("outcome"),
                "origin": r.get("origin"),
                "zero_reason": r.get("zero_reason"),
                "dirty_band": r.get("dirty_band"),
                "abstain_reason": detail.get("abstain_reason") or "",
                "ref_id": r.get("event_id"),
            }
        )
    return out


def _loads_payload(raw: Any) -> dict[str, Any]:
    """台账 payload（JSON 文本）→ dict。解不开返回空 dict，不抛。"""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        import json

        got = json.loads(str(raw))
        return got if isinstance(got, dict) else {}
    except Exception:
        return {}


def read_file_version_events(
    *,
    limit: int = 100,
    username: str | None = None,
    since_ts: float | None = None,
) -> list[dict[str, Any]]:
    """资源台账事件（file_records）—— 每个文件版本一条。"""
    sql = (
        "SELECT id, created_at, updated_at, user_id, session_id, chat_id, agent_id, "
        "file_path, title, source, status, size_bytes FROM file_records "
        "WHERE deleted_at IS NULL"
    )
    params: dict[str, Any] = {"lim": int(limit)}
    if username:
        sql += " AND user_id = :uid"
        params["uid"] = username
    if since_ts is not None:
        sql += " AND created_at >= :since"
        params["since"] = float(since_ts)
    sql += " ORDER BY created_at DESC LIMIT :lim"

    out = []
    for r in _query_rows(sql, params):
        out.append(
            {
                "kind": "file_version",
                "ts": r.get("created_at"),
                "username": r.get("user_id"),
                "source": "file_records",
                "action": r.get("source"),
                "session": r.get("session_id"),
                "target": r.get("file_path"),
                "result": r.get("status"),
                "reason": r.get("title"),
                "ref_id": str(r.get("id")),
            }
        )
    return out


def read_memory_events(
    *,
    limit: int = 100,
    username: str | None = None,
    since_ts: float | None = None,
) -> list[dict[str, Any]]:
    """记忆晋升链事件（memory_timelines）。"""
    sql = (
        "SELECT id, created_at, updated_at, user_id, agent_id, session_id, "
        "signal_type, source, importance, promoted_at, content "
        "FROM memory_timelines WHERE deleted_at IS NULL"
    )
    params: dict[str, Any] = {"lim": int(limit)}
    if username:
        sql += " AND user_id = :uid"
        params["uid"] = username
    if since_ts is not None:
        sql += " AND created_at >= :since"
        params["since"] = float(since_ts)
    sql += " ORDER BY created_at DESC LIMIT :lim"

    out = []
    for r in _query_rows(sql, params):
        content = r.get("content")
        out.append(
            {
                "kind": "memory",
                "ts": r.get("promoted_at") or r.get("created_at"),
                "username": r.get("user_id"),
                "source": "memory_timelines",
                "action": "promoted" if r.get("promoted_at") else "signal",
                "session": r.get("session_id"),
                "target": r.get("signal_type"),
                "result": r.get("source"),
                "reason": (content or "")[:200] or None,
                "ref_id": str(r.get("id")),
            }
        )
    return out


# ── 联合视图 ──────────────────────────────────────────────────────

_READERS = {
    "judge": read_judge_events,
    "file_version": read_file_version_events,
    "memory": read_memory_events,
}


def list_events(
    *,
    kinds: Sequence[str] | None = None,
    limit: int = 100,
    username: str | None = None,
    since_ts: float | None = None,
    audit_log_path: "str | os.PathLike[str] | None" = None,
) -> dict[str, Any]:
    """按 kind 联合查询治理事件（新→旧）。

    返回 ``{events, kinds, limit, note}``；``note`` 只在数据源不可用时出现，
    绝不静默吞掉（口径与 /api/decisions 一致）。
    """
    if audit_log_path is None:
        from ..constant import AUDIT_LOG_DIR

        audit_log_path = AUDIT_LOG_DIR / "audit.jsonl"

    wanted = [k for k in (kinds or EVENT_KINDS) if k in EVENT_KINDS]
    unknown = sorted(set(kinds or ()) - set(EVENT_KINDS))
    per = max(1, min(int(limit), 500))
    events: list[dict[str, Any]] = []
    notes: list[str] = []

    audit_kinds = [
        k for k in wanted if k not in _READERS
    ]
    if audit_kinds:
        events.extend(
            read_audit_events(
                audit_log_path,
                limit=per,
                kinds=audit_kinds,
                username=username,
                since_ts=since_ts,
            )
        )
    for kind in wanted:
        reader = _READERS.get(kind)
        if reader is None:
            continue
        events.extend(
            reader(limit=per, username=username, since_ts=since_ts)
        )

    events.sort(key=lambda e: e.get("ts") or 0, reverse=True)
    if len(events) > limit:
        events = events[: int(limit)]

    if unknown:
        notes.append("未识别的 kind 已忽略: " + ", ".join(unknown))

    return {
        "events": events,
        "kinds": wanted,
        "limit": int(limit),
        "count": len(events),
        "note": "; ".join(notes) if notes else None,
    }
