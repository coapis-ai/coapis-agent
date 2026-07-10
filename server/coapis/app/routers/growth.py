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

"""Growth system API endpoints.

Provides REST endpoints for:
- Growth system status and statistics
- Review history
- Nudge configuration
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..permissions.decorators import require_permission
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["growth"])
logger = logging.getLogger(__name__)


def _get_manager(request: Request) -> Any:
    """Get MultiAgentManager from app state."""
    return request.app.state.multi_agent_manager


# =========================================================================
# Growth System Status
# =========================================================================

@router.get("/growth/stats")
async def get_growth_stats(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
) -> Dict[str, Any]:
    """Get growth system statistics for an agent."""
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    growth = workspace.growth
    if not growth:
        return {"enabled": False, "message": "Growth system not configured for this agent"}

    return {
        "enabled": True,
        "agent_id": agent_id,
        "turns_since_memory": growth.turns_since_memory,
        "calls_since_skill": growth.calls_since_skill,
        "memory_nudge_interval": growth.memory_nudge_interval,
        "skill_nudge_interval": growth.skill_nudge_interval,
        "review_count": len(growth._review_log),
        "last_review_time": str(growth._last_review_time) if growth._last_review_time else None,
    }


@router.get("/growth/reviews")
@require_permission("admin:admin")
async def get_growth_reviews(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
    limit: int = Query(20, ge=1, le=100, description="Number of reviews to return"),
) -> Dict[str, Any]:
    """Get growth review history for an agent."""
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    growth = workspace.growth
    if not growth:
        return {"reviews": [], "message": "Growth system not configured"}

    reviews = growth._review_log[-limit:]
    return {
        "agent_id": agent_id,
        "reviews": reviews,
        "total": len(growth._review_log),
    }


@router.post("/growth/nudge/memory")
@require_permission("admin:admin")
async def trigger_memory_nudge(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
) -> Dict[str, Any]:
    """Trigger a memory review nudge manually."""
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    growth = workspace.growth
    if not growth:
        raise HTTPException(status_code=503, detail="Growth system not available")

    # Reset counter to trigger nudge on next check
    growth.turns_since_memory = growth.memory_nudge_interval
    return {
        "status": "triggered",
        "agent_id": agent_id,
        "message": "Memory nudge counter reset, will trigger on next turn",
    }


@router.post("/growth/nudge/skill")
@require_permission("admin:admin")
async def trigger_skill_nudge(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
) -> Dict[str, Any]:
    """Trigger a skill review nudge manually."""
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    growth = workspace.growth
    if not growth:
        raise HTTPException(status_code=503, detail="Growth system not available")

    # Reset counter to trigger nudge on next check
    growth.calls_since_skill = growth.skill_nudge_interval
    return {
        "status": "triggered",
        "agent_id": agent_id,
        "message": "Skill nudge counter reset, will trigger on next tool call",
    }
