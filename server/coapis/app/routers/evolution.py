# -*- coding: utf-8 -*-
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

"""Evolution monitoring API endpoints.

Provides REST endpoints for:
- Evolution engine status and statistics
- Trajectory query and export
- Experience extraction triggers and results
- Knowledge flow monitoring
- Backend review status and history
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..permissions.decorators import require_permission
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["evolution"])
logger = logging.getLogger(__name__)


def _get_manager(request: Request) -> Any:
    """Get MultiAgentManager from app state.
    
    The manager is stored in app.state.multi_agent_manager during create_app().
    """
    return request.app.state.multi_agent_manager


def _resolve_agent_id(request: Request, agent_id: str) -> str:
    """Resolve agent_id from request context when default."""
    if agent_id == "default":
        username = getattr(request.state, "username", None)
        if not username:
            user_info = getattr(request.state, "user_info", None)
            if user_info and isinstance(user_info, dict):
                username = user_info.get("username")
        if username and username != "anonymous":
            return f"user:{username}"
    return agent_id


# =========================================================================
# Evolution Engine Status
# =========================================================================

@router.get("/evolution/status")
@require_permission("evolution:read")
async def get_evolution_status(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
):
    """Get evolution engine status and statistics for an agent."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine:
        return {"enabled": False, "message": "Evolution engine not configured for this agent"}

    return {
        "enabled": engine.enabled,
        "agent_id": agent_id,
        "current_session": engine._current_session_id,
        "trajectory_count": len(engine._current_trajectory),
        "pending_experiences": len(engine._pending_experiences),
        "turns_since_memory_review": engine._turns_since_memory_review,
        "tools_since_skill_review": engine._tools_since_skill_review,
        "memory_nudge_interval": engine.memory_nudge_interval,
        "skill_nudge_interval": engine.skill_nudge_interval,
        "knowledge_flow": engine.knowledge_flow.get_stats() if engine.knowledge_flow else None,
        "backend_review": engine.backend_review.get_stats() if engine.backend_review else None,
    }


@router.get("/evolution/stats")
@require_permission("evolution:read")
async def get_evolution_stats(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
):
    """Get comprehensive evolution statistics for an agent."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine:
        return {"enabled": False}

    return engine.get_stats()


# =========================================================================
# Trajectory Management
# =========================================================================

@router.get("/evolution/trajectories")
@require_permission("evolution:read")
async def list_trajectories(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
    limit: int = Query(50, ge=1, le=200, description="Max trajectories to return"),
):
    """List trajectory files for an agent."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine:
        return {"trajectories": []}

    trajectory_dir = engine.data_dir / "evolution" / "trajectories"
    if not trajectory_dir.exists():
        return {"trajectories": []}

    trajectories = []
    for tf in sorted(trajectory_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)[:limit]:
        trajectories.append({
            "file": tf.name,
            "session_id": tf.stem,
            "size": tf.stat().st_size,
            "modified": tf.stat().st_mtime,
        })

    return {"trajectories": trajectories}


@router.get("/evolution/trajectories/{session_id}")
@require_permission("evolution:read")
async def get_trajectory(
    request: Request,
    session_id: str,
    agent_id: str = Query("default", description="Agent ID"),
    limit: int = Query(100, ge=1, le=500, description="Max entries to return"),
):
    """Get trajectory entries for a specific session."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine:
        raise HTTPException(status_code=404, detail="Evolution engine not configured")

    trajectory_file = engine.data_dir / "evolution" / "trajectories" / f"{session_id}.jsonl"
    if not trajectory_file.exists():
        raise HTTPException(status_code=404, detail=f"Trajectory {session_id} not found")

    entries = []
    with open(trajectory_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
            if len(entries) >= limit:
                break

    return {
        "session_id": session_id,
        "agent_id": agent_id,
        "entries": entries,
        "total": len(entries),
    }


# =========================================================================
# Experience Management
# =========================================================================

@router.get("/evolution/experiences")
@require_permission("evolution:read")
async def list_experiences(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
    status: str = Query("all", description="Filter by status: all|pending|approved|rejected"),
    limit: int = Query(50, ge=1, le=200, description="Max experiences to return"),
):
    """List extracted experiences for an agent."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine:
        return {"experiences": []}

    # Get pending experiences from engine
    experiences = []

    if status in ("all", "pending"):
        for exp in engine._pending_experiences:
            experiences.append({
                **exp.to_dict(),
                "status": "pending",
            })

    # Load stored experiences from disk
    exp_dir = engine.data_dir / "evolution" / "experiences"
    if exp_dir.exists():
        for ef in sorted(exp_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                data = json.loads(ef.read_text(encoding="utf-8"))
                if status == "all" or data.get("status") == status:
                    experiences.append(data)
            except Exception:
                pass

            if len(experiences) >= limit:
                break

    return {"experiences": experiences[:limit]}


@router.post("/evolution/experiences/extract")
@require_permission("evolution:read")
async def trigger_extraction(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
):
    """Trigger experience extraction for the current session."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine:
        raise HTTPException(status_code=400, detail="Evolution engine not configured")

    if not engine._current_trajectory:
        raise HTTPException(status_code=400, detail="No trajectory data available")

    # Trigger extraction
    experiences = await engine._extract_experiences()

    # Add to pending queue
    engine._pending_experiences.extend(experiences)

    return {
        "extracted": len(experiences),
        "pending_total": len(engine._pending_experiences),
        "experiences": [exp.to_dict() for exp in experiences],
    }


@router.post("/evolution/experiences/{experience_id}/approve")
@require_permission("evolution:read")
async def approve_experience(
    request: Request,
    experience_id: str,
    agent_id: str = Query("default", description="Agent ID"),
):
    """Approve an extracted experience for storage."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine:
        raise HTTPException(status_code=404, detail="Evolution engine not configured")

    # Find and approve the experience
    for i, exp in enumerate(engine._pending_experiences):
        if exp.experience_id == experience_id:
            approved = engine._pending_experiences.pop(i)
            approved_dict = approved.to_dict()
            approved_dict["status"] = "approved"

            # Save to disk
            exp_file = (
                engine.data_dir
                / "evolution"
                / "experiences"
                / f"{approved.experience_id}.json"
            )
            exp_file.write_text(
                json.dumps(approved_dict, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # Add to foundation memory if applicable
            if engine.foundation_manager and approved.memory_type == "long_term":
                from ...foundation import MemoryEntry

                memory = MemoryEntry(
                    content=approved.content,
                    memory_type=approved.memory_type,
                    category=approved.category,
                    tags=approved.tags,
                    priority_score=approved.confidence,
                    source_agent=approved.source_agent,
                    source_user=approved.source_user,
                    source_session=approved.source_session,
                )
                engine.foundation_manager.add_memory(memory)

            return {"approved": True, "experience": approved_dict}

    raise HTTPException(status_code=404, detail=f"Experience {experience_id} not found")


@router.post("/evolution/experiences/{experience_id}/reject")
@require_permission("evolution:read")
async def reject_experience(
    request: Request,
    experience_id: str,
    agent_id: str = Query("default", description="Agent ID"),
):
    """Reject an extracted experience."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine:
        raise HTTPException(status_code=404, detail="Evolution engine not configured")

    for i, exp in enumerate(engine._pending_experiences):
        if exp.experience_id == experience_id:
            engine._pending_experiences.pop(i)
            return {"rejected": True, "experience_id": experience_id}

    raise HTTPException(status_code=404, detail=f"Experience {experience_id} not found")


# =========================================================================
# Knowledge Flow
# =========================================================================

@router.get("/evolution/knowledge-flow/status")
@require_permission("evolution:read")
async def get_knowledge_flow_status(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
):
    """Get knowledge flow status and statistics."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine or not engine.knowledge_flow:
        return {"enabled": False, "message": "Knowledge flow not configured"}

    return engine.knowledge_flow.get_stats()


@router.get("/evolution/knowledge-flow/pending")
@require_permission("evolution:read")
async def list_pending_flows(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
):
    """List pending knowledge flow reviews."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine or not engine.knowledge_flow:
        return {"pending": []}

    return {"pending": engine.knowledge_flow.get_pending_reviews()}


@router.post("/evolution/knowledge-flow/{record_id}/approve")
@require_permission("evolution:read")
async def approve_flow(
    request: Request,
    record_id: str,
    agent_id: str = Query("default", description="Agent ID"),
    comment: str = Query("", description="Review comment"),
):
    """Approve a knowledge flow request."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine or not engine.knowledge_flow:
        raise HTTPException(status_code=404, detail="Knowledge flow not configured")

    success = await engine.knowledge_flow.review_flow_request(record_id, True, comment)
    if not success:
        raise HTTPException(status_code=404, detail=f"Flow record {record_id} not found")

    return {"approved": True, "record_id": record_id}


@router.post("/evolution/knowledge-flow/{record_id}/reject")
@require_permission("evolution:read")
async def reject_flow(
    request: Request,
    record_id: str,
    agent_id: str = Query("default", description="Agent ID"),
    comment: str = Query("", description="Review comment"),
):
    """Reject a knowledge flow request."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine or not engine.knowledge_flow:
        raise HTTPException(status_code=404, detail="Knowledge flow not configured")

    success = await engine.knowledge_flow.review_flow_request(record_id, False, comment)
    if not success:
        raise HTTPException(status_code=404, detail=f"Flow record {record_id} not found")

    return {"rejected": True, "record_id": record_id}


# =========================================================================
# Backend Review
# =========================================================================

@router.get("/evolution/review/status")
@require_permission("evolution:read")
async def get_review_status(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
):
    """Get backend review status."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine or not engine.backend_review:
        return {"enabled": False, "message": "Backend review not configured"}

    return engine.backend_review.get_stats()


@router.get("/evolution/review/history")
@require_permission("evolution:read")
async def get_review_history(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
    limit: int = Query(50, ge=1, le=200, description="Max reviews to return"),
):
    """Get backend review history."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine or not engine.backend_review:
        return {"history": []}

    return {"history": engine.backend_review.get_review_history(limit)}


@router.get("/evolution/review/pending")
@require_permission("evolution:read")
async def get_pending_reviews(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
):
    """Get reviews requiring human attention."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine or not engine.backend_review:
        return {"pending": []}

    return {"pending": engine.backend_review.get_pending_reviews()}


@router.post("/evolution/review/start")
@require_permission("evolution:read")
async def start_review(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
):
    """Start backend review tasks."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine or not engine.backend_review:
        raise HTTPException(status_code=404, detail="Backend review not configured")

    await engine.backend_review.start()
    return {"started": True}


@router.post("/evolution/review/stop")
@require_permission("evolution:read")
async def stop_review(
    request: Request,
    agent_id: str = Query("default", description="Agent ID"),
):
    """Stop backend review tasks."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine or not engine.backend_review:
        raise HTTPException(status_code=404, detail="Backend review not configured")

    await engine.backend_review.stop()
    return {"stopped": True}


# =========================================================================
# Knowledge Flow Approval/Rejection
# =========================================================================

@router.post("/evolution/knowledge-flow/approve")
@require_permission("evolution:read")
async def approve_flow(
    request: Request,
    record_id: str = Query(..., description="Flow record ID to approve"),
    agent_id: str = Query("default", description="Agent ID"),
    comment: str = Query("", description="Audit comment"),
):
    """Approve a knowledge flow record, executing the promotion."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine or not engine.knowledge_flow:
        raise HTTPException(status_code=404, detail="KnowledgeFlow not configured")

    # Find the pending record
    flow = engine.knowledge_flow
    record = None
    for r in flow._flow_queue:
        if r.record_id == record_id:
            record = r
            break

    if not record:
        raise HTTPException(status_code=404, detail=f"Flow record {record_id} not found")

    record.audit_comment = comment
    await flow._execute_flow(record)
    return {"approved": True, "record_id": record_id, "status": record.status}


@router.post("/evolution/knowledge-flow/reject")
@require_permission("evolution:read")
async def reject_flow(
    request: Request,
    record_id: str = Query(..., description="Flow record ID to reject"),
    agent_id: str = Query("default", description="Agent ID"),
    comment: str = Query("", description="Rejection reason"),
):
    """Reject a knowledge flow record."""
    agent_id = _resolve_agent_id(request, agent_id)
    manager = _get_manager(request)
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    engine = workspace.evolution_engine
    if not engine or not engine.knowledge_flow:
        raise HTTPException(status_code=404, detail="KnowledgeFlow not configured")

    # Find and reject the record
    flow = engine.knowledge_flow
    record = None
    for r in flow._flow_queue:
        if r.record_id == record_id:
            record = r
            break

    if not record:
        raise HTTPException(status_code=404, detail=f"Flow record {record_id} not found")

    record.status = "rejected"
    record.audit_comment = comment
    flow._flow_queue.remove(record)
    flow._completed_flows.append(record)
    return {"rejected": True, "record_id": record_id, "status": record.status}


# ── 审计日志 API ───────────────────────────────────────────────────────────

@router.get("/evolution/audit-log")
@require_permission("evolution:read")
async def get_audit_log(
    request: Request,
    change_type: Optional[str] = Query(None, description="筛选: add|update|delete|promote|demote|rollback"),
    target_type: Optional[str] = Query(None, description="筛选: memory|skill|experience|config"),
    risk_level: Optional[str] = Query(None, description="筛选: L0|L1|L2"),
    review_method: Optional[str] = Query(None, description="筛选: auto|llm|manual"),
    limit: int = Query(50, ge=1, le=500),
):
    """查询进化审计日志。"""
    from ...evolution.audit_logger import get_audit_logger
    al = get_audit_logger()
    entries = al.query(
        change_type=change_type,
        target_type=target_type,
        risk_level=risk_level,
        review_method=review_method,
        limit=limit,
    )
    return {"entries": entries, "total": len(entries)}


@router.get("/evolution/audit-log/stats")
@require_permission("evolution:read")
async def get_audit_log_stats(request: Request):
    """获取审计日志统计摘要。"""
    from ...evolution.audit_logger import get_audit_logger
    al = get_audit_logger()
    return al.stats()


@router.get("/evolution/audit-log/{entry_id}")
@require_permission("evolution:read")
async def get_audit_entry(request: Request, entry_id: str):
    """按 ID 查询单条审计记录。"""
    from ...evolution.audit_logger import get_audit_logger
    al = get_audit_logger()
    entry = al.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Audit entry {entry_id} not found")
    return entry


@router.post("/evolution/audit-log/{entry_id}/rollback")
@require_permission("evolution:write")
async def rollback_audit_entry(request: Request, entry_id: str):
    """回滚指定的进化变更。"""
    from ...evolution.audit_logger import get_audit_logger, AuditEntry
    al = get_audit_logger()
    entry = al.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Audit entry {entry_id} not found")
    if not entry.get("rollback_available"):
        raise HTTPException(status_code=400, detail="This entry is not rollbackable")
    if entry.get("rolled_back"):
        raise HTTPException(status_code=400, detail="Already rolled back")

    target_type = entry.get("target_type", "")
    content_before = entry.get("content_before", "")
    target_id = entry.get("target_id", "")

    if target_type == "memory" and content_before:
        # 恢复 MEMORY.md
        try:
            from pathlib import Path
            mem_path = Path(target_id)
            if mem_path.exists():
                mem_path.write_text(content_before, encoding="utf-8")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Rollback failed: {e}")
    elif target_type == "skill" and content_before:
        # 恢复 SKILL.md
        try:
            from pathlib import Path
            skill_path = Path(target_id)
            if skill_path.exists():
                skill_path.write_text(content_before, encoding="utf-8")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Rollback failed: {e}")
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported rollback target_type: {target_type}")

    # 写回滚审计记录
    rollback_entry = AuditEntry(
        change_type="rollback",
        target_type=target_type,
        target_id=target_id,
        risk_level="L0",
        review_method="manual",
        reviewer="admin",
        decision="approved",
        reason=f"回滚 {entry_id}",
        rollback_available=False,
    )
    al.log(rollback_entry)

    # 标记原记录已回滚
    # (直接追加一条标记记录，因为 JSONL 不支持原地修改)
    marker = AuditEntry(
        entry_id=entry_id,
        change_type="rollback_mark",
        target_type=target_type,
        target_id=target_id,
        reason=f"rolled_back_by_{rollback_entry.entry_id}",
    )
    al.log(marker)

    return {
        "rolled_back": True,
        "entry_id": entry_id,
        "rollback_entry_id": rollback_entry.entry_id,
    }
