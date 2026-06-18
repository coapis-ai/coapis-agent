# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
from __future__ import annotations
import asyncio, json, logging, os, time
from pathlib import Path
from typing import Any
from .registry import register_tool

logger = logging.getLogger(__name__)

OPT_DIR = Path(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "optimizer"))


def _ensure_dir():
    OPT_DIR.mkdir(parents=True, exist_ok=True)


def _load_profiles() -> dict[str, Any]:
    _ensure_dir()
    pf = OPT_DIR / "profiles.json"
    if pf.exists():
        try:
            return json.loads(pf.read_text())
        except Exception:
            pass
    return {"profiles": {}, "suggestions": []}


def _save_profiles(data: dict[str, Any]):
    _ensure_dir()
    (OPT_DIR / "profiles.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _analyze_tool_stats() -> dict[str, Any]:
    """Analyze tool_stats for optimization opportunities."""
    try:
        from .tool_stats import _stats
    except Exception:
        _stats = {}

    if not _stats:
        return {"status": "no_data", "suggestions": []}

    suggestions = []
    tool_ranking = []

    for name, data in _stats.items():
        calls = data.get("calls", 0)
        errors = data.get("errors", 0)
        avg_lat = data.get("avg_latency_ms", 0)
        error_rate = errors / max(calls, 1)

        score = 100
        reasons = []

        # High error rate
        if error_rate > 0.2 and calls >= 5:
            score -= 30
            reasons.append(f"错误率 {error_rate:.0%}")
            suggestions.append({
                "tool": name, "type": "high_error_rate",
                "suggestion": f"工具 {name} 错误率偏高 ({error_rate:.0%})，建议检查参数格式或降级到替代方案",
                "severity": "high",
            })

        # High latency
        if avg_lat > 3000 and calls >= 3:
            score -= 20
            reasons.append(f"延迟 {avg_lat:.0f}ms")
            suggestions.append({
                "tool": name, "type": "high_latency",
                "suggestion": f"工具 {name} 平均延迟 {avg_lat:.0f}ms，建议缓存结果或减少调用频率",
                "severity": "medium",
            })

        # Low usage but registered
        if calls < 3:
            score -= 5
            reasons.append("低频使用")

        tool_ranking.append({
            "tool": name, "calls": calls, "errors": errors,
            "avg_latency_ms": avg_lat, "error_rate": round(error_rate, 4),
            "score": max(score, 0), "reasons": reasons,
        })

    tool_ranking.sort(key=lambda x: x["score"], reverse=True)

    return {
        "status": "ok",
        "tool_count": len(tool_ranking),
        "ranking": tool_ranking,
        "suggestions": suggestions,
        "high_priority": [s for s in suggestions if s["severity"] == "high"],
    }


def _recommend_tool_strategy(tool_ranking: list[dict]) -> dict[str, Any]:
    """Recommend optimal tool calling strategy."""
    strategy = {
        "prefer_fast": [],     # Tools to prefer (low latency, low error)
        "avoid": [],           # Tools to avoid or deprecate
        "cache_candidates": [], # Tools whose results can be cached
        "fallback_pairs": [],  # Suggested fallback pairs
    }

    for t in tool_ranking:
        if t["error_rate"] > 0.3 and t["calls"] >= 5:
            strategy["avoid"].append(t["tool"])
        elif t["avg_latency_ms"] < 100 and t["error_rate"] < 0.05:
            strategy["prefer_fast"].append(t["tool"])
        elif t["avg_latency_ms"] > 2000:
            strategy["cache_candidates"].append(t["tool"])

    return strategy


@register_tool(
    name="agent_optimizer",
    description="Agent 自动调优：根据 tool_stats 分析工具使用模式，生成优化建议和调用策略，与 tool_stats + resource_guard + memory_manager 联动。",
    category="builtin",
    tags=["ai", "optimization", "strategy", "meta"],
    scene="ai"
)
async def agent_optimizer(
    action: str = "analyze",
    tool_filter: str = "",
    save_profile: bool = False,
    profile_name: str = "",
    apply: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Agent 自动调优。

    Args:
        action: 操作类型 (analyze/strategy/report/save_profile/load_profile/list_profiles)
        tool_filter: 工具名过滤（逗号分隔）
        save_profile: 是否保存分析结果
        profile_name: 配置名称
        apply: 是否应用推荐策略
        limit: 报告限制

    Returns:
        分析结果和优化建议
    """
    _ensure_dir()
    data = _load_profiles()

    if action == "analyze":
        analysis = _analyze_tool_stats()

        if tool_filter.strip():
            filter_set = {t.strip() for t in tool_filter.split(",")}
            analysis["ranking"] = [r for r in analysis["ranking"] if r["tool"] in filter_set]
            analysis["tool_count"] = len(analysis["ranking"])

        # Resource guard context
        resource_info = {}
        try:
            from .resource_guard import resource_guard
            r = await resource_guard(action="status")
            resource_info = {
                "tokens_used": r.get("tokens_used", 0),
                "calls_this_hour": r.get("calls_this_hour", 0),
                "memory_mb": r.get("memory_mb", 0),
                "throttled": r.get("throttled", False),
            }
        except Exception:
            pass

        return {
            "action": "analyze",
            **analysis,
            "resource_context": resource_info,
        }

    elif action == "strategy":
        analysis = _analyze_tool_stats()
        strategy = _recommend_tool_strategy(analysis.get("ranking", []))
        return {"action": "strategy", "strategy": strategy, "tool_count": analysis.get("tool_count", 0)}

    elif action == "report":
        analysis = _analyze_tool_stats()
        strategy = _recommend_tool_strategy(analysis.get("ranking", []))
        ranking = analysis.get("ranking", [])[:limit]
        report_lines = ["# Agent 优化报告\n"]
        report_lines.append(f"工具总数: {analysis.get('tool_count', 0)}")
        report_lines.append(f"高优先建议: {len(analysis.get('high_priority', []))}\n")
        report_lines.append("## 工具评分排名\n")
        report_lines.append("| 工具 | 调用 | 错误率 | 延迟(ms) | 评分 |")
        report_lines.append("|------|------|--------|----------|------|")
        for r in ranking:
            report_lines.append(f"| {r['tool']} | {r['calls']} | {r['error_rate']:.0%} | {r['avg_latency_ms']:.0f} | {r['score']} |")
        report_lines.append("\n## 推荐策略\n")
        report_lines.append(f"优先使用: {', '.join(strategy.get('prefer_fast', [])[:5]) or '无'}")
        report_lines.append(f"建议缓存: {', '.join(strategy.get('cache_candidates', [])[:5]) or '无'}")
        report_lines.append(f"建议避免: {', '.join(strategy.get('avoid', [])[:5]) or '无'}")
        if analysis.get("suggestions"):
            report_lines.append("\n## 具体建议\n")
            for s in analysis["suggestions"][:10]:
                report_lines.append(f"- [{s['severity']}] {s['suggestion']}")
        report = "\n".join(report_lines)
        return {"action": "report", "report": report, "lines": len(report_lines)}

    elif action == "save_profile":
        if not profile_name.strip():
            return {"error": "profile_name 不能为空"}
        analysis = _analyze_tool_stats()
        strategy = _recommend_tool_strategy(analysis.get("ranking", []))
        data.setdefault("profiles", {})[profile_name] = {
            "ranking": analysis.get("ranking", []),
            "strategy": strategy,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_profiles(data)
        return {"action": "saved", "profile_name": profile_name}

    elif action == "load_profile":
        if not profile_name.strip():
            return {"error": "profile_name 不能为空"}
        profile = data.get("profiles", {}).get(profile_name)
        if not profile:
            return {"error": f"配置不存在: {profile_name}"}
        return {"action": "loaded", "profile_name": profile_name, **profile}

    elif action == "list_profiles":
        profiles = {k: {"saved_at": v.get("saved_at", ""), "tools": len(v.get("ranking", []))}
                    for k, v in data.get("profiles", {}).items()}
        return {"action": "list_profiles", "count": len(profiles), "profiles": profiles}

    else:
        return {"error": f"未知操作: {action}，支持 analyze/strategy/report/save_profile/load_profile/list_profiles"}
