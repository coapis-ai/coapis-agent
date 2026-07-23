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

"""User scene preferences router - scene-related user preferences.

场景相关的用户偏好设置，包括职能标签、最近使用、收藏场景等。
存储于 user_preferences 表的 key-value 结构中。
"""
from __future__ import annotations

import json
import logging
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel, Field

from ....user_system.database import UserSystemDB
from ...auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scene-preferences", tags=["user/scene-preferences"])


# ── Pydantic models ─────────────────────────────────────────────────────

class FunctionTagsUpdate(BaseModel):
    """更新职能标签."""
    function_tags: List[str] = Field(default_factory=list, description="职能标签列表")


class SceneUsageRecord(BaseModel):
    """场景使用记录."""
    scene_id: str
    timestamp: float = Field(default_factory=lambda: time.time())


class ScenePreferencesResponse(BaseModel):
    """场景偏好响应."""
    function_tags: List[str] = Field(default_factory=list)
    recent_scenes: List[str] = Field(default_factory=list, max_items=10)
    favorite_scenes: List[str] = Field(default_factory=list)
    dashboard_config: Optional[dict] = None


# ── Helper functions ────────────────────────────────────────────────────

def _get_user_id(request: Request) -> int:
    """从请求中获取用户ID."""
    user = get_current_user(request)
    if not user or not hasattr(user, 'id'):
        raise HTTPException(status_code=401, detail="未登录")
    return user.id


def _get_preference(db: UserSystemDB, user_id: int, key: str, default: any = None) -> any:
    """获取用户偏好值."""
    try:
        value = db.get_user_preference(user_id, key)
        if value is None:
            return default
        return json.loads(value)
    except Exception as e:
        logger.error(f"获取用户偏好失败: {key}, {e}")
        return default


def _set_preference(db: UserSystemDB, user_id: int, key: str, value: any) -> bool:
    """设置用户偏好值."""
    try:
        value_str = json.dumps(value, ensure_ascii=False)
        return db.set_user_preference(user_id, key, value_str)
    except Exception as e:
        logger.error(f"设置用户偏好失败: {key}, {e}")
        return False


# ── API endpoints ───────────────────────────────────────────────────────

@router.get("", response_model=ScenePreferencesResponse)
async def get_scene_preferences(request: Request):
    """
    获取场景偏好设置
    
    返回用户的职能标签、最近使用场景、收藏场景等配置。
    """
    user_id = _get_user_id(request)
    db = UserSystemDB()
    
    return ScenePreferencesResponse(
        function_tags=_get_preference(db, user_id, "function_tags", []),
        recent_scenes=_get_preference(db, user_id, "recent_scenes", []),
        favorite_scenes=_get_preference(db, user_id, "favorite_scenes", []),
        dashboard_config=_get_preference(db, user_id, "dashboard_config"),
    )


@router.get("/function-tags")
async def get_function_tags(request: Request):
    """
    获取职能标签
    
    返回用户选择的职能标签列表，用于场景推荐。
    """
    user_id = _get_user_id(request)
    db = UserSystemDB()
    
    return {
        "function_tags": _get_preference(db, user_id, "function_tags", [])
    }


@router.post("/function-tags")
async def update_function_tags(
    request: Request,
    data: FunctionTagsUpdate = Body(...)
):
    """
    更新职能标签
    
    保存用户选择的职能标签，用于个性化场景推荐。
    """
    user_id = _get_user_id(request)
    db = UserSystemDB()
    
    # 限制标签数量（最多20个）
    if len(data.function_tags) > 20:
        raise HTTPException(
            status_code=400,
            detail="职能标签数量不能超过20个"
        )
    
    success = _set_preference(db, user_id, "function_tags", data.function_tags)
    
    if not success:
        raise HTTPException(
            status_code=500,
            detail="保存职能标签失败"
        )
    
    return {
        "success": True,
        "message": "职能标签已更新",
        "function_tags": data.function_tags
    }


@router.get("/recent-scenes")
async def get_recent_scenes(request: Request):
    """
    获取最近使用的场景
    
    返回最近使用的场景ID列表（最多10个）。
    """
    user_id = _get_user_id(request)
    db = UserSystemDB()
    
    return {
        "recent_scenes": _get_preference(db, user_id, "recent_scenes", [])
    }


@router.post("/recent-scenes")
async def record_scene_usage(
    request: Request,
    data: SceneUsageRecord = Body(...)
):
    """
    记录场景使用
    
    添加场景到最近使用列表，自动去重并保持最多10个。
    """
    user_id = _get_user_id(request)
    db = UserSystemDB()
    
    # 获取现有列表
    recent_scenes = _get_preference(db, user_id, "recent_scenes", [])
    
    # 去重：移除已存在的相同场景
    recent_scenes = [s for s in recent_scenes if s != data.scene_id]
    
    # 添加到开头
    recent_scenes.insert(0, data.scene_id)
    
    # 限制最多10个
    recent_scenes = recent_scenes[:10]
    
    # 保存
    success = _set_preference(db, user_id, "recent_scenes", recent_scenes)
    
    if not success:
        logger.error(f"记录场景使用失败: {data.scene_id}")
    
    return {
        "success": success,
        "recent_scenes": recent_scenes
    }


@router.get("/favorite-scenes")
async def get_favorite_scenes(request: Request):
    """
    获取收藏的场景
    
    返回用户收藏的场景ID列表。
    """
    user_id = _get_user_id(request)
    db = UserSystemDB()
    
    return {
        "favorite_scenes": _get_preference(db, user_id, "favorite_scenes", [])
    }


@router.post("/favorite-scenes/{scene_id}")
async def add_favorite_scene(
    scene_id: str,
    request: Request
):
    """
    收藏场景
    
    添加场景到收藏列表。
    """
    user_id = _get_user_id(request)
    db = UserSystemDB()
    
    # 获取现有列表
    favorite_scenes = _get_preference(db, user_id, "favorite_scenes", [])
    
    # 检查是否已收藏
    if scene_id in favorite_scenes:
        return {
            "success": True,
            "message": "场景已在收藏列表中",
            "favorite_scenes": favorite_scenes
        }
    
    # 添加收藏
    favorite_scenes.append(scene_id)
    
    # 保存
    success = _set_preference(db, user_id, "favorite_scenes", favorite_scenes)
    
    if not success:
        raise HTTPException(
            status_code=500,
            detail="收藏场景失败"
        )
    
    return {
        "success": True,
        "message": "场景已收藏",
        "favorite_scenes": favorite_scenes
    }


@router.delete("/favorite-scenes/{scene_id}")
async def remove_favorite_scene(
    scene_id: str,
    request: Request
):
    """
    取消收藏场景
    
    从收藏列表中移除场景。
    """
    user_id = _get_user_id(request)
    db = UserSystemDB()
    
    # 获取现有列表
    favorite_scenes = _get_preference(db, user_id, "favorite_scenes", [])
    
    # 移除收藏
    favorite_scenes = [s for s in favorite_scenes if s != scene_id]
    
    # 保存
    success = _set_preference(db, user_id, "favorite_scenes", favorite_scenes)
    
    if not success:
        raise HTTPException(
            status_code=500,
            detail="取消收藏失败"
        )
    
    return {
        "success": True,
        "message": "已取消收藏",
        "favorite_scenes": favorite_scenes
    }


@router.get("/dashboard-config")
async def get_dashboard_config(request: Request):
    """
    获取首页布局配置
    
    返回用户的首页卡片布局配置。
    """
    user_id = _get_user_id(request)
    db = UserSystemDB()
    
    return {
        "dashboard_config": _get_preference(db, user_id, "dashboard_config")
    }


@router.post("/dashboard-config")
async def update_dashboard_config(
    request: Request,
    config: dict = Body(...)
):
    """
    更新首页布局配置
    
    保存用户的首页卡片布局配置（包括显示哪些卡片、顺序等）。
    """
    user_id = _get_user_id(request)
    db = UserSystemDB()
    
    success = _set_preference(db, user_id, "dashboard_config", config)
    
    if not success:
        raise HTTPException(
            status_code=500,
            detail="保存首页配置失败"
        )
    
    return {
        "success": True,
        "message": "首页配置已更新",
        "dashboard_config": config
    }
