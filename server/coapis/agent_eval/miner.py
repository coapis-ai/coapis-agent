# -*- coding: utf-8 -*-
"""Weekly mining of online + benchmark trajectories (M0-b).

Inputs:
    * ``agent_trajectories`` rows with ``run_id IS NULL`` (online samples,
      last N days)
    * the latest benchmark ``AgentRun`` batch

Output: a markdown report written to
``{WORKSPACES_DIR}/system/agent_eval_reports/weekly_{ISO-year}-W{week}.md``.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..constant import WORKSPACES_DIR
from ..foundation.db.engine import get_session_factory
from ..foundation.db.models import AgentRun, AgentTrajectory

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(WORKSPACES_DIR) / "system" / "agent_eval_reports"


def mine_online(days: int = 7) -> dict:
    """Aggregate the last ``days`` of online-sampled trajectories."""
    # created_at is a Unix epoch float (data-layer convention) — compare
    # against an epoch, not a datetime object.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    factory = get_session_factory()
    with factory() as s:
        rows = (
            s.query(AgentTrajectory)
            .filter(AgentTrajectory.run_id.is_(None),
                    AgentTrajectory.created_at >= cutoff)
            .all()
        )
    total = len(rows)
    tool_usage: Counter = Counter()
    tool_errors: Counter = Counter()
    empty_answers = 0
    for r in rows:
        if not (r.final_answer or "").strip():
            empty_answers += 1
        try:
            steps = json.loads(r.trace or "[]")
        except (TypeError, ValueError):
            steps = []
        for st in steps:
            if isinstance(st, dict) and st.get("kind") == "tool":
                name = str(st.get("name") or "?")
                tool_usage[name] += 1
                if not st.get("ok", True):
                    tool_errors[name] += 1
    return {
        "window_days": days,
        "samples": total,
        "empty_answers": empty_answers,
        "tool_usage": dict(tool_usage.most_common()),
        "tool_errors": dict(tool_errors.most_common()),
    }


def latest_benchmark_runs(limit: int = 40) -> list:
    """Most recent benchmark batch (rows stay attached for the caller)."""
    factory = get_session_factory()
    with factory() as s:
        runs = (
            s.query(AgentRun)
            .order_by(AgentRun.id.desc())
            .limit(limit)
            .all()
        )
    # detach-safe: copy the fields we render
    return [
        {
            "task_uid": r.task_uid,
            "verdict": r.verdict,
            "score": float(r.score or 0.0),
            "success": bool(r.success),
            "duration_ms": int(r.duration_ms or 0),
            "metrics": _safe_json(r.metrics),
        }
        for r in reversed(runs)
    ]


def _safe_json(raw) -> dict:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (TypeError, ValueError):
        return {}


def build_weekly_markdown(online: dict, runs: list[dict]) -> str:
    now = datetime.now(timezone.utc)
    lines = [
        "# 智能体能力周报 (Agent Eval Weekly)",
        "",
        f"- 生成时间: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"- 在线窗口: 近 {online['window_days']} 天，采样 {online['samples']} 条"
        f"（空回答 {online['empty_answers']} 条）",
        "",
        "## 基准（最近一批）",
        "",
    ]
    if runs:
        passed = sum(1 for r in runs if r["verdict"] == "pass")
        avg = sum(r["score"] for r in runs) / len(runs)
        lines += [
            f"- 通过率: {passed}/{len(runs)} ({passed / len(runs):.0%})",
            f"- 平均分: {avg:.3f}",
            "",
            "| 任务 | 判定 | 分数 | 工具调用 | LLM轮次 | 耗时(s) |",
            "|---|---|---|---|---|---|",
        ]
        for r in sorted(runs, key=lambda x: x["task_uid"]):
            m = r["metrics"]
            lines.append("| %s | %s | %.3f | %s | %s | %d |" % (
                r["task_uid"], r["verdict"], r["score"],
                m.get("tool_calls", "-"), m.get("llm_calls", "-"),
                r["duration_ms"] // 1000,
            ))
    else:
        lines.append("- （暂无基准运行记录）")
    lines += ["", "## 在线工具使用 Top", ""]
    if online["tool_usage"]:
        for name, cnt in list(online["tool_usage"].items())[:10]:
            err = online["tool_errors"].get(name, 0)
            lines.append(f"- {name}: {cnt} 次（失败 {err}）")
    else:
        lines.append("- （窗口内无在线采样）")
    lines.append("")
    return "\n".join(lines)


def write_weekly_report(reports_dir: Path | None = None, days: int = 7) -> Path:
    """Mine + render + persist the weekly report; returns the file path."""
    base = Path(reports_dir) if reports_dir else REPORTS_DIR
    base.mkdir(parents=True, exist_ok=True)
    online = mine_online(days=days)
    runs = latest_benchmark_runs()
    md = build_weekly_markdown(online, runs)
    now = datetime.now(timezone.utc)
    path = base / f"weekly_{now.strftime('%G')}-W{now.strftime('%V')}.md"
    path.write_text(md, encoding="utf-8")
    logger.info("[eval-miner] weekly report written: %s", path)
    return path
