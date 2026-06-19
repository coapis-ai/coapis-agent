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

"""Agent context utilities for multi-agent support.

Provides utilities to get the correct agent instance for each request.
"""
from contextvars import ContextVar
from typing import Optional, TYPE_CHECKING
from fastapi import Request
from .multi_agent_manager import MultiAgentManager
from ..config.utils import load_config

if TYPE_CHECKING:
    from .workspace import Workspace

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

    # Check X-Agent-Id header
    if not target_agent_id:
        target_agent_id = request.headers.get("X-Agent-Id")

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
    if config is None:
        config = load_config()
    if target_agent_id not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{target_agent_id}' not found",
        )

    agent_ref = config.agents.profiles[target_agent_id]
    if not getattr(agent_ref, "enabled", True):
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{target_agent_id}' is disabled",
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
                import json
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
