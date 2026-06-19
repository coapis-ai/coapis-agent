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

"""MCP router - MCP client endpoints with user isolation.

Each user's MCP clients are stored in: workspaces/{username}/mcp/mcp_clients.json
This ensures complete isolation between users.

Note: Admin users can manage all MCP clients; regular users only see their own.
"""

import logging
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..permissions.decorators import require_permission
from fastapi import APIRouter, HTTPException, Body
from fastapi.requests import Request
from pydantic import BaseModel

from ...constant import WORKSPACES_DIR

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])


class MCPClientInfo(BaseModel):
    key: str
    name: str
    enabled: bool = True
    transport: str = "stdio"
    command: str = ""
    args: List[str] = []
    env: Dict[str, str] = {}
    url: str = ""
    timeout: int = 30


class MCPClientCreateRequest(BaseModel):
    key: str
    name: str
    transport: str = "stdio"
    command: str = ""
    args: List[str] = []
    env: Dict[str, str] = {}
    url: str = ""
    timeout: int = 30


class MCPClientUpdateRequest(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    transport: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    url: Optional[str] = None
    timeout: Optional[int] = None


class MCPToolInfo(BaseModel):
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = {}


# Per-user MCP store: {username: {key: MCPClientInfo}}
_mcp_clients: Dict[str, Dict[str, MCPClientInfo]] = {}


def _get_mcp_file(username: str) -> Path:
    """Get MCP file path for a specific user."""
    return WORKSPACES_DIR / username / "mcp" / "mcp_clients.json"


def _load_mcp_clients(username: str):
    """Load MCP clients from disk for a specific user."""
    if username in _mcp_clients:
        return  # Already loaded
    mcp_file = _get_mcp_file(username)
    user_clients: Dict[str, MCPClientInfo] = {}
    if mcp_file.exists():
        try:
            with open(mcp_file) as f:
                data = json.load(f)
            for item in data:
                user_clients[item["key"]] = MCPClientInfo(**item)
        except Exception as e:
            logger.error(f"Failed to load MCP clients for {username}: {e}")
    _mcp_clients[username] = user_clients


def _save_mcp_clients(username: str):
    """Save MCP clients to disk for a specific user."""
    mcp_file = _get_mcp_file(username)
    mcp_file.parent.mkdir(parents=True, exist_ok=True)
    user_clients = _mcp_clients.get(username, {})
    try:
        with open(mcp_file, "w") as f:
            json.dump([c.dict() for c in user_clients.values()], f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save MCP clients for {username}: {e}")


def _get_user_clients(request: Request) -> Dict[str, MCPClientInfo]:
    """Get MCP clients for the current user."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")
    _load_mcp_clients(username)
    return _mcp_clients.get(username, {})


@router.get("/mcp")
@require_permission("mcp:read")
async def list_mcp_clients(request: Request) -> List[Dict[str, Any]]:
    """List MCP clients for the current user."""
    username = getattr(request.state, "username", None)
    user_role = getattr(request.state, "role", "user")
    is_admin = (user_role in ("admin", "superadmin"))

    if is_admin:
        # Admin sees all MCP clients from all users
        all_clients = []
        for uname, clients in _mcp_clients.items():
            for c in clients.values():
                client_dict = c.dict()
                client_dict["username"] = uname
                all_clients.append(client_dict)
        return all_clients
    else:
        # Regular user sees only their own
        user_clients = _get_user_clients(request)
        return [c.dict() for c in user_clients.values()]


@router.get("/mcp/{client_key}")
@require_permission("mcp:read")
async def get_mcp_client(
    request: Request,
    client_key: str,
) -> Dict[str, Any]:
    """Get MCP client details for the current user."""
    username = getattr(request.state, "username", None)
    user_role = getattr(request.state, "role", "user")
    is_admin = (user_role in ("admin", "superadmin"))

    if is_admin:
        # Admin can access any client
        for uname, clients in _mcp_clients.items():
            if client_key in clients:
                result = clients[client_key].dict()
                result["username"] = uname
                return result
        raise HTTPException(status_code=404, detail="MCP client not found")
    else:
        # Regular user can only access their own
        user_clients = _get_user_clients(request)
        if client_key not in user_clients:
            raise HTTPException(status_code=404, detail="MCP client not found")
        return user_clients[client_key].dict()


@router.post("/mcp")
@require_permission("mcp:write")
async def create_mcp_client(
    request: Request,
    payload: MCPClientCreateRequest = Body(...),
) -> Dict[str, Any]:
    """Create a new MCP client for the current user."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    _load_mcp_clients(username)
    user_clients = _mcp_clients.setdefault(username, {})

    if payload.key in user_clients:
        raise HTTPException(status_code=409, detail="MCP client key already exists")

    client = MCPClientInfo(
        key=payload.key,
        name=payload.name,
        enabled=True,
        transport=payload.transport,
        command=payload.command,
        args=payload.args,
        env=payload.env,
        url=payload.url,
        timeout=payload.timeout,
    )

    user_clients[payload.key] = client
    _save_mcp_clients(username)

    return client.dict()


@router.put("/mcp/{client_key}")
@require_permission("mcp:write")
async def update_mcp_client(
    request: Request,
    client_key: str,
    payload: MCPClientUpdateRequest = Body(...),
) -> Dict[str, Any]:
    """Update an MCP client for the current user."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_clients = _get_user_clients(request)
    if client_key not in user_clients:
        raise HTTPException(status_code=404, detail="MCP client not found")

    client = user_clients[client_key]
    if payload.name is not None:
        client.name = payload.name
    if payload.enabled is not None:
        client.enabled = payload.enabled
    if payload.transport is not None:
        client.transport = payload.transport
    if payload.command is not None:
        client.command = payload.command
    if payload.args is not None:
        client.args = payload.args
    if payload.env is not None:
        client.env = payload.env
    if payload.url is not None:
        client.url = payload.url
    if payload.timeout is not None:
        client.timeout = payload.timeout

    _save_mcp_clients(username)
    return client.dict()


@router.patch("/mcp/{client_key}/toggle")
@require_permission("mcp:write")
async def toggle_mcp_client(
    request: Request,
    client_key: str,
) -> Dict[str, Any]:
    """Toggle MCP client enabled status for the current user."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_clients = _get_user_clients(request)
    if client_key not in user_clients:
        raise HTTPException(status_code=404, detail="MCP client not found")

    user_clients[client_key].enabled = not user_clients[client_key].enabled
    _save_mcp_clients(username)
    return user_clients[client_key].dict()


@router.delete("/mcp/{client_key}")
@require_permission("mcp:write")
async def delete_mcp_client(
    request: Request,
    client_key: str,
) -> Dict[str, Any]:
    """Delete an MCP client for the current user."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_clients = _get_user_clients(request)
    if client_key in user_clients:
        del user_clients[client_key]
        _save_mcp_clients(username)
    return {"message": "MCP client deleted"}


@router.get("/mcp/{client_key}/tools")
@require_permission("mcp:read")
async def list_mcp_tools(
    request: Request,
    client_key: str,
) -> List[Dict[str, Any]]:
    """List tools from an MCP client for the current user."""
    user_clients = _get_user_clients(request)
    if client_key not in user_clients:
        raise HTTPException(status_code=404, detail="MCP client not found")

    # For now, return empty list
    return []


# Startup hook
async def init_mcp_clients():
    """Initialize MCP clients on startup (load all existing users)."""
    for user_dir in constant.WORKSPACES_DIR.iterdir():
        if user_dir.is_dir():
            _load_mcp_clients(user_dir.name)
    total = sum(len(v) for v in _mcp_clients.values())
    logger.info(f"Loaded {total} MCP clients for {len(_mcp_clients)} users")
