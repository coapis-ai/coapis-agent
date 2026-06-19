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
ensuring zero impact on existing functionality.

IMPORTANT: Uses @app.middleware("http") pattern to avoid BaseHTTPMiddleware
thread-pool deadlock with SSE async generators.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

from ..user_system.config import get_config
from ..user_system.tokens import check_quota

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory rate limiter (sliding window)
# ---------------------------------------------------------------------------

class _RateLimiter:
    """In-memory sliding window rate limiter with per-key isolation.

    Each key (username or IP) has its own independent bucket.
    One user exceeding their limit does NOT affect other users.
    """

    def __init__(self, window_seconds: float = 60.0, burst_factor: float = 1.3):
        self._requests: Dict[str, list] = {}
        self._window = window_seconds
        self._burst_factor = burst_factor
        self._cleanup_interval = 300  # Clean every 5 minutes
        self._last_cleanup = time.time()

    def is_allowed(self, key: str, limit: int) -> bool:
        """Check if request is allowed under rate limit.

        Returns True if allowed, False if rate limited.
        Each key has an independent bucket — one user's excess
        never impacts another user's quota.
        """
        now = time.time()

        # Periodic cleanup
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup(now)
            self._last_cleanup = now

        if key not in self._requests:
            self._requests[key] = []

        # Remove old entries outside the window
        window_start = now - self._window
        self._requests[key] = [t for t in self._requests[key] if t > window_start]

        # Apply burst tolerance (1.3x = allow 30% burst over window limit)
        max_in_window = int(limit * self._burst_factor)
        if len(self._requests[key]) >= max_in_window:
            return False

        self._requests[key].append(now)
        return True

    def get_remaining(self, key: str, limit: int) -> int:
        """Get remaining request count for a key within the window."""
        now = time.time()
        if key not in self._requests:
            return limit
        window_start = now - self._window
        recent = [t for t in self._requests[key] if t > window_start]
        max_in_window = int(limit * self._burst_factor)
        return max(0, max_in_window - len(recent))

    def get_reset_seconds(self, key: str) -> float:
        """Get seconds until the oldest request in the window expires."""
        now = time.time()
        if key not in self._requests or not self._requests[key]:
            return 0.0
        window_start = now - self._window
        recent = [t for t in self._requests[key] if t > window_start]
        if not recent:
            return 0.0
        oldest = min(recent)
        return max(0.0, oldest + self._window - now)

    def _cleanup(self, now: float) -> None:
        """Remove stale entries."""
        window_start = now - (self._window * 2)
        self._requests = {
            k: [t for t in v if t > window_start]
            for k, v in self._requests.items()
        }
        # Remove empty entries
        self._requests = {k: v for k, v in self._requests.items() if v}


# Per-user rate limiter (each user gets independent bucket)
_global_rate_limiter = _RateLimiter(window_seconds=60.0, burst_factor=1.3)
# Per-model global rate limiter (shared across all users for same model)
_global_model_limiter = _RateLimiter(window_seconds=60.0, burst_factor=1.5)


# Paths to skip for rate limiting (high-frequency internal endpoints)
SKIP_PATHS = [
    "/health",
    "/api/health",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/status",
    "/api/auth/verify",
    "/api/user/me",
    "/api/user/preferences",
    "/api/users/config",
    "/api/level-info",
    "/api/tokens/config",
    "/api/console/chat",  # SSE streaming — skip rate limit
    "/api/console/push-messages",  # High-frequency polling — skip rate limit
    "/api/cron/jobs",
    "/api/evolution/status",
    "/api/evolution/stats",
    "/api/evolution/experiences",
    "/api/evolution/knowledge-flow/status",
    "/api/evolution/review/status",
    "/api/foundation/status",
    "/api/foundation/memory",
    "/api/admin/users",
    "/api/admin/audit",
    "/api/myfiles",
    "/api/myfiles/usage",
    "/api/agents",                # Called on every page load
    "/api/config/channels",       # Called on console page
    "/api/models/available",      # Called on console page
    "/api/plugins",               # Called on every page load
    "/api/settings/language",     # Called on every page load
    "/api/chats",                 # Called on console page
]

# Paths that should be skipped by prefix match (e.g. /api/chats/{id}).
# Used in addition to exact SKIP_PATHS matching.
SKIP_PATH_PREFIXES = [
    "/api/chats/",    # /api/chats/{id}, /api/chats/{id}/messages, etc.
]


def _should_skip_path(path: str) -> bool:
    """Check if a path should be skipped (exact match or prefix match)."""
    return path in SKIP_PATHS or any(path.startswith(p) for p in SKIP_PATH_PREFIXES)


# ---------------------------------------------------------------------------
# Install functions for @app.middleware("http") pattern
# ---------------------------------------------------------------------------

def install_user_context_middleware(app):
    """Install UserContextMiddleware using @app.middleware("http").
    
    Sets user context on request.state for downstream use.
    """
    user_config = get_config()

    @app.middleware("http")
    async def user_context_dispatch(request: Request, call_next):
        if not user_config.enabled:
            return await call_next(request)

        path = request.url.path

        # Skip public paths
        if _should_skip_path(path):
            return await call_next(request)

        # Get username from auth middleware (already set)
        username = getattr(request.state, "username", None)
        if not username:
            return await call_next(request)

        # Set additional context
        request.state.user_context = {
            "username": username,
            "role": getattr(request.state, "role", "user"),
        }

        return await call_next(request)


def install_user_isolation_middleware(app):
    """Install UserIsolationMiddleware using @app.middleware("http").
    
    Ensures users can only access their own resources.
    """
    from ..app.middleware.user_isolation import (
        is_public_path,
        is_workspace_path,
        is_admin_path,
    )

    user_config = get_config()

    @app.middleware("http")
    async def user_isolation_dispatch(request: Request, call_next):
        if not user_config.enabled:
            return await call_next(request)

        path = request.url.path

        # Skip public paths
        if is_public_path(path):
            return await call_next(request)

        # Get username from auth middleware
        username = getattr(request.state, "username", None)
        if not username:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )

        role = getattr(request.state, "role", "user")

        # Check admin paths
        if is_admin_path(path):
            if role != "admin":
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Admin access required"},
                )

        return await call_next(request)


def install_quota_check_middleware(app):
    """Install QuotaCheckMiddleware using @app.middleware("http").
    
    Checks token quota before processing requests.
    """
    user_config = get_config()

    @app.middleware("http")
    async def quota_check_dispatch(request: Request, call_next):
        if not user_config.enabled:
            return await call_next(request)

        path = request.url.path

        # Skip public paths and SSE streaming
        if _should_skip_path(path):
            return await call_next(request)

        # Get username from auth middleware
        username = getattr(request.state, "username", None)
        if not username or username == "anonymous":
            return await call_next(request)

        # Check quota (non-blocking — logs warning but doesn't block)
        try:
            allowed = check_quota(username)
            if not allowed:
                logger.warning(f"User {username} exceeded token quota")
                # Note: quota check is advisory, not blocking
        except Exception as e:
            logger.warning(f"Quota check failed for {username}: {e}")

        return await call_next(request)


def install_rate_limit_middleware(app):
    """Install RateLimitMiddleware using @app.middleware("http").

    Two-layer rate limiting:
      1. Per-user: each user gets an independent sliding window bucket.
         One user exceeding their limit NEVER blocks other users.
      2. Per-model (global): shared across all users for the same model,
         prevents overloading a single LLM provider.
    """
    user_config = get_config()

    @app.middleware("http")
    async def rate_limit_dispatch(request: Request, call_next):
        if not user_config.enabled:
            return await call_next(request)

        path = request.url.path

        # Skip public paths and high-frequency endpoints
        if _should_skip_path(path):
            return await call_next(request)

        # Get username for rate limiting
        username = getattr(request.state, "username", "anonymous")
        if username == "anonymous":
            # Rate limit by IP for anonymous users
            username = request.client.host if request.client else "unknown"

        # Check rate limit (use per-level config, default to 60 req/10s)
        role = getattr(request.state, "role", "user")
        level = 1
        if role == "admin":
            level = 3
        elif role == "superadmin":
            level = 4
        rate_limit = user_config.get_rate_limit(level) or 60

        # --- Layer 1: Per-user rate limit (independent bucket per user) ---
        if not _global_rate_limiter.is_allowed(username, rate_limit):
            remaining = 0
            reset_sec = int(_global_rate_limiter.get_reset_seconds(username))
            logger.warning(
                f"Rate limit exceeded for user={username} role={role}"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Try again later.",
                    "retry_after": reset_sec,
                },
                headers={
                    "X-RateLimit-Limit": str(rate_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_sec),
                    "Retry-After": str(max(1, reset_sec)),
                },
            )

        # --- Layer 2: Per-model global limit (prevents LLM overload) ---
        # Only check for agent query endpoints
        if "/agents/" in path and request.method == "POST":
            model_key = "default"  # Could extract from request headers
            model_limit = 120  # 120 req/min global per model
            if not _global_model_limiter.is_allowed(model_key, model_limit):
                logger.warning(
                    f"Global model rate limit exceeded for model={model_key}"
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Global model rate limit exceeded. Please wait.",
                        "retry_after": 10,
                    },
                    headers={
                        "Retry-After": "10",
                    },
                )

        # Proceed with request and add rate limit headers to response
        response = await call_next(request)

        remaining = _global_rate_limiter.get_remaining(username, rate_limit)
        reset_sec = int(_global_rate_limiter.get_reset_seconds(username))
        response.headers["X-RateLimit-Limit"] = str(rate_limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_sec)

        return response


# ---------------------------------------------------------------------------
# Legacy class aliases (for backward compatibility with existing imports)
# ---------------------------------------------------------------------------

class UserContextMiddleware:
    """Legacy class — use install_user_context_middleware(app) instead."""
    pass

class UserIsolationMiddleware:
    """Legacy class — use install_user_isolation_middleware(app) instead."""
    pass

class QuotaCheckMiddleware:
    """Legacy class — use install_quota_check_middleware(app) instead."""
    pass

class RateLimitMiddleware:
    """Legacy class — use install_rate_limit_middleware(app) instead."""
    pass
