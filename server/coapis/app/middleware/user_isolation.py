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

"""User isolation middleware - ensures users can only access their own resources.

Uses @app.middleware("http") pattern for SSE compatibility.
"""
from __future__ import annotations

import logging
from fastapi import FastAPI, Request, HTTPException
from starlette.responses import Response

from ..auth import is_auth_enabled

logger = logging.getLogger(__name__)


# Paths that require user isolation (user can only access own resources)
WORKSPACE_PREFIXES = [
    "/workspace/agents",
    "/workspace/models",
    "/workspace/skills",
    "/workspace/security",
    "/workspace/backups",
    "/workspace/audit",
    "/workspace/myspace",
    "/myfiles",  # legacy alias
]

# Paths that require admin role
ADMIN_PREFIXES = [
    "/admin/system",
    "/admin/users",
    "/admin/config",
    "/admin/audit",
    "/admin/templates",
    "/admin/global-agents",
    "/admin/tools",
    "/admin",
]

# Paths that don't require authentication
PUBLIC_PATHS = [
    "/api/health",
    "/health",
    "/api/auth/login",
    "/auth/login",
    "/api/auth/register",
    "/auth/register",
    "/api/auth/status",
    "/auth/status",
    "/api/users/config",
    "/users/config",
    "/api/users/register",
    "/users/register",
    "/api/level-info",
    "/level-info",
    "/api/tokens/config",
    "/tokens/config",
    # SSE streaming endpoints
    "/api/console/chat",
    "/console/chat",
]


def is_public_path(path: str) -> bool:
    """Check if path is public (no auth required).
    
    Uses exact match only to avoid false positives.
    e.g., /api/user/me should NOT match /api/users/register
    
    Returns True only if path exactly matches a public path.
    """
    return path in PUBLIC_PATHS


def is_workspace_path(path: str) -> bool:
    """Check if path is a workspace path (user isolation required)."""
    for prefix in WORKSPACE_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def is_admin_path(path: str) -> bool:
    """Check if path is an admin path (admin role required)."""
    for prefix in ADMIN_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def install_user_isolation_middleware(app: FastAPI):
    """Install user isolation middleware using @app.middleware('http') pattern.

    This avoids the BaseHTTPMiddleware thread-pool deadlock with SSE streaming.
    """

    @app.middleware("http")
    async def user_isolation_middleware(request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method

        # Skip OPTIONS requests (CORS preflight)
        if method == "OPTIONS":
            return await call_next(request)

        # Public paths: no check
        if is_public_path(path):
            return await call_next(request)

        # ── FIX P0-1: If auth is disabled, skip all checks ──
        if not is_auth_enabled():
            return await call_next(request)

        # Get current user info (set by AuthMiddleware or UserContextMiddleware)
        username = getattr(request.state, "username", None)
        user_role = getattr(request.state, "role", "user")

        # Fallback: try to get from user_info dict (AuthMiddleware)
        if not username:
            user_info = getattr(request.state, "user_info", None)
            if user_info and isinstance(user_info, dict):
                username = user_info.get("username", "anonymous")
                user_role = user_info.get("role", "user")

        # Final fallback
        if not username:
            username = "anonymous"
        if not user_role:
            user_role = "user"

        # Admin paths: require admin role
        if is_admin_path(path):
            if user_role not in ("admin", "superadmin"):
                logger.warning(
                    f"Unauthorized admin access attempt: "
                    f"user={username} role={user_role} path={path}"
                )
                raise HTTPException(
                    status_code=403,
                    detail="需要管理员权限",
                )
            return await call_next(request)

        # Workspace paths: require authentication + user isolation
        if is_workspace_path(path):
            if username == "anonymous":
                raise HTTPException(
                    status_code=401,
                    detail="需要登录",
                )

            # Extract target username from query params if present
            target_username = None

            # Check query parameter
            if "username" in request.query_params:
                target_username = request.query_params.get("username")

            # Admin can access any user's resources
            if user_role in ("admin", "superadmin"):
                return await call_next(request)

            # Non-admin can only access own resources
            if target_username and target_username != username:
                logger.warning(
                    f"User isolation violation: "
                    f"user={username} tried to access {target_username}'s resource at {path}"
                )
                raise HTTPException(
                    status_code=403,
                    detail="无权访问其他用户的资源",
                )

            return await call_next(request)

        # ── FIX P0-2: Other non-public paths require authentication ──
        # When auth is enabled, anonymous users cannot access non-public paths
        if username == "anonymous":
            raise HTTPException(
                status_code=401,
                detail="需要登录",
            )

        return await call_next(request)
