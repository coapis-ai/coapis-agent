# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
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

"""Cron job management API routes (user-scoped).

Each user has their own CronManager instance with isolated storage.
Storage path: workspaces/{username}/crons/jobs.json
"""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Request

from .manager import CronManager
from .models import CronExecutionRecord, CronJobSpec, CronJobView
from .registry import get_user_cron_manager
from ..permissions.decorators import require_permission

router = APIRouter(prefix="/cron", tags=["cron"])


@router.get("/jobs", response_model=list[CronJobSpec])
@require_permission("cron-jobs:read")
async def list_jobs(request: Request, mgr: CronManager = Depends(get_user_cron_manager)):
    """List cron jobs for the current user."""
    return await mgr.list_jobs()


@router.get("/jobs/{job_id}", response_model=CronJobView)
@require_permission("cron-jobs:read")
async def get_job(request: Request, job_id: str, mgr: CronManager = Depends(get_user_cron_manager)):
    """Get a specific cron job."""
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return CronJobView(spec=job, state=mgr.get_state(job_id))


@router.post("/jobs", response_model=CronJobSpec)
@require_permission("cron-jobs:write")
async def create_job(
    request: Request,
    spec: CronJobSpec,
    mgr: CronManager = Depends(get_user_cron_manager),
):
    """Create a new cron job for the current user.

    Security: target_user_id is always overridden to the authenticated user
    to prevent cross-user workspace access via cron jobs.
    """
    job_id = str(uuid.uuid4())
    # Force target_user_id to current user — prevents one user from
    # creating a cron job that executes in another user's workspace
    current_user = request.state.username
    if spec.dispatch and spec.dispatch.target:
        spec.dispatch.target.user_id = current_user
    # 默认 agent_id 为 "default"（用户未指定时）
    if not spec.agent_id:
        spec.agent_id = "default"
    created = spec.model_copy(update={"id": job_id})
    await mgr.create_or_replace_job(created)
    return created


@router.put("/jobs/{job_id}", response_model=CronJobSpec)
@require_permission("cron-jobs:write")
async def replace_job(
    request: Request,
    job_id: str,
    spec: CronJobSpec,
    mgr: CronManager = Depends(get_user_cron_manager),
):
    """Replace an existing cron job.

    Security: target_user_id is always overridden to the authenticated user.
    """
    if spec.id is None:
        spec.id = job_id
    elif spec.id != job_id:
        raise HTTPException(status_code=400, detail="job_id mismatch")
    # Force target_user_id to current user
    current_user = request.state.username
    if spec.dispatch and spec.dispatch.target:
        spec.dispatch.target.user_id = current_user
    await mgr.create_or_replace_job(spec)
    return spec


@router.delete("/jobs/{job_id}")
@require_permission("cron-jobs:delete")
async def delete_job(
    request: Request,
    job_id: str,
    mgr: CronManager = Depends(get_user_cron_manager),
):
    """Delete a cron job."""
    deleted = await mgr.delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="job not found")
    return {"deleted": True}


@router.post("/jobs/{job_id}/run")
@require_permission("cron-jobs:execute")
async def run_job_now(
    request: Request,
    job_id: str,
    mgr: CronManager = Depends(get_user_cron_manager),
):
    """Trigger immediate execution of a cron job."""
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    result = await mgr.run_job_once(job_id)
    return {"result": result}


@router.post("/jobs/{job_id}/pause")
@require_permission("cron-jobs:write")
async def pause_job(
    request: Request,
    job_id: str,
    mgr: CronManager = Depends(get_user_cron_manager),
):
    """Pause a cron job."""
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    await mgr.pause_job(job_id)
    return {"paused": True}


@router.post("/jobs/{job_id}/resume")
@require_permission("cron-jobs:write")
async def resume_job(
    request: Request,
    job_id: str,
    mgr: CronManager = Depends(get_user_cron_manager),
):
    """Resume a paused cron job."""
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    await mgr.resume_job(job_id)
    return {"resumed": True}


@router.get("/jobs/{job_id}/state")
@require_permission("cron-jobs:read")
async def get_job_state(
    request: Request,
    job_id: str,
    mgr: CronManager = Depends(get_user_cron_manager),
):
    """Get runtime state of a cron job."""
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    state = mgr.get_state(job_id)
    return state.model_dump()


@router.get("/jobs/{job_id}/history", response_model=list[CronExecutionRecord])
@require_permission("cron-jobs:read")
async def get_job_history(
    request: Request,
    job_id: str,
    limit: int = 20,
    mgr: CronManager = Depends(get_user_cron_manager),
):
    """Get execution history for a cron job.

    Returns the most recent execution records (default 20, max 50).
    Records include run_at, status, duration, error, and trigger_type.
    """
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    limit = max(1, min(limit, 50))
    return mgr.get_history(job_id, limit=limit)
