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

"""Admin endpoints for the agent capability evaluation system (M0).

Read endpoints serve dataset/run/report data from the foundation DB.
``POST /runs`` launches the eval runner as a detached subprocess so a
long benchmark never blocks the API event loop.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import coapis

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..permissions.decorators import require_permission
from ...foundation.db.engine import get_session_factory
from ...foundation.db.models import AgentRun, AgentTask, AgentTrajectory
from ...agent_eval.dataset.loader import list_categories, load_tasks
from ...agent_eval.report import REPORTS_DIR, build_report, emit_report

router = APIRouter(tags=["admin/agent-eval"])


def _ts_iso(epoch: Optional[float]) -> Optional[str]:
    """Epoch float (data-layer convention) -> UTC ISO-8601 string."""
    if not epoch:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


class RunTriggerRequest(BaseModel):
    category: Optional[str] = None
    tasks: Optional[list[str]] = None
    limit: int = 0
    source_user: str = "admin"


# --------------------------------------------------------------------- #
# dataset
# --------------------------------------------------------------------- #
@router.get("/admin/agent-eval/categories")
@require_permission("admin:admin")
async def get_categories() -> dict[str, Any]:
    cats = list_categories()
    tasks = load_tasks()
    return {"categories": cats, "counts": {
        c: sum(1 for t in tasks if t["category"] == c) for c in cats
    }}


@router.get("/admin/agent-eval/tasks")
@require_permission("admin:admin")
async def get_tasks(
    category: Optional[str] = Query(None),
) -> dict[str, Any]:
    tasks = load_tasks(category)
    slim = [{k: t[k] for k in
             ("uid", "title", "category", "difficulty")} for t in tasks]
    return {"total": len(slim), "tasks": slim}


# --------------------------------------------------------------------- #
# runs
# --------------------------------------------------------------------- #
@router.get("/admin/agent-eval/runs")
@require_permission("admin:admin")
async def list_runs(
    agent_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
) -> dict[str, Any]:
    factory = get_session_factory()
    with factory() as session:
        q = session.query(AgentRun)
        if agent_id:
            q = q.filter(AgentRun.agent_id == agent_id)
        runs = q.order_by(AgentRun.started_at.desc()).limit(limit).all()
        if category:
            task_rows = session.query(AgentTask).filter(
                AgentTask.category == category).all()
            uids = {t.task_uid for t in task_rows}
            runs = [r for r in runs if r.task_uid in uids]
        return {"total": len(runs), "runs": [
            {
                "id": r.id, "task_uid": r.task_uid, "agent_id": r.agent_id,
                "started_at": r.started_at, "duration_ms": r.duration_ms,
                "success": r.success, "score": r.score, "verdict": r.verdict,
            } for r in runs
        ]}


@router.get("/admin/agent-eval/runs/{run_id}")
@require_permission("admin:admin")
async def get_run_detail(run_id: int) -> dict[str, Any]:
    factory = get_session_factory()
    with factory() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        traj = (session.query(AgentTrajectory)
                .filter(AgentTrajectory.run_id == run.id).first())
        return {
            "id": run.id, "task_uid": run.task_uid, "agent_id": run.agent_id,
            "started_at": run.started_at, "finished_at": run.finished_at,
            "duration_ms": run.duration_ms, "success": run.success,
            "score": run.score, "verdict": run.verdict,
            "metrics": json.loads(run.metrics) if run.metrics else None,
            "trajectory": {
                "steps": traj.steps, "tool_calls": traj.tool_calls,
                "llm_calls": traj.llm_calls,
                "input_tokens": traj.input_tokens,
                "output_tokens": traj.output_tokens,
                "final_answer": traj.final_answer,
                "trace": json.loads(traj.trace) if traj.trace else [],
            } if traj else None,
        }


# --------------------------------------------------------------------- #
# trigger
# --------------------------------------------------------------------- #
@router.post("/admin/agent-eval/runs")
@require_permission("admin:admin")
async def trigger_runs(req: RunTriggerRequest) -> dict[str, Any]:
    """Launch the benchmark in a detached subprocess (non-blocking)."""
    # Package mode: coapis.* must stay importable, so cwd is the directory
    # that contains the coapis package (derived, not hard-coded).
    pkg_root = str(Path(coapis.__file__).resolve().parents[1])
    cmd = [sys.executable, "-m", "coapis.agent_eval.runner",
           "--source-user", req.source_user]
    if req.category:
        cmd += ["--category", req.category]
    if req.tasks:
        cmd += ["--tasks", *req.tasks]
    if req.limit:
        cmd += ["--limit", str(req.limit)]
    proc = subprocess.Popen(
        cmd, cwd=pkg_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return {"pid": proc.pid, "cmd": " ".join(cmd),
            "note": "benchmark running in background; poll GET /runs"}


# --------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------- #
@router.get("/admin/agent-eval/report/latest")
@require_permission("admin:admin")
async def latest_report() -> dict[str, Any]:
    factory = get_session_factory()
    return build_report(factory)


@router.post("/admin/agent-eval/report")
@require_permission("admin:admin")
async def refresh_report() -> dict[str, Any]:
    factory = get_session_factory()
    path = await asyncio.to_thread(emit_report, factory)
    return {"written": str(path),
            "report": json.loads(path.read_text(encoding="utf-8"))}


# --------------------------------------------------------------------- #
# baseline / online trajectories / weekly report
# --------------------------------------------------------------------- #
@router.get("/admin/agent-eval/baseline")
@require_permission("admin:admin")
async def get_baseline() -> dict[str, Any]:
    """Latest benchmark batch summary (per-category pass rates + averages)."""
    from collections import defaultdict
    factory = get_session_factory()
    with factory() as s:
        runs = s.query(AgentRun).order_by(AgentRun.id.desc()).limit(40).all()
    if not runs:
        return {"runs": 0, "overall": None, "by_category": {}}
    cats: dict[str, list[float]] = defaultdict(list)
    for r in runs:
        cats[r.task_uid.split("-")[0]].append(float(r.score or 0.0))
    passed = sum(1 for r in runs if r.verdict == "pass")
    overall_avg = sum(float(r.score or 0.0) for r in runs) / len(runs)
    return {
        "runs": len(runs),
        "overall": {
            "pass_rate": round(passed / len(runs), 4),
            "average_score": round(overall_avg, 4),
        },
        "by_category": {
            c: {
                "count": len(scores),
                "average_score": round(sum(scores) / len(scores), 4),
            }
            for c, scores in sorted(cats.items())
        },
    }


@router.get("/admin/agent-eval/trajectories")
@require_permission("admin:admin")
async def list_trajectories(
    online_only: bool = Query(False, description="只返回在线采样（run_id IS NULL）"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Recent trajectories, newest first. ``online_only`` scopes to the
    sampled production turns mined by the weekly report."""
    factory = get_session_factory()
    with factory() as s:
        q = s.query(AgentTrajectory).order_by(AgentTrajectory.id.desc()).limit(limit)
        if online_only:
            q = q.filter(AgentTrajectory.run_id.is_(None))
        rows = q.all()
    return {
        "count": len(rows),
        "items": [
            {
                "id": t.id,
                "run_id": t.run_id,
                "steps": t.steps,
                "tool_calls": t.tool_calls,
                "llm_calls": t.llm_calls,
                "duration_ms": t.duration_ms,
                "final_answer": (t.final_answer or "")[:500],
                "created_at": _ts_iso(t.created_at),
            }
            for t in rows
        ],
    }


@router.get("/admin/agent-eval/report/weekly")
@require_permission("admin:admin")
async def weekly_report_now(force: bool = Query(False)) -> dict[str, Any]:
    """Render the weekly report on demand. With ``force=true`` it is also
    written to disk (same path as the Friday 18:00 job)."""
    from datetime import datetime, timezone
    from ...agent_eval.miner import (
        REPORTS_DIR,
        build_weekly_markdown,
        latest_benchmark_runs,
        mine_online,
    )
    online = mine_online(days=7)
    runs = latest_benchmark_runs()
    md = build_weekly_markdown(online, runs)
    path = None
    if force:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        path = REPORTS_DIR / f"weekly_{now.strftime('%G')}-W{now.strftime('%V')}.md"
        path.write_text(md, encoding="utf-8")
        path = str(path)
    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "markdown": md, "path": path}
