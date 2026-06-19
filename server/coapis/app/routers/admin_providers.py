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

"""Admin Provider Management - 管理员配置全局 Provider 和可用模型池。

管理员在此配置 Provider（API Base、API Key、模型列表），
并决定哪些模型对普通用户可见。
"""
from __future__ import annotations

import logging
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..permissions.decorators import require_permission
from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel

from ...constant import WORKSPACES_DIR, WORKING_DIR

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin/providers"])

# ── Pydantic models ─────────────────────────────────────────────────────

class AdminProviderConfig(BaseModel):
    """全局 Provider 配置（管理员管理）."""
    id: str
    name: str = ""
    api_base: str = ""
    api_key: str = ""
    models: List[str] = []
    enabled: bool = True
    # 哪些模型对用户可见（True=全部可见，False=需手动勾选）
    visible_to_users: bool = True
    # 用户可见的具体模型列表（当 visible_to_users=False 时生效）
    visible_models: List[str] = []


class AdminProviderUpdate(BaseModel):
    """更新 Provider 配置（部分更新）."""
    name: Optional[str] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    models: Optional[List[str]] = None
    enabled: Optional[bool] = None
    visible_to_users: Optional[bool] = None
    visible_models: Optional[List[str]] = None


class AvailableModelsResponse(BaseModel):
    """可用模型池响应."""
    providers: List[Dict[str, Any]] = []
    models: List[str] = []
    total: int = 0


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

def _get_providers_path() -> Path:
    """获取 providers.json 路径."""
    return WORKING_DIR / "config" / "providers.json"


def _load_providers() -> Dict[str, Any]:
    """加载全局 Provider 配置."""
    path = _get_providers_path()
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return {}


def _save_providers(data: Dict[str, Any]) -> None:
    """保存全局 Provider 配置."""
    path = _get_providers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _is_admin(request: Request) -> bool:
    """检查是否为管理员."""
    role = getattr(request.state, "role", "user")
    return role == "admin"


def _get_available_models_for_users() -> List[str]:
    """获取对普通用户可见的模型列表（模型池）."""
    providers = _load_providers()
    available = []
    
    for pid, pconfig in providers.items():
        if not isinstance(pconfig, dict):
            continue
        if not pconfig.get("enabled", True):
            continue
        
        models = pconfig.get("models", [])
        visible = pconfig.get("visible_to_users", True)
        
        if visible:
            available.extend(models)
        else:
            # 仅返回勾选的可见模型
            available.extend(pconfig.get("visible_models", []))
    
    return list(dict.fromkeys(available))  # 去重保序


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/admin/providers")
@require_permission("admin:admin")
async def get_all_providers(request: Request) -> Dict[str, Any]:
    """获取所有 Provider 配置（仅管理员）."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    providers = _load_providers()
    
    # 转换为 AdminProviderConfig 格式
    result = []
    for pid, pconfig in providers.items():
        if isinstance(pconfig, dict):
            result.append({
                "id": pid,
                "name": pconfig.get("name", pid),
                "api_base": pconfig.get("api_base", ""),
                "api_key": pconfig.get("api_key", ""),
                "models": pconfig.get("models", []),
                "enabled": pconfig.get("enabled", True),
                "visible_to_users": pconfig.get("visible_to_users", True),
                "visible_models": pconfig.get("visible_models", []),
            })
        else:
            # 兼容旧格式（字符串 ID）
            result.append({
                "id": pid,
                "name": pid,
                "api_base": "",
                "api_key": "",
                "models": [],
                "enabled": True,
                "visible_to_users": True,
                "visible_models": [],
            })
    
    return {
        "providers": result,
        "available_models": _get_available_models_for_users(),
    }


@router.put("/admin/providers/{provider_id}")
@require_permission("admin:admin")
async def update_provider(
    request: Request,
    provider_id: str,
    payload: AdminProviderUpdate = Body(...),
) -> Dict[str, Any]:
    """更新 Provider 配置（仅管理员，部分更新）."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    providers = _load_providers()
    
    # 确保 Provider 存在
    if provider_id not in providers:
        providers[provider_id] = {}
    
    pconfig = providers[provider_id]
    if not isinstance(pconfig, dict):
        pconfig = providers[provider_id] = {}
    
    # 部分更新
    if payload.name is not None:
        pconfig["name"] = payload.name
    if payload.api_base is not None:
        pconfig["api_base"] = payload.api_base
    if payload.api_key is not None:
        pconfig["api_key"] = payload.api_key
    if payload.models is not None:
        pconfig["models"] = payload.models
    if payload.enabled is not None:
        pconfig["enabled"] = payload.enabled
    if payload.visible_to_users is not None:
        pconfig["visible_to_users"] = payload.visible_to_users
    if payload.visible_models is not None:
        pconfig["visible_models"] = payload.visible_models
    
    # 确保 id 字段存在
    pconfig["id"] = provider_id
    
    providers[provider_id] = pconfig
    _save_providers(providers)
    
    return {
        "success": True,
        "provider_id": provider_id,
        "available_models": _get_available_models_for_users(),
    }


@router.post("/admin/providers")
@require_permission("admin:admin")
async def create_provider(
    request: Request,
    payload: AdminProviderConfig = Body(...),
) -> Dict[str, Any]:
    """创建新 Provider（仅管理员）."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    providers = _load_providers()
    
    if payload.id in providers:
        raise HTTPException(status_code=409, detail=f"Provider '{payload.id}' 已存在")
    
    providers[payload.id] = payload.model_dump(exclude_unset=True)
    _save_providers(providers)
    
    return {
        "success": True,
        "provider_id": payload.id,
        "available_models": _get_available_models_for_users(),
    }


@router.delete("/admin/providers/{provider_id}")
@require_permission("admin:admin")
async def delete_provider(
    request: Request,
    provider_id: str,
) -> Dict[str, Any]:
    """删除 Provider（仅管理员）."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    providers = _load_providers()
    
    if provider_id not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' 不存在")
    
    del providers[provider_id]
    _save_providers(providers)
    
    return {
        "success": True,
        "provider_id": provider_id,
        "available_models": _get_available_models_for_users(),
    }


@router.get("/admin/providers/models")
@require_permission("admin:admin")
async def get_available_models(request: Request) -> AvailableModelsResponse:
    """获取可用模型池（仅管理员）."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    providers = _load_providers()
    provider_list = []
    all_models = []
    
    for pid, pconfig in providers.items():
        if isinstance(pconfig, dict):
            models = pconfig.get("models", [])
            visible = pconfig.get("visible_to_users", True)
            visible_models = pconfig.get("visible_models", models if visible else [])
            
            provider_list.append({
                "id": pid,
                "name": pconfig.get("name", pid),
                "enabled": pconfig.get("enabled", True),
                "visible_to_users": visible,
                "models": models,
                "visible_models": visible_models,
            })
            
            if pconfig.get("enabled", True):
                all_models.extend(visible_models)
    
    unique_models = list(dict.fromkeys(all_models))
    
    return AvailableModelsResponse(
        providers=provider_list,
        models=unique_models,
        total=len(unique_models),
    )


@router.post("/admin/providers/test")
@require_permission("admin:admin")
async def test_provider_connection(
    request: Request,
    payload: TestConnectionRequest = Body(...),
) -> TestConnectionResponse:
    """测试 Provider 连接（仅管理员）."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    try:
        from openai import AsyncOpenAI
        
        api_base = payload.api_base
        api_key = payload.api_key or "none"
        
        client = AsyncOpenAI(
            base_url=api_base,
            api_key=api_key,
        )
        
        # 尝试获取模型列表
        models = await client.models.list()
        model_ids = [m.id for m in models[:50]]  # 限制返回数量
        
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


# ── 公开端点：获取可用模型池（所有用户可访问） ─────────────────────────────

@router.get("/models/available")
@require_permission("models:read")
async def get_public_available_models(request: Request) -> Dict[str, Any]:
    """获取可用模型池（所有用户可见）.
    
    只返回真正可用的 Provider：已配置 API Key（或不需要 Key）且有模型。
    """
    from ...providers.provider_manager import ProviderManager
    
    username = getattr(request.state, "username", "anonymous")
    
    # 从 ProviderManager 获取全局模型
    manager = getattr(request.app.state, "provider_manager", None)
    if manager is None:
        manager = ProviderManager.get_instance()
    
    provider_infos = await manager.list_provider_info()
    
    global_models = []
    for pi in provider_infos:
        # 判断 Provider 是否可用：有 Key 或不需要 Key
        has_key = bool(getattr(pi, 'api_key', ''))
        require_key = getattr(pi, 'require_api_key', True)
        is_available = has_key or not require_key
        
        # 只处理可用的 Provider
        if not is_available:
            continue
        
        pid = getattr(pi, 'id', None) or (pi.get('id') if isinstance(pi, dict) else None)
        pname = getattr(pi, 'name', None) or (pi.get('name') if isinstance(pi, dict) else None)
        
        # 从 ProviderInfo 的 models 字段获取模型列表
        for m in (pi.models or []):
            model_id = m.id if hasattr(m, 'id') else (m.get('id') if isinstance(m, dict) else '')
            model_name = m.name if hasattr(m, 'name') else (m.get('name', model_id) if isinstance(m, dict) else model_id)
            if model_id:
                global_models.append({
                    "id": model_id,
                    "name": model_name,
                    "provider_id": pid,
                    "provider_name": pname,
                })
        # 也从 extra_models 获取
        for m in (pi.extra_models or []):
            model_id = m.id if hasattr(m, 'id') else (m.get('id') if isinstance(m, dict) else '')
            model_name = m.name if hasattr(m, 'name') else (m.get('name', model_id) if isinstance(m, dict) else model_id)
            if model_id:
                global_models.append({
                    "id": model_id,
                    "name": model_name,
                    "provider_id": pid,
                    "provider_name": pname,
                })
    
    # 获取用户自定义模型（如果有）
    custom_providers = []
    custom_path = WORKSPACES_DIR / username / "custom_providers.json"
    if custom_path.exists():
        try:
            with open(custom_path, "r") as f:
                custom_data = json.load(f)
                custom_providers = custom_data.get("providers", [])
        except Exception:
            pass
    
    # 合并去重
    all_models = list(dict.fromkeys([m["id"] for m in global_models]))
    
    return {
        "global_models": global_models,
        "custom_providers": custom_providers,
        "all_models": all_models,
        "total": len(all_models),
    }
