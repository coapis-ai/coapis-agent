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

"""Unified Multi-Layer Evolution API endpoints.

Integrates Evolution Engine (Level 3 - User) and Cross-Agent Evolution (Level 1/2 - Global).
Provides REST endpoints for the three-layer architecture:
- Level 3 (User Level): Per-user evolution data
- Level 2 (Intermediate): Bucket A/B system for review
- Level 1 (Global Foundation): Verified shared knowledge
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..permissions.decorators import require_permission
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["multi-layer-evolution"])
logger = logging.getLogger(__name__)


def _get_manager(request: Request) -> Any:
    """Get MultiAgentManager from app state."""
    return request.app.state.multi_agent_manager


def _get_cross_agent_engine(request: Request) -> Any:
    """Get CrossAgentEvolution engine from app state."""
    return request.app.state.cross_agent_evolution


def _get_username(request: Request) -> str:
    """Get username from request state."""
    return request.state.username


def _get_config_profiles(request: Request) -> Dict[str, Any]:
    """Get agent profiles from config."""
    from ...config import load_config
    config = load_config()
    return config.agents.profiles


def _get_user_agents(request: Request) -> List[str]:
    """Get list of agent IDs for the current user."""
    username = _get_username(request)
    profiles = _get_config_profiles(request)
    return [
        agent_id for agent_id, profile in profiles.items()
        if getattr(profile, "username", None) == username
    ]


# =========================================================================
# Overview (Global Stats)
# =========================================================================

@router.get("/evolution/overview")
@require_permission("evolution:read")
async def get_evolution_overview(request: Request):
    """Get unified evolution overview with user-dimension stats."""
    manager = _get_manager(request)
    username = _get_username(request)
    is_admin = getattr(request.state, "role", "") == "admin"

    # Collect per-user stats
    users_stats = []
    total_experiences = 0
    total_promoted = 0
    active_users = 0

    profiles = _get_config_profiles(request)
    for agent_id, profile in profiles.items():
        profile_username = getattr(profile, "username", None)
        if not profile_username:
            continue  # Skip global agents without username

        workspace = manager.get_workspace(agent_id, username=username)
        if not workspace or not workspace.evolution_engine:
            continue

        engine = workspace.evolution_engine
        stats = engine.get_stats() if engine else {}

        exp_count = stats.get("total_experiences", 0)
        approved = stats.get("total_approved", 0)
        rejected = stats.get("total_rejected", 0)
        pending = stats.get("total_pending", 0)

        # Accumulate per-user
        user_entry = next(
            (u for u in users_stats if u["username"] == profile_username),
            None
        )
        if user_entry:
            user_entry["agent_count"] += 1
            user_entry["experience_count"] += exp_count
            user_entry["promoted_count"] += approved
        else:
            users_stats.append({
                "username": profile_username,
                "agent_count": 1,
                "experience_count": exp_count,
                "promoted_count": approved,
            })

        total_experiences += exp_count
        total_promoted += approved
        if exp_count > 0:
            active_users += 1

    # Get bucket stats from CrossAgentEvolution
    cross_engine = _get_cross_agent_engine(request)
    bucket_a_count = 0
    bucket_b_count = 0
    if cross_engine:
        bucket_a_count = getattr(cross_engine, "bucket_a_count", len(getattr(cross_engine, "bucket_a", [])))
        bucket_b_count = getattr(cross_engine, "bucket_b_count", len(getattr(cross_engine, "bucket_b", [])))

    promotion_rate = (total_promoted / total_experiences * 100) if total_experiences > 0 else 0

    # Non-admin users only see their own stats
    if not is_admin:
        users_stats = [u for u in users_stats if u["username"] == username]

    return {
        "total_experiences": total_experiences,
        "promoted_count": total_promoted,
        "promotion_rate": round(promotion_rate, 1),
        "active_users": active_users,
        "active_agents": len(profiles),
        "bucket_a_count": bucket_a_count,
        "bucket_b_count": bucket_b_count,
        "users": users_stats,
    }


# =========================================================================
# User Level (Level 3) - Per-User Evolution
# =========================================================================

@router.get("/evolution/user/{username}")
@require_permission("evolution:read")
async def get_user_evolution_status(
    request: Request,
    username: str,
):
    """Get evolution status for a specific user (all their agents)."""
    is_admin = getattr(request.state, "role", "") == "admin"
    current_username = _get_username(request)

    # Non-admin can only view their own data
    if not is_admin and username != current_username:
        raise HTTPException(status_code=403, detail="Access denied")

    manager = _get_manager(request)

    # Find all agents for this user
    user_agents = []
    total_experiences = 0
    total_pending = 0
    total_approved = 0
    total_rejected = 0

    profiles = _get_config_profiles(request)
    for agent_id, profile in profiles.items():
        profile_username = getattr(profile, "username", None)
        if profile_username != username:
            continue

        workspace = manager.get_workspace(agent_id, username=username)
        if not workspace or not workspace.evolution_engine:
            user_agents.append({
                "agent_id": agent_id,
                "enabled": False,
                "trajectory_count": 0,
                "pending_experiences": 0,
                "approved_experiences": 0,
                "rejected_experiences": 0,
            })
            continue

        engine = workspace.evolution_engine
        stats = engine.get_stats() if engine else {}

        agent_entry = {
            "agent_id": agent_id,
            "enabled": engine.enabled,
            "trajectory_count": stats.get("trajectory_count", 0),
            "pending_experiences": stats.get("total_pending", 0),
            "approved_experiences": stats.get("total_approved", 0),
            "rejected_experiences": stats.get("total_rejected", 0),
        }
        user_agents.append(agent_entry)

        total_experiences += stats.get("total_experiences", 0)
        total_pending += stats.get("total_pending", 0)
        total_approved += stats.get("total_approved", 0)
        total_rejected += stats.get("total_rejected", 0)

    return {
        "username": username,
        "agents": user_agents,
        "total_experiences": total_experiences,
        "total_pending": total_pending,
        "total_approved": total_approved,
        "total_rejected": total_rejected,
    }


@router.get("/evolution/user/{username}/experiences")
@require_permission("evolution:read")
async def list_user_experiences(
    request: Request,
    username: str,
    status: str = Query("all", description="Filter by status: all, pending, approved, rejected, promoted"),
    limit: int = Query(50, ge=1, le=200, description="Max experiences to return"),
):
    """List experiences for a specific user across all their agents."""
    is_admin = getattr(request.state, "role", "") == "admin"
    current_username = _get_username(request)

    if not is_admin and username != current_username:
        raise HTTPException(status_code=403, detail="Access denied")

    manager = _get_manager(request)
    all_experiences = []

    profiles = _get_config_profiles(request)
    for agent_id, profile in profiles.items():
        if getattr(profile, "username", None) != username:
            continue

        workspace = manager.get_workspace(agent_id, username=username)
        if not workspace or not workspace.evolution_engine:
            continue

        engine = workspace.evolution_engine
        exp_dir = engine.data_dir / "evolution" / "experiences"
        if not exp_dir.exists():
            continue

        for exp_file in exp_dir.glob("*.json"):
            try:
                exp_data = json.loads(exp_file.read_text())
                exp_data["source_agent"] = agent_id
                exp_data["source_user"] = username

                # Status filter
                if status != "all" and exp_data.get("status") != status:
                    continue

                all_experiences.append(exp_data)
            except (json.JSONDecodeError, OSError):
                continue

    # Sort by created_at descending
    all_experiences.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {
        "experiences": all_experiences[:limit],
        "total": len(all_experiences),
    }


@router.get("/evolution/user/{username}/agents")
@require_permission("evolution:read")
async def get_user_agents(
    request: Request,
    username: str,
):
    """Get list of agents for a specific user."""
    is_admin = getattr(request.state, "role", "") == "admin"
    current_username = _get_username(request)

    if not is_admin and username != current_username:
        raise HTTPException(status_code=403, detail="Access denied")

    manager = _get_manager(request)
    agents = []

    profiles = _get_config_profiles(request)
    for agent_id, profile in profiles.items():
        if getattr(profile, "username", None) == username:
            # Read agent name from agent.json (AgentProfileRef has no 'name' field)
            agent_name = agent_id
            try:
                agent_json_path = (WORKING_DIR / profile.workspace_dir / "agent.json")
                if agent_json_path.exists():
                    import json as _json
                    agent_data = _json.loads(agent_json_path.read_text())
                    agent_name = agent_data.get("name", agent_id)
            except Exception:
                pass
            agents.append({
                "agent_id": agent_id,
                "name": agent_name,
                "enabled": profile.enabled,
            })

    return {"agents": agents}


# =========================================================================
# Intermediate Layer (Level 2) - Bucket Management
# =========================================================================

@router.get("/evolution/bucket-a")
@require_permission("evolution:read")
async def get_bucket_a(
    request: Request,
    status: str = Query("all", description="Filter by status"),
    username: str = Query(None, description="Filter by source user (admin only)"),
):
    """Get Bucket A entries (reviewed & accepted experiences)."""
    cross_engine = _get_cross_agent_engine(request)
    if not cross_engine:
        return {"entries": [], "total": 0}

    entries = cross_engine.bucket_a

    # Filter by status
    if status != "all":
        entries = [e for e in entries if e.status == status]

    # Filter by username (admin only)
    is_admin = getattr(request.state, "role", "") == "admin"
    if username and is_admin:
        entries = [e for e in entries if e.source_user == username]
    elif username and not is_admin:
        raise HTTPException(status_code=403, detail="Only admin can filter by user")

    return {"entries": [e.to_dict() for e in entries], "total": len(entries)}


@router.get("/evolution/bucket-b")
@require_permission("evolution:read")
async def get_bucket_b(
    request: Request,
    status: str = Query("all", description="Filter by status"),
    username: str = Query(None, description="Filter by source user (admin only)"),
):
    """Get Bucket B entries (pending review experiences)."""
    cross_engine = _get_cross_agent_engine(request)
    if not cross_engine:
        return {"entries": [], "total": 0}

    entries = cross_engine.bucket_b

    if status != "all":
        entries = [e for e in entries if e.status == status]

    is_admin = getattr(request.state, "role", "") == "admin"
    if username and is_admin:
        entries = [e for e in entries if e.source_user == username]
    elif username and not is_admin:
        raise HTTPException(status_code=403, detail="Only admin can filter by user")

    return {"entries": [e.to_dict() for e in entries], "total": len(entries)}


@router.post("/evolution/review/{experience_id}")
@require_permission("evolution:write")
async def review_experience(
    request: Request,
    experience_id: str,
    action: str = Query(..., description="'approve' or 'reject'"),
    comment: str = Query("", description="Review comment"),
):
    """Review an experience in Bucket B (approve → Bucket A, reject → archived)."""
    cross_engine = _get_cross_agent_engine(request)
    if not cross_engine:
        raise HTTPException(status_code=500, detail="Cross-agent evolution not configured")

    # Find experience in bucket B (ExperienceEntry dataclass objects)
    bucket_b = cross_engine.bucket_b
    exp = next((e for e in bucket_b if e.id == experience_id), None)

    if not exp:
        raise HTTPException(status_code=404, detail="Experience not found in Bucket B")

    if action == "approve":
        exp.status = "reviewed"
        exp.review_result = comment or "Approved"
        # Move to bucket A
        cross_engine._bucket_b.remove(exp)
        cross_engine._bucket_a.append(exp)
        cross_engine._save_bucket_a()
        cross_engine._save_bucket_b()
        message = "Experience approved and moved to Bucket A"
    elif action == "reject":
        exp.status = "rejected"
        exp.review_result = comment or "Rejected"
        cross_engine._bucket_b.remove(exp)
        cross_engine._save_bucket_b()
        message = "Experience rejected"
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'approve' or 'reject'")

    return {"success": True, "message": message}


# =========================================================================
# Global Foundation Layer (Level 1)
# =========================================================================

@router.get("/evolution/foundation")
@require_permission("evolution:read")
async def list_foundation_entries(
    request: Request,
    limit: int = Query(100, ge=1, le=500, description="Max entries to return"),
):
    """List entries in the global foundation layer (independent storage)."""
    cross_engine = _get_cross_agent_engine(request)
    if not cross_engine:
        return {"entries": [], "total": 0}

    # Read from independent foundation storage
    foundation = cross_engine.foundation
    foundation.sort(key=lambda x: x.promoted_at or "", reverse=True)
    return {"entries": [e.to_dict() for e in foundation[:limit]], "total": len(foundation)}


@router.post("/evolution/promote/{experience_id}")
@require_permission("evolution:write")
@require_permission("admin:admin")
async def promote_to_foundation(
    request: Request,
    experience_id: str,
    comment: str = Query("", description="Promotion comment"),
):
    """Promote an experience from Bucket A to global foundation (independent storage)."""
    cross_engine = _get_cross_agent_engine(request)
    if not cross_engine:
        raise HTTPException(status_code=500, detail="Cross-agent evolution not configured")

    exp = cross_engine.promote_to_foundation(
        experience_id=experience_id,
        promoted_by=_get_username(request),
        comment=comment,
    )
    if not exp:
        raise HTTPException(status_code=404, detail="Experience not found in Bucket A")

    return {"success": True, "message": "Experience promoted to foundation"}


@router.post("/evolution/demote/{experience_id}")
@require_permission("evolution:write")
@require_permission("admin:admin")
async def demote_from_foundation(
    request: Request,
    experience_id: str,
    comment: str = Query("", description="Demotion reason"),
):
    """Demote an experience from global foundation back to Bucket A."""
    cross_engine = _get_cross_agent_engine(request)
    if not cross_engine:
        raise HTTPException(status_code=500, detail="Cross-agent evolution not configured")

    exp = cross_engine.demote_from_foundation(
        experience_id=experience_id,
        comment=comment,
    )
    if not exp:
        raise HTTPException(status_code=404, detail="Promoted experience not found in foundation")

    return {"success": True, "message": "Experience demoted from foundation"}


@router.get("/evolution/archive")
@require_permission("evolution:read")
@require_permission("admin:admin")
async def list_archived_entries(
    request: Request,
    limit: int = Query(100, ge=1, le=500, description="Max entries to return"),
    month: str = Query(None, description="Filter by month (YYYYMM format)"),
):
    """List archived experience entries."""
    cross_engine = _get_cross_agent_engine(request)
    if not cross_engine:
        return {"entries": [], "total": 0}

    entries = []
    archive_dir = cross_engine._archive_dir
    if not archive_dir.exists():
        return {"entries": [], "total": 0}

    for archive_file in sorted(archive_dir.glob("archived_*.json"), reverse=True):
        if month:
            month_str = archive_file.stem.replace("archived_", "")
            if month_str != month:
                continue
        try:
            import json as _json
            with open(archive_file, "r", encoding="utf-8") as f:
                data = _json.load(f)
            entries.extend(data)
        except Exception:
            continue
        if len(entries) >= limit:
            break

    return {"entries": entries[:limit], "total": len(entries)}


@router.post("/evolution/archive/cleanup")
@require_permission("evolution:write")
@require_permission("admin:admin")
async def cleanup_expired_archives(
    request: Request,
):
    """Clean up expired archive files."""
    cross_engine = _get_cross_agent_engine(request)
    if not cross_engine:
        raise HTTPException(status_code=500, detail="Cross-agent evolution not configured")

    cleaned = cross_engine.cleanup_expired_archives()
    return {"success": True, "cleaned": cleaned}


@router.get("/evolution/bucket-stats")
@require_permission("evolution:read")
async def get_bucket_stats(
    request: Request,
):
    """Get bucket statistics including foundation."""
    cross_engine = _get_cross_agent_engine(request)
    if not cross_engine:
        return {}
    return cross_engine.get_bucket_stats()


# =========================================================================
# Backward Compatibility - Proxy to old endpoints
# =========================================================================

@router.get("/evolution/status")
@require_permission("evolution:read")
async def get_evolution_status_proxy(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
):
    """Proxy to old evolution status endpoint for backward compatibility."""
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine:
        return {"enabled": False, "message": "Evolution engine not configured"}

    return {
        "enabled": engine.enabled,
        "agent_id": agent_id,
        "current_session": engine._current_session_id,
        "trajectory_count": len(engine._current_trajectory),
        "pending_experiences": len(engine._pending_experiences),
    }
