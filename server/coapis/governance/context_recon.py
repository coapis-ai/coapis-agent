"""上下文消费对账尺子 —— 纯函数，零副作用。

为什么要有这把尺子：压缩每天都在发生，但没人说得出「压缩后留下多少
token」「这一轮窗口用了百分之几」「这次是按哪一档预算收的」。治理页
要的是数字，不是形容词。

档位口径（实施方案 D7）：full / thinking / lightweight 三档压缩目标
= 6000 / 4000 / 2000 token。

- 覆盖开关：`COAPIS_TIER_COMPACT=1` 才启用按档位收口（默认关，
  关闭时行为与今天逐字节一致）。
- 目标覆盖：`COAPIS_COMPACT_TIER_TARGETS="6000:4000:2000"`
  （顺序固定 full:thinking:lightweight）。

这里刻意不 import 运行时模块：热路径反过来调用这里，避免成环。
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Mapping

__all__ = [
    "TIER_FULL",
    "TIER_THINKING",
    "TIER_LIGHTWEIGHT",
    "DEFAULT_TIER_TARGETS",
    "tier_compaction_enabled",
    "tier_targets",
    "tier_of_effort",
    "compact_target_tokens",
    "apply_tier_target",
    "window_utilization",
    "summarize_usage",
]

TIER_FULL = "full"
TIER_THINKING = "thinking"
TIER_LIGHTWEIGHT = "lightweight"

#: 三档压缩目标（token）。full 档保留最多上下文，轻量档收得最狠。
DEFAULT_TIER_TARGETS: dict[str, int] = {
    TIER_FULL: 6000,
    TIER_THINKING: 4000,
    TIER_LIGHTWEIGHT: 2000,
}

_ENABLED_ENV = "COAPIS_TIER_COMPACT"
_TARGETS_ENV = "COAPIS_COMPACT_TIER_TARGETS"

#: 思考预算档位 → 压缩档位。minimal/low 归轻量，medium 归思考，high 归满档。
_EFFORT_TO_TIER = {
    "high": TIER_FULL,
    "medium": TIER_THINKING,
    "low": TIER_LIGHTWEIGHT,
    "minimal": TIER_LIGHTWEIGHT,
}


def _flag(env: Mapping[str, str] | None, name: str) -> bool:
    raw = (env or os.environ).get(name, "")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def tier_compaction_enabled(env: Mapping[str, str] | None = None) -> bool:
    """按档位收口是否启用（默认关 = 今天的行为不变）。"""
    return _flag(env, _ENABLED_ENV)


def _parse_targets(raw: str) -> dict[str, int] | None:
    parts = [p.strip() for p in str(raw).split(":") if p.strip()]
    if len(parts) != len(DEFAULT_TIER_TARGETS):
        return None
    out: dict[str, int] = {}
    for tier, value in zip(
        (TIER_FULL, TIER_THINKING, TIER_LIGHTWEIGHT),
        parts,
    ):
        try:
            num = int(value)
        except ValueError:
            return None
        if num <= 0:
            return None
        out[tier] = num
    return out


def tier_targets(env: Mapping[str, str] | None = None) -> dict[str, int]:
    """三档压缩目标；环境变量写错就退回默认值（不抛，不让调用方崩）。"""
    raw = (env or os.environ).get(_TARGETS_ENV, "")
    parsed = _parse_targets(raw) if raw else None
    return dict(parsed or DEFAULT_TIER_TARGETS)


def tier_of_effort(effort: str | None) -> str:
    """思考预算档位 → 压缩档位；认不出来按满档（最保守，不收狠）。"""
    key = str(effort or "").strip().lower()
    return _EFFORT_TO_TIER.get(key, TIER_FULL)


def compact_target_tokens(tier: str, env: Mapping[str, str] | None = None) -> int:
    """该档位的压缩目标 token 数（未知档位回满档目标）。"""
    table = tier_targets(env)
    return table.get(str(tier or "").strip().lower(), table[TIER_FULL])


def apply_tier_target(
    formula_budget: int,
    tier: str,
    env: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """把「按窗口比例算出来的预算」按档位收口。

    返回 (生效预算, 对账说明)。开关关闭时生效预算 == 公式预算，
    说明里 applied=False —— 这样日志里能看出「今天没启用」而不是
    装作启用过。
    """
    formula = max(0, int(formula_budget))
    target = compact_target_tokens(tier, env)
    enabled = tier_compaction_enabled(env)
    effective = min(formula, target) if enabled else formula
    return effective, {
        "tier": str(tier or "").strip().lower() or TIER_FULL,
        "formula_budget": formula,
        "tier_target": target,
        "effective_budget": effective,
        "applied": bool(enabled and effective < formula),
        "enabled": bool(enabled),
    }


def window_utilization(
    input_tokens: int | None,
    window_tokens: int | None,
) -> dict[str, Any]:
    """窗口利用率：一次调用吃进多少输入 token / 模型窗口多大。"""
    tokens = int(input_tokens or 0)
    window = int(window_tokens or 0)
    if window <= 0:
        return {
            "input_tokens": tokens,
            "window_tokens": window,
            "used_pct": None,
            "over_budget": None,
            "note": "窗口大小未知，利用率不可计算（不猜）",
        }
    pct = round(100.0 * tokens / window, 2)
    return {
        "input_tokens": tokens,
        "window_tokens": window,
        "used_pct": pct,
        "over_budget": tokens > window,
        "note": "",
    }


def summarize_usage(
    rows: Iterable[Mapping[str, Any]],
    *,
    window_tokens: int | None = None,
) -> dict[str, Any]:
    """按会话聚合 token_usage 行，给出窗口利用率实测。

    rows 的键：session_id / input_tokens / window_tokens（缺则用
    传入的 window_tokens）/ model。
    """
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = str(row.get("session_id") or "")
        if not sid:
            continue
        bucket = buckets.setdefault(
            sid,
            {"session_id": sid, "calls": 0, "input_tokens_sum": 0,
             "input_tokens_max": 0, "windows": set(), "models": set()},
        )
        tokens = int(row.get("input_tokens") or 0)
        bucket["calls"] += 1
        bucket["input_tokens_sum"] += tokens
        bucket["input_tokens_max"] = max(bucket["input_tokens_max"], tokens)
        win = row.get("window_tokens")
        if win:
            bucket["windows"].add(int(win))
        model = row.get("model")
        if model:
            bucket["models"].add(str(model))

    sessions = []
    pcts = []
    for sid in sorted(buckets):
        bucket = buckets[sid]
        windows = sorted(bucket["windows"])
        win = windows[-1] if windows else int(window_tokens or 0)
        util = window_utilization(bucket["input_tokens_max"], win)
        avg = int(round(bucket["input_tokens_sum"] / max(1, bucket["calls"])))
        avg_util = window_utilization(avg, win)
        sessions.append({
            "session_id": sid,
            "calls": bucket["calls"],
            "input_tokens_avg": avg,
            "input_tokens_max": bucket["input_tokens_max"],
            "window_tokens": win,
            "peak_used_pct": util["used_pct"],
            "avg_used_pct": avg_util["used_pct"],
            "over_budget": util["over_budget"],
            "models": sorted(bucket["models"]),
        })
        if util["used_pct"] is not None:
            pcts.append(util["used_pct"])

    return {
        "sessions": sessions,
        "session_count": len(sessions),
        "measurable_sessions": len(pcts),
        "peak_used_pct_max": max(pcts) if pcts else None,
        "peak_used_pct_avg": round(sum(pcts) / len(pcts), 2) if pcts else None,
        "tier_targets": tier_targets(),
        "tier_compact_enabled": tier_compaction_enabled(),
    }
