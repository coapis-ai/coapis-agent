# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tool stats — record tool usage metrics for evolution system.

Tracks call count, success rate, and average latency per tool.
Provides data foundation for the evolution system's learning loop.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# Stats file location
_STATS_FILE = "tool_stats.json"
# Max recent calls to keep per tool
_MAX_RECENT = 50


def _stats_path() -> Path:
    """Path to the stats file."""
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws) / "files" / _STATS_FILE
    except Exception:
        pass
    return Path.cwd() / "files" / _STATS_FILE


def _load_stats() -> dict[str, Any]:
    """Load stats from disk."""
    path = _stats_path()
    if not path.exists():
        return {"tools": {}, "updated_at": ""}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"tools": {}, "updated_at": ""}


def _save_stats(stats: dict[str, Any]) -> None:
    """Persist stats to disk using atomic rename (crash-safe)."""
    path = _stats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stats["updated_at"] = datetime.now().isoformat()
    # Atomic write: write to tmpfile then rename
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _ensure_tool_entry(tools: dict, name: str) -> None:
    """Ensure a tool entry exists in stats."""
    if name not in tools:
        tools[name] = {
            "call_count": 0,
            "success_count": 0,
            "error_count": 0,
            "total_latency_ms": 0,
            "avg_latency_ms": 0,
            "success_rate": 0.0,
            "first_used": datetime.now().isoformat(),
            "last_used": "",
            "recent_calls": [],
        }


# ── Public API for other tools to call ──────────────────────────────

def record_tool_call(
    tool_name: str,
    success: bool,
    latency_ms: float,
    error_msg: str = "",
) -> None:
    """Record a tool call (called internally by the framework).

    This is the core tracking function. Other modules should call this
    after each tool invocation.
    """
    stats = _load_stats()
    tools = stats.setdefault("tools", {})
    _ensure_tool_entry(tools, tool_name)

    entry = tools[tool_name]
    entry["call_count"] += 1
    if success:
        entry["success_count"] += 1
    else:
        entry["error_count"] += 1
    entry["total_latency_ms"] += latency_ms
    entry["avg_latency_ms"] = round(
        entry["total_latency_ms"] / entry["call_count"], 1
    )
    entry["success_rate"] = round(
        entry["success_count"] / entry["call_count"] * 100, 1
    ) if entry["call_count"] > 0 else 0.0
    entry["last_used"] = datetime.now().isoformat()

    # Keep recent calls (newest first)
    recent = entry.setdefault("recent_calls", [])
    recent.insert(0, {
        "time": datetime.now().isoformat(),
        "success": success,
        "latency_ms": round(latency_ms, 1),
        "error": error_msg[:200] if error_msg else "",
    })
    # Trim to max
    if len(recent) > _MAX_RECENT:
        entry["recent_calls"] = recent[:_MAX_RECENT]

    _save_stats(stats)


@register_tool(
    name="tool_stats",
    description="工具使用追踪：查看/查询/重置工具调用统计（次数/成功率/耗时），为进化系统提供数据基础。",
    category="builtin",
    tags=["analytics", "stats", "evolution"],
    scene="ops"
)
async def tool_stats(
    action: str = "list",
    tool_name: str = "",
    limit: int = 15,
) -> dict[str, Any]:
    """工具使用追踪。

    Args:
        action: 操作类型 (list/query/reset/record)
        tool_name: 工具名称（query 时必填）
        limit: list 时最大返回数，默认 15
        record: 调用记录（record 时使用）

    Returns:
        统计数据
    """
    stats = _load_stats()
    tools = stats.get("tools", {})

    if action == "list":
        # Sort by call_count descending
        sorted_tools = sorted(
            tools.items(),
            key=lambda x: x[1].get("call_count", 0),
            reverse=True,
        )[:limit]

        results = []
        for name, data in sorted_tools:
            results.append({
                "tool": name,
                "calls": data.get("call_count", 0),
                "success_rate": data.get("success_rate", 0),
                "avg_latency_ms": data.get("avg_latency_ms", 0),
                "last_used": data.get("last_used", ""),
            })

        total_calls = sum(d.get("call_count", 0) for d in tools.values())
        total_success = sum(d.get("success_count", 0) for d in tools.values())
        overall_rate = round(total_success / total_calls * 100, 1) if total_calls > 0 else 0

        return {
            "results": results,
            "count": len(results),
            "total_tools": len(tools),
            "total_calls": total_calls,
            "overall_success_rate": overall_rate,
            "updated_at": stats.get("updated_at", ""),
        }

    elif action == "query":
        if not tool_name.strip():
            return {"error": "tool_name 不能为空"}

        entry = tools.get(tool_name.strip())
        if not entry:
            return {"error": f"未找到工具统计: {tool_name.strip()}"}

        return {
            "tool": tool_name.strip(),
            "call_count": entry.get("call_count", 0),
            "success_count": entry.get("success_count", 0),
            "error_count": entry.get("error_count", 0),
            "success_rate": entry.get("success_rate", 0),
            "avg_latency_ms": entry.get("avg_latency_ms", 0),
            "first_used": entry.get("first_used", ""),
            "last_used": entry.get("last_used", ""),
            "recent_calls": entry.get("recent_calls", [])[:10],
        }

    elif action == "reset":
        if tool_name.strip():
            # Reset specific tool
            if tool_name.strip() in tools:
                del tools[tool_name.strip()]
                _save_stats(stats)
                return {"message": f"✅ 已重置工具统计: {tool_name.strip()}"}
            return {"error": f"未找到工具统计: {tool_name.strip()}"}
        else:
            # Reset all
            _save_stats({"tools": {}, "updated_at": ""})
            return {"message": "✅ 已重置所有工具统计"}

    elif action == "record":
        # Manual record (for testing or external use)
        return {"error": "record 操作应通过 record_tool_call() 函数调用，而非直接调用"}

    elif action == "low_frequency":
        """Analyze low-frequency tools (30 days, < 3 calls) and suggest defaults."""
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        low_freq = []
        never_used = []
        for name, entry in tools.items():
            last_used = entry.get("last_used", "")
            call_count = entry.get("call_count", 0)
            if not last_used:
                never_used.append(name)
            elif last_used < cutoff and call_count < 3:
                low_freq.append({
                    "name": name,
                    "call_count": call_count,
                    "last_used": last_used,
                    "avg_latency_ms": entry.get("avg_latency_ms", 0),
                })
        low_freq.sort(key=lambda x: x["call_count"])
        return {
            "action": "low_frequency",
            "cutoff_days": 30,
            "threshold": 3,
            "low_frequency": low_freq,
            "never_used": never_used,
            "suggestion": (
                f"发现 {len(low_freq)} 个低频工具和 {len(never_used)} 个从未使用的工具，"
                "建议在 Agent 配置中默认禁用以减少上下文负载"
            ),
        }

    else:
        return {"error": f"未知操作: {action}，支持 list/query/reset/low_frequency"}
