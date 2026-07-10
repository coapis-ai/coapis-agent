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

"""Resource guard — Agent resource budget management with context_manager + tool_stats integration.

Tracks token budgets, call frequency, memory limits and auto-blocks
when limits are exceeded. Persists state via context_manager, reads
statistics from tool_stats.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# ── Default budgets ──
_DEFAULT_BUDGETS = {
    "token_limit": 500000,          # max tokens per session
    "tool_calls_per_hour": 200,     # max tool calls per hour
    "memory_limit_mb": 1024,        # max process memory in MB
    "latency_budget_ms": 3000,      # max avg latency before throttle
}

CONTEXT_KEY = "resource_guard_state"


async def _load_state() -> dict[str, Any]:
    """Load guard state from context_manager."""
    try:
        from .context_manager import context_manager
        r = await context_manager(action="get", key=CONTEXT_KEY)
        if r.get("value"):
            return json.loads(r["value"]) if isinstance(r["value"], str) else r["value"]
    except Exception:
        pass
    return {
        "tokens_used": 0,
        "calls_this_hour": 0,
        "hour_start": int(time.time()),
        "throttled": False,
        "throttle_reason": "",
        "violations": [],
    }


async def _save_state(state: dict[str, Any]) -> None:
    """Save guard state to context_manager."""
    try:
        from .context_manager import context_manager
        await context_manager(
            action="set",
            key=CONTEXT_KEY,
            value=json.dumps(state, ensure_ascii=False),
        )
    except Exception as e:
        logger.warning(f"Failed to save resource_guard state: {e}")


def _get_process_rss_mb() -> float:
    """Get current process RSS in MB."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        pass
    return 0.0


def _get_tool_stats_summary() -> dict[str, Any]:
    """Read tool_stats for latency/error metrics."""
    try:
        from .tool_stats import _stats
        if not _stats:
            return {"tools": 0, "total_calls": 0, "avg_latency_ms": 0, "error_rate": 0}

        total_calls = sum(d.get("calls", 0) for d in _stats.values())
        total_errors = sum(d.get("errors", 0) for d in _stats.values())
        latencies = [d.get("avg_latency_ms", 0) for d in _stats.values() if d.get("calls", 0) > 0]
        avg_lat = round(sum(latencies) / max(len(latencies), 1), 1)
        error_rate = round(total_errors / max(total_calls, 1), 4)

        return {
            "tools": len(_stats),
            "total_calls": total_calls,
            "total_errors": total_errors,
            "avg_latency_ms": avg_lat,
            "error_rate": error_rate,
        }
    except Exception:
        return {"tools": 0, "total_calls": 0, "avg_latency_ms": 0, "error_rate": 0}


def _check_budgets(state: dict[str, Any], budgets: dict[str, Any]) -> list[dict[str, Any]]:
    """Check current state against budgets, return violations."""
    violations = []
    now = int(time.time())

    # Reset hourly counter if hour has passed
    if now - state.get("hour_start", 0) >= 3600:
        state["calls_this_hour"] = 0
        state["hour_start"] = now

    # Token budget
    token_used = state.get("tokens_used", 0)
    token_limit = budgets.get("token_limit", _DEFAULT_BUDGETS["token_limit"])
    if token_limit > 0 and token_used >= token_limit:
        violations.append({
            "type": "token_limit",
            "used": token_used,
            "limit": token_limit,
            "severity": "critical",
        })
    elif token_limit > 0 and token_used >= token_limit * 0.8:
        violations.append({
            "type": "token_warning",
            "used": token_used,
            "limit": token_limit,
            "severity": "warning",
        })

    # Calls per hour
    calls = state.get("calls_this_hour", 0)
    call_limit = budgets.get("tool_calls_per_hour", _DEFAULT_BUDGETS["tool_calls_per_hour"])
    if call_limit > 0 and calls >= call_limit:
        violations.append({
            "type": "call_limit",
            "used": calls,
            "limit": call_limit,
            "severity": "critical",
        })

    # Memory
    rss = _get_process_rss_mb()
    mem_limit = budgets.get("memory_limit_mb", _DEFAULT_BUDGETS["memory_limit_mb"])
    if mem_limit > 0 and rss >= mem_limit:
        violations.append({
            "type": "memory_limit",
            "used_mb": rss,
            "limit_mb": mem_limit,
            "severity": "critical",
        })

    # Latency from tool_stats
    tool_stats = _get_tool_stats_summary()
    lat_limit = budgets.get("latency_budget_ms", _DEFAULT_BUDGETS["latency_budget_ms"])
    if tool_stats["avg_latency_ms"] > 0 and tool_stats["avg_latency_ms"] > lat_limit:
        violations.append({
            "type": "latency_budget",
            "avg_ms": tool_stats["avg_latency_ms"],
            "limit_ms": lat_limit,
            "severity": "warning",
        })

    return violations


async def resource_guard(
    action: str = "status",
    budgets: str = "",
    tokens: int = 0,
    calls: int = 0,
    budget_key: str = "",
    budget_value: str = "",
) -> dict[str, Any]:
    """资源守卫。

    Agent 自身资源预算管理，超限自动拦截。

    Args:
        action: 操作类型 (status/check/use/set_budget/reset/list_budgets)
        budgets: 自定义预算 JSON
        tokens: 本次消耗的 token 数（用于 use）
        calls: 本次调用次数（用于 use）
        budget_key: 要设置的预算键（用于 set_budget）
        budget_value: 要设置的预算值（用于 set_budget）

    Returns:
        资源状态和告警
    """
    state = await _load_state()
    th = dict(_DEFAULT_BUDGETS)

    # Merge custom budgets
    if budgets.strip():
        try:
            custom = json.loads(budgets)
            th.update(custom)
        except Exception:
            pass

    # Update per-request budget overrides
    if budget_key and budget_key in _DEFAULT_BUDGETS:
        try:
            th[budget_key] = int(budget_value) if budget_value.isdigit() else float(budget_value)
        except Exception:
            pass

    rss = _get_process_rss_mb()
    tool_stats = _get_tool_stats_summary()

    if action == "status":
        violations = _check_budgets(state, th)
        critical = [v for v in violations if v["severity"] == "critical"]

        return {
            "tokens_used": state.get("tokens_used", 0),
            "token_limit": th["token_limit"],
            "token_usage_pct": round(state.get("tokens_used", 0) / max(th["token_limit"], 1) * 100, 1),
            "calls_this_hour": state.get("calls_this_hour", 0),
            "call_limit": th["tool_calls_per_hour"],
            "memory_mb": rss,
            "memory_limit_mb": th["memory_limit_mb"],
            "tool_stats": tool_stats,
            "violations": violations,
            "violation_count": len(violations),
            "throttled": len(critical) > 0,
            "budgets": th,
        }

    elif action == "check":
        violations = _check_budgets(state, th)
        return {
            "check": "ok" if not violations else "violations",
            "violations": violations,
            "recommendation": "可继续" if not violations else "建议降级或等待冷却",
        }

    elif action == "use":
        # Record token/call consumption
        now = int(time.time())
        if now - state.get("hour_start", 0) >= 3600:
            state["calls_this_hour"] = 0
            state["hour_start"] = now

        state["tokens_used"] = state.get("tokens_used", 0) + max(tokens, 0)
        state["calls_this_hour"] = state.get("calls_this_hour", 0) + max(calls, 0)

        violations = _check_budgets(state, th)
        critical = [v for v in violations if v["severity"] == "critical"]
        state["throttled"] = len(critical) > 0
        state["throttle_reason"] = critical[0]["type"] if critical else ""

        await _save_state(state)

        return {
            "action": "use",
            "tokens_used": state["tokens_used"],
            "calls_this_hour": state["calls_this_hour"],
            "throttled": state["throttled"],
            "violations": violations,
        }

    elif action == "reset":
        state = {
            "tokens_used": 0,
            "calls_this_hour": 0,
            "hour_start": int(time.time()),
            "throttled": False,
            "throttle_reason": "",
            "violations": [],
        }
        await _save_state(state)
        return {"action": "reset", "message": "资源计数器已重置"}

    elif action == "set_budget":
        if not budget_key.strip():
            return {"error": "budget_key 不能为空"}
        if budget_key not in _DEFAULT_BUDGETS:
            return {"error": f"未知预算键: {budget_key}，支持: {list(_DEFAULT_BUDGETS.keys())}"}
        try:
            th[budget_key] = int(budget_value) if budget_value.isdigit() else float(budget_value)
            # Save budgets to context_manager
            from .context_manager import context_manager
            await context_manager(
                action="set",
                key="resource_guard_budgets",
                value=json.dumps(th, ensure_ascii=False),
            )
            return {"action": "set_budget", "budget": budget_key, "value": th[budget_key]}
        except Exception as e:
            return {"error": str(e)}

    elif action == "list_budgets":
        # Load saved budgets if any
        try:
            from .context_manager import context_manager
            r = await context_manager(action="get", key="resource_guard_budgets")
            if r.get("value"):
                saved = json.loads(r["value"])
                th.update(saved)
        except Exception:
            pass
        return {"budgets": th}

    else:
        return {"error": f"未知操作: {action}，支持 status/check/use/reset/set_budget/list_budgets"}
