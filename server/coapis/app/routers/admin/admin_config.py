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

"""Admin config router - global system configuration management."""
from __future__ import annotations

import logging
import os
from typing import Dict, Any

from coapis.constant import SYSTEM_DIR
from fastapi import APIRouter, Body, Request

from ...permissions import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin/config"])


@router.get("/admin/config")
@require_permission("admin:admin")
async def get_global_config(request: Request) -> Dict[str, Any]:
    """获取全局系统配置."""

    # 从环境变量和 config.json 读取配置
    from ....config import load_config
    cfg = load_config()

    return {
        "user_system_enabled": True,
        "auth_enabled": True,
        "cors_origins": os.environ.get("COAPIS_CORS_ORIGINS", "*"),
        "token_expiry": int(os.environ.get("COAPIS_TOKEN_EXPIRY_SECONDS", "86400")),
        "max_agents_per_user": int(os.environ.get("COAPIS_MAX_AGENTS_PER_USER", "10")),
        "max_skills_per_user": int(os.environ.get("COAPIS_MAX_SKILLS_PER_USER", "50")),
        "rag_enabled": getattr(cfg, "rag_enabled", False),
        "heartbeat_enabled": getattr(cfg, "heartbeat_enabled", True),
        "heartbeat_interval": int(os.environ.get("COAPIS_HEARTBEAT_INTERVAL", "30")),
        "dream_cron": os.environ.get("COAPIS_DREAM_CRON", ""),
    }


@router.put("/admin/config")
@require_permission("admin:admin")
async def update_global_config(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """更新全局系统配置."""

    # 注意：当前配置通过环境变量/配置文件管理
    # 此端点返回提示，告知管理员如何修改配置
    return {
        "success": False,
        "message": "全局配置通过环境变量和配置文件管理，请修改 docker-compose.yaml 或 config.json 后重启服务",
        "config_location": str(SYSTEM_DIR / "config.json"),
    }
