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
    is_default: bool = False
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

    # Determine if this is a default agent
    # - Global default: agent_id == "global_default"
    # - User default: agent_id == "user:{username}"
    is_default = False
    if agent_id == "global_default":
        is_default = True
    elif ws_username and agent_id == f"user:{ws_username}":
        is_default = True

    return {
        "id": agent_id,
        "name": name,
        "description": description,
        "workspace_dir": str(workspace.workspace_dir) if workspace else "",
        "username": ws_username,
        "enabled": True,
        "is_default": is_default,
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
    """List the current user's agents from the registry in config.json.

    The registry is the single source of truth for agent ownership.
    Each entry has id, name, description, workspace_dir, created_at, enabled.
    """
    username = getattr(request.state, 'username', None)
    if not username:
        return {'agents': []}

    from ...config.config import load_agents_registry
    from ...constant import WORKSPACES_DIR
    from pathlib import Path

    registry = load_agents_registry(username)
    user_ws_base = WORKSPACES_DIR / username

    agents = []
    for entry in registry:
        # Resolve absolute workspace_dir from relative path
        ws_abs = str((user_ws_base / entry.workspace_dir).resolve()) if entry.workspace_dir else ""

        # Load channels from agent.json if it exists (for display purposes)
        channels = []
        agent_json = Path(ws_abs) / "agent.json" if ws_abs else None
        if agent_json and agent_json.exists():
            try:
                meta = json.loads(agent_json.read_text(encoding='utf-8'))
                if isinstance(meta.get('channels'), dict):
                    channels = list(meta['channels'].keys())
            except Exception:
                pass

        agents.append({
            'id': entry.id,
            'name': entry.name,
            'description': entry.description,
            'workspace_dir': ws_abs,
            'owner': username,
            'username': username,
            'is_global': False,
            'enabled': entry.enabled,
            'is_default': entry.is_default,
            'channels': channels,
        })

    return {'agents': agents}

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

    import re, uuid

    # Auto-generate ID if not provided
    agent_id = payload.id or ""
    if not agent_id:
        agent_id = f"user_{uuid.uuid4().hex[:6]}"

    # Validate ID: ASCII-only (letters, digits, underscore, hyphen, colon, dot)
    if not re.match(r'^[a-zA-Z0-9_:.\-]+$', agent_id):
        raise HTTPException(
            status_code=400,
            detail=f"Agent ID must be ASCII-only (letters, digits, _ - : .), got: {agent_id!r}",
        )

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

    # Guard: user: prefix agents must NEVER be global
    if is_global and agent_id.startswith("user:"):
        raise HTTPException(
            status_code=400,
            detail="user: 前缀的智能体不能设为全局智能体 (is_global=true)",
        )

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

        # Persist agent.json to disk (slim format, required for get_agent_for_request lookup)
        ws_dir = Path(workspace.workspace_dir) if hasattr(workspace, "workspace_dir") else None
        if ws_dir:
            ws_dir.mkdir(parents=True, exist_ok=True)
            agent_json_path = ws_dir / "agent.json"
            if not agent_json_path.exists():
                agent_data = {
                    "id": agent_id,
                    "name": payload.name or agent_id,
                    "description": payload.description or "",
                    "owner": username or "",
                    "workspace_dir": ".",
                }
                # active_model is an optional override — only write if explicitly set
                if payload.active_model:
                    agent_data["active_model"] = {
                        "provider_id": payload.active_model.provider_id,
                        "model": payload.active_model.model,
                    }
                agent_json_path.write_text(
                    json.dumps(agent_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(f"Wrote agent.json for new agent: {agent_id}")

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
                    agent_data = json.loads(agent_json.read_text(encoding="utf-8"))
                    agent_data["system_prompt_files"] = config["system_prompt_files"]
                    agent_json.write_text(
                        json.dumps(agent_data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    logger.info(f"Applied agent-level templates to sub-agent {agent_id}")

            # Register agent in user's config.json agents registry
            from ...config.config import add_agent_to_registry
            rel_ws = str(ws_path.relative_to(WORKSPACES_DIR / username))
            add_agent_to_registry(
                username=username,
                agent_id=agent_id,
                name=payload.name or agent_id,
                description=payload.description or "",
                workspace_dir=rel_ws,
            )

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
    """Get agent details by loading from user workspace directory."""
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail='Not authenticated')

    from ...app.user_store import get_user_workspace_dir, get_user_agents_dir

    # Resolve agent.json path under user workspace
    user_ws_dir = get_user_workspace_dir(username)
    agent_json = None

    # Try default agent first
    default_json = user_ws_dir / 'agent.json'
    if default_json.exists():
        meta = json.loads(default_json.read_text(encoding='utf-8'))
        if meta.get('id') == agent_id or (not meta.get('id') and agent_id == f'user:{username}'):
            agent_json = default_json

    # Try sub-agent
    if agent_json is None:
        sub_json = get_user_agents_dir(username) / agent_id / 'agent.json'
        if sub_json.exists():
            agent_json = sub_json

    if agent_json is None:
        raise HTTPException(status_code=404, detail='Agent not found')

    meta = json.loads(agent_json.read_text(encoding='utf-8'))

    # Build workspace-like object for _agent_to_profile
    class _DiskWs:
        def __init__(self, ws_dir):
            self.workspace_dir = str(ws_dir)
            self.username = username
            self.is_global = False
    workspace = _DiskWs(agent_json.parent)

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
    
    # ┌──────────────────────────────────────────────────────────────────┐
    # │ Prevent deletion of default agents (registry-based check)       │
    # └──────────────────────────────────────────────────────────────────┘
    from ...config.config import load_agents_registry
    registry = load_agents_registry(username or "")
    for entry in registry:
        if entry.id == agent_id and entry.is_default:
            raise HTTPException(
                status_code=403,
                detail=f"Cannot delete the default agent ({agent_id})",
            )
    
    try:
        # Admin can delete any agent
        owner_username = username  # default: current user
        success = False

        if user_role in ("admin", "superadmin"):
            # Try to find the agent owner by iterating all workspaces
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

        # ┌──────────────────────────────────────────────────────────────┐
        # │ Fallback: disk-level cleanup when workspace not in memory   │
        # │ (e.g. directory exists but agent.json is missing/invalid)   │
        # └──────────────────────────────────────────────────────────────┘
        if not success:
            import shutil
            from ...constant import WORKSPACES_DIR, AGENTS_DIR

            cleaned = False
            # Try user-level directory first
            search_usernames = [username] if username else []
            if user_role in ("admin", "superadmin"):
                # Admin: scan all user workspaces
                if WORKSPACES_DIR.exists():
                    for d in WORKSPACES_DIR.iterdir():
                        if d.is_dir() and d.name not in search_usernames:
                            search_usernames.append(d.name)

            for uname in search_usernames:
                agent_dir = WORKSPACES_DIR / uname / "agents" / agent_id
                if agent_dir.exists():
                    shutil.rmtree(agent_dir)
                    logger.info(f"Cleaned up orphan agent directory: {agent_dir}")
                    owner_username = uname
                    cleaned = True
                    break

            # Try global agents directory
            if not cleaned:
                global_dir = AGENTS_DIR / agent_id
                if global_dir.exists():
                    shutil.rmtree(global_dir)
                    logger.info(f"Cleaned up orphan global agent directory: {global_dir}")
                    owner_username = None
                    cleaned = True

            if not cleaned:
                raise HTTPException(status_code=404, detail="Agent not found")

            success = True

        # Remove agent from user's config.json agents registry
        if owner_username:
            from ...config.config import remove_agent_from_registry
            remove_agent_from_registry(owner_username, agent_id)

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

    # ┌──────────────────────────────────────────────────────────────────┐
    # │ Prevent toggling default agents (registry-based check)          │
    # └──────────────────────────────────────────────────────────────────┘
    from ...config.config import load_agents_registry
    username_for_check = getattr(request.state, "username", "")
    registry = load_agents_registry(username_for_check or "")
    for entry in registry:
        if entry.id == agent_id and entry.is_default:
            raise HTTPException(
                status_code=403,
                detail=f"Cannot disable the default agent ({agent_id})",
            )

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
