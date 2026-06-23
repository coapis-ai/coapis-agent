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
