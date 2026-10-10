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

"""User Model Preferences - 用户模型偏好设置。

普通用户只需选择默认模型和排序。
自定义 Provider 统一由 ProviderManager 管理。
"""
from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel

from ...constant import WORKSPACES_DIR

logger = logging.getLogger(__name__)

router = APIRouter(tags=["user/model-prefs"])


# ── Pydantic models ─────────────────────────────────────────────────────

class UserModelPrefs(BaseModel):
    """用户模型偏好配置（用户全局，不分智能体/场景）。

    模型以 (provider_id, model) 成对存储：同名模型可能来自不同
    provider（实测 dev 有 A3@a3 与 A3@local3-new 两个），只存 model
    无法确定用哪个 provider 调用。
    """
    # 聊天模型（LLM）——用户全局偏好，唯一有运行时消费者的槽位。
    # 嵌入/重排序模型不在此存储：二者运行时无消费者（社区版记忆是关键词+LLM
    # 重排，重排跟随聊天模型；企业版嵌入走 KB 配置与全局默认槽位）。
    # 换嵌入模型会让已入库向量失效，属系统级/库级资源，不作用户级偏好。
    default_model: Optional[str] = None
    default_provider_id: Optional[str] = None
    language: str = "zh"


class UpdateModelPrefsRequest(BaseModel):
    """更新模型偏好（部分更新，字段为 None 表示不改；空字符串表示清除）。"""
    default_model: Optional[str] = None
    default_provider_id: Optional[str] = None
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
                # 兼容旧格式：删除已退役字段（custom_providers / 嵌入 / 重排序 / 优先级）
                for legacy in (
                    "custom_providers",
                    "default_embedding_model",
                    "default_embedding_provider_id",
                    "default_rerank_model",
                    "default_rerank_provider_id",
                    "model_priority",
                ):
                    data.pop(legacy, None)
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
        "default_provider_id": prefs.default_provider_id,
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
    
    chat_changed = False

    # 空字符串 = 清除该项偏好（回退系统默认）
    def _apply(field: str, provider_field: str) -> None:
        nonlocal chat_changed
        model_val = getattr(payload, field)
        provider_val = getattr(payload, provider_field)
        if model_val is not None:
            setattr(prefs, field, model_val or None)
            if field == "default_model":
                chat_changed = True
        if provider_val is not None:
            setattr(prefs, provider_field, provider_val or None)

    _apply("default_model", "default_provider_id")
    if payload.language is not None:
        prefs.language = payload.language

    # 校验：成对出现的偏好必须指向真实存在的 provider+模型
    pid = prefs.default_provider_id
    mid = prefs.default_model
    if pid and mid and not _slot_is_valid(pid, mid):
        raise HTTPException(
            status_code=400,
            detail=f"模型 {mid} 不在 provider {pid} 的模型列表中，无法设为偏好",
        )

    _save_user_prefs(username, prefs)

    # 聊天模型变更后热生效：模型在 agent 构造时绑定，实例被缓存，
    # 必须 reload 用户智能体，否则要重启才生效。
    if chat_changed:
        try:
            from ..utils import schedule_agent_reload

            schedule_agent_reload(request, f"user:{username}")
        except Exception as e:  # 热重载失败不影响偏好已保存
            logger.warning(f"Failed to schedule agent reload for {username}: {e}")
    
    # 审计日志
    try:
        # 本文件位于 coapis/app/routers/ 下，三级点才到 coapis 顶层；
        # 四点会越过顶层包（attempted relative import beyond top-level）。
        from ...user_system.database import UserSystemDB
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
        "language": prefs.language,
    }


# ── 模型解析逻辑 ─────────────────────────────────────────────────────────

def _slot_is_valid(provider_id: str, model: str) -> bool:
    """偏好指向的 (provider, model) 当前是否可用。

    provider 被删除/禁用、或模型被移出列表时返回 False，供上层回退，
    不抛错——偏好失效不能让聊天链路崩。
    """
    if not provider_id or not model:
        return False
    try:
        from ...providers.provider_manager import ProviderManager

        provider = ProviderManager.get_instance().get_provider(provider_id)
        if provider is None:
            return False
        for m in list(getattr(provider, "models", []) or []) + list(
            getattr(provider, "extra_models", []) or []
        ):
            mid = m.id if hasattr(m, "id") else (m.get("id") if isinstance(m, dict) else None)
            if mid == model:
                return True
        return False
    except Exception:
        return False


def resolve_chat_model_slot(
    username: Optional[str],
    agent_id: Optional[str] = None,
) -> Optional[tuple[str, str]]:
    """聊天模型的唯一解析入口：用户偏好 → 智能体默认 → 全局默认。

    返回 ``(provider_id, model)``，无法解析时返回 None。

    这是唯一权威解析函数（model_factory / prompt / view_media 三处共用），
    避免"聊天用模型 A、多模态判断用模型 B"导致图片上传误警告。
    """
    # 1) 用户全局偏好
    if username:
        prefs = _load_user_prefs(username)
        if prefs.default_provider_id and prefs.default_model:
            if _slot_is_valid(prefs.default_provider_id, prefs.default_model):
                return prefs.default_provider_id, prefs.default_model
            logger.warning(
                "User %s preference %s/%s is stale (provider/model missing); "
                "falling back to agent/global.",
                username,
                prefs.default_provider_id,
                prefs.default_model,
            )

    # 2) 智能体默认
    if agent_id:
        try:
            from ...config.config import load_agent_config

            agent_model = load_agent_config(agent_id).active_model
            if agent_model and agent_model.provider_id and agent_model.model:
                return agent_model.provider_id, agent_model.model
        except Exception:
            pass

    # 3) 全局默认兜底
    try:
        from ...providers.provider_manager import ProviderManager

        global_slot = ProviderManager.get_instance().get_active_model()
        if global_slot and global_slot.provider_id and global_slot.model:
            return global_slot.provider_id, global_slot.model
    except Exception:
        pass

    return None
