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

"""Default data definitions for system initialization.

All default configurations, roles, permissions, and templates are defined here.
This is the single source of truth for initial system state.
"""
from __future__ import annotations

from typing import Any, Dict, List

# ═══════════════════════════════════════════════════════════════════
# 系统版本
# ═══════════════════════════════════════════════════════════════════
SYSTEM_VERSION = "0.8.12"
INIT_SCHEMA_VERSION = 1

# ═══════════════════════════════════════════════════════════════════
# 目录结构
# ═══════════════════════════════════════════════════════════════════
DEFAULT_DIRECTORIES: List[str] = [
    # 系统目录
    "system",
    "system/.secret",
    "system/templates",
    "system/evolution",
    "system/reviews",
    # 用户工作区
    "workspaces",
    # 智能体数据
    "agents",
    # 技能
    "skills",
    "skill_pool",
    # 日志
    "logs",
    # 媒体
    "media",
    # 本地模型
    "local_models",
    # 记忆
    "memory",
    # 备份
    ".backups",
    # 自定义频道
    "custom_channels",
    # 插件
    "plugins",
    # 模型配置
    "models",
]

# ═══════════════════════════════════════════════════════════════════
# 默认配置文件
# ═══════════════════════════════════════════════════════════════════
DEFAULT_CONFIG: Dict[str, Any] = {
    "version": SYSTEM_VERSION,
    "channels": {},
    "heartbeat": {
        "enabled": True,
        "every": 60,
        "query": "What should I work on next?",
    },
    "active_hours": {},
    "auth": {
        "enabled": False,
        "secret_key": "CHANGE_ME_TO_RANDOM_STRING",
    },
    "user_system": {
        "enabled": False,
        "default_token_quota": 1_000_000,
        "token_quota_hard_limit": False,
    },
    "providers": {},
    "workspace": {
        "default_agent_name": "CoApis",
        "default_skills": ["guidance"],
    },
}

# ═══════════════════════════════════════════════════════════════════
# 默认角色定义
# ═══════════════════════════════════════════════════════════════════
DEFAULT_ROLES: Dict[str, Dict[str, Any]] = {
    "user": {
        "name": "用户",
        "description": "标准用户，可通过权限矩阵配置",
        "level": 0,
        "is_default": True,
        "modules": {
            "chat": {"read": True, "create": True, "update": True, "delete": False},
            "skills": {"read": True, "create": True, "update": True, "delete": False},
            "models": {"read": True, "create": True, "update": True, "delete": True},
            "agents": {"read": True, "create": True, "update": False, "delete": False},
            "admin": {"read": False, "create": False, "update": False, "delete": False},
            "system": {"read": False, "create": False, "update": False, "delete": False},
            "audit": {"read": True, "create": False, "update": False, "delete": False},
            "token_usage": {"read": True, "create": False, "update": False, "delete": False},
            "cron": {"read": True, "create": True, "update": True, "delete": True},
            "heartbeat": {"read": True, "create": False, "update": False, "delete": False},
            "channels": {"read": True, "create": False, "update": False, "delete": False},
            "config": {"read": True, "create": False, "update": False, "delete": False},
            "workspace": {"read": True, "create": True, "update": True, "delete": True},
            "myspace": {"read": True, "create": True, "update": True, "delete": True},
            "security": {"read": False, "create": False, "update": False, "delete": False},
            "backups": {"read": True, "create": False, "update": False, "delete": False},
            "debug": {"read": False, "create": False, "update": False, "delete": False},
            "evolution": {"read": True, "create": False, "update": False, "delete": False},
            "knowledge": {"read": True, "create": False, "update": False, "delete": False},
            "user_system": {"read": True, "create": False, "update": False, "delete": False},
            "sessions": {"read": True, "create": True, "update": True, "delete": True},
            "files": {"read": True, "create": True, "update": True, "delete": True},
        },
    },
    "advanced": {
        "name": "高级用户",
        "description": "高级用户，拥有更多权限",
        "level": 1,
        "is_default": False,
        "modules": {
            "chat": {"read": True, "create": True, "update": True, "delete": True},
            "skills": {"read": True, "create": True, "update": True, "delete": True},
            "models": {"read": True, "create": True, "update": True, "delete": False},
            "agents": {"read": True, "create": True, "update": True, "delete": True},
            "admin": {"read": False, "create": False, "update": False, "delete": False},
            "system": {"read": True, "create": False, "update": False, "delete": False},
            "audit": {"read": True, "create": False, "update": False, "delete": False},
            "token_usage": {"read": True, "create": False, "update": False, "delete": False},
            "cron": {"read": True, "create": True, "update": True, "delete": True},
            "heartbeat": {"read": True, "create": True, "update": True, "delete": False},
            "channels": {"read": True, "create": True, "update": True, "delete": False},
            "config": {"read": True, "create": False, "update": False, "delete": False},
            "workspace": {"read": True, "create": True, "update": True, "delete": True},
            "myspace": {"read": True, "create": True, "update": True, "delete": True},
            "security": {"read": True, "create": False, "update": False, "delete": False},
            "backups": {"read": True, "create": True, "update": False, "delete": False},
            "debug": {"read": True, "create": False, "update": False, "delete": False},
            "evolution": {"read": True, "create": True, "update": True, "delete": False},
            "knowledge": {"read": True, "create": True, "update": True, "delete": False},
            "user_system": {"read": True, "create": False, "update": False, "delete": False},
            "sessions": {"read": True, "create": True, "update": True, "delete": True},
            "files": {"read": True, "create": True, "update": True, "delete": True},
        },
    },
    "admin": {
        "name": "管理员",
        "description": "拥有所有权限",
        "level": 2,
        "is_default": False,
        "modules": "*",
    },
}

# ═══════════════════════════════════════════════════════════════════
# 默认权限配置 (v2.0 格式)
# ═══════════════════════════════════════════════════════════════════
DEFAULT_PERMISSIONS: Dict[str, Any] = {
    "version": "2.0",
    "description": "CoApis permission system — CRUD matrix format.",
    "roles": DEFAULT_ROLES,
    "user_overrides": {},
    "module_definitions": {
        "chat": {"name": "聊天", "description": "AI 对话功能"},
        "skills": {"name": "技能", "description": "技能管理"},
        "models": {"name": "模型", "description": "模型配置"},
        "agents": {"name": "智能体", "description": "智能体管理"},
        "admin": {"name": "管理后台", "description": "系统管理"},
        "system": {"name": "系统", "description": "系统配置"},
        "audit": {"name": "审计", "description": "审计日志"},
        "token_usage": {"name": "Token 消耗", "description": "Token 用量统计"},
        "cron": {"name": "定时任务", "description": "定时任务管理"},
        "heartbeat": {"name": "心跳", "description": "心跳配置"},
        "channels": {"name": "频道", "description": "频道管理"},
        "config": {"name": "配置", "description": "系统配置"},
        "workspace": {"name": "工作区", "description": "工作区管理"},
        "myspace": {"name": "我的空间", "description": "用户个人空间"},
        "security": {"name": "安全", "description": "安全配置"},
        "backups": {"name": "备份", "description": "备份管理"},
        "debug": {"name": "调试", "description": "调试工具"},
        "evolution": {"name": "进化", "description": "智能体进化"},
        "knowledge": {"name": "知识库", "description": "知识库管理"},
        "user_system": {"name": "用户体系", "description": "用户体系管理"},
        "sessions": {"name": "会话", "description": "会话管理"},
        "files": {"name": "文件", "description": "文件管理"},
    },
}

# ═══════════════════════════════════════════════════════════════════
# 默认管理员用户
# ═══════════════════════════════════════════════════════════════════
DEFAULT_ADMIN_USER: Dict[str, Any] = {
    "username": "admin",
    "display_name": "管理员",
    "password": "admin123",  # 首次登录后应修改
    "role": "admin",
    "is_active": True,
}

# ═══════════════════════════════════════════════════════════════════
# 默认用户工作区模板
# ═══════════════════════════════════════════════════════════════════
DEFAULT_WORKSPACE_TEMPLATE: Dict[str, Any] = {
    "chats.json": {"version": 1, "chats": []},
    "jobs.json": {"version": 1, "jobs": []},
}

DEFAULT_WORKSPACE_FILES: List[str] = [
    "AGENTS.md",
    "SOUL.md",
    "PROFILE.md",
    "MEMORY.md",
    "HEARTBEAT.md",
]

# ═══════════════════════════════════════════════════════════════════
# 环境变量默认值
# ═══════════════════════════════════════════════════════════════════
DEFAULT_ENV_VARS: Dict[str, str] = {
    "COAPIS_PORT": "8000",
    "COAPIS_WORKING_DIR": "/apps/ai/coapis",
}
