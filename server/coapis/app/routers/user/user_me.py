# -*- coding: utf-8 -*-
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

"""User me router - get current user info."""
from __future__ import annotations

import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ....user_system.service import get_user_by_username
from ....user_system.models import UserResponse
from ..permissions import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["user/me"])


class UserInfoResponse(BaseModel):
    """当前用户信息（含角色、配额）."""
    id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str = "user"
    token_remaining: int = 0
    is_active: bool = True


@router.get("/user/me")
@require_permission("chat:read")
async def get_current_user(request: Request) -> UserInfoResponse:
    """获取当前用户信息（含角色、等级、积分）。

    双存储查询：先查 SQLite user_system，回退到 JSON user_store。
    与 authenticate 逻辑保持一致，确保注册后即使 SQLite 同步失败也能正常获取信息。
    
    权限：user 及以上角色均可访问。
    """
    username = getattr(request.state, "username", "anonymous")

    if username == "anonymous":
        raise HTTPException(status_code=401, detail="需要登录")

    # 1. 优先查询 SQLite user_system
    user = get_user_by_username(username)

    # 2. 回退到 JSON user_store
    if not user:
        try:
            from ...user_store import get_user as json_get_user
            json_user = json_get_user(username)
            if json_user:
                # 自动同步到 SQLite（避免下次查询再走回退路径）
                try:
                    from ..user_system.service import create_user as create_user_sql
                    from ..user_system.models import UserCreate
                    from ..user_system.config import get_config
                    cfg = get_config()
                    level = 0
                    token_quota = cfg.get_token_quota(level)
                    user_create = UserCreate(
                        username=username,
                        password="synced_from_json",  # 无法还原密码，标记为已同步
                        email=json_user.get("email"),
                        display_name=json_user.get("display_name", username),
                        role=json_user.get("role", "user"),
                    )
                    create_user_sql(user_create)
                    # 重新获取同步后的用户
                    user = get_user_by_username(username)
                    logger.info(f"Auto-synced JSON user {username} to SQLite")
                except Exception as sync_err:
                    logger.warning(f"Failed to sync {username} to SQLite: {sync_err}")
                    # 如果同步失败，使用 JSON 数据构造响应
                    user = None

                # 如果同步失败或用户仍不存在，使用 JSON 数据
                if not user and json_user:
                    # 从 JSON 数据构造 UserInfoResponse
                    return UserInfoResponse(
                        id=0,
                        username=username,
                        display_name=json_user.get("display_name", username),
                        avatar_url=json_user.get("avatar_url"),
                        role=json_user.get("role", "user"),
                        level=0,
                        points=0,
                        token_remaining=100000,  # 默认配额
                        is_active=True,
                    )
        except Exception as e:
            logger.warning(f"Failed to query JSON user_store for {username}: {e}")

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 懒加载：如果用户 workspace 不存在，自动初始化
    try:
        from ...user_provisioning import ensure_user_workspace_exists
        ensure_user_workspace_exists(username)
    except Exception as e:
        logger.warning(
            f"Failed to auto-initialize workspace for {username}: {e}. "
            "User can still function but may lack dedicated agent.",
            exc_info=True,
        )

    # 计算 Token 剩余
    token_remaining = max(0, user.token_quota_monthly - user.token_used_monthly)

    return UserInfoResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=user.role,
        token_remaining=token_remaining,
        is_active=user.is_active,
    )
