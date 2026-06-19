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

"""User Model Preferences - 用户模型偏好设置。

普通用户只需选择默认模型和排序，无需配置 API Key 等技术参数。
高级用户可以添加自定义 Provider。
"""
from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel

from ...constant import WORKSPACES_DIR

logger = logging.getLogger(__name__)

router = APIRouter(tags=["user/model-prefs"])


# ── Pydantic models ─────────────────────────────────────────────────────

class UserModelPrefs(BaseModel):
    """用户模型偏好配置."""
    default_model: Optional[str] = None  # 默认模型
    model_priority: List[str] = []  # 模型优先级排序
    custom_providers: List[Dict[str, Any]] = []  # 自定义 Provider（高级用户）
    language: str = "zh"  # 用户语言偏好 (zh=中文, en=英文)


class UpdateModelPrefsRequest(BaseModel):
    """更新模型偏好（部分更新）."""
    default_model: Optional[str] = None
    model_priority: Optional[List[str]] = None
    custom_providers: Optional[List[Dict[str, Any]]] = None
    language: Optional[str] = None  # 用户语言偏好


class CustomProviderConfig(BaseModel):
    """用户自定义 Provider 配置."""
    id: str
    name: str = ""
    api_base: str = ""
    api_key: str = ""
    models: List[str] = []
    enabled: bool = True


# ── Helper functions ─────────────────────────────────────────────────────

def _get_username(request: Request) -> str:
    """获取当前用户名."""
    username = getattr(request.state, "username", "anonymous")
    if username == "anonymous":
        raise HTTPException(status_code=401, detail="需要登录")
    return username


def _get_prefs_path(username: str) -> Path:
    """获取用户模型偏好配置文件路径."""
    prefs_dir = WORKSPACES_DIR / username
    prefs_dir.mkdir(parents=True, exist_ok=True)
    return prefs_dir / "model_prefs.json"


def _load_user_prefs(username: str) -> UserModelPrefs:
    """加载用户模型偏好."""
    prefs_path = _get_prefs_path(username)
    if prefs_path.exists():
        try:
            with open(prefs_path, "r") as f:
                data = json.load(f)
                return UserModelPrefs(**data)
        except Exception as e:
            logger.warning(f"Failed to load prefs for {username}: {e}")
    return UserModelPrefs()


def _save_user_prefs(username: str, prefs: UserModelPrefs) -> None:
    """保存用户模型偏好."""
    prefs_path = _get_prefs_path(username)
    with open(prefs_path, "w") as f:
        json.dump(prefs.model_dump(), f, indent=2, ensure_ascii=False)


def get_user_language(username: str) -> str:
    """获取用户语言偏好（供 runner 等模块调用）."""
    prefs = _load_user_prefs(username)
    return prefs.language or "zh"


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/user/model-prefs")
async def get_model_prefs(request: Request) -> Dict[str, Any]:
    """获取当前用户的模型偏好."""
    username = _get_username(request)
    prefs = _load_user_prefs(username)
    
    # 获取全局可用模型（只读参考）
    global_models = []
    try:
        from .admin_providers import _get_available_models_for_users
        global_models = _get_available_models_for_users()
    except (ImportError, Exception):
        # 同目录导入失败时，直接读取 providers.json
        from ...constant import WORKING_DIR
        providers_path = WORKING_DIR / "config" / "providers.json"
        if providers_path.exists():
            with open(providers_path, "r") as f:
                providers = json.load(f)
            for pid, pconfig in providers.items():
                if isinstance(pconfig, dict) and pconfig.get("enabled", True):
                    visible = pconfig.get("visible_to_users", True)
                    models = pconfig.get("models", [])
                    if visible:
                        global_models.extend(models)
                    else:
                        global_models.extend(pconfig.get("visible_models", []))
        global_models = list(dict.fromkeys(global_models))
    
    return {
        "username": username,
        "default_model": prefs.default_model,
        "model_priority": prefs.model_priority,
        "custom_providers": prefs.custom_providers,
        "language": prefs.language,
        "global_available_models": global_models,  # 只读参考
    }


@router.put("/user/model-prefs")
async def update_model_prefs(
    request: Request,
    payload: UpdateModelPrefsRequest = Body(...),
) -> Dict[str, Any]:
    """更新用户模型偏好（部分更新）."""
    username = _get_username(request)
    prefs = _load_user_prefs(username)
    
    # 部分更新
    if payload.default_model is not None:
        prefs.default_model = payload.default_model
    if payload.model_priority is not None:
        prefs.model_priority = payload.model_priority
    if payload.custom_providers is not None:
        prefs.custom_providers = payload.custom_providers
    if payload.language is not None:
        prefs.language = payload.language
    
    _save_user_prefs(username, prefs)
    
    # 审计日志
    try:
        from ....user_system.database import UserSystemDB
        db = UserSystemDB()
        user = db.get_user_by_username(username)
        if user:
            db.insert_audit_log(
                user_id=user["id"],
                username=username,
                action="update_model_prefs",
                resource_type="model",
                resource_id="user_prefs",
            )
    except Exception as e:
        logger.warning(f"Failed to record audit log: {e}")
    
    return {
        "success": True,
        "default_model": prefs.default_model,
        "model_priority": prefs.model_priority,
        "language": prefs.language,
    }


@router.get("/user/custom-providers")
async def get_custom_providers(request: Request) -> Dict[str, Any]:
    """获取用户自定义 Provider 列表."""
    username = _get_username(request)
    prefs = _load_user_prefs(username)
    
    return {
        "custom_providers": prefs.custom_providers,
        "total": len(prefs.custom_providers),
    }


@router.post("/user/custom-providers")
async def create_custom_provider(
    request: Request,
    payload: CustomProviderConfig = Body(...),
) -> Dict[str, Any]:
    """添加自定义 Provider（高级用户功能）."""
    username = _get_username(request)
    prefs = _load_user_prefs(username)
    
    # 检查是否已存在
    for cp in prefs.custom_providers:
        if cp.get("id") == payload.id:
            raise HTTPException(status_code=409, detail=f"Provider '{payload.id}' 已存在")
    
    prefs.custom_providers.append(payload.model_dump())
    _save_user_prefs(username, prefs)
    
    return {
        "success": True,
        "provider": payload.model_dump(),
    }


@router.put("/user/custom-providers/{provider_id}")
async def update_custom_provider(
    request: Request,
    provider_id: str,
    payload: CustomProviderConfig = Body(...),
) -> Dict[str, Any]:
    """更新自定义 Provider."""
    username = _get_username(request)
    prefs = _load_user_prefs(username)
    
    # 查找并更新
    found = False
    for i, cp in enumerate(prefs.custom_providers):
        if cp.get("id") == provider_id:
            prefs.custom_providers[i] = payload.model_dump()
            found = True
            break
    
    if not found:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' 不存在")
    
    _save_user_prefs(username, prefs)
    
    return {
        "success": True,
        "provider": payload.model_dump(),
    }


@router.delete("/user/custom-providers/{provider_id}")
async def delete_custom_provider(
    request: Request,
    provider_id: str,
) -> Dict[str, Any]:
    """删除自定义 Provider."""
    username = _get_username(request)
    prefs = _load_user_prefs(username)
    
    original_len = len(prefs.custom_providers)
    prefs.custom_providers = [cp for cp in prefs.custom_providers if cp.get("id") != provider_id]
    
    if len(prefs.custom_providers) == original_len:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' 不存在")
    
    _save_user_prefs(username, prefs)
    
    return {
        "success": True,
        "provider_id": provider_id,
    }


@router.post("/user/custom-providers/test")
async def test_custom_provider(
    request: Request,
    payload: CustomProviderConfig = Body(...),
) -> Dict[str, Any]:
    """测试自定义 Provider 连接."""
    try:
        from openai import AsyncOpenAI
        
        api_base = payload.api_base
        api_key = payload.api_key or "none"
        
        client = AsyncOpenAI(
            base_url=api_base,
            api_key=api_key,
        )
        
        # 测试连接
        models = await client.models.list()
        model_ids = [m.id for m in models[:50]]
        
        await client.close()
        
        return {
            "success": True,
            "message": "连接成功",
            "available_models": model_ids,
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"连接失败: {str(e)}",
        }


# ── 模型解析逻辑 ─────────────────────────────────────────────────────────

def resolve_model_for_user(username: str, agent_model: Optional[str] = None) -> Optional[str]:
    """解析用户实际使用的模型。
    
    优先级：
    1. 用户自定义 Provider 中的模型
    2. 用户从可用模型池中选择的默认模型
    3. Agent 配置的 active_model
    4. 全局默认模型（兜底）
    """
    prefs = _load_user_prefs(username)
    
    # 1. 检查自定义 Provider 中的模型
    if prefs.custom_providers:
        for provider in prefs.custom_providers:
            if provider.get("enabled", True):
                models = provider.get("models", [])
                if models:
                    return models[0]  # 返回第一个可用自定义模型
    
    # 2. 用户默认模型
    if prefs.default_model:
        return prefs.default_model
    
    # 3. Agent 配置的模型
    if agent_model:
        return agent_model
    
    # 4. 全局默认（返回 None，由 Agent 处理）
    return None
