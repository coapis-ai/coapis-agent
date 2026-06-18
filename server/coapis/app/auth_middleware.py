# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

"""
Async-compatible Auth Middleware for SSE streaming.

Uses @app.middleware("http") pattern — runs in the same event loop as route handlers.
This avoids the BaseHTTPMiddleware thread-pool deadlock that kills SSE async generators.

IMPORTANT: Must be installed via install_auth_middleware(app), NOT via app.add_middleware().
"""

import logging
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def install_auth_middleware(app):
    """Install auth middleware using @app.middleware('http') pattern.
    
    This MUST be called after the FastAPI app is created.
    Do NOT use app.add_middleware() for this — it wraps in BaseHTTPMiddleware
    which switches threads and deadlocks SSE streaming.
    """

    @app.middleware("http")
    async def auth_dispatch(request: Request, call_next):
        from .auth import (
            is_auth_enabled,
            verify_token,
            get_user,
            PUBLIC_PATHS,
            PUBLIC_PREFIXES,
        )

        path = request.url.path

        # Fast path: skip auth for public paths / disabled auth
        auth_disabled = not is_auth_enabled()
        is_public = (path in PUBLIC_PATHS)
        if not is_public:
            for prefix in PUBLIC_PREFIXES:
                if path.startswith(prefix):
                    is_public = True
                    break

        if auth_disabled:
            request.state.username = "anonymous"
            request.state.role = "user"
            request.state.user_info = {"username": "anonymous", "role": "user"}
            return await call_next(request)

        if is_public:
            # For SSE paths: extract token inline (no thread switch)
            if path == "/api/console/chat":
                auth_header = request.headers.get("authorization", "")
                username = "anonymous"
                role = "user"
                user_info = {"username": "anonymous", "role": "user"}

                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]
                    username = verify_token(token) or "anonymous"
                    if username != "anonymous":
                        user_info = get_user(username)
                        if user_info:
                            role = user_info.get("role", "user")

                # SECURITY: When auth is enabled, reject unauthenticated SSE requests
                if username == "anonymous" and not auth_disabled:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "需要登录"}
                    )

                request.state.username = username
                request.state.role = role
                request.state.user_info = user_info
                if username != "anonymous":
                    request.state.token = token

                return await call_next(request)

            # Other public paths: set anonymous context and skip auth
            request.state.username = "anonymous"
            request.state.role = "user"
            request.state.user_info = {"username": "anonymous", "role": "user"}
            return await call_next(request)

        # Allow browser page requests (SPA routes) to pass through.
        # The frontend will check auth state after loading and redirect to /login if needed.
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            request.state.username = "anonymous"
            request.state.role = "user"
            request.state.user_info = {"username": "anonymous", "role": "user"}
            return await call_next(request)

        # Full authentication required
        auth_header = request.headers.get("authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing authentication token"},
            )

        username = verify_token(token)
        if username is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        # Resolve user info - PREFER SQLite (authoritative source for roles)
        # SQLite-first strategy: roles are managed in user_system, not JSON
        user_info = None
        try:
            from ..user_system.service import get_user_by_username as us_get_user
            us_user = us_get_user(username)
            if us_user:
                user_info = {
                    "username": us_user.username,
                    "role": us_user.role,
                    "email": getattr(us_user, "email", ""),
                    "display_name": getattr(us_user, "display_name", us_user.username),
                }
                logger.info(f"Resolved user {username} from user_system SQLite (role={us_user.role})")
        except (ImportError, Exception) as e:
            logger.warning(f"user_system lookup failed: {e}")

        # Fallback: try JSON user_store if SQLite didn't have the user
        if user_info is None:
            user_info = get_user(username)
            if user_info:
                logger.info(f"Resolved user {username} from JSON user_store (role={user_info.get('role')})")

        if user_info is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "User not found"},
            )

        # Store in request.state
        request.state.user_info = user_info
        request.state.username = user_info.get("username", username)
        request.state.role = user_info.get("role", "user")
        request.state.token = token

        return await call_next(request)
