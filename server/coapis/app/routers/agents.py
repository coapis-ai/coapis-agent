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

"""Agents router - Agent management endpoints (CoApis console compatible).

Returns data in CoApis AgentSummary/AgentProfileConfig format.
"""

import logging
import json
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..permissions.decorators import require_permission, check_agent_scope
from fastapi import APIRouter, HTTPException, Body
from fastapi.requests import Request
from pydantic import BaseModel

from ...agents.skills_manager import SkillPoolService, get_workspace_skills_dir
from ...agents.utils import copy_workspace_md_files

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agents"])


def get_manager(request: Request):
    """Get agent manager from app state.
    
    Returns None if MultiAgentManager is not initialized (e.g., TestClient mode).
    Callers should handle None gracefully.
    """
    return getattr(request.app.state, "multi_agent_manager", None)


def get_skill_manager(request: Request):
    """Get skill manager from app state.
    
    Returns None if MultiAgentManager is not initialized.
    """
    manager = get_manager(request)
    if manager is None:
        return None
    return getattr(manager, "skill_manager", None)


# ── Pydantic models matching CoApis frontend types ──────────────────────

class ModelSlotConfig(BaseModel):
    provider_id: str
    model: str


class AgentSummary(BaseModel):
    id: str
    name: str
    description: str = ""
    workspace_dir: str = ""
    enabled: bool = True
    active_model: Optional[ModelSlotConfig] = None


class AgentProfileConfig(BaseModel):
    id: str
    name: str
    description: str = ""
    workspace_dir: str = ""
    owner: str = ""
    approval_level: str = ""
    active_model: Optional[ModelSlotConfig] = None
    channels: Any = None
    mcp: Any = None
    heartbeat: Any = None
    running: Any = None
    llm_routing: Any = None
    system_prompt_files: List[str] = []
    tools: Any = None
    security: Any = None


class CreateAgentRequest(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    workspace_dir: str = ""
    language: str = ""
    skill_names: List[str] = []
    active_model: Optional[ModelSlotConfig] = None
    is_global: Optional[bool] = None  # None=auto (admin=True, user=False)


class AgentProfileRef(BaseModel):
    id: str
    workspace_dir: str


class ReorderAgentsRequest(BaseModel):
    agent_ids: List[str]


class ReorderAgentsResponse(BaseModel):
    success: bool
    agent_ids: List[str]


class ToggleEnabledRequest(BaseModel):
    enabled: bool


# ── Helper functions ─────────────────────────────────────────────────────

def _extract_agent_id(cache_key: str) -> str:
    """Extract real agent_id from composite cache key.
    
    Cache key format: "{username}:{agent_id}" or "global:{agent_id}"
    Returns the actual agent_id (e.g. "default", "my-agent").
    
    Note: user_provisioning creates default agents with id "user:{username}",
    but chats.json stores agent_id as "default". We normalize "user:*" to
    "default" so frontend filtering works correctly.
    """
    # Handle "global:{agent_id}" format
    if cache_key.startswith("global:"):
        return cache_key[len("global:"):]
    # Handle "{username}:{agent_id}" format
    if ":" in cache_key:
        agent_id = cache_key.split(":", 1)[1]
        # Normalize user: prefix to "default" for chat filtering consistency
        if agent_id.startswith("user:"):
            return "default"
        return agent_id
    # Fallback: assume it's already a plain agent_id (backward compat)
    return cache_key


def _to_dict(obj: Any) -> Dict[str, Any]:
    """Safely convert any object to dict (handles Pydantic models, dicts, etc)."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()
    if hasattr(obj, 'dict'):
        return obj.dict()
    return {}


def _get_provider_config(request: Request) -> Dict[str, Any]:
    """Get global provider configuration."""
    from ...config import load_config
    config = _to_dict(load_config())
    return config.get("providers", {})


def _get_active_model(agent_id: str, request: Request) -> Optional[ModelSlotConfig]:
    """Get active model for an agent."""
    # Try agent-specific config first
    from ...config import load_agent_config
    agent_config = _to_dict(load_agent_config(agent_id))
    
    # Check active_model field first (this is part of AgentProfileConfig schema)
    active_model = agent_config.get("active_model")
    if isinstance(active_model, dict) and active_model.get("model"):
        return ModelSlotConfig(
            provider_id=active_model.get("provider_id", "local_llm"),
            model=active_model.get("model", "")
        )
    
    # Fallback: check provider field (from raw agent.json, may be None in Pydantic)
    provider = agent_config.get("provider", {})
    if provider and isinstance(provider, dict):
        provider_id = provider.get("id", "local_llm")
        model = provider.get("model", "")
        if model:
            return ModelSlotConfig(provider_id=provider_id, model=model)

    # Fall back to global config
    providers = _get_provider_config(request)
    if isinstance(providers, dict):
        for pid, pconfig in providers.items():
            if isinstance(pconfig, dict):
                model = pconfig.get("model", "")
                if model:
                    return ModelSlotConfig(provider_id=pid, model=model)

    return None


def _agent_to_summary(agent_id: str, workspace: Any, request: Request) -> Dict[str, Any]:
    """Convert workspace to AgentSummary format."""
    # Try to get name from agent config (with error handling for deleted agents)
    from ...config import load_agent_config
    try:
        agent_config = _to_dict(load_agent_config(agent_id))
    except Exception:
        # Agent config missing — try reading agent.json directly from workspace
        agent_config = {}
        if workspace and hasattr(workspace, "workspace_dir"):
            agent_json = Path(str(workspace.workspace_dir)) / "agent.json"
            if agent_json.is_file():
                try:
                    agent_config = json.loads(agent_json.read_text(encoding="utf-8"))
                except Exception:
                    pass
    name = agent_config.get("name", agent_id)
    description = agent_config.get("description", "")

    try:
        active_model = _get_active_model(agent_id, request)
    except Exception:
        active_model = None

    # Determine username from workspace or config
    ws_username = getattr(workspace, "username", None) if workspace else None
    if not ws_username:
        # Try to infer from agent_config
        ws_username = agent_config.get("username", "")
    if not ws_username and agent_id.startswith("user:"):
        ws_username = agent_id.split(":", 1)[1]

    return {
        "id": agent_id,
        "name": name,
        "description": description,
        "workspace_dir": str(workspace.workspace_dir) if workspace else "",
        "username": ws_username,
        "enabled": True,
        "active_model": active_model.model_dump() if active_model else None,
    }


def _agent_to_profile(agent_id: str, workspace: Any, request: Request) -> Dict[str, Any]:
    """Convert workspace to AgentProfileConfig format."""
    from ...config import load_agent_config
    agent_config = _to_dict(load_agent_config(agent_id))

    active_model = _get_active_model(agent_id, request)

    return {
        "id": agent_id,
        "name": agent_config.get("name", agent_id),
        "description": agent_config.get("description", ""),
        "workspace_dir": str(workspace.workspace_dir) if workspace else "",
        "approval_level": "",
        "active_model": active_model.model_dump() if active_model else None,
        "channels": None,
        "mcp": None,
        "heartbeat": None,
        "running": None,
        "llm_routing": None,
        "system_prompt_files": [],
        "tools": None,
        "security": None,
    }


# =============================================================================
# STATIC ROUTES (must come BEFORE parameterized routes like /agents/{agent_id})
# =============================================================================

@router.get("/agents/order")
@require_permission("agents:read")
async def get_agents_order(request: Request) -> Dict[str, Any]:
    """Get agent order (frontend calls GET)."""
    from ...constant import DATA_DIR
    
    order_file = DATA_DIR / "agent_order.json"
    if order_file.exists():
        with open(order_file, "r") as f:
            data = json.load(f)
        return {"agent_ids": data.get("agent_ids", [])}
    
    # Default: get from manager (extract real agent_ids from composite keys)
    manager = get_manager(request)
    if manager:
        agent_ids = [_extract_agent_id(k) for k in manager._workspaces.keys()]
        return {"agent_ids": agent_ids}
    return {"agent_ids": []}


@router.put("/agents/order")
@require_permission("agents:write")
async def reorder_agents(
    request: Request,
    payload: ReorderAgentsRequest = Body(...),
) -> Dict[str, Any]:
    """Reorder agents (persist order)."""
    from ...constant import DATA_DIR
    order_file = DATA_DIR / "agent_order.json"

    with open(order_file, "w") as f:
        json.dump({"agent_ids": payload.agent_ids}, f)

    logger.info(f"Agent order updated: {payload.agent_ids}")
    return {
        "success": True,
        "agent_ids": payload.agent_ids,
    }


# =============================================================================
# MAIN ROUTES
# =============================================================================

@router.get("/agents")
@require_permission("agents:read")
async def list_agents(request: Request) -> Dict[str, Any]:
    """List all managed agents (returns AgentSummary format).
    
    For non-admin users, filters to show only:
    - User-specific agents (owned by current user only)
    
    For admin users, shows all agents.
    
    Falls back to config-based listing when MultiAgentManager is not available
    (e.g., TestClient mode or during startup).
    """
    manager = get_manager(request)
    
    username = getattr(request.state, "username", None)
    user_role = getattr(request.state, "role", "user")
    is_admin = (user_role in ("admin", "superadmin"))
    
    if manager is not None:
        # Normal mode: use MultiAgentManager workspaces
        workspaces = manager._workspaces
        
        # Filter workspaces by user (deduplicate by real agent_id)
        seen_ids = set()
        filtered = []
        for cache_key, ws in workspaces.items():
            real_id = _extract_agent_id(cache_key)
            if real_id in seen_ids:
                continue
            seen_ids.add(real_id)
            
            # Skip global agents — users only see their own user-specific agents
            ws_is_global = getattr(ws, "is_global", False)
            if ws_is_global:
                continue

            # Users can only see their own user-specific agents
            if ws.username != username:
                continue
            
            # Skip agents whose workspace no longer exists (deleted)
            ws_dir = getattr(ws, "workspace_dir", None)
            if ws_dir and not Path(ws_dir).exists():
                logger.debug(f"Skipping agent {real_id}: workspace {ws_dir} does not exist")
                continue
            
            filtered.append((real_id, ws))
        
        agents = []
        for real_id, ws in filtered:
            agent = _agent_to_summary(real_id, ws, request)
            # Ensure username is set for user-specific agents (e.g., user:admin -> admin)
            if not agent.get('username') and real_id.startswith('user:'):
                agent['username'] = real_id.split(':', 1)[1]
            agents.append(agent)
    else:
        # Fallback mode: read from config profiles
        from ...config import load_config
        config = load_config()
        profiles = getattr(config, "agents", {}).profiles if hasattr(config, "agents") else {}
        
        agents = []
        for agent_id, profile in profiles.items():
            profile_username = getattr(profile, "username", "")
            profile_role = getattr(profile, "role", None)
            profile_enabled = getattr(profile, "enabled", True)
            profile_is_global = getattr(profile, "is_global", True)

            # Skip global agents — users only see their own user-specific agents
            if profile_is_global:
                continue

            # Users can only see their own user-specific agents
            if profile_username != username:
                continue
            
            # Create a minimal workspace for the summary
            class MinimalWorkspace:
                def __init__(self, aid: str, p):
                    self.agent_id = aid
                    self.workspace_dir = Path(getattr(p, "workspace_dir",
                        f"{Path.cwd().parent.parent}/workspaces/{profile_username}/agents/{aid}"))
                    self.username = profile_username
                    self.is_global = getattr(p, "is_global", True)
                    self.config = {}
            
            agents.append(_agent_to_summary(agent_id, MinimalWorkspace(agent_id, profile), request))

    return {
        "agents": agents,
    }


@router.post("/agents")
@require_permission("agents:write")
async def create_agent(
    request: Request,
    payload: CreateAgentRequest = Body(...),
) -> Dict[str, Any]:
    """Create a new agent workspace (returns AgentProfileRef format)."""
    manager = get_manager(request)
    if not manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")

    agent_id = payload.id or payload.name
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent id or name is required")

    # Build config from request
    username = getattr(request.state, "username", "")
    config = {
        "name": payload.name,
        "description": payload.description,
        "owner": username,
    }
    if payload.active_model:
        config["provider"] = {
            "id": payload.active_model.provider_id,
            "model": payload.active_model.model,
        }

    # Get current username and role for user isolation
    username = getattr(request.state, "username", None)
    user_role = getattr(request.state, "role", "user")
    is_admin = (user_role in ("admin", "superadmin"))

    # Determine if this should be a global or user-specific agent
    # All users (including admin) create user-specific agents by default.
    # Only set is_global=true when explicitly requested via API payload.
    is_global = payload.is_global is True

    # Handle workspace_dir: user agents must be under workspaces/{username}/agents/
    from ...constant import WORKSPACES_DIR, WORKING_DIR
    workspace_dir = payload.workspace_dir
    if not is_global and username:
        # User agent: enforce path prefix
        if workspace_dir:
            # Validate: path must start with workspaces/{username}/agents/
            required_prefix = str(WORKSPACES_DIR / username / "agents")
            actual_path = str(Path(workspace_dir).expanduser())
            if not actual_path.startswith(required_prefix):
                raise HTTPException(
                    status_code=400,
                    detail=f"User agent workspace_dir must be under {required_prefix}",
                )
        else:
            # Auto-generate: workspaces/{username}/agents/{agent_id}
            workspace_dir = str(WORKSPACES_DIR / username / "agents" / agent_id)
            config["workspace_dir"] = workspace_dir
    elif is_global:
        # Global agent: allow custom path or auto-generate under agents/
        if workspace_dir:
            config["workspace_dir"] = workspace_dir
        else:
            workspace_dir = str(WORKING_DIR / "agents" / agent_id)
            config["workspace_dir"] = workspace_dir

    try:
        workspace = await manager.create_agent(
            agent_id, config, username=username, is_global=is_global
        )

        # For user sub-agents: apply agent-level templates and slim system_prompt_files
        if not is_global and username and workspace.workspace_dir:
            from ..user_provisioning import _copy_base_templates
            ws_path = Path(workspace.workspace_dir)
            if ws_path.parent.name == "agents":
                # This is a sub-agent under workspaces/{username}/agents/{id}/
                _copy_base_templates(ws_path, username, level="agent")
                # Set slim system_prompt_files for sub-agents
                config["system_prompt_files"] = ["AGENTS.md", "SOUL.md", "PROFILE.md"]
                # Persist slim config to agent.json
                agent_json = ws_path / "agent.json"
                if agent_json.exists():
                    import json
                    agent_data = json.loads(agent_json.read_text(encoding="utf-8"))
                    agent_data["system_prompt_files"] = config["system_prompt_files"]
                    agent_json.write_text(
                        json.dumps(agent_data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    logger.info(f"Applied agent-level templates to sub-agent {agent_id}")

        return {
            "id": agent_id,
            "workspace_dir": str(workspace.workspace_dir),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# PARAMETERIZED ROUTES (must come AFTER static routes)
# =============================================================================

@router.get("/agents/{agent_id}")
@require_permission("agents:read")
async def get_agent(
    request: Request,
    agent_id: str,
) -> Dict[str, Any]:
    """Get agent details (returns AgentProfileConfig format)."""
    manager = get_manager(request)
    if not manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")

    username = getattr(request.state, "username", None)
    workspace = manager.get_workspace(agent_id, username=username)
    if not workspace:
        raise HTTPException(status_code=404, detail="Agent not found")

    return _agent_to_profile(agent_id, workspace, request)


@router.put("/agents/{agent_id}")
@require_permission("agents:write")
async def update_agent(
    request: Request,
    agent_id: str,
    payload: AgentProfileConfig = Body(...),
) -> Dict[str, Any]:
    """Update agent configuration."""
    manager = get_manager(request)
    if not manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")

    username = getattr(request.state, "username", None)
    user_role = getattr(request.state, "role", "user")
    is_admin = (user_role in ("admin", "superadmin"))
    
    workspace = manager.get_workspace(agent_id, username=username)
    if not workspace:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Non-admin users can only update their own agents
    if not is_admin and workspace.username and workspace.username != username:
        raise HTTPException(status_code=403, detail="No permission to update this agent")

    # Save agent config to file
    from ...constant import AGENTS_DIR
    agent_config_file = AGENTS_DIR / agent_id / "config.yaml"
    agent_config_file.parent.mkdir(parents=True, exist_ok=True)

    config = {
        "name": payload.name,
        "description": payload.description,
    }
    if payload.active_model:
        config["provider"] = {
            "id": payload.active_model.provider_id,
            "model": payload.active_model.model,
        }

    with open(agent_config_file, "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    logger.info(f"Updated agent config: {agent_id}")
    return _agent_to_profile(agent_id, workspace, request)


@router.delete("/agents/{agent_id}")
@require_permission("agents:write")
async def delete_agent(
    request: Request,
    agent_id: str,
) -> Dict[str, Any]:
    """Delete an agent.
    
    Admin can delete any agent (global or user-specific).
    Regular users can only delete their own agents.
    """
    manager = get_manager(request)
    if not manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")

    username = getattr(request.state, "username", None)
    user_role = getattr(request.state, "role", "user")
    
    # ┌──────────────────────────────────────────────────────────────┐
    # │ Prevent deletion of global_default (it's the default agent) │
    # └──────────────────────────────────────────────────────────────┘
    if agent_id == "global_default":
        raise HTTPException(status_code=403, detail="Cannot delete the default agent (global_default)")
    
    try:
        # Admin can delete any agent
        if user_role in ("admin", "superadmin"):
            # Try to find the agent owner by iterating all workspaces
            success = False
            for cache_key, workspace in list(manager._workspaces.items()):
                if _extract_agent_id(cache_key) == agent_id:
                    owner_username = workspace.username
                    success = await manager.destroy_agent(agent_id, username=owner_username)
                    break
            
            # Fallback: try global agent
            if not success:
                success = await manager.destroy_agent(agent_id, username=None)
        else:
            # Regular users can only delete their own agents
            success = await manager.destroy_agent(agent_id, username=username)
        
        if not success:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {
            "success": True,
            "agent_id": agent_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/agents/{agent_id}/toggle")
@require_permission("agents:write")
async def toggle_agent_enabled(
    request: Request,
    agent_id: str,
    payload: ToggleEnabledRequest = Body(...),
) -> Dict[str, Any]:
    """Toggle agent enabled state."""
    manager = get_manager(request)
    if not manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")

    username = getattr(request.state, "username", None)
    user_role = getattr(request.state, "role", "user")
    is_admin = (user_role in ("admin", "superadmin"))

    workspace = manager.get_workspace(agent_id, username=username)
    if not workspace:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Non-admin users can only toggle their own agents
    if not is_admin and workspace.username and workspace.username != username:
        raise HTTPException(status_code=403, detail="No permission to toggle this agent")

    # For now, just return success (CoApis doesn't have enabled/disabled concept)
    return {
        "success": True,
        "agent_id": agent_id,
        "enabled": payload.enabled,
    }


def _apply_workspace_md_templates(
    workspace_dir: Path,
    language: str,
    *,
    md_template_id: str | None,
) -> None:
    """Copy common and template-specific markdown files for a workspace."""
    copy_workspace_md_files(
        language,
        workspace_dir,
        md_template_id=md_template_id,
    )


def _ensure_heartbeat_file(workspace_dir: Path, language: str) -> None:
    """Create the default HEARTBEAT.md if it is missing."""
    heartbeat_file = workspace_dir / "HEARTBEAT.md"
    if heartbeat_file.exists():
        return

    default_heartbeat_mds = {
        "zh": """# Heartbeat checklist
- 扫描收件箱紧急邮件
- 查看未来 2h 的日历
- 检查待办是否卡住
- 若安静超过 8h，轻量 check-in
""",
        "en": """# Heartbeat checklist
- Scan inbox for urgent email
- Check calendar for next 2h
- Check tasks for blockers
- Light check-in if quiet for 8h
""",
    }
    heartbeat_content = default_heartbeat_mds.get(
        language,
        default_heartbeat_mds["en"],
    )
    with open(heartbeat_file, "w", encoding="utf-8") as file:
        file.write(heartbeat_content.strip())


def _install_initial_skills(
    workspace_dir: Path,
    skill_names: list[str] | None,
) -> None:
    """Install requested initial skills from the skill pool."""
    if not skill_names:
        return

    pool_service = SkillPoolService()
    for skill_name in skill_names:
        try:
            result = pool_service.download_to_workspace(
                skill_name=skill_name,
                workspace_dir=workspace_dir,
                overwrite=False,
            )
            if result.get("success"):
                continue
            logger.warning(
                "Failed to install initial skill %s for %s: %s",
                skill_name,
                workspace_dir,
                result.get("reason", "unknown"),
            )
        except Exception as e:
            logger.warning(
                "Failed to install initial skill %s for %s: %s",
                skill_name,
                workspace_dir,
                e,
            )


def _initialize_agent_workspace(
    workspace_dir: Path,
    skill_names: list[str] | None = None,
    md_template_id: str | None = None,
    language: str | None = None,
) -> None:
    """Initialize agent workspace with only explicitly requested skills."""
    from ...config import load_config as load_global_config

    (workspace_dir / "sessions").mkdir(exist_ok=True)
    (workspace_dir / "memory").mkdir(exist_ok=True)
    get_workspace_skills_dir(workspace_dir).mkdir(exist_ok=True)

    config = load_global_config()
    if not language:
        language = config.agents.language or "zh"

    _apply_workspace_md_templates(
        workspace_dir,
        language,
        md_template_id=md_template_id,
    )
    _ensure_heartbeat_file(workspace_dir, language)
    _install_initial_skills(workspace_dir, skill_names)

    # jobs.json 已移至 crons/jobs.json，由 CronManager 自动创建

    chats_file = workspace_dir / "chats.json"
    if not chats_file.exists():
        with open(chats_file, "w", encoding="utf-8") as file:
            json.dump(
                {"version": 1, "chats": []},
                file,
                ensure_ascii=False,
                indent=2,
            )
