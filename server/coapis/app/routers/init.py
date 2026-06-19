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

"""System initialization API endpoints."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["System Initialization"])


@router.get("/init/status")
async def get_init_status() -> Dict[str, Any]:
    """检查系统初始化状态."""
    from coapis.system.initializer import check_system_status

    return check_system_status()


@router.post("/init/run")
async def run_initialization(
    request: Request,
    force: bool = False,
) -> Dict[str, Any]:
    """执行系统初始化.

    Args:
        force: 是否强制重新初始化（覆盖现有配置）

    注意: 此端点需要管理员权限
    """
    from coapis.system.initializer import initialize_system

    # 权限检查
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admin users can run system initialization",
        )

    result = initialize_system(force=force)
    return result


@router.get("/init/defaults")
async def get_defaults() -> Dict[str, Any]:
    """获取系统默认配置（用于预览）."""
    from coapis.system.defaults import (
        DEFAULT_CONFIG,
        DEFAULT_PERMISSIONS,
        DEFAULT_ROLES,
        SYSTEM_VERSION,
    )

    return {
        "version": SYSTEM_VERSION,
        "config": DEFAULT_CONFIG,
        "permissions": DEFAULT_PERMISSIONS,
        "roles": DEFAULT_ROLES,
    }
