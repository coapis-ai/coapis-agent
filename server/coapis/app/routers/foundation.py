# -*- coding: utf-8 -*-
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

"""Foundation layer monitoring API endpoints.

Provides endpoints to monitor the hierarchical agent's foundation layer:
- Core principles status
- Thinking patterns status
- Knowledge base statistics
- Memory quota usage
- Injection state
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from coapis.constant import WORKING_DIR
from ..permissions.decorators import require_permission
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["foundation"])


def _get_manager(request: Request) -> Any:
    """Get MultiAgentManager from request state."""
    manager = request.app.state.multi_agent_manager
    if not manager:
        raise HTTPException(status_code=500, detail="Agent manager not initialized")
    return manager


@router.get("/foundation/status")
@require_permission("admin:admin")
async def get_foundation_status(request: Request) -> Dict[str, Any]:
    """Get foundation layer status for all active agents.
    
    Returns aggregated status across all workspaces.
    """
    manager = _get_manager(request)
    
    result = {
        "foundation_dir": str(WORKING_DIR / "coapis/foundation"),
        "agents": {},
        "global_stats": {
            "total_agents": 0,
            "active_agents": 0,
            "total_knowledge_entries": 0,
            "total_pending_reviews": 0,
        }
    }
    
    # Iterate through all workspaces
    workspaces = manager._workspaces
    result["global_stats"]["total_agents"] = len(workspaces)
    
    for agent_id, workspace in workspaces.items():
        if not workspace or not workspace.foundation_manager:
            continue
            
        result["global_stats"]["active_agents"] += 1
        fm = workspace.foundation_manager
        
        # Load knowledge index
        knowledge_index = fm.load_knowledge_index()
        entries = knowledge_index.get("entries", [])
        categories = knowledge_index.get("categories", [])
        
        agent_status = {
            "status": workspace.status,
            "core_injected": fm._core_injected,
            "knowledge_entries": len(entries),
            "categories": len(categories),
            "pending_reviews": len(fm._pending_memories),
            "quota": {
                "core": fm.quota.injection_limits.get("core", 0),
                "long_term": fm.quota.injection_limits.get("long_term", 0),
                "short_term": fm.quota.injection_limits.get("short_term", 0),
                "total": fm.quota.max_tokens,
            },
            "cache_status": {
                "core_memory_cached": fm._core_memory_cache is not None,
                "thinking_patterns_cached": fm._thinking_patterns_cache is not None,
                "knowledge_index_cached": fm._knowledge_index_cache is not None,
                "initial_context_cached": fm._initial_context_cache is not None,
            },
        }
        
        result["agents"][agent_id] = agent_status
        result["global_stats"]["total_knowledge_entries"] += len(entries)
        result["global_stats"]["total_pending_reviews"] += len(fm._pending_memories)
    
    return result


@router.get("/foundation/memory")
@require_permission("admin:admin")
async def get_foundation_memory(
    request: Request,
    agent_id: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Get foundation memory entries.
    
    Args:
        agent_id: Filter by specific agent (optional)
        category: Filter by category (optional)
    """
    manager = _get_manager(request)
    
    if agent_id:
        workspace = manager.get_workspace(agent_id)
        if not workspace or not workspace.foundation_manager:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found or has no foundation manager")
        
        fm = workspace.foundation_manager
        knowledge_index = fm.load_knowledge_index()
        entries = knowledge_index.get("entries", [])
        
        # Filter by category if specified
        if category:
            entries = [e for e in entries if e.get("category", "") == category]
        
        return {
            "agent_id": agent_id,
            "total_entries": len(entries),
            "entries": entries,
            "quota": {
                "core": fm.quota.injection_limits.get("core", 0),
                "long_term": fm.quota.injection_limits.get("long_term", 0),
                "short_term": fm.quota.injection_limits.get("short_term", 0),
                "total": fm.quota.max_tokens,
            },
        }
    else:
        # Return aggregated across all agents
        all_entries = []
        workspaces = manager._workspaces
        
        for aid, ws in workspaces.items():
            if not ws or not ws.foundation_manager:
                continue
            
            fm = ws.foundation_manager
            knowledge_index = fm.load_knowledge_index()
            entries = knowledge_index.get("entries", [])
            
            if category:
                entries = [e for e in entries if e.get("category", "") == category]
            
            for entry in entries:
                entry["agent_id"] = aid
                all_entries.append(entry)
        
        return {
            "total_entries": len(all_entries),
            "entries": all_entries,
        }


@router.get("/foundation/memory/{entry_id}")
@require_permission("admin:admin")
async def get_foundation_memory_entry(
    request: Request,
    entry_id: str,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Get a specific foundation memory entry by ID.
    
    Args:
        entry_id: Memory entry ID
        agent_id: Filter by specific agent (optional)
    """
    manager = _get_manager(request)
    
    if agent_id:
        workspace = manager.get_workspace(agent_id)
        if not workspace or not workspace.foundation_manager:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        
        fm = workspace.foundation_manager
        knowledge_index = fm.load_knowledge_index()
        
        for entry in knowledge_index.get("entries", []):
            if entry.get("id") == entry_id:
                return entry
        
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
    else:
        # Search across all agents
        workspaces = manager._workspaces
        
        for aid, ws in workspaces.items():
            if not ws or not ws.foundation_manager:
                continue
            
            fm = ws.foundation_manager
            knowledge_index = fm.load_knowledge_index()
            
            for entry in knowledge_index.get("entries", []):
                if entry.get("id") == entry_id:
                    return {"agent_id": aid, **entry}
        
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found in any agent")


@router.post("/foundation/memory/clear-cache")
@require_permission("admin:admin")
async def clear_foundation_cache(
    request: Request,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Clear foundation layer caches.
    
    Args:
        agent_id: Clear cache for specific agent (optional, clears all if not specified)
    """
    manager = _get_manager(request)
    cleared = []
    
    if agent_id:
        workspace = manager.get_workspace(agent_id)
        if workspace and workspace.foundation_manager:
            fm = workspace.foundation_manager
            fm.clear_cache()
            fm._knowledge_index_cache = None
            fm._initial_context_cache = None
            cleared.append(agent_id)
            return {"cleared": cleared, "count": len(cleared)}
        else:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    else:
        workspaces = manager._workspaces
        for aid, ws in workspaces.items():
            if ws and ws.foundation_manager:
                fm = ws.foundation_manager
                fm.clear_cache()
                fm._knowledge_index_cache = None
                fm._initial_context_cache = None
                cleared.append(aid)
        
        return {"cleared": cleared, "count": len(cleared)}


@router.get("/foundation/quota")
@require_permission("admin:admin")
async def get_foundation_quota(request: Request) -> Dict[str, Any]:
    """Get memory quota configuration and usage.
    
    Returns quota limits and current usage across all agents.
    """
    from ...foundation.memory_quota import MemoryQuota
    
    # Return default quota configuration
    default_quota = MemoryQuota()
    
    return {
        "default_quota": {
            "core_limit": default_quota.injection_limits.get("core", 0),
            "long_term_limit": default_quota.injection_limits.get("long_term", 0),
            "short_term_limit": default_quota.injection_limits.get("short_term", 0),
            "ephemeral_limit": default_quota.injection_limits.get("ephemeral", 0),
            "total_limit": default_quota.max_tokens,
        },
        "description": "Memory quota limits in tokens. Core memory is always injected, other layers are injected based on relevance.",
    }
