"""
用户场景API路由
"""

from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any
from pydantic import BaseModel

from ..auth import get_current_user
from ...services.user_scene_service import UserSceneService
from ...constant import WORKING_DIR

router = APIRouter(prefix="/api/user-scenes", tags=["User Scenes"])


class SetUserScenesRequest(BaseModel):
    """设置用户场景请求"""
    enabled_scenes: List[str] = []
    custom_scenes: List[Dict[str, Any]] = []
    preferences: Dict[str, Any] = {}


@router.get("/my-scenes")
async def get_my_scenes(
    user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取当前用户的场景配置"""
    user_id = user.get('id', user.get('username', 'default'))
    service = UserSceneService(str(WORKING_DIR))
    return service.get_user_scenes(user_id)


@router.post("/my-scenes")
async def set_my_scenes(
    request: SetUserScenesRequest,
    user: dict = Depends(get_current_user)
) -> dict:
    """设置当前用户的场景配置"""
    user_id = user.get('id', user.get('username', 'default'))
    service = UserSceneService(str(WORKING_DIR))
    
    success = service.set_user_scenes(user_id, request.model_dump())
    
    if success:
        return {"success": True, "message": "场景配置保存成功"}
    else:
        raise HTTPException(status_code=500, detail="场景配置保存失败")


@router.get("/recommended")
async def get_recommended_scenes(
    limit: int = 10,
    user: dict = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """获取推荐场景"""
    user_id = user.get('id', user.get('username', 'default'))
    service = UserSceneService(str(WORKING_DIR))
    return service.get_recommended_scenes(user_id, limit)
