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

"""Workspace Models router - user-level model/provider management.

每个用户可以配置自己的 Provider 和模型偏好。
"""
from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel

from ....constant import WORKSPACES_DIR
from ....providers.provider_manager import ProviderManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workspace/models"])


# ── Pydantic models ─────────────────────────────────────────────────────

class ProviderConfig(BaseModel):
    id: str
    name: str = ""
    api_base: str = ""
    api_key: str = ""
    models: List[str] = []
    enabled: bool = True


class UserModelConfig(BaseModel):
    providers: List[ProviderConfig] = []
    default_model: Optional[str] = None
    model_priority: List[str] = []  # 模型优先级排序


class UpdateModelConfigRequest(BaseModel):
    providers: Optional[List[ProviderConfig]] = None
    default_model: Optional[str] = None
    model_priority: Optional[List[str]] = None


class TestConnectionRequest(BaseModel):
    provider_id: str
    api_base: str
    api_key: str = ""
    model: str = ""


class TestConnectionResponse(BaseModel):
    success: bool
    message: str = ""
    available_models: List[str] = []


# ── Helper functions ─────────────────────────────────────────────────────

def _get_username(request: Request) -> str:
    """获取当前用户名."""
    username = getattr(request.state, "username", "anonymous")
    if username == "anonymous":
        raise HTTPException(status_code=401, detail="需要登录")
    return username


def _get_user_config_path(username: str) -> Path:
    """获取用户模型配置文件路径."""
    config_dir = WORKSPACES_DIR / username
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "models.json"


def _load_user_model_config(username: str) -> UserModelConfig:
    """加载用户模型配置."""
    config_path = _get_user_config_path(username)
    if config_path.exists():
        with open(config_path, "r") as f:
            data = json.load(f)
            return UserModelConfig(**data)
    return UserModelConfig()


def _save_user_model_config(username: str, config: UserModelConfig) -> None:
    """保存用户模型配置."""
    config_path = _get_user_config_path(username)
    with open(config_path, "w") as f:
        json.dump(config.model_dump(), f, indent=2, ensure_ascii=False)


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/workspace/models")
async def get_my_models(request: Request) -> Dict[str, Any]:
    """获取当前用户的模型配置."""
    username = _get_username(request)
    config = _load_user_model_config(username)
    
    # 获取全局可用模型（只读参考）
    global_models = []
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager:
        from ....config import load_config
        sys_config = load_config()
        providers = sys_config.get("providers", {})
        for pid, pconfig in providers.items():
            if isinstance(pconfig, dict):
                global_models.append({
                    "id": pid,
                    "name": pconfig.get("name", pid),
                    "models": pconfig.get("models", []),
                })
    
    return {
        "username": username,
        "providers": [p.model_dump() for p in config.providers],
        "default_model": config.default_model,
        "model_priority": config.model_priority,
        "global_models": global_models,  # 只读参考
    }


@router.put("/workspace/models")
async def update_my_models(
    request: Request,
    payload: UpdateModelConfigRequest = Body(...),
) -> Dict[str, Any]:
    """更新用户模型配置."""
    username = _get_username(request)
    config = _load_user_model_config(username)
    
    if payload.providers is not None:
        config.providers = payload.providers
    if payload.default_model is not None:
        config.default_model = payload.default_model
    if payload.model_priority is not None:
        config.model_priority = payload.model_priority
    
    _save_user_model_config(username, config)
    
    # Record audit log
    from ....user_system.database import UserSystemDB
    db = UserSystemDB()
    user = db.get_user_by_username(username)
    if user:
        db.insert_audit_log(
            user_id=user["id"],
            username=username,
            action="update_model_config",
            resource_type="model",
            resource_id="user_config",
        )
    
    return {
        "success": True,
        "providers": [p.model_dump() for p in config.providers],
        "default_model": config.default_model,
    }


@router.post("/workspace/models/test")
async def test_model_connection(
    request: Request,
    payload: TestConnectionRequest = Body(...),
) -> TestConnectionResponse:
    """测试模型连接."""
    username = _get_username(request)
    
    try:
        from openai import AsyncOpenAI
        
        import os
        api_base = payload.api_base or os.environ.get("COAPIS_LLM_BASE_URL", "http://localhost:8082/v1")
        api_key = payload.api_key or "none"
        
        client = AsyncOpenAI(
            base_url=api_base,
            api_key=api_key,
        )
        
        # 尝试获取模型列表
        models = await client.models.list()
        model_ids = [m.id for m in models[:20]]  # 限制返回数量
        
        await client.close()
        
        return TestConnectionResponse(
            success=True,
            message="连接成功",
            available_models=model_ids,
        )
        
    except Exception as e:
        return TestConnectionResponse(
            success=False,
            message=f"连接失败: {str(e)}",
        )


@router.put("/workspace/models/default")
async def set_default_model(
    request: Request,
    payload: Dict[str, str] = Body(...),
) -> Dict[str, Any]:
    """设置默认模型."""
    username = _get_username(request)
    model = payload.get("model", "")
    
    if not model:
        raise HTTPException(status_code=400, detail="模型不能为空")
    
    config = _load_user_model_config(username)
    config.default_model = model
    _save_user_model_config(username, config)
    
    return {
        "success": True,
        "default_model": model,
    }


@router.get("/workspace/models/available")
async def get_available_models(request: Request) -> Dict[str, Any]:
    """获取所有可用模型（全局 + 用户自定义）."""
    username = _get_username(request)
    
    all_models = {}
    
    # 全局模型
    from ....config import load_config
    sys_config = load_config()
    providers = sys_config.get("providers", {})
    for pid, pconfig in providers.items():
        if isinstance(pconfig, dict):
            all_models[pid] = pconfig.get("models", [])
    
    # 用户自定义模型
    user_config = _load_user_model_config(username)
    for provider in user_config.providers:
        if provider.models:
            all_models[provider.id] = provider.models
    
    return {
        "models": all_models,
        "default_model": user_config.default_model,
    }
