"""上下文消费对账 —— 只读聚合层（B4c 治理可读层）。

定位（2026-11-15 拍板）：这是**只读**的治理可读层，不写盘、不新增表、不做迁移、
不参与任何热路径。它做两件别人做不了的事：

1. **台账 → 窗口利用率**：从 ``token_usage`` 真实表按会话聚合「每次调用吃进多少
   input token / 模型窗口多大 / 峰值与均值利用率」，出数交给
   :func:`coapis.governance.context_recon.summarize_usage`（尺子是父代理写的，
   这里不造第二把）。窗口大小**只从 provider 注册表自报值取**
   （:func:`coapis.agents.context.window_source.reported_window_for_model_name`），
   取不到就明确标注「窗口未知，利用率不可计算」——**绝不编一个窗口值**。

2. **压缩预览**：拿现成计量层 :func:`~measure_prompt` +
   :func:`~trim_messages_to_budget` 对某个会话做**纯计算**，回答「按当前档位目标，
   计划丢几条、留几条、压完剩多少 token」。预览**不落盘**，并自带自证字段
   （调用前后台账行数 / 会话目录文件清单与内容哈希逐项相等 + ``writes_performed: 0``）。

时间口径（铁律）：台账里的 ``created_at`` 是 **Float epoch 秒**，过滤一律用 epoch
浮点比较。SQLite 里 real 恒小于 text，用 datetime 参数会把全部真实行筛掉。
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_DAYS",
    "DEFAULT_LIMIT",
    "DEFAULT_RATIO",
    "LEDGER_TABLES",
    "MAX_DAYS",
    "MAX_LIMIT",
    "attach_windows",
    "cutoff_epoch",
    "find_session_state",
    "fingerprint_dir",
    "latest_model_for_session",
    "ledger_counts",
    "preview_compaction",
    "session_messages",
    "session_windows",
    "usage_report",
    "usage_rows",
    "window_lookup_for",
]

#: 台账查询默认回看天数（和 decisions.py 的口径一致）
DEFAULT_DAYS = 7
#: 回看天数上限：一年内的账有意义，更远的应去查归档而不是这个端点
MAX_DAYS = 365
#: 明细行数上限。逐行拉账是重读操作，不放开到无界
DEFAULT_LIMIT = 500
MAX_LIMIT = 2000
#: 压缩触发阈值兜底值。运行配置里 compact_threshold_ratio 的默认值就是 0.8
#: （见 react_agent.py:868 / agents/core.py:202 的取法），取不到配置时用它
DEFAULT_RATIO = 0.8

#: 自证用的台账/用量相关表（只 COUNT，不写）
LEDGER_TABLES = ("token_usage", "decision_events")


# ---------------------------------------------------------------------------
# 时间口径
# ---------------------------------------------------------------------------


def cutoff_epoch(days: int, *, now: float | None = None) -> float:
    """把「回看 N 天」换算成 epoch 秒下界。

    台账的 ``created_at`` 是 Float epoch 秒，过滤必须用 epoch 比较；
    传 datetime 进 SQLite 会让 real 列恒小于 text 参数，把全部真实行筛掉。
    """
    base = time.time() if now is None else float(now)
    return base - float(days) * 86400.0


# ---------------------------------------------------------------------------
# 台账读取
# ---------------------------------------------------------------------------


def usage_rows(
    days: int = DEFAULT_DAYS,
    limit: int = DEFAULT_LIMIT,
    *,
    user_id: str | None = None,
    now: float | None = None,
    engine: Any = None,
) -> list[dict]:
    """从 ``token_usage`` 真实表读最近若干行的账（只读）。

    列名全部来自 :class:`coapis.foundation.db.models.usage.TokenUsage`，
    不引入任何幽灵列。``user_id`` 给定时按登录名收窄（非管理员只能看自己）。

    Returns:
        行字典列表，按 ``created_at`` 倒序。引擎未初始化时返回空列表。
    """
    from sqlalchemy import text

    from ..foundation.db.engine import get_engine

    eng = engine if engine is not None else get_engine()
    if eng is None:
        return []

    cut = cutoff_epoch(days, now=now)
    # 上界留 1 小时余量：多实例时钟偏移不该把刚写完的账筛掉
    upper = (time.time() if now is None else float(now)) + 3600.0
    params: dict[str, Any] = {"cut": cut, "upper": upper, "lim": int(limit)}

    sql = (
        "SELECT id, user_id, username, agent_id, model, provider_id,"
        " input_tokens, output_tokens, total_tokens, cost_cents,"
        " created_at, session_id, chat_id, turn_index, latency_ms,"
        " stream_interrupted"
        " FROM token_usage"
        " WHERE created_at IS NOT NULL"
        " AND created_at >= :cut AND created_at <= :upper"
    )
    if user_id is not None:
        sql += " AND user_id = :uid"
        params["uid"] = str(user_id)
    sql += " ORDER BY created_at DESC LIMIT :lim"

    try:
        with eng.connect() as conn:
            rows = [dict(r) for r in conn.execute(text(sql), params).mappings()]
    except Exception:
        logger.warning("context_usage: 台账读取失败（按空账处理）", exc_info=True)
        return []
    return rows


def ledger_counts(engine: Any = None) -> dict[str, int]:
    """台账/用量相关表的行数快照（dry_run 自证用，只 COUNT）。"""
    from sqlalchemy import text

    from ..foundation.db.engine import get_engine

    eng = engine if engine is not None else get_engine()
    out: dict[str, int] = {}
    if eng is None:
        return {name: -1 for name in LEDGER_TABLES}
    for name in LEDGER_TABLES:
        try:
            with eng.connect() as conn:
                out[name] = int(
                    conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar() or 0,
                )
        except Exception:  # noqa: BLE001
            out[name] = -1
    return out


def latest_model_for_session(
    session_id: str,
    *,
    user_id: str | None = None,
    engine: Any = None,
) -> dict[str, Any]:
    """取某会话最近一次调用用的模型与 provider（窗口自报值的查询键）。

    没有账时返回 ``{"model": None, ...}`` —— 让调用方明确知道「模型未知」，
    而不是拿一个默认模型假装算得出。
    """
    from sqlalchemy import text

    from ..foundation.db.engine import get_engine

    eng = engine if engine is not None else get_engine()
    if eng is None or not session_id:
        return {"model": None, "provider_id": None, "source": "no_ledger"}
    params: dict[str, Any] = {"sid": str(session_id)}
    sql = (
        "SELECT model, provider_id, created_at FROM token_usage"
        " WHERE session_id = :sid AND model IS NOT NULL"
        " ORDER BY created_at DESC LIMIT 1"
    )
    if user_id is not None:
        sql += " AND user_id = :uid"
        params["uid"] = str(user_id)
    try:
        with eng.connect() as conn:
            row = conn.execute(text(sql), params).mappings().first()
    except Exception:  # noqa: BLE001
        return {"model": None, "provider_id": None, "source": "query_failed"}
    if not row:
        return {"model": None, "provider_id": None, "source": "no_ledger"}
    return {
        "model": row.get("model"),
        "provider_id": row.get("provider_id"),
        "source": "token_usage_latest_row",
    }


# ---------------------------------------------------------------------------
# 窗口取数（复用现成的 provider 自报值层，不造第二把尺子）
# ---------------------------------------------------------------------------


def window_lookup_for(models: Iterable[str | None]) -> dict[str, dict[str, Any]]:
    """模型名 → 窗口自报值。

    取数函数：``coapis.agents.context.window_source.reported_window_for_model_name``
    （window_source.py:154）。它只认 provider 注册表里上报的
    ``max_input_length`` / ``max_sequence_length``；取不到就返回 ``None``，
    本层据此标注「窗口未知」，**不编造窗口值**。
    """
    from ..agents.context.window_source import reported_window_for_model_name

    out: dict[str, dict[str, Any]] = {}
    for raw in models:
        model = str(raw or "").strip()
        if not model or model in out:
            continue
        try:
            provider_id, window = reported_window_for_model_name(model)
        except Exception:  # noqa: BLE001 — 注册表读取失败按未知处理
            provider_id, window = None, None
        out[model] = {
            "model": model,
            "provider_id": provider_id,
            "window_tokens": int(window) if window else None,
            "source": "provider_registry_report" if window else "unknown",
            "note": (
                None
                if window
                else "窗口自报值缺失（provider 注册表未上报该模型窗口），利用率不可计算"
            ),
        }
    return out


def attach_windows(
    rows: list[dict],
    *,
    windows: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict], dict[str, dict[str, Any]]]:
    """给台账行补上 ``window_tokens``（新副本，不改入参）。"""
    lookup = windows if windows is not None else window_lookup_for(
        r.get("model") for r in rows
    )
    attached: list[dict] = []
    for row in rows:
        item = dict(row)
        info = lookup.get(str(row.get("model") or "").strip()) or {}
        item["window_tokens"] = info.get("window_tokens")
        item["window_source"] = info.get("source", "unknown")
        attached.append(item)
    return attached, lookup


def session_windows(
    rows: list[dict],
    *,
    windows: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """按会话聚合出窗口利用率实测（出数交给 context_recon.summarize_usage）。

    Args:
        rows: :func:`usage_rows` 的台账行。
        windows: 可选的窗口注入（测试/上层已查好时复用，避免重复读注册表）。

    Returns:
        ``summarize_usage`` 的产出（session_count / measurable_sessions /
        peak_used_pct_max / peak_used_pct_avg / sessions 明细）外加窗口来源明细
        与「窗口未知的模型」清单。
    """
    from .context_recon import summarize_usage

    attached, lookup = attach_windows(rows, windows=windows)
    summary = summarize_usage(attached)

    unknown = sorted(
        model for model, info in lookup.items() if not info.get("window_tokens")
    )
    per_session: dict[str, list[dict[str, Any]]] = {}
    for row in attached:
        key = str(row.get("session_id") or row.get("chat_id") or "")
        per_session.setdefault(key, []).append(row)

    sessions: list[dict[str, Any]] = []
    for item in summary.get("sessions", []):
        detail = dict(item)
        rows_of = per_session.get(item.get("session_id"), [])
        detail["input_tokens_per_call"] = [
            int(r.get("input_tokens") or 0) for r in rows_of
        ]
        # summarize_usage 的均值字段叫 avg_used_pct；治理口径统一给出 mean_used_pct 别名
        detail["mean_used_pct"] = item.get("avg_used_pct")
        detail["window_source"] = (
            "provider_registry_report"
            if item.get("window_tokens")
            else "unknown"
        )
        detail["utilization_note"] = (
            None
            if item.get("window_tokens")
            else "窗口大小未知（provider 未上报该模型窗口），利用率不可计算（不猜）"
        )
        sessions.append(detail)

    summary["sessions"] = sessions
    summary["window_lookup"] = [lookup[k] for k in sorted(lookup)]
    # 利用率是百分数（0~100），沿用 summarize_usage 的口径，别再乘一次 100
    summary["utilization_unit"] = "percent"
    summary["window_tokens"] = max(
        [info.get("window_tokens") or 0 for info in lookup.values()] or [0],
    )
    summary["unknown_window_models"] = unknown
    summary["window_note"] = (
        None
        if not unknown
        else "窗口自报值缺失的模型：" + ", ".join(unknown) + " —— 这些会话的利用率为 null"
    )
    return summary


def usage_report(
    days: int = DEFAULT_DAYS,
    limit: int = DEFAULT_LIMIT,
    *,
    user_id: str | None = None,
    env: dict[str, Any] | None = None,
    engine: Any = None,
    windows: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``GET /api/memory/context-usage`` 的载荷（纯聚合，无副作用）。"""
    from .context_recon import tier_compaction_enabled, tier_targets

    rows = usage_rows(days, limit, user_id=user_id, engine=engine)
    summary = session_windows(rows, windows=windows)
    return {
        "ok": True,
        "scope": {"user_id": user_id, "days": int(days), "limit": int(limit)},
        "cutoff_epoch": cutoff_epoch(days),
        "rows_scanned": len(rows),
        "usage": summary,
        "tier": {
            "compact_enabled": tier_compaction_enabled(env),
            "targets": tier_targets(env),
        },
        "note": (
            "input_tokens 是运行时记账真值；利用率分母是 provider 上报的模型窗口，"
            "取不到即为 null（不编窗口值）"
        ),
    }


# ---------------------------------------------------------------------------
# 会话定位与消息读取（只读文件系统）
# ---------------------------------------------------------------------------


def _safe(name: str) -> str:
    """与 SafeJSONSession 的落盘命名保持一致（非法字符 → ``--``）。"""
    out = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "--" for ch in str(name))
    return out[-48:] if len(out) > 48 else out


def find_session_state(
    session_id: str,
    *,
    root: Path,
    username: str | None = None,
) -> list[dict[str, Any]]:
    """在会话目录里找某会话的状态文件（只读扫描）。

    落盘命名沿用 ``SafeJSONSession._get_save_path``：``{user_id}_{session_id}.json``
    （``coapis/app/runner/session.py:190``）。新格式用 chat UUID 当 session_id，
    因此同时接受「裸 session_id」与「带用户名前缀」两种文件名。

    Returns:
        ``[{"path": Path, "role": "legacy"|"chat", "username": str}, ...]``
    """
    root = Path(root)
    if not session_id or not root.is_dir():
        return []
    safe_sid = _safe(session_id)
    hits: list[dict[str, Any]] = []

    users = [username] if username else [p.name for p in root.iterdir() if p.is_dir()]
    for user in users:
        if not user:
            continue
        sessions_dir = root / user / "sessions"
        if not sessions_dir.is_dir():
            continue
        for path in sorted(sessions_dir.glob("*.json")):
            stem = path.stem
            if stem == safe_sid:
                hits.append({"path": path, "role": "chat", "username": user})
            elif stem.endswith(f"_{safe_sid}"):
                hits.append({"path": path, "role": "legacy", "username": user})
    return hits


def session_messages(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读会话状态文件里的消息（只读，返回**副本**）。

    状态结构（实测 dev 会话文件）::

        {"agent": {"memory": {"content": [[msg_dict, marks], ...],
                              "_compressed_summary": "..."}}}

    Returns:
        ``(rows, meta)``：rows 是可直接丢进计量层的 prompt 行
        （``role``/``content``/``name``）；meta 带压缩摘要长度等信息。
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    memory = ((data.get("agent") or {}).get("memory")) or {}
    content = memory.get("content") or []

    rows: list[dict[str, Any]] = []
    for entry in content:
        msg = entry[0] if isinstance(entry, (list, tuple)) and entry else entry
        if not isinstance(msg, dict):
            continue
        rows.append(
            {
                "role": str(msg.get("role") or ""),
                "content": msg.get("content"),
                "name": msg.get("name") or msg.get("role") or "",
            },
        )
    summary = memory.get("_compressed_summary") or ""
    meta = {
        "state_path": str(path),
        "row_count": len(rows),
        "compressed_summary_chars": len(str(summary)),
    }
    return rows, meta


# ---------------------------------------------------------------------------
# 压缩预览（纯计算，不落盘）
# ---------------------------------------------------------------------------


def _tier_window(window: Any, effective_budget: int) -> Any:
    """按档位目标临时改窗口对象（纯值操作，不回写任何配置）。

    ``WindowInfo``（window_source.py:58）只有四个字段：``reported_tokens`` /
    ``effective_tokens`` / ``source`` / ``chars_per_token``——没有别的字段可写，
    所以这里只是造一个新的窗口值给计量层用。
    """
    from ..agents.context.window_source import WindowInfo

    return WindowInfo(
        reported_tokens=int(window.reported_tokens),
        effective_tokens=int(effective_budget),
        source=f"{window.source}+tier_target",
        chars_per_token=float(window.chars_per_token),
    )


def preview_compaction(
    rows: list[dict[str, Any]],
    *,
    window: Any,
    tier: str | None = None,
    compact_threshold_ratio: float = DEFAULT_RATIO,
    keep_chars_floor: int = 12_000,
    env: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对一组 prompt 行做**压缩预览**（纯计算：measure + trim）。

    尺子全部复用现成计量层：
      * :func:`coapis.agents.context.context_budget.measure_prompt`（context_budget.py:352）
      * :func:`coapis.agents.context.context_budget.trim_messages_to_budget`（context_budget.py:490）

    本函数**不写盘、不改入参**（内部 deepcopy），因此可安全用于生产会话的 dry_run。
    """
    from ..agents.context.context_budget import (
        ContextOverflowError,
        measure_prompt,
        trim_messages_to_budget,
    )
    from .context_recon import (
        apply_tier_target,
        tier_compaction_enabled,
        tier_of_effort,
        tier_targets,
    )

    rows = copy.deepcopy(list(rows))
    ratio = float(compact_threshold_ratio)

    tier_name = tier
    tier_source = "explicit" if tier else "default"
    if tier_name is None:
        tier_name = tier_of_effort(None)
        tier_source = "effort" if tier_name else "none"

    formula_budget = int(window.effective_tokens * ratio)
    effective_budget, tier_recon = apply_tier_target(formula_budget, tier_name, env=env)

    before = measure_prompt(rows, None, window, ratio)
    target_window = _tier_window(window, effective_budget)

    plan: dict[str, Any]
    try:
        kept, dropped, after = trim_messages_to_budget(
            rows,
            target_window,
            compact_threshold_ratio=1.0,
            keep_chars_floor=int(keep_chars_floor),
            tools=None,
        )
        plan = {
            "feasible": True,
            "planned_keep_count": len(kept),
            "planned_drop_count": len(dropped),
            "preview_tokens_after": int(target_window.to_tokens(after.total_chars)),
            "preview_chars_after": int(after.total_chars),
            # BudgetSnapshot 只有 headroom_chars 这个派生属性，没有 over_budget 字段
            "fits_budget": after.headroom_chars >= 0,
            "headroom_tokens": int(target_window.to_tokens(after.headroom_chars)),
            "blocked_reason": None,
        }
    except ContextOverflowError as exc:
        plan = {
            "feasible": False,
            "planned_keep_count": None,
            "planned_drop_count": None,
            "preview_tokens_after": None,
            "preview_chars_after": None,
            "fits_budget": False,
            "headroom_tokens": None,
            "blocked_reason": str(exc),
        }

    return {
        "row_count": len(rows),
        "current_tokens": int(window.to_tokens(before.total_chars)),
        "current_chars": int(before.total_chars),
        "fixed_tokens": int(window.to_tokens(before.fixed_chars)),
        "target_budget_tokens": int(effective_budget),
        "target_budget_chars": int(target_window.to_chars(effective_budget)),
        "formula_budget_tokens": int(formula_budget),
        "compact_threshold_ratio": ratio,
        "keep_chars_floor": int(keep_chars_floor),
        "tier": {
            "tier": tier_name,
            "tier_source": tier_source,
            "compact_enabled": tier_compaction_enabled(env),
            "targets": tier_targets(env),
            "recon": tier_recon,
        },
        "plan": plan,
        "writes_performed": 0,
    }


# ---------------------------------------------------------------------------
# dry_run 自证
# ---------------------------------------------------------------------------


def fingerprint_dir(directory: Path) -> list[dict[str, Any]]:
    """目录内容指纹（文件名 + 字节数 + sha256），dry_run 自证用（只读）。"""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        out.append(
            {
                "path": str(path.relative_to(directory)),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
        )
    return out
