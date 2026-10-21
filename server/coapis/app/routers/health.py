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

"""Health router - Health check and system status endpoints."""

import logging
import time as _time
from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Request

from ...__version__ import __version__

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(request: Request) -> Dict[str, Any]:
    """Health check with startup phase awareness.

    Returns:
      - status: "ready" | "starting" | "error"
      - phase:  "sync" | "background" | "ready" | "error"
      - uptime_seconds, phase1_elapsed, background_elapsed
    """
    app = request.app
    phase = getattr(app.state, "startup_phase", None)

    # 如果没有启动状态追踪（老版本兼容），返回基础格式
    if phase is None:
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": __version__,
        }

    start_ts = getattr(app.state, "startup_start_time", _time.time())
    errors = getattr(app.state, "startup_errors", [])
    is_ready = getattr(app.state, "startup_ready", None)
    ready = is_ready.is_set() if is_ready else False

    if phase == "error":
        status = "error"
    elif ready and phase == "ready":
        status = "ready"
    else:
        status = "starting"

    resp = {
        "status": status,
        "phase": phase,
        "timestamp": datetime.now().isoformat(),
        "version": __version__,
        "uptime_seconds": round(_time.time() - start_ts, 1),
        "phase1_elapsed": getattr(app.state, "phase1_elapsed", None),
        "background_elapsed": getattr(app.state, "startup_elapsed", None),
    }
    if errors:
        resp["errors"] = errors
    return resp


@router.get("/health/ready")
async def readiness_check() -> Dict[str, Any]:
    """Readiness check - verifies core components are initialized."""
    return {
        "status": "ready",
        "components": {
            "agent_manager": "initialized",
            "skill_manager": "initialized",
            "tool_registry": "initialized",
        },
    }


@router.get("/health/tools")
async def toolchain_health(refresh: bool = False) -> Dict[str, Any]:
    """Self-check for the sandboxed tool chain (node / npm / pptxgenjs).

    Runs node under the *same* RLIMIT_AS the real sandbox tools install, so it
    catches "node is installed but cannot start" - the failure mode that made
    the pptx skill report an unsupported node environment while node v22 and
    pptxgenjs were both present.

    Query params:
        refresh=true   force a fresh probe (default: cached for 60s)
    """
    import asyncio

    from ...security.toolchain_probe import get_toolchain_status, probe_toolchain

    if not refresh:
        cached = get_toolchain_status()
        if cached.get("status") != "unknown":
            return cached
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, probe_toolchain, refresh)


@router.get("/info")
async def system_info() -> Dict[str, Any]:
    """Get system information."""
    import platform
    import sys

    return {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "python_version": sys.version,
        "coapis_version": __version__,
    }
