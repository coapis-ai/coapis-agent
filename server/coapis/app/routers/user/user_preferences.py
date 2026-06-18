# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

"""User preferences router - personal preference settings.

个人偏好设置，包括界面主题、聊天显示、通知等。
存储于 user_preferences 表，优先级：localStorage > 数据库 > 默认值。
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel, Field

from ....user_system.database import UserSystemDB

logger = logging.getLogger(__name__)

router = APIRouter(tags=["user/preferences"])


# ── Pydantic models ─────────────────────────────────────────────────────

class ChatDisplayConfig(BaseModel):
    """聊天显示配置."""
    hideToolCall: bool = True
    hideThinking: bool = True
    hideFooter: bool = True
    hideSystemMessages: bool = True
    displayMode: str = "simple"
    showTimestamps: bool = False
    showTokenCounts: bool = False
    showModelName: bool = False
    autoScroll: bool = True
    fontSize: str = "normal"
    codeTheme: str = "dark"


class NotificationConfig(BaseModel):
    email: bool = False
    push: bool = False


class UserPreferencesResponse(BaseModel):
    """完整的用户偏好响应."""
    user_id: Optional[int] = None
    theme: str = "coapis"
    language: str = "zh"
    sidebar_collapsed: bool = False
    chat_display: ChatDisplayConfig = Field(default_factory=ChatDisplayConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    default_agent_id: Optional[str] = None
    default_model: Optional[str] = None
    updated_at: Optional[float] = None


class UserPreferencesUpdate(BaseModel):
    """更新用户偏好（部分更新）."""
    theme: Optional[str] = None
    language: Optional[str] = None
    sidebar_collapsed: Optional[bool] = None
    chat_display: Optional[ChatDisplayConfig] = None
    notifications: Optional[NotificationConfig] = None
    default_agent_id: Optional[str] = None
    default_model: Optional[str] = None


# ── Flat format for frontend compatibility ──────────────────────────────

class FlatPreferencesUpdate(BaseModel):
    """前端直接发送的扁平化偏好数据（兼容 UserPreferences 接口）."""
    theme: Optional[str] = None
    language: Optional[str] = None
    sidebar_collapsed: Optional[int] = None
    chat_display_mode: Optional[str] = None
    chat_hide_tool_call: Optional[int] = None
    chat_hide_thinking: Optional[int] = None
    chat_hide_footer: Optional[int] = None
    chat_hide_system_messages: Optional[int] = None
    chat_show_timestamps: Optional[int] = None
    chat_show_token_counts: Optional[int] = None
    chat_show_model_name: Optional[int] = None
    chat_auto_scroll: Optional[int] = None
    chat_font_size: Optional[str] = None
    chat_code_theme: Optional[str] = None
    email_notifications: Optional[int] = None
    push_notifications: Optional[int] = None
    default_agent_id: Optional[str] = None
    default_model: Optional[str] = None

    def to_nested_update(self) -> UserPreferencesUpdate:
        """转换为嵌套格式的 UserPreferencesUpdate（仅包含非 None 字段）."""
        # 构建 chat_display 的 kwargs（仅包含非 None 字段）
        chat_kwargs: Dict[str, Any] = {}
        field_map = {
            'chat_display_mode': 'displayMode',
            'chat_hide_tool_call': ('hideToolCall', bool),
            'chat_hide_thinking': ('hideThinking', bool),
            'chat_hide_footer': ('hideFooter', bool),
            'chat_hide_system_messages': ('hideSystemMessages', bool),
            'chat_show_timestamps': ('showTimestamps', bool),
            'chat_show_token_counts': ('showTokenCounts', bool),
            'chat_show_model_name': ('showModelName', bool),
            'chat_auto_scroll': ('autoScroll', bool),
            'chat_font_size': 'fontSize',
            'chat_code_theme': 'codeTheme',
        }
        for flat_key, target in field_map.items():
            val = getattr(self, flat_key)
            if val is not None:
                if isinstance(target, tuple):
                    chat_kwargs[target[0]] = target[1](val)
                else:
                    chat_kwargs[target] = val

        chat_display = ChatDisplayConfig(**chat_kwargs) if chat_kwargs else None

        # 构建 notifications 的 kwargs
        notif_kwargs: Dict[str, Any] = {}
        if self.email_notifications is not None:
            notif_kwargs['email'] = bool(self.email_notifications)
        if self.push_notifications is not None:
            notif_kwargs['push'] = bool(self.push_notifications)

        notifications = NotificationConfig(**notif_kwargs) if notif_kwargs else None

        return UserPreferencesUpdate(
            theme=self.theme,
            language=self.language,
            sidebar_collapsed=bool(self.sidebar_collapsed) if self.sidebar_collapsed is not None else None,
            chat_display=chat_display,
            notifications=notifications,
            default_agent_id=self.default_agent_id,
            default_model=self.default_model,
        )


# ── Helper functions ─────────────────────────────────────────────────────

def _get_username(request: Request) -> str:
    """获取当前用户名."""
    username = getattr(request.state, "username", "anonymous")
    if username == "anonymous":
        raise HTTPException(status_code=401, detail="需要登录")
    return username


def _row_to_response(row: Dict[str, Any]) -> UserPreferencesResponse:
    """将数据库行转换为 UserPreferencesResponse."""
    return UserPreferencesResponse(
        user_id=row.get("user_id"),
        theme=row.get("theme", "coapis"),
        language=row.get("language", "zh"),
        sidebar_collapsed=bool(row.get("sidebar_collapsed", 0)),
        chat_display=ChatDisplayConfig(
            hideToolCall=bool(row.get("chat_hide_tool_call", 1)),
            hideThinking=bool(row.get("chat_hide_thinking", 1)),
            hideFooter=bool(row.get("chat_hide_footer", 1)),
            hideSystemMessages=bool(row.get("chat_hide_system_messages", 1)),
            displayMode=row.get("chat_display_mode", "simple"),
            showTimestamps=bool(row.get("chat_show_timestamps", 0)),
            showTokenCounts=bool(row.get("chat_show_token_counts", 0)),
            showModelName=bool(row.get("chat_show_model_name", 0)),
            autoScroll=bool(row.get("chat_auto_scroll", 1)),
            fontSize=row.get("chat_font_size", "normal"),
            codeTheme=row.get("chat_code_theme", "dark"),
        ),
        notifications=NotificationConfig(
            email=bool(row.get("email_notifications", 0)),
            push=bool(row.get("push_notifications", 0)),
        ),
        default_agent_id=row.get("default_agent_id"),
        default_model=row.get("default_model"),
        updated_at=row.get("updated_at"),
    )


def _load_preferences(username: str) -> UserPreferencesResponse:
    """从数据库加载用户偏好，不存在则返回默认值."""
    db = UserSystemDB()
    user = db.get_user_by_username(username)

    if not user:
        return UserPreferencesResponse()

    row = db.execute(
        "SELECT * FROM user_preferences WHERE user_id = ?",
        (user["id"],),
    ).fetchone()

    if not row:
        # 创建默认记录
        db.execute(
            "INSERT INTO user_preferences "
            "(user_id, theme, language, updated_at) VALUES (?, ?, ?, ?)",
            (user["id"], "coapis", "zh", time.time()),
        )
        db.commit()
        # 重新读取
        row = db.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?",
            (user["id"],),
        ).fetchone()

    return _row_to_response(dict(row))


def _save_preferences_flat(username: str, flat: FlatPreferencesUpdate) -> UserPreferencesResponse:
    """保存用户偏好更新（使用扁平格式，仅更新非 None 字段）."""
    db = UserSystemDB()
    user = db.get_user_by_username(username)

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 构建 SET 子句（仅包含非 None 字段）
    set_clauses = []
    params = []

    flat_field_map = {
        'theme': ('theme', None),
        'language': ('language', None),
        'sidebar_collapsed': ('sidebar_collapsed', bool),
        'chat_display_mode': ('chat_display_mode', None),
        'chat_hide_tool_call': ('chat_hide_tool_call', lambda v: 1 if v else 0),
        'chat_hide_thinking': ('chat_hide_thinking', lambda v: 1 if v else 0),
        'chat_hide_footer': ('chat_hide_footer', lambda v: 1 if v else 0),
        'chat_hide_system_messages': ('chat_hide_system_messages', lambda v: 1 if v else 0),
        'chat_show_timestamps': ('chat_show_timestamps', lambda v: 1 if v else 0),
        'chat_show_token_counts': ('chat_show_token_counts', lambda v: 1 if v else 0),
        'chat_show_model_name': ('chat_show_model_name', lambda v: 1 if v else 0),
        'chat_auto_scroll': ('chat_auto_scroll', lambda v: 1 if v else 0),
        'chat_font_size': ('chat_font_size', None),
        'chat_code_theme': ('chat_code_theme', None),
        'email_notifications': ('email_notifications', lambda v: 1 if v else 0),
        'push_notifications': ('push_notifications', lambda v: 1 if v else 0),
        'default_agent_id': ('default_agent_id', None),
        'default_model': ('default_model', None),
    }

    for flat_key, (db_col, converter) in flat_field_map.items():
        val = getattr(flat, flat_key)
        if val is not None:
            set_clauses.append(f"{db_col} = ?")
            params.append(converter(val) if converter else val)

    set_clauses.append("updated_at = ?")
    params.append(time.time())
    params.append(user["id"])

    if set_clauses:
        sql = f"UPDATE user_preferences SET {', '.join(set_clauses)} WHERE user_id = ?"
        db.execute(sql, tuple(params))
        db.commit()

    return _load_preferences(username)


def _save_preferences(username: str, update: UserPreferencesUpdate) -> UserPreferencesResponse:
    """保存用户偏好更新（嵌套格式，用于兼容旧接口）."""
    # 嵌套格式无法判断哪些字段是"有意义的"，所以直接更新所有字段
    db = UserSystemDB()
    user = db.get_user_by_username(username)

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    set_clauses = []
    params = []

    if update.theme is not None:
        set_clauses.append("theme = ?")
        params.append(update.theme)

    if update.language is not None:
        set_clauses.append("language = ?")
        params.append(update.language)

    if update.sidebar_collapsed is not None:
        set_clauses.append("sidebar_collapsed = ?")
        params.append(1 if update.sidebar_collapsed else 0)

    if update.chat_display is not None:
        cd = update.chat_display
        set_clauses.extend([
            "chat_hide_tool_call = ?", "chat_hide_thinking = ?",
            "chat_hide_footer = ?", "chat_hide_system_messages = ?",
            "chat_display_mode = ?",
            "chat_show_timestamps = ?", "chat_show_token_counts = ?",
            "chat_show_model_name = ?", "chat_auto_scroll = ?",
            "chat_font_size = ?", "chat_code_theme = ?",
        ])
        params.extend([
            1 if cd.hideToolCall else 0,
            1 if cd.hideThinking else 0,
            1 if cd.hideFooter else 0,
            1 if cd.hideSystemMessages else 0,
            cd.displayMode,
            1 if cd.showTimestamps else 0,
            1 if cd.showTokenCounts else 0,
            1 if cd.showModelName else 0,
            1 if cd.autoScroll else 0,
            cd.fontSize,
            cd.codeTheme,
        ])

    if update.notifications is not None:
        n = update.notifications
        set_clauses.extend(["email_notifications = ?", "push_notifications = ?"])
        params.extend([1 if n.email else 0, 1 if n.push else 0])

    if update.default_agent_id is not None:
        set_clauses.append("default_agent_id = ?")
        params.append(update.default_agent_id)

    if update.default_model is not None:
        set_clauses.append("default_model = ?")
        params.append(update.default_model)

    set_clauses.append("updated_at = ?")
    params.append(time.time())
    params.append(user["id"])

    if set_clauses:
        sql = f"UPDATE user_preferences SET {', '.join(set_clauses)} WHERE user_id = ?"
        db.execute(sql, tuple(params))
        db.commit()

    return _load_preferences(username)


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/user/preferences")
async def get_preferences(request: Request) -> UserPreferencesResponse:
    """获取当前用户偏好设置."""
    username = _get_username(request)
    return _load_preferences(username)


@router.put("/user/preferences")
async def update_preferences_put(
    request: Request,
    data: FlatPreferencesUpdate = Body(...),
) -> UserPreferencesResponse:
    """更新当前用户偏好设置（使用扁平格式，仅更新非 None 字段）."""
    username = _get_username(request)
    return _save_preferences_flat(username, data)


@router.post("/user/preferences")
async def update_preferences_post(
    request: Request,
    data: FlatPreferencesUpdate = Body(...),
) -> UserPreferencesResponse:
    """更新当前用户偏好设置（POST 兼容接口）."""
    username = _get_username(request)
    return _save_preferences_flat(username, data)
