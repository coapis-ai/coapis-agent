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

"""Admin system router - system overview and metrics."""
from __future__ import annotations

import logging
import os
import time
from typing import Dict, Any

from fastapi import APIRouter, Request

from ...permissions import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin/system"])


@router.get("/admin/system/overview")
@require_permission("admin:admin")
async def get_system_overview(request: Request) -> Dict[str, Any]:
    """获取系统概览."""

    # 获取系统指标
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        system_metrics = {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_used_mb": memory.used // (1024 * 1024),
            "memory_total_mb": memory.total // (1024 * 1024),
            "disk_percent": disk.percent,
            "disk_used_mb": disk.used // (1024 * 1024),
            "disk_total_mb": disk.total // (1024 * 1024),
        }
    except ImportError:
        system_metrics = {
            "cpu_percent": 0,
            "memory_percent": 0,
            "disk_percent": 0,
        }

    # 获取用户统计
    from ....user_system.database import UserSystemDB
    db = UserSystemDB()

    total_users = db.execute("SELECT COUNT(*) as total FROM users").fetchone()["total"]
    active_users = db.execute(
        "SELECT COUNT(*) as total FROM users WHERE is_active = 1"
    ).fetchone()["total"]

    # 获取 Agent 统计
    manager = getattr(request.app.state, "multi_agent_manager", None)
    total_agents = 0
    running_agents = 0
    if manager:
        for ws in manager._workspaces.values():
            total_agents += 1
            if ws.status == "running":
                running_agents += 1

    return {
        "system": system_metrics,
        "users": {
            "total": total_users,
            "active": active_users,
        },
        "agents": {
            "total": total_agents,
            "running": running_agents,
        },
        "uptime": time.time() - getattr(request.app.state, "start_time", time.time()),
    }


@router.get("/admin/system/metrics")
@require_permission("admin:admin")
async def get_system_metrics(request: Request) -> Dict[str, Any]:
    """获取实时指标."""

    try:
        import psutil
        return {
            "cpu": psutil.cpu_percent(interval=0.1),
            "memory": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage("/").percent,
            "timestamp": time.time(),
        }
    except ImportError:
        return {"timestamp": time.time()}


@router.get("/admin/system/logs")
@require_permission("admin:admin")
async def get_system_logs(request: Request, lines: int = 100) -> Dict[str, Any]:
    """获取系统日志（最近 N 行）."""

    from ....constant import LOG_FILE_PATH

    if not LOG_FILE_PATH or not os.path.exists(LOG_FILE_PATH):
        return {"logs": [], "total": 0}

    try:
        with open(LOG_FILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        log_lines = all_lines[-lines:]
        return {
            "logs": [line.rstrip() for line in log_lines],
            "total": len(all_lines),
        }
    except Exception as e:
        return {"logs": [f"Error reading logs: {str(e)}"], "total": 0}
