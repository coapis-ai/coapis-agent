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

"""User system middleware - quota checking and rate limiting.

IMPORTANT: Uses @app.middleware("http") pattern to avoid BaseHTTPMiddleware
thread-pool deadlock with SSE async generators.

Simplified: no user levels, no points auto-earning.
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
        """Check if request is allowed under rate limit."""
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

        # Apply burst tolerance
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

# Paths that should be skipped by prefix match
SKIP_PATH_PREFIXES = [
    "/api/chats/",
]


def _should_skip(request: Request) -> bool:
    """Check if this request should skip user-system middleware."""
    path = request.url.path

    # Exact match
    if path in SKIP_PATHS:
        return True

    # Prefix match
    for prefix in SKIP_PATH_PREFIXES:
        if path.startswith(prefix):
            return True

    return False


# ---------------------------------------------------------------------------
# Middleware factory
# ---------------------------------------------------------------------------

def install_user_system_middleware(app) -> None:
    """Install user system middleware (quota + rate limit)."""

    @app.middleware("http")
    async def user_system_middleware(request: Request, call_next):
        """Combined user system middleware: quota + rate limiting."""
        # Skip non-API paths and internal endpoints
        if _should_skip(request):
            return await call_next(request)

        # Only apply to /api/ paths
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        # Extract username from request (if authenticated)
        username = getattr(request.state, "username", None)

        # ── Rate limiting ──
        if username:
            rate_limit = 120  # Default: 120 req/min
            if not _global_rate_limiter.is_allowed(username, rate_limit):
                reset_seconds = _global_rate_limiter.get_reset_seconds(username)
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded",
                        "retry_after": round(reset_seconds, 1),
                    },
                    headers={"Retry-After": str(int(reset_seconds))},
                )

        # ── Token quota check ──
        if username and get_config().token_quota_hard_limit:
            quota_ok = check_quota(username)
            if not quota_ok:
                return JSONResponse(
                    status_code=402,
                    content={"detail": "Token quota exceeded"},
                )

        # ── Points auto-earning REMOVED ──
        # Simplified: no automatic point accumulation on chat/login/etc.

        response = await call_next(request)
        return response

    logger.info("User system middleware installed (quota + rate limit)")


# ---------------------------------------------------------------------------
# Backward-compatible aliases (old code imports these individually)
# ---------------------------------------------------------------------------

def install_user_context_middleware(app) -> None:
    """Alias: installs user context extraction (part of unified middleware)."""
    install_user_system_middleware(app)


def install_user_isolation_middleware(app) -> None:
    """Alias: no-op (user isolation handled by unified middleware)."""
    pass


def install_quota_check_middleware(app) -> None:
    """Alias: no-op (quota check handled by unified middleware)."""
    pass


def install_rate_limit_middleware(app) -> None:
    """Alias: no-op (rate limit handled by unified middleware)."""
    pass
