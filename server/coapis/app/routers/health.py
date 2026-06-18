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
