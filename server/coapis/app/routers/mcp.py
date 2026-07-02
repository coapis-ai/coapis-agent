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

"""MCP router — unified data source for MCP client management.

Design:
- Single source of truth: agent.json → mcp.clients
- API operations = read/write agent.json + hot-reload via MCPConfigWatcher
- Global MCP pool: admin's MCP clients serve as system-wide templates
- Per-user isolation: each user has independent MCP config in their agent.json
- Merge logic: user config overrides global defaults at runtime

Storage:
  workspaces/{username}/agent.json → mcp.clients.{key} = MCPClientConfig
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Literal

from fastapi import APIRouter, Body, HTTPException, Path, Request
from pydantic import BaseModel, Field

from ...config.config import (
    MCPClientConfig,
    MCPConfig,
    load_agent_config,
    save_agent_config,
)
from ...constant import WORKSPACES_DIR
from ..permissions.decorators import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])


# ─── Request / Response models ────────────────────────────────────────────


class MCPClientOAuthStatus(BaseModel):
    """Summarised OAuth status (placeholder for future)."""

    authorized: bool = False
    expires_at: float = 0.0
    scope: str = ""
    client_id: str = ""


class MCPClientInfo(BaseModel):
    """MCP client information for API responses."""

    key: str = Field(..., description="Unique client key identifier")
    name: str = Field(..., description="Client display name")
    description: str = Field(default="", description="Client description")
    enabled: bool = Field(..., description="Whether the client is enabled")
    transport: Literal["stdio", "streamable_http", "sse"] = Field(
        ..., description="MCP transport type",
    )
    url: str = Field(default="")
    headers: Dict[str, str] = Field(default_factory=dict)
    command: str = Field(default="")
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    cwd: str = Field(default="")
    source: str = Field(
        default="user",
        description="Configuration source: 'global' or 'user'",
    )
    oauth_status: Optional[MCPClientOAuthStatus] = None


class MCPClientCreateRequest(BaseModel):
    """Request body for creating an MCP client."""

    name: str
    description: str = ""
    enabled: bool = True
    transport: Literal["stdio", "streamable_http", "sse"] = "stdio"
    url: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)
    command: str = ""
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    cwd: str = ""


class MCPClientUpdateRequest(BaseModel):
    """Request body for partially updating an MCP client."""

    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    transport: Optional[Literal["stdio", "streamable_http", "sse"]] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    cwd: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────


def _validate_client_key(key: str) -> None:
    """Validate client key format."""
    if not key or not re.match(r"^[a-zA-Z0-9_-]+$", key):
        raise HTTPException(
            400,
            detail="Client key must be non-empty and contain only "
            "letters, digits, underscores, and hyphens.",
        )


def _mask_env(env: Dict[str, str]) -> Dict[str, str]:
    """Mask sensitive environment variable values."""
    sensitive_patterns = {"key", "secret", "token", "password", "api_key"}
    masked = {}
    for k, v in env.items():
        if any(p in k.lower() for p in sensitive_patterns) and v:
            masked[k] = "***"
        else:
            masked[k] = v
    return masked


def _build_client_info(
    key: str,
    config: MCPClientConfig,
    source: str = "user",
) -> MCPClientInfo:
    """Build MCPClientInfo from config with masked sensitive values."""
    return MCPClientInfo(
        key=key,
        name=config.name,
        description=getattr(config, "description", ""),
        enabled=config.enabled,
        transport=config.transport,
        url=config.url,
        headers=config.headers,
        command=config.command,
        args=config.args,
        env=_mask_env(config.env),
        cwd=getattr(config, "cwd", ""),
        source=source,
    )


def _get_user_id(request: Request) -> str:
    """Extract authenticated username from request."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(401, detail="Not authenticated")
    return username


def _get_admin_agent_id() -> str:
    """Get admin's agent ID for global MCP pool."""
    from ...config.utils import load_config

    config = load_config()
    # Admin's active agent is the global pool source
    return config.agents.active_agent or "user:admin"


def _load_global_mcp() -> Dict[str, MCPClientConfig]:
    """Load admin's MCP config as the global pool."""
    try:
        admin_agent_id = _get_admin_agent_id()
        admin_config = load_agent_config(admin_agent_id)
        if admin_config.mcp and admin_config.mcp.clients:
            return dict(admin_config.mcp.clients)
    except Exception as e:
        logger.debug(f"Could not load global MCP pool: {e}")
    return {}


def _load_user_mcp(agent_id: str) -> Dict[str, MCPClientConfig]:
    """Load user's own MCP config from their agent.json."""
    try:
        agent_config = load_agent_config(agent_id)
        if agent_config.mcp and agent_config.mcp.clients:
            return dict(agent_config.mcp.clients)
    except Exception as e:
        logger.debug(f"Could not load MCP config for {agent_id}: {e}")
    return {}


def _resolve_effective_mcp(
    agent_id: str,
    user_id: str,
) -> Dict[str, MCPClientConfig]:
    """Merge global + user MCP configs.

    Rules:
    - User's own keys take priority over global keys with the same name
    - If user has a key that global doesn't → user-only
    - If global has a key that user doesn't → inherited from global
    - User can disable a global key by setting enabled=False
    """
    global_clients = _load_global_mcp()
    user_clients = _load_user_mcp(agent_id)

    # User config overrides global
    merged = dict(global_clients)
    merged.update(user_clients)

    # If user is not admin, filter out admin-only global keys
    # (admin's keys are available to all unless user explicitly overrides)
    return merged


def _get_agent_id_for_user(user_id: str) -> str:
    """Get the agent_id for a given user."""
    from ...config.utils import load_config

    config = load_config()
    # Check if user has a registered agent profile
    user_agent_id = f"user:{user_id}"
    if user_agent_id in config.agents.profiles:
        return user_agent_id
    # Fallback to active agent
    return config.agents.active_agent or "user:admin"


def _trigger_reload(request: Request, agent_id: str) -> None:
    """Trigger MCP config hot-reload.

    The MCPConfigWatcher will automatically pick up agent.json changes
    within its poll interval (2s). For faster feedback, we also try to
    directly reinitialize the MCP manager.
    """
    try:
        manager = getattr(request.app.state, "multi_agent_manager", None)
        if manager:
            import asyncio

            async def _reload():
                try:
                    ws = manager.get_workspace(agent_id)
                    if ws and ws.mcp_manager:
                        from ..mcp import MCPClientManager
                        from ...config.config import MCPConfig

                        # Reload merged config (global + user)
                        agent_config = load_agent_config(agent_id)
                        merged = _resolve_effective_mcp(
                            agent_id,
                            agent_id.split(":", 1)[-1]
                            if ":" in agent_id
                            else agent_id,
                        )
                        active = {k: v for k, v in merged.items() if v.enabled}
                        if active:
                            await ws.mcp_manager.init_from_config(
                                MCPConfig(clients=active),
                            )
                except Exception as e:
                    logger.debug(f"MCP hot-reload skipped: {e}")

            asyncio.create_task(_reload())
    except Exception:
        pass  # Watcher will pick it up eventually


# ─── Personal MCP endpoints ──────────────────────────────────────────────


@router.get(
    "/mcp",
    response_model=List[MCPClientInfo],
    summary="List effective MCP clients (global + user merged)",
)
@require_permission("mcp:read")
async def list_mcp_clients(request: Request) -> List[MCPClientInfo]:
    """Get list of all effective MCP clients for the current user.

    Returns the merged view of global (admin) + user's own MCP configs.
    Each client has a 'source' field indicating whether it comes from
    the global pool or the user's own config.
    """
    user_id = _get_user_id(request)
    agent_id = _get_agent_id_for_user(user_id)
    global_clients = _load_global_mcp()
    user_clients = _load_user_mcp(agent_id)

    result: List[MCPClientInfo] = []

    # Process global clients (that user hasn't overridden)
    for key, gconfig in global_clients.items():
        if key in user_clients:
            # User has overridden — show user's version with source=user
            result.append(_build_client_info(key, user_clients[key], "user"))
        else:
            # Inherited from global
            result.append(_build_client_info(key, gconfig, "global"))

    # Process user-only clients
    for key, uconfig in user_clients.items():
        if key not in global_clients:
            result.append(_build_client_info(key, uconfig, "user"))

    return result


@router.get(
    "/mcp/global",
    response_model=List[MCPClientInfo],
    summary="List global MCP pool (admin-configured)",
)
@require_permission("mcp:read")
async def list_global_mcp_clients(request: Request) -> List[MCPClientInfo]:
    """Get the global MCP pool configured by admin."""
    global_clients = _load_global_mcp()
    return [
        _build_client_info(key, config, "global")
        for key, config in global_clients.items()
    ]


@router.get(
    "/mcp/{client_key}",
    response_model=MCPClientInfo,
    summary="Get a specific MCP client",
)
@require_permission("mcp:read")
async def get_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> MCPClientInfo:
    """Get details of a specific MCP client."""
    user_id = _get_user_id(request)
    agent_id = _get_agent_id_for_user(user_id)
    global_clients = _load_global_mcp()
    user_clients = _load_user_mcp(agent_id)

    if client_key in user_clients:
        return _build_client_info(client_key, user_clients[client_key], "user")
    if client_key in global_clients:
        return _build_client_info(
            client_key, global_clients[client_key], "global",
        )
    raise HTTPException(404, detail=f"MCP client '{client_key}' not found")


@router.post(
    "/mcp",
    response_model=MCPClientInfo,
    summary="Create a personal MCP client",
    status_code=201,
)
@require_permission("mcp:write")
async def create_mcp_client(
    request: Request,
    client_key: str = Body(..., embed=True),
    client: MCPClientCreateRequest = Body(..., embed=True),
) -> MCPClientInfo:
    """Create a new MCP client in the user's agent.json."""
    _validate_client_key(client_key)
    user_id = _get_user_id(request)
    agent_id = _get_agent_id_for_user(user_id)

    # Load current config
    agent_config = load_agent_config(agent_id)

    # Initialize mcp config if not exists
    if agent_config.mcp is None:
        agent_config.mcp = MCPConfig(clients={})

    # Check if client already exists
    if client_key in agent_config.mcp.clients:
        raise HTTPException(
            400,
            detail=f"MCP client '{client_key}' already exists. Use PUT to update.",
        )

    # Create new client config
    new_client = MCPClientConfig(
        name=client.name,
        description=client.description,
        enabled=client.enabled,
        transport=client.transport,
        url=client.url,
        headers=client.headers,
        command=client.command,
        args=client.args,
        env=client.env,
        cwd=client.cwd,
    )

    # Add to agent's config and save
    agent_config.mcp.clients[client_key] = new_client
    save_agent_config(agent_id, agent_config)

    # Hot reload
    _trigger_reload(request, agent_id)

    return _build_client_info(client_key, new_client, "user")


@router.put(
    "/mcp/{client_key}",
    response_model=MCPClientInfo,
    summary="Update a personal MCP client",
)
@require_permission("mcp:write")
async def update_mcp_client(
    request: Request,
    client_key: str = Path(...),
    updates: MCPClientUpdateRequest = Body(...),
) -> MCPClientInfo:
    """Update an existing MCP client in the user's agent.json."""
    user_id = _get_user_id(request)
    agent_id = _get_agent_id_for_user(user_id)

    agent_config = load_agent_config(agent_id)

    if (
        agent_config.mcp is None
        or client_key not in agent_config.mcp.clients
    ):
        # If it exists in global but not user, we need to create it in user's config
        global_clients = _load_global_mcp()
        if client_key not in global_clients:
            raise HTTPException(
                404, detail=f"MCP client '{client_key}' not found",
            )
        # Copy global config to user as base for modification
        if agent_config.mcp is None:
            agent_config.mcp = MCPConfig(clients={})
        agent_config.mcp.clients[client_key] = global_clients[
            client_key
        ].model_copy()

    client = agent_config.mcp.clients[client_key]

    # Apply partial updates
    update_data = updates.model_dump(exclude_none=True)
    for field, value in update_data.items():
        if hasattr(client, field):
            setattr(client, field, value)

    save_agent_config(agent_id, agent_config)
    _trigger_reload(request, agent_id)

    return _build_client_info(client_key, client, "user")


@router.patch(
    "/mcp/{client_key}/toggle",
    response_model=MCPClientInfo,
    summary="Toggle MCP client enabled status",
)
@require_permission("mcp:write")
async def toggle_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> MCPClientInfo:
    """Toggle the enabled status of an MCP client."""
    user_id = _get_user_id(request)
    agent_id = _get_agent_id_for_user(user_id)

    agent_config = load_agent_config(agent_id)

    if agent_config.mcp is None or client_key not in agent_config.mcp.clients:
        # Check if it exists in global — if so, create user override
        global_clients = _load_global_mcp()
        if client_key not in global_clients:
            raise HTTPException(
                404, detail=f"MCP client '{client_key}' not found",
            )
        if agent_config.mcp is None:
            agent_config.mcp = MCPConfig(clients={})
        agent_config.mcp.clients[client_key] = global_clients[
            client_key
        ].model_copy()

    client = agent_config.mcp.clients[client_key]
    client.enabled = not client.enabled
    save_agent_config(agent_id, agent_config)
    _trigger_reload(request, agent_id)

    return _build_client_info(client_key, client, "user")


@router.delete(
    "/mcp/{client_key}",
    summary="Delete a personal MCP client",
)
@require_permission("mcp:write")
async def delete_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> Dict[str, str]:
    """Delete an MCP client from the user's agent.json.

    If the client is inherited from global, this creates a disabled
    override so it no longer appears for this user.
    """
    user_id = _get_user_id(request)
    agent_id = _get_agent_id_for_user(user_id)

    agent_config = load_agent_config(agent_id)

    if agent_config.mcp and client_key in agent_config.mcp.clients:
        del agent_config.mcp.clients[client_key]
        save_agent_config(agent_id, agent_config)
        _trigger_reload(request, agent_id)
        return {"status": "deleted", "key": client_key}

    # Check if it's a global-only client
    global_clients = _load_global_mcp()
    if client_key in global_clients:
        # Create a disabled override to hide it for this user
        if agent_config.mcp is None:
            agent_config.mcp = MCPConfig(clients={})
        disabled = global_clients[client_key].model_copy()
        disabled.enabled = False
        agent_config.mcp.clients[client_key] = disabled
        save_agent_config(agent_id, agent_config)
        _trigger_reload(request, agent_id)
        return {"status": "disabled", "key": client_key}

    raise HTTPException(404, detail=f"MCP client '{client_key}' not found")


@router.get(
    "/mcp/{client_key}/tools",
    summary="List tools exposed by an MCP client",
)
@require_permission("mcp:read")
async def list_mcp_tools(
    request: Request,
    client_key: str = Path(...),
) -> List[Dict[str, Any]]:
    """List tools provided by a specific MCP server."""
    user_id = _get_user_id(request)
    agent_id = _get_agent_id_for_user(user_id)

    # Find the MCP client config
    user_clients = _load_user_mcp(agent_id)
    global_clients = _load_global_mcp()
    client_config = user_clients.get(client_key) or global_clients.get(
        client_key,
    )

    if not client_config:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    if not client_config.enabled:
        raise HTTPException(
            400,
            detail=f"MCP client '{client_key}' is disabled. "
            "Enable it first to list tools.",
        )

    # Try to get tools from the running MCP client manager
    try:
        from ..mcp import MCPClientManager
        from ...config.config import load_config as _load_sys_config

        sys_config = _load_sys_config()
        # Find workspace with this MCP client connected
        manager = getattr(request.app.state, "multi_agent_manager", None)
        if manager:
            ws = manager.get_workspace(agent_id)
            if ws and ws.mcp_manager:
                clients = await ws.mcp_manager.get_clients()
                for c in clients:
                    if getattr(c, "name", None) == client_key:
                        tools = await c.list_tools()
                        return [
                            {
                                "name": t.name,
                                "description": t.description or "",
                                "input_schema": t.inputSchema
                                if hasattr(t, "inputSchema")
                                else {},
                            }
                            for t in tools
                        ]
    except Exception as e:
        logger.warning(f"Failed to list tools for MCP '{client_key}': {e}")

    # Fallback: return empty list (client not connected yet)
    return []


# ─── Global MCP pool endpoints (admin only) ──────────────────────────────


@router.post(
    "/mcp/global",
    response_model=MCPClientInfo,
    summary="Create a global MCP client (admin only)",
    status_code=201,
)
@require_permission("mcp:write")
async def create_global_mcp_client(
    request: Request,
    client_key: str = Body(..., embed=True),
    client: MCPClientCreateRequest = Body(..., embed=True),
) -> MCPClientInfo:
    """Create a global MCP client in admin's agent.json.

    Only admin users can create global MCP clients.
    Global clients are inherited by all users unless overridden.
    """
    user_id = _get_user_id(request)
    # Verify admin role
    role = getattr(request.state, "role", "user")
    if role != "admin":
        raise HTTPException(403, detail="Only admins can manage global MCP")

    _validate_client_key(client_key)
    admin_agent_id = _get_admin_agent_id()

    admin_config = load_agent_config(admin_agent_id)
    if admin_config.mcp is None:
        admin_config.mcp = MCPConfig(clients={})

    if client_key in admin_config.mcp.clients:
        raise HTTPException(
            400,
            detail=f"Global MCP client '{client_key}' already exists.",
        )

    new_client = MCPClientConfig(
        name=client.name,
        description=client.description,
        enabled=client.enabled,
        transport=client.transport,
        url=client.url,
        headers=client.headers,
        command=client.command,
        args=client.args,
        env=client.env,
        cwd=client.cwd,
    )

    admin_config.mcp.clients[client_key] = new_client
    save_agent_config(admin_agent_id, admin_config)
    _trigger_reload(request, admin_agent_id)

    return _build_client_info(client_key, new_client, "global")


@router.delete(
    "/mcp/global/{client_key}",
    summary="Delete a global MCP client (admin only)",
)
@require_permission("mcp:write")
async def delete_global_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> Dict[str, str]:
    """Delete a global MCP client from admin's agent.json."""
    role = getattr(request.state, "role", "user")
    if role != "admin":
        raise HTTPException(403, detail="Only admins can manage global MCP")

    admin_agent_id = _get_admin_agent_id()
    admin_config = load_agent_config(admin_agent_id)

    if admin_config.mcp is None or client_key not in admin_config.mcp.clients:
        raise HTTPException(
            404, detail=f"Global MCP client '{client_key}' not found",
        )

    del admin_config.mcp.clients[client_key]
    save_agent_config(admin_agent_id, admin_config)
    _trigger_reload(request, admin_agent_id)

    return {"status": "deleted", "key": client_key, "scope": "global"}


# ─── MCP Package Installation ─────────────────────────────────────────────


class MCPInstallRequest(BaseModel):
    """Request to install an MCP server package."""

    package: str = Field(..., description="Package name (e.g. 'mcp-server-time')")
    install_type: Literal["pip", "npm"] = Field(
        default="pip",
        description="Package manager: 'pip' or 'npm'",
    )


class MCPInstallResponse(BaseModel):
    """Response for MCP package installation."""

    status: Literal["success", "error", "already_installed"]
    message: str
    package: str
    install_type: str


def _get_installed_record(agent_id: str) -> Dict[str, List[str]]:
    """Load installed MCP packages record for a user."""
    import json as _json
    from pathlib import Path

    username = agent_id.split(":")[-1] if ":" in agent_id else agent_id
    record_path = Path(WORKSPACES_DIR) / username / "mcp_installed.json"
    if record_path.exists():
        try:
            return _json.loads(record_path.read_text())
        except Exception:
            pass
    return {"pip": [], "npm": []}


def _save_installed_record(agent_id: str, record: Dict[str, List[str]]) -> None:
    """Save installed MCP packages record for a user."""
    import json as _json
    from pathlib import Path

    username = agent_id.split(":")[-1] if ":" in agent_id else agent_id
    record_path = Path(WORKSPACES_DIR) / username / "mcp_installed.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(_json.dumps(record, indent=2, ensure_ascii=False))


def _validate_package_name(package: str) -> None:
    """Validate package name for safety."""
    # Only allow alphanumeric, hyphens, underscores, dots, @, /
    if not re.match(r'^[@a-zA-Z0-9_./-]+$', package):
        raise HTTPException(400, detail=f"Invalid package name: {package}")
    # Block obviously dangerous patterns
    for bad in ["..", ";", "|", "&", "$", "`", "(", ")"]:
        if bad in package:
            raise HTTPException(400, detail=f"Invalid package name: {package}")


@router.post(
    "/mcp/install",
    response_model=MCPInstallResponse,
    summary="Install an MCP server package",
)
@require_permission("mcp:write")
async def install_mcp_package(
    request: Request,
    body: MCPInstallRequest = Body(...),
) -> MCPInstallResponse:
    """Install an MCP server package via pip or npm.

    - Validates package name for safety
    - Installs with --no-cache-dir (pip) or -g (npm)
    - Records installed packages for auto-restore on container restart
    - Returns installation result
    """
    import asyncio

    _validate_package_name(body.package)

    # Determine agent_id
    username = getattr(request.state, "username", "admin")
    agent_id = f"user:{username}"

    record = _get_installed_record(agent_id)
    pkg_list = record.setdefault(body.install_type, [])

    # Check if already installed
    already = body.package in pkg_list
    if already:
        # Verify it's actually importable
        if body.install_type == "pip":
            try:
                module_name = body.package.replace("-", "_").split("[")[0]
                proc = await asyncio.create_subprocess_exec(
                    "python3", "-c", f"import {module_name}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
                if proc.returncode == 0:
                    return MCPInstallResponse(
                        status="already_installed",
                        message=f"{body.package} is already installed",
                        package=body.package,
                        install_type=body.install_type,
                    )
            except Exception:
                pass  # Reinstall

    # Build install command
    if body.install_type == "pip":
        cmd = ["pip", "install", "--no-cache-dir", "-q", body.package]
    elif body.install_type == "npm":
        cmd = ["npm", "install", "-g", body.package]
    else:
        raise HTTPException(400, detail=f"Unsupported install type: {body.install_type}")

    logger.info(f"MCP install: {' '.join(cmd)} (user={username})")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        output = stdout.decode("utf-8", errors="replace")[-500:]  # Last 500 chars

        if proc.returncode == 0:
            # Record successful installation
            if body.package not in pkg_list:
                pkg_list.append(body.package)
            _save_installed_record(agent_id, record)

            return MCPInstallResponse(
                status="success",
                message=f"Installed successfully. {output}".strip(),
                package=body.package,
                install_type=body.install_type,
            )
        else:
            return MCPInstallResponse(
                status="error",
                message=f"Installation failed (exit {proc.returncode}): {output}",
                package=body.package,
                install_type=body.install_type,
            )
    except asyncio.TimeoutError:
        return MCPInstallResponse(
            status="error",
            message="Installation timed out (120s)",
            package=body.package,
            install_type=body.install_type,
        )
    except Exception as e:
        return MCPInstallResponse(
            status="error",
            message=f"Installation error: {e}",
            package=body.package,
            install_type=body.install_type,
        )
