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

"""User system middleware - optional quota checking and rate limiting.

These middleware are no-ops when USER_SYSTEM_ENABLED=False,
ensering zero impact on existing functionality.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..user_system.config import get_config
from ..user_system.tokens import check_quota

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory rate limiter (sliding window)
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Simple in-memory sliding window rate limiter."""

    def __init__(self):
        self._requests: Dict[str, list] = {}
        self._cleanup_interval = 300  # Clean every 5 minutes
        self._last_cleanup = time.time()

    def is_allowed(self, key: str, limit: int) -> bool:
        """Check if request is allowed under rate limit."""
        now = time.time()

        # Periodic cleanup
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup(now)
            self._last_cleanup = now

        if key not in self._requests:
            self._requests[key] = []

        # Remove old entries outside the window (1 second window)
        window_start = now - 1.0
        self._requests[key] = [t for t in self._requests[key] if t > window_start]

        if len(self._requests[key]) >= limit:
            return False

        self._requests[key].append(now)
        return True

    def _cleanup(self, now: float) -> None:
        """Remove stale entries."""
        window_start = now - 2.0
        self._requests = {
            k: [t for t in v if t > window_start]
            for k, v in self._requests.items()
        }
        # Remove empty entries
        self._requests = {k: v for k, v in self._requests.items() if v}


_global_rate_limiter = _RateLimiter()


# ---------------------------------------------------------------------------
# QuotaCheckMiddleware
# ---------------------------------------------------------------------------

class QuotaCheckMiddleware(BaseHTTPMiddleware):
    """Middleware that checks token quota before processing chat requests.

    - Disabled when USER_SYSTEM_ENABLED=False
    - Only checks on chat-related endpoints
    - Soft limit by default (allows up to 120%)
    """

    # Paths that should trigger quota checking
    QUOTA_CHECK_PATHS = ("/api/console/chat", "/api/chat")

    async def dispatch(self, request: Request, call_next):
        cfg = get_config()

        # Skip if user system is disabled
        if not cfg.enabled:
            return await call_next(request)

        # Only check quota on chat endpoints
        if request.url.path not in self.QUOTA_CHECK_PATHS:
            return await call_next(request)

        # Only check on POST requests
        if request.method != "POST":
            return await call_next(request)

        # Get username from request state (set by auth middleware)
        username = getattr(request.state, "username", "anonymous")

        # Skip anonymous users (they always have quota)
        if username == "anonymous":
            return await call_next(request)

        # Check quota
        quota_status = check_quota(username)
        if not quota_status["allowed"]:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Token quota exceeded",
                    "detail": {
                        "quota": quota_status["quota"],
                        "used": quota_status["used"],
                        "remaining": quota_status["remaining"],
                        "usage_percent": quota_status["usage_percent"],
                    },
                },
            )

        # Add quota info to response headers
        response = await call_next(request)
        if isinstance(response, JSONResponse):
            response.headers["X-Token-Remaining"] = str(quota_status["remaining"])
            response.headers["X-Token-Quota"] = str(quota_status["quota"])
        return response


# ---------------------------------------------------------------------------
# RateLimitMiddleware
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces per-user rate limits based on user level.

    - Disabled when USER_SYSTEM_ENABLED=False
    - Uses sliding window (1 second)
    - Rate limit varies by user level
    """

    # Paths to skip rate limiting
    SKIP_PATHS = ("/api/health", "/health", "/api/auth/login", "/api/auth/register", "/docs")

    async def dispatch(self, request: Request, call_next):
        cfg = get_config()

        # Skip if user system is disabled
        if not cfg.enabled:
            return await call_next(request)

        # Skip certain paths
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        # Get username from request state
        username = getattr(request.state, "username", "anonymous")

        # Get user level
        from ..user_system.service import get_user_by_username
        user = get_user_by_username(username) if username != "anonymous" else None
        level = user.level if user else 0

        # Get rate limit for this level
        limit = cfg.get_rate_limit(level)

        # Create rate limit key
        rl_key = f"rate:{username}"

        # Check rate limit
        if not _global_rate_limiter.is_allowed(rl_key, limit):
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "detail": {
                        "limit": limit,
                        "window": "1s",
                        "level": level,
                    },
                },
            )

        response = await call_next(request)
        return response


# ---------------------------------------------------------------------------
# UserContextMiddleware
# ---------------------------------------------------------------------------

class UserContextMiddleware(BaseHTTPMiddleware):
    """Middleware that sets user context on request.state.

    Extracts username from existing auth system and sets it on request.state
    for use by other middleware and endpoints.

    - When USER_SYSTEM_ENABLED=False: sets username to "anonymous"
    - When USER_SYSTEM_ENABLED=True: uses existing auth middleware result
    """

    async def dispatch(self, request: Request, call_next):
        cfg = get_config()

        # Get username from existing auth system
        username = getattr(request.state, "username", None)

        if not username:
            if cfg.enabled:
                # User system enabled but no auth - check token from existing system
                username = self._extract_username_from_token(request)

            if not username:
                username = "anonymous"

        request.state.username = username

        if cfg.enabled and username != "anonymous":
            # Also set user object on request.state
            from ..user_system.service import get_user_by_username
            request.state.user = get_user_by_username(username)

        return await call_next(request)

    def _extract_username_from_token(self, request: Request) -> Optional[str]:
        """Try to extract username from existing auth token."""
        # Check Authorization header
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            # Use existing auth verification
            from ..app.auth import verify_token
            payload = verify_token(token)
            if payload and "username" in payload:
                return payload["username"]

        # Check existing request.state from AuthMiddleware
        if hasattr(request.state, "user_info"):
            return request.state.user_info.get("username")

        return None
