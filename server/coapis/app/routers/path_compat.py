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

"""Frontend path compatibility layer - maps legacy frontend paths to actual backend routes.

This solves P0-1: Frontend API paths don't match backend routes.
Instead of modifying frontend code, we add a compatibility layer that redirects
legacy paths to correct endpoints.

Path Mappings:
- /api/agent/skills       → /api/skills
- /api/channels           → /api/config/channels
- /api/cron-jobs          → /api/cron/jobs
- /api/admin/settings     → /api/admin/system/overview
- /api/growth/evolution   → /api/evolution/status
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Path mapping: legacy_path → actual_path
PATH_MAPPINGS = {
    "/api/agent/skills": "/api/skills",
    "/api/channels": "/api/config/channels",
    "/api/cron-jobs": "/api/cron/jobs",
    "/api/admin/settings": "/api/admin/system/overview",
    "/api/growth/evolution": "/api/evolution/status",
}

# Prefix mappings for dynamic paths
# NOTE: Do NOT use "/api/agent/" as a prefix mapping — it conflicts with
# the real AgentScope Runtime endpoint at /api/agent/process.
PREFIX_MAPPINGS = {
    # "/api/agent/skills" is handled by PATH_MAPPINGS above (exact match)
    "/api/cron-": "/api/cron/",
    "/api/growth/": "/api/evolution/",
}

router = APIRouter()


def _remap_path(path: str) -> str:
    """Remap a legacy path to actual backend path.

    Returns:
        Remapped path, or original if no mapping found.
    """
    # Check exact match first
    if path in PATH_MAPPINGS:
        return PATH_MAPPINGS[path]

    # Check prefix match
    for prefix, target_prefix in PREFIX_MAPPINGS.items():
        if path.startswith(prefix):
            suffix = path[len(prefix):]
            return target_prefix + suffix

    return path


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def path_compatibility_handler(request: Request, path: str):
    """Handle legacy frontend API paths by remapping to actual routes.

    This is a catch-all route that should be mounted last to avoid
    interfering with actual route handlers.
    """
    original_path = f"/{path}"

    # Check if this is a legacy path that needs remapping
    remapped_path = _remap_path(original_path)

    if remapped_path != original_path:
        # Log the remapping for debugging
        logger.debug(
            "Path remapped: %s → %s (method: %s)",
            original_path,
            remapped_path,
            request.method,
        )

        # Forward the request to the remapped path
        # Note: This is a simple proxy; for production, consider using
        # a proper reverse proxy or middleware
        from starlette.routing import Match, Route

        # Get the app's router
        app = request.app
        scopes = []

        # Try to find matching route
        for route in app.routes:
            if hasattr(route, "methods") and request.method in (route.methods or []):
                match, child_scope = route.matches(request.scope)
                if match == Match.FULL:
                    # Found matching route, call it
                    response = await route.handle(request)
                    return response

        # If no direct match, return helpful error
        return JSONResponse(
            status_code=404,
            content={
                "error": "Path remapped but no handler found",
                "original_path": original_path,
                "remapped_path": remapped_path,
                "hint": "This path was remapped from legacy frontend. Check if the target endpoint exists.",
            },
        )

    # Not a legacy path, return 404
    return JSONResponse(
        status_code=404,
        content={"error": "Not found", "path": original_path},
    )


# ---- Alternative: Middleware Approach ----

class PathCompatibilityMiddleware:
    """Middleware that remaps legacy paths before routing.

    Usage:
        app.add_middleware(PathCompatibilityMiddleware)
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")

            # Remap path if needed
            remapped_path = _remap_path(path)
            if remapped_path != path:
                logger.debug("Path remapped: %s → %s", path, remapped_path)
                scope["path"] = remapped_path

        await self.app(scope, receive, send)
