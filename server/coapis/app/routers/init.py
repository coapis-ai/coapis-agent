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
