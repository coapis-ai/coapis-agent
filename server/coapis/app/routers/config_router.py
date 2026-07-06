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

"""Config router - Configuration endpoints (CoApis console compatible).

NOTE: CoApis uses JSON config (config.json), not YAML.
  - load_config() is in config/utils.py (NOT config/loader.py)
  - Config file path: request.app.state.config_file
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..permissions.decorators import require_permission
from coapis.constant import SYSTEM_DIR
from fastapi import APIRouter, HTTPException, Body
from fastapi.requests import Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])

# Built-in channel keys
BUILTIN_CHANNEL_KEYS = frozenset({
    "console", "telegram", "dingtalk", "discord", "feishu", "qq",
    "imessage", "voice", "mattermost", "mqtt", "matrix", "wecom",
    "xiaoyi", "weixin", "onebot", "sip",
})

DEFAULT_CHANNEL_CONFIG = {
    "enabled": False, "bot_prefix": "", "filter_tool_messages": False,
    "filter_thinking": False, "dm_policy": "open", "group_policy": "open",
    "allow_from": [], "require_mention": False,
}


def _get_config_file(request: Request) -> Path:
    """Get config file path from app state."""
    config_file = getattr(request.app.state, "config_file", None)
    if config_file:
        return Path(config_file)
    # Fallback to default path using CONFIG_DIR from constant.py
    return SYSTEM_DIR / "config.json"


def _load_config(request: Request) -> Dict[str, Any]:
    """Load JSON config file."""
    config_path = _get_config_file(request)
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(request: Request, config: Dict[str, Any]) -> None:
    """Save JSON config file."""
    config_path = _get_config_file(request)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def _resolve_agent_workspace(request: Request) -> Optional[Path]:
    """Resolve agent workspace from disk (no profiles dependency)."""
    agent_id = request.headers.get("X-Agent-Id")
    username = getattr(request.state, "username", None)

    if agent_id and username:
        from ...constant import WORKSPACES_DIR, AGENTS_DIR
        # Default agent
        default_ws = WORKSPACES_DIR / username
        if (default_ws / "agent.json").exists():
            meta = json.loads((default_ws / "agent.json").read_text(encoding="utf-8"))
            if meta.get("id") == agent_id:
                return default_ws
        # Sub-agent
        sub_ws = WORKSPACES_DIR / username / "agents" / agent_id
        if (sub_ws / "agent.json").exists():
            return sub_ws
        # Global agent
        global_ws = AGENTS_DIR / agent_id
        if (global_ws / "agent.json").exists():
            return global_ws

    # Fallback: username-based default agent
    if username:
        from ...constant import WORKSPACES_DIR
        return WORKSPACES_DIR / username

    return None

def _load_channel_configs(request: Request) -> Dict[str, Any]:
    """Load channel configs with strict per-agent isolation.

    Each agent's channel configs are stored in their own agent.json.
    An agent only sees its own config - no cross-agent inheritance.
    If an agent hasn't configured a channel, it appears as disabled.

    Storage structure:
    - Global config.json: system-level config, NO channel configs
    - Default agent: workspaces/{username}/agent.json
    - Sub-agent: workspaces/{username}/agents/{agentId}/agent.json
    """
    # Load this agent's own channel configs from agent.json
    agent_ws = _resolve_agent_workspace(request)
    agent_channels = {}
    if agent_ws:
        agent_json = agent_ws / "agent.json"
        if agent_json.exists():
            try:
                with open(agent_json, "r", encoding="utf-8") as f:
                    agent_channels = json.load(f).get("channels", {})
            except (json.JSONDecodeError, OSError):
                pass

    result = {}

    # Build channel list: agent's config > disabled default
    # NO fallback to global config.json - strict per-agent isolation
    for key in BUILTIN_CHANNEL_KEYS:
        if key in agent_channels:
            ch = agent_channels[key]
            merged = {**DEFAULT_CHANNEL_CONFIG, **(ch if isinstance(ch, dict) else {})}
            merged["isBuiltin"] = True
            result[key] = merged
        else:
            result[key] = {**DEFAULT_CHANNEL_CONFIG, "isBuiltin": True}

    # Load custom channels (from this agent only)
    for key, ch in agent_channels.items():
        if key not in BUILTIN_CHANNEL_KEYS:
            merged = {**DEFAULT_CHANNEL_CONFIG, **(ch if isinstance(ch, dict) else {})}
            merged["isBuiltin"] = False
            result[key] = merged

    return result


def _save_channel_configs(request: Request, channel_data: Dict[str, Any]) -> None:
    """Save channel configs to this agent's agent.json only.

    Channel configs are stored per-agent in agent.json.
    Global config.json is NOT modified - strict per-agent isolation.
    """
    # Build save data (strip isBuiltin metadata)
    save_data = {}
    for key, ch in channel_data.items():
        if isinstance(ch, dict):
            ch_copy = {k: v for k, v in ch.items() if k not in ("isBuiltin",)}
            save_data[key] = ch_copy

    # Save to agent's agent.json only - NO sync to global config.json
    agent_ws = _resolve_agent_workspace(request)
    if agent_ws:
        agent_json = agent_ws / "agent.json"
        try:
            with open(agent_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            data = {}
        data["channels"] = save_data
        agent_json.parent.mkdir(parents=True, exist_ok=True)
        with open(agent_json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# ── Legacy user-level channel helpers (kept for compatibility) ──


@router.get("/config/channels/types")
@require_permission("channels:read")
async def list_channel_types(request: Request) -> List[str]:
    return sorted(list(BUILTIN_CHANNEL_KEYS))


@router.get("/config/channels")
@require_permission("channels:read")
async def list_channels(request: Request) -> Dict[str, Any]:
    return _load_channel_configs(request)


@router.put("/config/channels")
@require_permission("channels:write")
async def update_channels(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    channel_data = payload.get("channels", payload)
    _save_channel_configs(request, channel_data)
    return _load_channel_configs(request)


@router.get("/config/channels/{channel_name}")
@require_permission("channels:read")
async def get_channel_config(request: Request, channel_name: str) -> Dict[str, Any]:
    all_configs = _load_channel_configs(request)
    if channel_name not in all_configs:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_name}' not found")
    return all_configs[channel_name]


@router.put("/config/channels/{channel_name}")
@require_permission("channels:write")
async def update_channel_config(request: Request, channel_name: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    all_configs = _load_channel_configs(request)
    existing = all_configs.get(channel_name, {**DEFAULT_CHANNEL_CONFIG})
    merged = {**existing, **payload}
    merged["isBuiltin"] = channel_name in BUILTIN_CHANNEL_KEYS

    # Save to agent's agent.json only - NO sync to global config.json
    agent_ws = _resolve_agent_workspace(request)
    if agent_ws:
        agent_json = agent_ws / "agent.json"
        try:
            with open(agent_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            data = {}
        agent_channels = data.get("channels", {})
        ch_copy = {k: v for k, v in merged.items() if k not in ("isBuiltin",)}
        agent_channels[channel_name] = ch_copy
        data["channels"] = agent_channels
        agent_json.parent.mkdir(parents=True, exist_ok=True)
        with open(agent_json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    return merged


@router.get("/config/heartbeat")
@require_permission("heartbeat:read")
async def get_heartbeat_config(request: Request) -> Dict[str, Any]:
    from ..heartbeat import get_heartbeat_repo
    username = getattr(request.state, "username", None) or "admin"
    agent_id = request.headers.get("X-Agent-Id") or "global_default"
    key = f"{username}:{agent_id}"
    return get_heartbeat_repo().get(key)


@router.put("/config/heartbeat")
@require_permission("heartbeat:update")
async def update_heartbeat_config(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    from ..heartbeat import get_heartbeat_repo
    username = getattr(request.state, "username", None) or "admin"
    agent_id = request.headers.get("X-Agent-Id") or "global_default"
    key = f"{username}:{agent_id}"
    return get_heartbeat_repo().update(key, payload)


@router.get("/config/user-timezone")
@require_permission("chat:read")
async def get_user_timezone(request: Request) -> Dict[str, Any]:
    config = _load_config(request)
    return {"timezone": config.get("timezone", "Asia/Shanghai")}


@router.put("/config/user-timezone")
@require_permission("admin:admin")
async def update_user_timezone(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    config = _load_config(request)
    config["timezone"] = payload.get("timezone", "Asia/Shanghai")
    _save_config(request, config)
    return {"timezone": config["timezone"]}


@router.get("/config")
async def get_config_info(request: Request) -> Dict[str, Any]:
    config_file = _get_config_file(request)
    return {"version": "0.1.0", "config_file": str(config_file)}


@router.post("/config/reload")
@require_permission("admin:admin")
async def reload_permissions_config(request: Request) -> Dict[str, Any]:
    """Hot-reload permissions.json config.

    Triggers PermissionManager to reload from disk.
    This propagates to WorkspaceGuard and ToolGuard automatically
    since they read from PermissionManager.get_instance().

    Returns:
        Status and summary of reloaded config
    """
    from ..permissions.manager import PermissionManager

    try:
        pm = PermissionManager.get_instance()
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="PermissionManager not initialized. Service may be starting up."
        )

    # Force reload by resetting the modification time tracker
    pm._last_modified = 0
    pm._load_config()

    # Return summary
    roles = pm._config.get("roles", {})

    return {
        "status": "reloaded",
        "roles_count": len(roles),
        "roles": list(roles.keys()),
        "config_path": str(pm._config_path),
    }


@router.get("/config/agents")
@require_permission("admin:admin")
async def get_config_agents(request: Request) -> Dict[str, Any]:
    """Get all available agents from MultiAgentManager.
    
    Returns the list of all configured agents for the current user.
    Admin users see all agents; regular users see only their accessible agents.
    Requires 'advanced' role or higher.
    """
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if not manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    
    username = getattr(request.state, "username", None)
    user_role = getattr(request.state, "role", "user")
    
    # Admin sees all agents, others see filtered list
    if user_role == "admin":
        agents = manager.get_all_agents()
    else:
        agents = manager.get_user_agents(username or "anonymous")
    
    return {
        "agents": agents,
        "count": len(agents),
        "username": username,
        "role": user_role,
    }


@router.get("/config/models")
@require_permission("admin:admin")
async def get_config_models(request: Request) -> Dict[str, Any]:
    """Get all available models from providers.
    
    Returns the list of all configured model providers and their models.
    Admin users see all providers; regular users see only available models.
    Requires 'advanced' role or higher.
    """
    # 从 ProviderManager 读取 provider 列表
    from ...providers.provider_manager import ProviderManager
    pm = ProviderManager.get_instance()
    provider_infos = await pm.list_provider_info()
    providers = [info.model_dump() for info in provider_infos]
    
    # Also check global config for models section
    config = _load_config(request)
    models_section = config.get("models", {})
    
    username = getattr(request.state, "username", None)
    user_role = getattr(request.state, "role", "user")
    
    return {
        "providers": providers,
        "models": models_section,
        "count": len(providers),
        "username": username,
        "role": user_role,
    }


# ─── ACP (Agent Communication Protocol) Config ────────────────────────
# These endpoints were originally in config.py (disabled due to get_agent_for_request).
# Reimplemented here using JSON file read/write pattern.

@router.get("/config/acp")
@require_permission("acp:read")
async def get_acp_config(request: Request) -> Dict[str, Any]:
    """Get ACP configuration from config.json."""
    config = _load_config(request)
    return config.get("acp", {"agents": {}})


@router.put("/config/acp")
@require_permission("acp:write")
async def update_acp_config(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update ACP configuration in config.json."""
    config = _load_config(request)
    config["acp"] = payload
    _save_config(request, config)
    return config["acp"]


@router.get("/config/acp/{agent_name}")
@require_permission("acp:read")
async def get_acp_agent_config(
    request: Request,
    agent_name: str,
) -> Dict[str, Any]:
    """Get ACP config for a specific ACP agent."""
    config = _load_config(request)
    acp = config.get("acp", {"agents": {}})
    agents = acp.get("agents", {})
    if agent_name not in agents:
        raise HTTPException(
            status_code=404,
            detail=f"ACP agent '{agent_name}' not found",
        )
    return agents[agent_name]


@router.put("/config/acp/{agent_name}")
@require_permission("acp:write")
async def update_acp_agent_config(
    request: Request,
    agent_name: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update ACP config for a specific ACP agent."""
    config = _load_config(request)
    if "acp" not in config:
        config["acp"] = {"agents": {}}
    if "agents" not in config["acp"]:
        config["acp"]["agents"] = {}
    config["acp"]["agents"][agent_name] = payload
    _save_config(request, config)
    return payload
