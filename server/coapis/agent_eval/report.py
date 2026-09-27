# -*- coding: utf-8 -*-
"""Weekly mining: aggregate runs into a weakness report.

Output lands in ``reports/agent_eval_YYYYWW.json`` (host-visible under the
server data dir) so the wecom/heartbeat layer can surface it to the user.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


def build_report(session_factory: Any) -> dict[str, Any]:
    try:  # package mode (coapis.*)
        from ..foundation.db.models import AgentRun, AgentTask
    except ImportError:  # container mode (bare agent_eval.*, cwd=/app/coapis)
        from foundation.db.models import AgentRun, AgentTask

    now = datetime.now(timezone.utc)
    iso = now.isocalendar()
    week_tag = f"{iso[0]}W{iso[1]:02d}"

    with session_factory() as session:
        runs = session.query(AgentRun).all()
        tasks = {t.task_uid: t for t in session.query(AgentTask).all()}

    by_cat: dict[str, list[AgentRun]] = {}
    for run in runs:
        cat = tasks.get(run.task_uid)
        key = cat.category if cat else "unknown"
        by_cat.setdefault(key, []).append(run)

    categories = {}
    for cat, rs in sorted(by_cat.items()):
        scores = [r.score for r in rs if r.score is not None]
        passed = sum(1 for r in rs if r.success)
        categories[cat] = {
            "runs": len(rs),
            "pass_rate": round(passed / len(rs), 4) if rs else 0.0,
            "avg_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        }

    weakest = sorted(
        ((r.task_uid, r.score if r.score is not None else 0.0, r.verdict)
         for r in runs),
        key=lambda x: x[1],
    )[:10]

    return {
        "week": week_tag,
        "generated_at": now.isoformat(),
        "total_runs": len(runs),
        "overall_pass_rate": (
            round(sum(1 for r in runs if r.success) / len(runs), 4) if runs else 0.0
        ),
        "categories": categories,
        "weakest_tasks": [
            {"task_uid": uid, "score": s, "verdict": v} for uid, s, v in weakest
        ],
    }


def emit_report(session_factory: Any, out_dir: Path | None = None) -> Path:
    rep = build_report(session_factory)
    out_dir = Path(out_dir) if out_dir else REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"agent_eval_{rep['week']}.json"
    path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
