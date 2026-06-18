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

"""Cron router - Cron job endpoints with user isolation.

Each user's cron jobs are stored in: workspaces/{username}/crons/cron_jobs.json
This ensures complete isolation between users.
"""

import logging
import json
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.requests import Request
from pydantic import BaseModel

from ..permissions.decorators import require_permission
from ..constant import WORKSPACES_DIR

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cron"])


class CronJobSpecInput(BaseModel):
    name: str
    schedule: str
    command: str
    enabled: bool = True
    agent_id: Optional[str] = None


class CronJobSpecOutput(CronJobSpecInput):
    id: str = ""
    created_at: str = ""
    updated_at: str = ""


class CronJobView(CronJobSpecOutput):
    next_run: Optional[str] = None
    last_run: Optional[str] = None
    status: str = "idle"


# Per-user cron store: {username: {job_id: CronJobSpecOutput}}
_cron_jobs: Dict[str, Dict[str, CronJobSpecOutput]] = {}


def _get_cron_file(username: str) -> Path:
    """Get cron file path for a specific user."""
    return WORKSPACES_DIR / username / "crons" / "cron_jobs.json"


def _load_cron_jobs(username: str):
    """Load cron jobs from disk for a specific user."""
    if username in _cron_jobs:
        return  # Already loaded
    cron_file = _get_cron_file(username)
    user_jobs: Dict[str, CronJobSpecOutput] = {}
    if cron_file.exists():
        try:
            with open(cron_file) as f:
                data = json.load(f)
            for item in data:
                user_jobs[item["id"]] = CronJobSpecOutput(**item)
        except Exception as e:
            logger.error(f"Failed to load cron jobs for {username}: {e}")
    _cron_jobs[username] = user_jobs


def _save_cron_jobs(username: str):
    """Save cron jobs to disk for a specific user."""
    cron_file = _get_cron_file(username)
    cron_file.parent.mkdir(parents=True, exist_ok=True)
    user_jobs = _cron_jobs.get(username, {})
    try:
        with open(cron_file, "w") as f:
            json.dump([j.dict() for j in user_jobs.values()], f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save cron jobs for {username}: {e}")


def _get_user_jobs(request: Request) -> Dict[str, CronJobSpecOutput]:
    """Get cron jobs for the current user."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")
    _load_cron_jobs(username)
    return _cron_jobs.get(username, {})


@router.get("/cron/jobs")
@require_permission("cron-jobs:read")
async def list_cron_jobs(request: Request) -> List[Dict[str, Any]]:
    """List cron jobs for the current user."""
    user_jobs = _get_user_jobs(request)
    return [j.dict() for j in user_jobs.values()]


@router.post("/cron/jobs")
@require_permission("cron-jobs:write")
async def create_cron_job(
    request: Request,
    payload: CronJobSpecInput = Body(...),
) -> Dict[str, Any]:
    """Create a new cron job for the current user."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    _load_cron_jobs(username)
    user_jobs = _cron_jobs.setdefault(username, {})

    job_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    job = CronJobSpecOutput(
        id=job_id,
        name=payload.name,
        schedule=payload.schedule,
        command=payload.command,
        enabled=payload.enabled,
        agent_id=payload.agent_id,
        created_at=now,
        updated_at=now,
    )

    user_jobs[job_id] = job
    _save_cron_jobs(username)

    return job.dict()


@router.get("/cron/jobs/{job_id}")
@require_permission("cron-jobs:read")
async def get_cron_job(
    request: Request,
    job_id: str,
) -> Dict[str, Any]:
    """Get cron job details for the current user."""
    user_jobs = _get_user_jobs(request)
    if job_id not in user_jobs:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return user_jobs[job_id].dict()


@router.put("/cron/jobs/{job_id}")
@require_permission("cron-jobs:write")
async def replace_cron_job(
    request: Request,
    job_id: str,
    payload: CronJobSpecInput = Body(...),
) -> Dict[str, Any]:
    """Replace a cron job for the current user."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_jobs = _get_user_jobs(request)
    if job_id not in user_jobs:
        raise HTTPException(status_code=404, detail="Cron job not found")

    now = datetime.now().isoformat()
    job = CronJobSpecOutput(
        id=job_id,
        name=payload.name,
        schedule=payload.schedule,
        command=payload.command,
        enabled=payload.enabled,
        agent_id=payload.agent_id,
        created_at=user_jobs[job_id].created_at,
        updated_at=now,
    )

    user_jobs[job_id] = job
    _save_cron_jobs(username)

    return job.dict()


@router.delete("/cron/jobs/{job_id}")
@require_permission("cron-jobs:write")
async def delete_cron_job(
    request: Request,
    job_id: str,
) -> Dict[str, Any]:
    """Delete a cron job for the current user."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_jobs = _get_user_jobs(request)
    if job_id in user_jobs:
        del user_jobs[job_id]
        _save_cron_jobs(username)
    return {}


@router.post("/cron/jobs/{job_id}/pause")
@require_permission("cron-jobs:write")
async def pause_cron_job(
    request: Request,
    job_id: str,
) -> Dict[str, Any]:
    """Pause a cron job for the current user."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_jobs = _get_user_jobs(request)
    if job_id not in user_jobs:
        raise HTTPException(status_code=404, detail="Cron job not found")
    user_jobs[job_id].enabled = False
    _save_cron_jobs(username)
    return {}


@router.post("/cron/jobs/{job_id}/resume")
@require_permission("cron-jobs:write")
async def resume_cron_job(
    request: Request,
    job_id: str,
) -> Dict[str, Any]:
    """Resume a cron job for the current user."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_jobs = _get_user_jobs(request)
    if job_id not in user_jobs:
        raise HTTPException(status_code=404, detail="Cron job not found")
    user_jobs[job_id].enabled = True
    _save_cron_jobs(username)
    return {}


@router.post("/cron/jobs/{job_id}/run")
@require_permission("cron-jobs:write")
async def run_cron_job(
    request: Request,
    job_id: str,
) -> Dict[str, Any]:
    """Run a cron job immediately for the current user."""
    user_jobs = _get_user_jobs(request)
    if job_id not in user_jobs:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return {"success": True}


@router.get("/cron/jobs/{job_id}/state")
@require_permission("cron-jobs:read")
async def get_cron_job_state(
    request: Request,
    job_id: str,
) -> Dict[str, Any]:
    """Get cron job state for the current user."""
    user_jobs = _get_user_jobs(request)
    if job_id not in user_jobs:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return {"state": "idle"}


# Startup hook
async def init_cron_jobs():
    """Initialize cron jobs on startup (load all existing users)."""
    for user_dir in WORKSPACES_DIR.iterdir():
        if user_dir.is_dir():
            _load_cron_jobs(user_dir.name)
    total = sum(len(v) for v in _cron_jobs.values())
    logger.info(f"Loaded {total} cron jobs for {len(_cron_jobs)} users")
