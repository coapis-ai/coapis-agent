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

"""Admin Provider Management - 管理员配置全局 Provider。

管理员在此配置 Provider（API Base、API Key、模型列表）。
模型可用性由 Provider 自身配置状态自动决定（isConfigured && hasModels），
不需要额外的 visible_to_users / visible_models 配置。
"""
from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional

from ..permissions.decorators import require_permission
from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel

from ...constant import WORKSPACES_DIR

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


class AdminProviderUpdate(BaseModel):
    """更新 Provider 配置（部分更新）."""
    name: Optional[str] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    models: Optional[List[str]] = None
    enabled: Optional[bool] = None


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

def _is_admin(request: Request) -> bool:
    """检查是否为管理员."""
    role = getattr(request.state, "role", "user")
    return role == "admin"


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/admin/providers")
@require_permission("admin:admin")
async def get_all_providers(request: Request) -> Dict[str, Any]:
    """获取所有 Provider 配置（仅管理员）.
    
    从 ProviderManager 读取，返回所有 provider 的配置信息。
    """
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    from ...providers.provider_manager import ProviderManager
    pm = ProviderManager.get_instance()
    provider_infos = await pm.list_provider_info()
    
    result = []
    for info in provider_infos:
        d = info.model_dump() if hasattr(info, "model_dump") else info
        result.append({
            "id": d.get("id", ""),
            "name": d.get("name", ""),
            "base_url": d.get("base_url", ""),
            "api_key": d.get("api_key", ""),
            "models": d.get("models", []),
            "is_custom": d.get("is_custom", False),
            "is_local": d.get("is_local", False),
            "require_api_key": d.get("require_api_key", True),
            "chat_model": d.get("chat_model", ""),
            "support_model_discovery": d.get("support_model_discovery", False),
            "support_connection_check": d.get("support_connection_check", True),
            "freeze_url": d.get("freeze_url", False),
            "generate_kwargs": d.get("generate_kwargs", {}),
        })
    
    return {
        "providers": result,
    }


@router.get("/admin/providers/models")
@require_permission("admin:admin")
async def get_available_models(request: Request) -> AvailableModelsResponse:
    """获取可用模型池（仅管理员）."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    from ...providers.provider_manager import ProviderManager
    pm = ProviderManager.get_instance()
    provider_infos = await pm.list_provider_info()
    
    provider_list = []
    all_models = []
    
    for info in provider_infos:
        d = info.model_dump() if hasattr(info, "model_dump") else info
        pid = d.get("id", "")
        models = d.get("models", [])
        
        provider_list.append({
            "id": pid,
            "name": d.get("name", pid),
            "models": models,
        })
        all_models.extend(m.get("id", m) if isinstance(m, dict) else m for m in models)
    
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
    
    遍历 ProviderManager 中所有 provider，
    isAvailable = isConfigured && hasModels 的自动过滤。
    """
    global_models = []
    
    try:
        from ...providers.provider_manager import ProviderManager
        pm = ProviderManager.get_instance()
        provider_infos = await pm.list_provider_info()
        
        for info in provider_infos:
            d = info.model_dump() if hasattr(info, "model_dump") else info
            pid = d.get("id", "")
            pname = d.get("name", pid)
            
            # isAvailable = isConfigured && hasModels
            is_custom = d.get("is_custom", False)
            base_url = d.get("base_url", "")
            api_key = d.get("api_key", "")
            require_api_key = d.get("require_api_key", True)
            models = d.get("models", []) or []
            
            if not models:
                continue
            
            # isConfigured 判断（与前端 RemoteProviderCard 一致）
            is_configured = False
            if is_custom and base_url:
                is_configured = True
            elif not require_api_key:
                is_configured = True
            elif require_api_key and api_key:
                is_configured = True
            
            if not is_configured:
                continue
            
            seen_model_ids = set()
            for m in models:
                if isinstance(m, str):
                    model_id = m
                    model_name = m
                elif isinstance(m, dict):
                    model_id = m.get("id", "")
                    model_name = m.get("name", model_id)
                else:
                    continue
                
                if model_id and model_id not in seen_model_ids:
                    seen_model_ids.add(model_id)
                    global_models.append({
                        "id": model_id,
                        "name": model_name,
                        "provider_id": pid,
                        "provider_name": pname,
                    })
    except Exception as e:
        logger.error("Failed to read models from ProviderManager: %s", e)
    
    # 合并去重
    all_models = list(dict.fromkeys([m["id"] for m in global_models]))
    
    return {
        "global_models": global_models,
        "all_models": all_models,
        "total": len(all_models),
    }
