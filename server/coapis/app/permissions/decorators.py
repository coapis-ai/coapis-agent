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

"""Permission gates for route-level access control.

TWO STYLES, BOTH ENFORCED (fail-closed):

1. Dependency style — RECOMMENDED, order-proof, no `request` param needed:

       from fastapi import Depends
       from ..permissions.decorators import require_perm

       @router.get("/admin/tags", dependencies=[Depends(require_perm("tag:read"))])
       async def list_tags():
           ...

   FastAPI injects `Request` into the dependency itself, so the gate can
   never be silently skipped by forgetting a parameter, and decorator
   ordering does not matter.

2. Decorator style — legacy, kept for compatibility:

       @router.post("/skills/install")     # router.* MUST be OUTSIDE (above)
       @require_permission("skills:write") # require_* MUST be INSIDE (below)
       async def install_skill(request: Request):   # MUST take `request`
           ...

   FastAPI's @router.* registers the function it wraps; if @require_* is
   outside, FastAPI sees the original unwrapped function and the gate
   never runs.

⚠️ FAIL-CLOSED: the decorator style raises 500 when `request` is missing
   instead of silently allowing the call. A gate that cannot identify the
   caller must deny, never allow. (This is the fix for the 2026-10 audit
   finding "52 routes skipped the permission check".)
"""

from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, Callable, Optional, Tuple

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


# ── Ownership fast track policy ─────────────────────────────────────
#
# The fast track lets a user act on their OWN data without the permission
# matrix. It used to fire on the mere presence of an `X-Agent-Id` header
# pointing at the caller's own agent, which is sent by the console on every
# chat/agents/skills/channel request — so it silently bypassed the matrix on
# ~175 admin endpoints (envs, tool-guard, tools enable-all, ...).
#
# Tightened: the fast track fires ONLY on path prefixes that are inherently
# user-scoped, and NEVER for admin/system-level permission keys.

_FAST_TRACK_PREFIXES: Tuple[str, ...] = (
    "/api/workspace/",
    "/api/myspace/",
)

# Modules that are never user-owned, whatever the path says.
_FAST_TRACK_DENY_MODULES: frozenset = frozenset({
    "admin", "system", "audit", "acp", "debug", "tools", "tag", "scene",
    "models", "mcp", "backups", "channels",
})

# Specific keys that must always go through the matrix even in
# user-scoped namespaces.
_FAST_TRACK_DENY_KEYS: frozenset = frozenset({
    "security:write",
    "security:delete",
    "evolution:delete",
    "agents:delete",
})


def _is_user_workspace_resource(
    request: Request,
    username: str,
    permission: Optional[str] = None,
) -> bool:
    """True when the request targets the caller's own workspace namespace.

    Only path prefixes that are inherently user-scoped qualify
    (`/api/workspace/*`, `/api/myspace/*`). Admin/system permission keys are
    excluded outright — owning an agent does not make you an admin.

    Args:
        request: FastAPI request object
        username: Authenticated username
        permission: Permission key being gated (used for the deny-list)

    Returns:
        True if the permission matrix may be skipped for this call
    """
    if not username or username == "anonymous":
        return False

    if permission:
        module = permission.split(":", 1)[0] if ":" in permission else permission
        if module in _FAST_TRACK_DENY_MODULES:
            return False
        if permission in _FAST_TRACK_DENY_KEYS:
            return False

    path = request.url.path
    for prefix in _FAST_TRACK_PREFIXES:
        if path.startswith(prefix):
            logger.debug(
                f"[PERM] Ownership fast track: {username} → {path}"
            )
            return True

    return False


# ── Shared core check ───────────────────────────────────────────────


def _resolve_identity(request: Request) -> Tuple[Optional[str], str]:
    username = getattr(request.state, "username", None)
    role = getattr(request.state, "role", "user")
    return username, role


def _perform_permission_check(request: Request, permission: str) -> None:
    """Enforce a permission key against the caller. Raises HTTPException.

    This is the single source of truth used by BOTH the decorator style and
    the dependency style, so the two can never drift apart.
    """
    username, role = _resolve_identity(request)

    # Auth disabled → middleware sets username="anonymous"; allow through.
    if username == "anonymous":
        from ..auth import is_auth_enabled

        if not is_auth_enabled():
            return
        raise HTTPException(status_code=401, detail="需要登录")
    if not username:
        raise HTTPException(status_code=401, detail="需要登录")

    # ── Ownership fast track (tightened: user-scoped prefixes only) ──
    if _is_user_workspace_resource(request, username, permission):
        logger.info(
            f"[PERM] fast-track user={username} permission={permission} "
            f"path={request.url.path} → ALLOW"
        )
        return

    try:
        from .manager import PermissionManager

        pm = PermissionManager.get_instance()
    except (RuntimeError, ImportError) as e:
        # SECURITY: Deny access when PermissionManager is not initialized.
        # Never silently allow — this was a critical RBAC bypass vulnerability.
        logger.error(f"[PERM] PermissionManager not initialized, DENYING: {e}")
        raise HTTPException(
            status_code=503,
            detail="Permission system unavailable. Contact administrator.",
        )

    allowed = pm.has_permission(username, permission, role)
    if not allowed:
        logger.info(
            f"[PERM] DENY user={username} role={role} permission={permission} "
            f"path={request.url.path}"
        )
        raise HTTPException(status_code=403, detail=f"需要权限: {permission}")
    logger.debug(
        f"[PERM] ALLOW user={username} role={role} permission={permission} "
        f"path={request.url.path}"
    )


def _extract_request(
    func: Callable, args: tuple, kwargs: dict
) -> Optional[Request]:
    """Locate the Request object FastAPI injected, if any."""
    request = kwargs.get("request")
    if isinstance(request, Request):
        return request
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())
    if "request" in params:
        idx = params.index("request")
        if idx < len(args) and isinstance(args[idx], Request):
            return args[idx]
    return None


# ── Dependency style (recommended) ──────────────────────────────────


def require_perm(permission: str):
    """Build a FastAPI dependency enforcing `permission`.

    Usage:
        @router.get("/x", dependencies=[Depends(require_perm("admin:admin"))])

    Order-proof and parameter-proof: FastAPI hands the dependency the
    Request itself, so the gate always runs.
    """

    async def _dependency(request: Request) -> None:
        _perform_permission_check(request, permission)

    _dependency.__name__ = f"require_perm_{permission.replace(':', '_')}"
    _dependency._required_permission = permission
    return _dependency


# ── Decorator style (legacy, kept compatible) ───────────────────────


def require_permission(permission: str):
    """Decorator enforcing `permission` on a route.

    The wrapped route MUST accept a `request: Request` parameter; if it does
    not, the call fails with 500 (fail-closed) instead of skipping the gate.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            request = _extract_request(func, args, kwargs)

            if request is None:
                # Fail-closed: a gate that cannot see the caller must deny.
                logger.error(
                    f"[PERM] {func.__name__}: missing `request: Request` — "
                    f"gate for '{permission}' cannot run. DENYING. "
                    f"Fix: add `request: Request` to the signature, or "
                    f"migrate to dependencies=[Depends(require_perm(...))]."
                )
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Permission check cannot run: route is missing "
                        "`request: Request`. This is a server bug."
                    ),
                )

            _perform_permission_check(request, permission)
            return await func(*args, **kwargs)

        # 审计/测试用：把路由要求的权限串挂在 wrapper 上，
        # 便于断言“某条路由到底把守在哪一格”，避免权限位挂错无人发现。
        wrapper._required_permission = permission
        return wrapper

    return decorator


def require_role(role: str):
    """Decorator enforcing a minimum role (admin > advanced > user)."""
    ROLE_HIERARCHY = {"admin": 4, "advanced": 3, "user": 2}

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            request = _extract_request(func, args, kwargs)
            if request is None:
                logger.error(
                    f"[ROLE] {func.__name__}: missing `request: Request` — "
                    f"role gate for '{role}' cannot run. DENYING."
                )
                raise HTTPException(
                    status_code=500,
                    detail="Role check cannot run: route is missing `request: Request`.",
                )

            username, user_role = _resolve_identity(request)
            if username == "anonymous":
                from ..auth import is_auth_enabled

                if not is_auth_enabled():
                    return await func(*args, **kwargs)
                raise HTTPException(status_code=401, detail="需要登录")
            if not username:
                raise HTTPException(status_code=401, detail="需要登录")

            required_level = ROLE_HIERARCHY.get(role, 0)
            user_level = ROLE_HIERARCHY.get(user_role, 0)
            logger.info(
                f"[ROLE] {func.__name__}: user={username}, role={user_role}, "
                f"required={role}, allowed={user_level >= required_level}"
            )
            if user_level < required_level:
                raise HTTPException(
                    status_code=403, detail=f"需要角色: {role} 或更高"
                )
            return await func(*args, **kwargs)

        wrapper._required_role = role
        return wrapper

    return decorator


def require_module_access(module: str):
    """Decorator enforcing access to a whole module (any CRUD bit)."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            request = _extract_request(func, args, kwargs)
            if request is None:
                logger.error(
                    f"[MODULE] {func.__name__}: missing `request: Request` — "
                    f"module gate for '{module}' cannot run. DENYING."
                )
                raise HTTPException(
                    status_code=500,
                    detail="Module check cannot run: route is missing `request: Request`.",
                )

            username, role = _resolve_identity(request)
            if username == "anonymous":
                from ..auth import is_auth_enabled

                if not is_auth_enabled():
                    return await func(*args, **kwargs)
                raise HTTPException(status_code=401, detail="需要登录")
            if not username:
                raise HTTPException(status_code=401, detail="需要登录")

            try:
                from .manager import PermissionManager

                pm = PermissionManager.get_instance()
            except (RuntimeError, ImportError) as e:
                # SECURITY: Deny access when PermissionManager is not initialized.
                logger.error(
                    f"[MODULE] {func.__name__}: PermissionManager not "
                    f"initialized, DENYING access: {e}"
                )
                raise HTTPException(
                    status_code=503,
                    detail="Permission system unavailable. Contact administrator.",
                )

            allowed = pm.can_access_module(username, module, role)
            logger.info(
                f"[MODULE] {func.__name__}: user={username}, role={role}, "
                f"module={module}, allowed={allowed}"
            )
            if not allowed:
                raise HTTPException(
                    status_code=403, detail=f"无法访问模块: {module}"
                )
            return await func(*args, **kwargs)

        wrapper._required_module = module
        return wrapper

    return decorator


def check_agent_scope(request, agent_id, manager=None):
    """Check if current user has access to the target agent.

    Raises HTTPException(403) if denied.
    """
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
