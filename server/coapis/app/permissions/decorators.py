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

"""Permission decorators for route-level access control.

⚠️ CRITICAL: @router.* MUST be OUTSIDE (above), @require_* MUST be INSIDE (below):

    ✅ CORRECT (FastAPI registers the wrapped function):
    @router.post("/skills/install")
    @require_permission("skills:write")
    async def install_skill(request: Request):
        ...

    ❌ WRONG (FastAPI registers the original function — decorator won't execute):
    @require_permission("skills:write")
    @router.post("/skills/install")
    async def install_skill(request: Request):
        ...

Why? FastAPI's @router.* decorator registers the function it wraps.
If @require_* is outside, FastAPI sees the original unwrapped function.

NOTE: All protected routes MUST have `request: Request` parameter for the
decorator to extract user info. FastAPI will inject it automatically.
"""

from __future__ import annotations

import functools
import inspect
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def _is_user_workspace_resource(request: Request, username: str) -> bool:
    """Check if the request targets a resource within the user's own workspace.

    Users have full CRUD权限 on resources under their workspace path
    (workspaces/{username}/). This enables "ownership fast track" — bypass
    the permission matrix when the user is operating on their own data.

    Args:
        request: FastAPI request object
        username: Current authenticated username

    Returns:
        True if the resource belongs to the user's workspace
    """
    if not username or username == "anonymous":
        return False

    # Get agent_id from X-Agent-Id header
    try:
        from ..agent_context import get_decoded_agent_id
        agent_id = get_decoded_agent_id(request)
    except Exception:
        agent_id = None

    # Case 1: User's default agent (user:{username})
    if agent_id == f"user:{username}":
        logger.debug(f"[PERM] Ownership fast track: {username} → default agent")
        return True

    # Case 2: User's sub-agent (any non-global agent_id)
    # Sub-agents live at workspaces/{username}/agents/{agent_id}/
    if agent_id and not agent_id.startswith("global_"):
        try:
            from ...constant import WORKSPACES_DIR
            agent_path = WORKSPACES_DIR / username / "agents" / agent_id
            if agent_path.exists() and agent_path.is_dir():
                logger.debug(f"[PERM] Ownership fast track: {username} → sub-agent {agent_id}")
                return True
        except Exception:
            pass

    # Case 3: Check request path for workspace-scoped endpoints
    # /api/workspace/*, /api/myspace/* etc. are always user-scoped
    path = request.url.path
    workspace_scoped_prefixes = [
        "/api/workspace/",
        "/api/myspace/",
    ]
    for prefix in workspace_scoped_prefixes:
        if path.startswith(prefix):
            logger.debug(f"[PERM] Ownership fast track: {username} → workspace path {path}")
            return True

    return False


def require_permission(permission: str):
    """Decorator that checks if user has the specified permission.

    The wrapped route function MUST have `request: Request` parameter.

    Args:
        permission: Permission string (e.g., "chat:send", "myspace:delete")

    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            # Find request object - try kwargs first, then positional args
            request = kwargs.get("request")
            
            if request is None:
                # FastAPI may inject Request as positional arg
                # Try to find it from positional arguments
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                
                if "request" in params:
                    req_idx = params.index("request")
                    if req_idx < len(args):
                        request = args[req_idx]
            
            if request is None:
                # Check if original function expects request
                sig = inspect.signature(func)
                if "request" in sig.parameters:
                    # FastAPI should have injected it — something is wrong
                    logger.error(
                        f"[PERM] {func.__name__}: request not found but expected. "
                        f"args={len(args)}, kwargs={list(kwargs.keys())}"
                    )
                    raise HTTPException(
                        status_code=500,
                        detail="Permission check failed: request not available"
                    )
                else:
                    # Function doesn't have request parameter — can't check
                    logger.warning(
                        f"[PERM] {func.__name__}: no request parameter, "
                        f"skipping permission check for '{permission}'"
                    )
                    return await func(*args, **kwargs)

            username = getattr(request.state, "username", None)

            # When auth is disabled, middleware sets username="anonymous"
            # and role="user" — allow through with default permissions
            if username == "anonymous":
                from ..auth import is_auth_enabled
                if not is_auth_enabled():
                    return await func(*args, **kwargs)
                raise HTTPException(status_code=401, detail="需要登录")
            if not username:
                raise HTTPException(status_code=401, detail="需要登录")

            role = getattr(request.state, "role", "user")

            # ── Ownership fast track ────────────────────────────────────
            # Users have full CRUD on resources within their own workspace
            # (workspaces/{username}/). No permission matrix check needed.
            if _is_user_workspace_resource(request, username):
                logger.info(
                    f"[PERM] {func.__name__}: user={username}, ownership fast track → ALLOW"
                )
                return await func(*args, **kwargs)

            # ── Permission matrix check ─────────────────────────────────
            try:
                from .manager import PermissionManager
                pm = PermissionManager.get_instance()
            except (RuntimeError, ImportError) as e:
                # SECURITY: Deny access when PermissionManager not initialized
                # Never silently allow — this was a critical RBAC bypass vulnerability
                logger.error(f"[PERM] {func.__name__}: PermissionManager not initialized, DENYING access")
                raise HTTPException(
                    status_code=503,
                    detail="Permission system unavailable. Contact administrator."
                )

            allowed = pm.has_permission(username, permission, role)
            logger.info(
                f"[PERM] {func.__name__}: user={username}, role={role}, "
                f"permission={permission}, allowed={allowed}"
            )

            if not allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"需要权限: {permission}"
                )

            return await func(*args, **kwargs)

        return wrapper
    return decorator


def require_role(role: str):
    """Decorator that checks if user has the specified role.

    The wrapped route function MUST have `request: Request` parameter.

    Args:
        role: Role string (e.g., "admin", "advanced", "user")

    Returns:
        Decorator function
    """
    # Role hierarchy: admin > advanced > user
    ROLE_HIERARCHY = {"admin": 4, "advanced": 3, "user": 2}

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            # Find request object - try kwargs first, then positional args
            request = kwargs.get("request")
            
            if request is None:
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                
                if "request" in params:
                    req_idx = params.index("request")
                    if req_idx < len(args):
                        request = args[req_idx]
            
            if request is None:
                sig = inspect.signature(func)
                if "request" in sig.parameters:
                    logger.error(
                        f"[ROLE] {func.__name__}: request not found but expected"
                    )
                    raise HTTPException(
                        status_code=500,
                        detail="Role check failed: request not available"
                    )
                else:
                    logger.warning(
                        f"[ROLE] {func.__name__}: no request parameter, "
                        f"skipping role check for '{role}'"
                    )
                    return await func(*args, **kwargs)

            username = getattr(request.state, "username", None)
            if username == "anonymous":
                from ..auth import is_auth_enabled
                if not is_auth_enabled():
                    return await func(*args, **kwargs)
                raise HTTPException(status_code=401, detail="需要登录")
            if not username:
                raise HTTPException(status_code=401, detail="需要登录")

            user_role = getattr(request.state, "role", "user")

            required_level = ROLE_HIERARCHY.get(role, 0)
            user_level = ROLE_HIERARCHY.get(user_role, 0)

            logger.info(
                f"[ROLE] {func.__name__}: user={username}, role={user_role}, "
                f"required={role}, allowed={user_level >= required_level}"
            )

            if user_level < required_level:
                raise HTTPException(
                    status_code=403,
                    detail=f"需要角色: {role} 或更高"
                )

            return await func(*args, **kwargs)

        return wrapper
    return decorator


def require_module_access(module: str):
    """Decorator that checks if user can access the specified module.

    The wrapped route function MUST have `request: Request` parameter.

    Args:
        module: Module name (e.g., "chat", "skills", "evolution")

    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            # Find request object - try kwargs first, then positional args
            request = kwargs.get("request")
            
            if request is None:
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                
                if "request" in params:
                    req_idx = params.index("request")
                    if req_idx < len(args):
                        request = args[req_idx]
            
            if request is None:
                sig = inspect.signature(func)
                if "request" in sig.parameters:
                    logger.error(
                        f"[MODULE] {func.__name__}: request not found but expected"
                    )
                    raise HTTPException(
                        status_code=500,
                        detail="Module check failed: request not available"
                    )
                else:
                    logger.warning(
                        f"[MODULE] {func.__name__}: no request parameter, "
                        f"skipping module check for '{module}'"
                    )
                    return await func(*args, **kwargs)

            username = getattr(request.state, "username", None)
            if username == "anonymous":
                from ..auth import is_auth_enabled
                if not is_auth_enabled():
                    return await func(*args, **kwargs)
                raise HTTPException(status_code=401, detail="需要登录")
            if not username:
                raise HTTPException(status_code=401, detail="需要登录")

            role = getattr(request.state, "role", "user")

            try:
                from .manager import PermissionManager
                pm = PermissionManager.get_instance()
            except (RuntimeError, ImportError) as e:
                # SECURITY: Deny access when PermissionManager not initialized
                # Never silently allow — this is a critical RBAC bypass vulnerability
                logger.error(f"[MODULE] {func.__name__}: PermissionManager not initialized, DENYING access")
                raise HTTPException(
                    status_code=503,
                    detail="Permission system unavailable. Contact administrator."
                )

            allowed = pm.can_access_module(username, module, role)
            logger.info(
                f"[MODULE] {func.__name__}: user={username}, role={role}, "
                f"module={module}, allowed={allowed}"
            )

            if not allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"无法访问模块: {module}"
                )

            return await func(*args, **kwargs)

        return wrapper
    return decorator


def check_agent_scope(request, agent_id, manager=None):
    """Check if current user has access to the target agent. Raises HTTPException(403) if denied."""
    username = getattr(request.state, "username", None)
    role = getattr(request.state, "role", "user")
    if role in ("admin", "superadmin"):
        return True
    if not username:
        raise HTTPException(status_code=403, detail="Authentication required")
    if manager is None:
        try:
            from ....app.agent_context import get_multi_agent_manager
            manager = get_multi_agent_manager()
        except Exception:
            raise HTTPException(status_code=503, detail="Service unavailable")
    try:
        agent = manager.agents.get(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        ws_dir = str(getattr(agent, "workspace_dir", "") or getattr(agent, "data_dir", ""))
        if not ws_dir or f"/workspaces/{username}/" in ws_dir:
            return True
        raise HTTPException(status_code=403, detail="Access denied: agent belongs to another user")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Scope check failed")
