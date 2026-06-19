# -*- coding: utf-8 -*-
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

"""Workspace Agents router - user-level agent management.

每个用户独立管理自己的智能体。
- 列出当前用户的所有智能体（自己的 + 全局共享只读）
- 创建/编辑/删除自己的智能体
- 调整排序、启用/停用
"""
from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from coapis.constant import AGENTS_DIR, WORKSPACES_DIR

from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel

from ....config import load_agent_config, save_agent_config
from ....constant import WORKSPACES_DIR
from ....app.user_store import get_user_agents_dir

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workspace/agents"])


# ── Pydantic models ─────────────────────────────────────────────────────

class ModelSlotConfig(BaseModel):
    provider_id: str
    model: str


class AgentSummary(BaseModel):
    id: str
    name: str
    description: str = ""
    workspace_dir: str = ""
    enabled: bool = True
    scope: str = "user"  # "user" or "global"
    active_model: Optional[ModelSlotConfig] = None


class CreateAgentRequest(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    language: str = ""
    skill_names: List[str] = []
    active_model: Optional[ModelSlotConfig] = None


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    active_model: Optional[ModelSlotConfig] = None
    enabled: Optional[bool] = None


class ReorderAgentsRequest(BaseModel):
    agent_ids: List[str]


class ToggleEnabledRequest(BaseModel):
    enabled: bool


# ── Helper functions ─────────────────────────────────────────────────────

def _get_username(request: Request) -> str:
    """获取当前用户名."""
    username = getattr(request.state, "username", "anonymous")
    if username == "anonymous":
        raise HTTPException(status_code=401, detail="需要登录")
    return username


def _to_dict(obj: Any) -> Dict[str, Any]:
    """Safely convert any object to dict."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()
    return {}


def _get_active_model(agent_id: str) -> Optional[ModelSlotConfig]:
    """获取智能体的活跃模型配置."""
    agent_config = _to_dict(load_agent_config(agent_id))
    
    active_model = agent_config.get("active_model")
    if isinstance(active_model, dict) and active_model.get("model"):
        return ModelSlotConfig(
            provider_id=active_model.get("provider_id", "local_llm"),
            model=active_model.get("model", "")
        )
    
    provider = agent_config.get("provider", {})
    if provider and isinstance(provider, dict):
        model = provider.get("model", "")
        if model:
            return ModelSlotConfig(
                provider_id=provider.get("id", "local_llm"),
                model=model
            )
    
    return None


def _agent_to_summary(agent_id: str, scope: str = "user") -> Dict[str, Any]:
    """Convert agent_id to AgentSummary format."""
    agent_config = _to_dict(load_agent_config(agent_id))
    name = agent_config.get("name", agent_id)
    description = agent_config.get("description", "")
    active_model = _get_active_model(agent_id)
    
    # Determine workspace dir based on scope
    if scope == "global":
        workspace_dir = str(AGENTS_DIR / agent_id)
    else:
        workspace_dir = ""  # User agents dir is internal
    
    return {
        "id": agent_id,
        "name": name,
        "description": description,
        "workspace_dir": workspace_dir,
        "enabled": True,
        "scope": scope,
        "active_model": active_model.model_dump() if active_model else None,
    }


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/workspace/agents")
async def list_my_agents(request: Request) -> Dict[str, Any]:
    """列出当前用户的所有智能体."""
    username = _get_username(request)
    manager = getattr(request.app.state, "multi_agent_manager", None)
    
    if not manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    
    # 获取用户的所有智能体
    user_agents = manager.get_user_agents(username)
    
    agents = []
    for agent_info in user_agents:
        agent_id = agent_info["id"]
        scope = agent_info.get("scope", "user")
        agents.append(_agent_to_summary(agent_id, scope))
    
    return {
        "agents": agents,
        "total": len(agents),
        "username": username,
    }


@router.post("/workspace/agents")
async def create_my_agent(
    request: Request,
    payload: CreateAgentRequest = Body(...),
) -> Dict[str, Any]:
    """创建新的智能体（用户级）."""
    username = _get_username(request)
    manager = getattr(request.app.state, "multi_agent_manager", None)
    
    if not manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    
    agent_id = payload.id or f"agent_{username}_{int(__import__('time').time())}"
    
    # 检查是否已存在
    if manager.get_workspace(agent_id):
        raise HTTPException(status_code=409, detail=f"智能体 {agent_id} 已存在")
    
    # 构建配置
    config = {
        "name": payload.name,
        "description": payload.description,
        "language": payload.language,
    }
    
    if payload.active_model:
        config["active_model"] = payload.active_model.model_dump()
        config["provider"] = {
            "id": payload.active_model.provider_id,
            "model": payload.active_model.model,
            "api_base": "",  # Will be filled from global config
            "api_key": "none",
        }
    
    try:
        workspace = await manager.create_agent(
            agent_id=agent_id,
            config=config,
            username=username,
            is_global=False,
        )
        
        # Record audit log
        from ....user_system.database import UserSystemDB
        db = UserSystemDB()
        user = db.get_user_by_username(username)
        if user:
            db.insert_audit_log(
                user_id=user["id"],
                username=username,
                action="create_agent",
                resource_type="agent",
                resource_id=agent_id,
                details={"name": payload.name},
            )
        
        return _agent_to_summary(agent_id, "user")
        
    except Exception as e:
        logger.error(f"Failed to create agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.get("/workspace/agents/{agent_id}")
async def get_my_agent(
    request: Request,
    agent_id: str,
) -> Dict[str, Any]:
    """获取智能体详情."""
    username = _get_username(request)
    manager = getattr(request.app.state, "multi_agent_manager", None)
    
    if not manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="智能体不存在")
    
    # 检查权限（只能访问自己的或全局的）
    if workspace.username and workspace.username != username and workspace.is_global:
        scope = "global"
    elif workspace.username == username or (not workspace.username and workspace.is_global):
        scope = "global" if workspace.is_global else "user"
    else:
        raise HTTPException(status_code=403, detail="无权访问此智能体")
    
    return _agent_to_summary(agent_id, scope)


@router.put("/workspace/agents/{agent_id}")
async def update_my_agent(
    request: Request,
    agent_id: str,
    payload: UpdateAgentRequest = Body(...),
) -> Dict[str, Any]:
    """更新智能体配置."""
    username = _get_username(request)
    manager = getattr(request.app.state, "multi_agent_manager", None)
    
    if not manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="智能体不存在")
    
    # 检查权限（只能修改自己的）
    if not workspace.is_global and workspace.username != username:
        raise HTTPException(status_code=403, detail="无权修改此智能体")
    
    # 加载当前配置并更新
    config = _to_dict(load_agent_config(agent_id))
    
    if payload.name is not None:
        config["name"] = payload.name
    if payload.description is not None:
        config["description"] = payload.description
    if payload.active_model is not None:
        config["active_model"] = payload.active_model.model_dump()
        config["provider"] = {
            "id": payload.active_model.provider_id,
            "model": payload.active_model.model,
            "api_key": "none",
        }
    
    save_agent_config(agent_id, config)
    
    # Record audit log
    from ....user_system.database import UserSystemDB
    db = UserSystemDB()
    user = db.get_user_by_username(username)
    if user:
        db.insert_audit_log(
            user_id=user["id"],
            username=username,
            action="update_agent",
            resource_type="agent",
            resource_id=agent_id,
            details={"updated_fields": [k for k, v in payload.model_dump().items() if v is not None]},
        )
    
    return _agent_to_summary(agent_id, "user")


@router.delete("/workspace/agents/{agent_id}")
async def delete_my_agent(
    request: Request,
    agent_id: str,
) -> Dict[str, Any]:
    """删除智能体（只能删除自己的）."""
    username = _get_username(request)
    manager = getattr(request.app.state, "multi_agent_manager", None)
    
    if not manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="智能体不存在")
    
    # 只能删除自己的智能体
    if workspace.is_global:
        raise HTTPException(status_code=403, detail="无法删除全局智能体")
    if workspace.username != username:
        raise HTTPException(status_code=403, detail="无权删除此智能体")
    
    success = await manager.destroy_agent(agent_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")
    
    # Record audit log
    from ....user_system.database import UserSystemDB
    db = UserSystemDB()
    user = db.get_user_by_username(username)
    if user:
        db.insert_audit_log(
            user_id=user["id"],
            username=username,
            action="delete_agent",
            resource_type="agent",
            resource_id=agent_id,
        )
    
    return {"success": True, "agent_id": agent_id}


@router.put("/workspace/agents/reorder")
async def reorder_my_agents(
    request: Request,
    payload: ReorderAgentsRequest = Body(...),
) -> Dict[str, Any]:
    """调整智能体排序."""
    username = _get_username(request)
    
    # 存储用户级排序
    order_dir = WORKSPACES_DIR / username / "agent_order"
    order_dir.mkdir(parents=True, exist_ok=True)
    order_file = order_dir / "order.json"
    
    with open(order_file, "w") as f:
        json.dump({"agent_ids": payload.agent_ids}, f)
    
    return {
        "success": True,
        "agent_ids": payload.agent_ids,
    }


@router.post("/workspace/agents/{agent_id}/toggle")
async def toggle_my_agent(
    request: Request,
    agent_id: str,
    payload: ToggleEnabledRequest = Body(...),
) -> Dict[str, Any]:
    """启用/停用智能体."""
    username = _get_username(request)
    manager = getattr(request.app.state, "multi_agent_manager", None)
    
    if not manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    
    workspace = manager.get_workspace(agent_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="智能体不存在")
    
    # 只能修改自己的
    if not workspace.is_global and workspace.username != username:
        raise HTTPException(status_code=403, detail="无权操作此智能体")
    
    # 更新配置中的 enabled 字段
    config = _to_dict(load_agent_config(agent_id))
    config["enabled"] = payload.enabled
    save_agent_config(agent_id, config)
    
    if payload.enabled:
        await workspace.start()
    else:
        await workspace.stop()
    
    return {
        "success": True,
        "agent_id": agent_id,
        "enabled": payload.enabled,
    }
