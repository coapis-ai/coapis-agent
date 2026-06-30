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

普通用户只需选择默认模型和排序。
自定义 Provider 统一由 ProviderManager 管理。
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
    default_model: Optional[str] = None
    model_priority: List[str] = []
    language: str = "zh"


class UpdateModelPrefsRequest(BaseModel):
    """更新模型偏好（部分更新）."""
    default_model: Optional[str] = None
    model_priority: Optional[List[str]] = None
    language: Optional[str] = None


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
                # 兼容旧格式：删除 custom_providers 字段
                data.pop("custom_providers", None)
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
    
    return {
        "username": username,
        "default_model": prefs.default_model,
        "model_priority": prefs.model_priority,
        "language": prefs.language,
    }


@router.put("/user/model-prefs")
async def update_model_prefs(
    request: Request,
    payload: UpdateModelPrefsRequest = Body(...),
) -> Dict[str, Any]:
    """更新用户模型偏好（部分更新）."""
    username = _get_username(request)
    prefs = _load_user_prefs(username)
    
    if payload.default_model is not None:
        prefs.default_model = payload.default_model
    if payload.model_priority is not None:
        prefs.model_priority = payload.model_priority
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


# ── 模型解析逻辑 ─────────────────────────────────────────────────────────

def resolve_model_for_user(username: str, agent_model: Optional[str] = None) -> Optional[str]:
    """解析用户实际使用的模型。
    
    优先级：
    1. 用户从可用模型池中选择的默认模型
    2. Agent 配置的 active_model
    3. 全局默认模型（兜底）
    """
    prefs = _load_user_prefs(username)
    
    if prefs.default_model:
        return prefs.default_model
    
    if agent_model:
        return agent_model
    
    return None
