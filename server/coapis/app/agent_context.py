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

"""Agent context utilities for multi-agent support.

Provides utilities to get the correct agent instance for each request.
"""
import json
from contextvars import ContextVar
from typing import Optional, TYPE_CHECKING
from fastapi import Request
from .multi_agent_manager import MultiAgentManager
from ..config.utils import load_config

if TYPE_CHECKING:
    from .workspace import Workspace


def get_decoded_agent_id(request: Request) -> Optional[str]:
    """Get the decoded X-Agent-Id from request.

    Priority: request.state.decoded_agent_id (set by middleware) → header raw.
    The middleware decodes encodeURIComponent()-encoded values, so downstream
    code should always use this helper instead of reading the header directly.
    """
    decoded = getattr(request.state, "decoded_agent_id", None)
    if decoded:
        return decoded
    raw = request.headers.get("X-Agent-Id")
    return raw

# Context variable to store current agent ID across async calls
_current_agent_id: ContextVar[Optional[str]] = ContextVar(
    "current_agent_id",
    default=None,
)

# Context variable to store current session id across async calls
_current_session_id: ContextVar[Optional[str]] = ContextVar(
    "current_session_id",
    default=None,
)

# Context variable to store current root session id for cross-session approval
_current_root_session_id: ContextVar[Optional[str]] = ContextVar(
    "current_root_session_id",
    default=None,
)


async def get_agent_for_request(
    request: Request,
    agent_id: Optional[str] = None,
) -> "Workspace":
    """Get agent workspace for current request.

    Priority:
    1. agent_id parameter (explicit override)
    2. request.state.agent_id (from agent-scoped router)
    3. X-Agent-Id header (from frontend)
    4. Active agent from config

    Args:
        request: FastAPI request object
        agent_id: Agent ID override (highest priority)

    Returns:
        Workspace for the specified or active agent

    Raises:
        HTTPException: If agent not found
    """
    from fastapi import HTTPException

    # Determine which agent to use
    target_agent_id = agent_id

    # Check request.state.agent_id (set by agent-scoped router)
    if not target_agent_id and hasattr(request.state, "agent_id"):
        target_agent_id = request.state.agent_id

    # Check X-Agent-Id header (decoded by middleware)
    if not target_agent_id:
        target_agent_id = get_decoded_agent_id(request)

    # Resolve legacy "default" agent_id to user:{username}
    if target_agent_id == "default":
        username = None
        if hasattr(request.state, "username"):
            username = request.state.username
        if not username:
            user_info = getattr(request.state, "user_info", None)
            if user_info and isinstance(user_info, dict):
                username = user_info.get("username")
        if username:
            target_agent_id = f"user:{username}"
            # Store resolved ID so downstream sees the correct value
            request.state.agent_id = target_agent_id

    # Load config once for fallback and validation
    config = None
    if not target_agent_id:
        # Fallback to active agent from config
        config = load_config()
        target_agent_id = config.agents.active_agent or "global_default"

    # Check if agent exists and is enabled
    # Check if agent exists by scanning workspace directories
    if config is None:
        config = load_config()
    agent_found = False
    agent_meta = {}
    caller = getattr(request.state, "username", None)
    from ..constant import AGENTS_DIR, WORKSPACES_DIR
    # 1. Check user workspace: workspaces/{caller}/agent.json
    if caller:
        ws_json = WORKSPACES_DIR / caller / "agent.json"
        if ws_json.exists():
            meta = json.loads(ws_json.read_text(encoding="utf-8"))
            if meta.get("id") == target_agent_id:
                agent_found = True
                agent_meta = meta
                if not agent_meta.get("owner"):
                    agent_meta["owner"] = caller  # auto-infer from workspace
    # 2. Check user sub-agent: workspaces/{caller}/agents/{agent_id}/agent.json
    if not agent_found and caller:
        sub_json = WORKSPACES_DIR / caller / "agents" / target_agent_id / "agent.json"
        if sub_json.exists():
            agent_meta = json.loads(sub_json.read_text(encoding="utf-8"))
            agent_found = True
            if not agent_meta.get("owner"):
                agent_meta["owner"] = caller
    # 3. Check global agent: agents/{agent_id}/agent.json
    if not agent_found:
        global_json = AGENTS_DIR / target_agent_id / "agent.json"
        if global_json.exists():
            agent_meta = json.loads(global_json.read_text(encoding="utf-8"))
            agent_found = True
    if not agent_found:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{target_agent_id}' not found",
        )
    if not agent_meta.get("enabled", True):
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{target_agent_id}' is disabled",
        )
    # Ownership check: user agents must belong to caller
    agent_owner = agent_meta.get("owner", "") or ""
    if not agent_owner or agent_owner != (caller or ""):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Access denied: agent '{target_agent_id}' "
                + (f"belongs to '{agent_owner}'" if agent_owner else "is a global agent")
                + f", not accessible by '{caller or 'anonymous'}'"
            ),
        )

    # Get MultiAgentManager (use _state dict to avoid Starlette State __getattr__ issues)
    manager = request.app.state._state.get("multi_agent_manager") if hasattr(request.app.state, "_state") else None
    
    if manager is None:
        # Fallback: try to get workspace from config when manager is not available
        # (e.g., TestClient mode or during startup)
        try:
            from ..constant import AGENTS_DIR
            from pathlib import Path
            
            # Try to load agent config directly from system/
            agent_config_path = AGENTS_DIR.parent / "system" / f"agent_{target_agent_id}.json"
            if agent_config_path.exists():
                with open(agent_config_path, "r") as f:
                    agent_data = json.load(f)
                
                # Create a minimal workspace object
                class MinimalWorkspace:
                    def __init__(self, agent_id: str, data: dict):
                        self.agent_id = agent_id
                        # Prefer workspace_dir from config; fallback to agents/{id}, never system/
                        self.workspace_dir = Path(data.get("workspace_dir",
                            str(AGENTS_DIR / agent_id)))
                        self.username = data.get("username", "")
                        self.is_global = data.get("is_global", True)
                        self.config = data
                    
                    @property
                    def profile(self):
                        return self.config
                
                return MinimalWorkspace(target_agent_id, agent_data)
        except Exception:
            pass
        
        # If fallback fails, return a workspace with default path (never system/)
        class MinimalWorkspace:
            def __init__(self, agent_id: str):
                from ..constant import AGENTS_DIR
                self.agent_id = agent_id
                self.workspace_dir = AGENTS_DIR / agent_id
                self.username = ""
                self.is_global = True
                self.config = {}
            
            @property
            def profile(self):
                return self.config
        
        return MinimalWorkspace(target_agent_id)

    # Manager is available - use it normally
    try:
        username = getattr(request.state, "username", None)
        workspace = await manager.get_agent(target_agent_id, username=username)
        if not workspace:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{target_agent_id}' not found",
            )
        return workspace
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get agent: {str(e)}",
        ) from e


def get_active_agent_id() -> str:
    """Get current active agent ID from config.

    Returns:
        Active agent ID, defaults to "global_default"
    """
    try:
        config = load_config()
        return config.agents.active_agent or "global_default"
    except Exception:
        return "global_default"


def set_current_agent_id(agent_id: str) -> None:
    """Set current agent ID in context.

    Args:
        agent_id: Agent ID to set
    """
    _current_agent_id.set(agent_id)


def get_current_agent_id() -> str:
    """Get current agent ID from context or config fallback.

    Returns:
        Current agent ID, defaults to active agent or "global_default"
    """
    agent_id = _current_agent_id.get()
    if agent_id:
        return agent_id
    return get_active_agent_id()


def set_current_session_id(session_id: str) -> None:
    _current_session_id.set(session_id)


def get_current_session_id() -> Optional[str]:
    return _current_session_id.get()


def set_current_root_session_id(root_session_id: Optional[str]) -> None:
    """Set current root session ID in context.

    Args:
        root_session_id: Root session ID to set
    """
    _current_root_session_id.set(root_session_id)


def get_current_root_session_id() -> Optional[str]:
    """Get current root session ID from context.

    Returns:
        Root session ID or None
    """
    return _current_root_session_id.get()
