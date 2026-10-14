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

"""Default data definitions for system initialization.

数据来源优先级:
1. data/packs/{lang}/ — 语言感知的数据包文件
2. data/packs/base/   — 语言无关的基础数据
3. 本文件硬编码兜底    — 最后防线

All default configurations, roles, permissions, and templates are defined here.
This is the single source of truth for initial system state.
"""
from __future__ import annotations

import logging
import os as _os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 系统版本
# ═══════════════════════════════════════════════════════════════════
SYSTEM_VERSION = _os.environ.get("COAPIS_VERSION", "0.0.0-dev")
INIT_SCHEMA_VERSION = 2

# ═══════════════════════════════════════════════════════════════════
# 数据包加载器
# ═══════════════════════════════════════════════════════════════════

def _load_from_pack(loader_func, fallback):
    """从数据包加载，失败则用硬编码兜底。"""
    try:
        result = loader_func()
        if result is not None:
            return result
    except Exception as e:
        logger.debug("Data pack load failed, using fallback: %s", e)
    return fallback


# ═══════════════════════════════════════════════════════════════════
# 目录结构
# ═══════════════════════════════════════════════════════════════════

_DEFAULT_DIRECTORIES_FALLBACK: List[str] = [
    "system/.secret", "system/templates", "system/evolution",
    "system/reviews", "system/skill_evolution",
    "workspaces", "agents", "skills", "skill_pool",
    "logs", "audit_log", "media", "local_models", "memory",
    ".backups", "custom_channels", "plugins", "models", "tmp", "files",
]


def _load_directories() -> List[str]:
    from .data_loader import load_directories
    return load_directories() or []


DEFAULT_DIRECTORIES: List[str] = _load_from_pack(_load_directories, _DEFAULT_DIRECTORIES_FALLBACK)

# ═══════════════════════════════════════════════════════════════════
# 默认配置文件
# ═══════════════════════════════════════════════════════════════════

_DEFAULT_CONFIG_FALLBACK: Dict[str, Any] = {
    "channels": {},
    "heartbeat": {"enabled": True, "every": 60, "query": "What should I work on next?"},
    "active_hours": {},
    "auth": {"enabled": False, "secret_key": "CHANGE_ME_TO_RANDOM_STRING"},
    "user_system": {"enabled": False, "default_token_quota": 1_000_000, "token_quota_hard_limit": False},
    "providers": {},
    "workspace": {"default_agent_name": "CoApis", "default_skills": ["guidance"]},
}


def _load_config() -> Dict[str, Any]:
    from .data_loader import load_system_config
    return load_system_config() or {}


DEFAULT_CONFIG: Dict[str, Any] = _load_from_pack(_load_config, _DEFAULT_CONFIG_FALLBACK)
DEFAULT_CONFIG["version"] = SYSTEM_VERSION  # 版本号始终动态注入

# ═══════════════════════════════════════════════════════════════════
# 默认角色定义
# ═══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════
# 权限模块权威清单（兜底用）
# ═══════════════════════════════════════════════════════════════════
# 模块键必须与后端 `require_permission("<module>:<action>")` 逐字一致。
# 后端 has_permission() 对不存在的模块名**直接拒绝且不报错**（默认拒绝），
# 所以键名写错一个字符 = 该模块权限静默失效，前端菜单会跟着一起消失。
# 权威来源：data/packs/base/auth/permissions.json（19 个，kebab-case）
PERMISSION_MODULE_KEYS: tuple = (
    "acp", "admin", "agents", "audit",
    "backups", "channels", "chat", "cron-jobs", "debug", "evolution",
    "heartbeat", "mcp", "models", "profile", "scene",
    "security", "skills", "tag",
    "tools", 
)

_MODULE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "acp": {"name": "ACP配置", "description": "ACP配置"},
    "admin": {"name": "管理面板", "description": "管理面板", "adminOnly": True},
    "agents": {"name": "智能体管理", "description": "智能体管理"},
    "audit": {"name": "审计日志", "description": "审计日志", "adminOnly": True},
    "backups": {"name": "备份管理", "description": "备份管理"},
    "channels": {"name": "通道管理", "description": "通道管理"},
    "chat": {"name": "聊天", "description": "聊天"},
    "cron-jobs": {"name": "定时任务", "description": "定时任务"},
    "debug": {"name": "调试", "description": "调试", "adminOnly": True},
    "evolution": {"name": "进化系统", "description": "进化系统"},
    "heartbeat": {"name": "心跳", "description": "心跳"},
    "mcp": {"name": "MCP", "description": "MCP"},
    "models": {"name": "模型管理", "description": "模型管理"},
    "profile": {"name": "个人资料", "description": "个人资料"},
    "scene": {"name": "场景管理", "description": "场景管理"},
    "security": {"name": "安全设置", "description": "安全设置"},
    "skills": {"name": "技能管理", "description": "技能管理"},
    "tag": {"name": "标签管理", "description": "标签管理"},
    "tools": {"name": "工具管理", "description": "工具管理"},
}


def _crud(read: bool = False, create: bool = False,
          update: bool = False, delete: bool = False) -> Dict[str, bool]:
    return {"read": read, "create": create, "update": update, "delete": delete}


_ALL_OPEN = _crud(True, True, True, True)
_READ_ONLY = _crud(True)
_RWU = _crud(True, True, True)
_DENY = _crud()

# 普通用户：逐位照抄 dev 实况权限矩阵（permissions_config.roles.user），
# 保证「出厂默认」与「线上实况」不产生第二套真值。
# 门禁约定：读类路由用 <mod>:read，写类路由用 <mod>:write（= create+update 位）。
# 策略「admin 配置一次，全员可用」→ 技能全员全开；工具/MCP 全员可读可用，
# 配置增删改留给 admin。
_USER_GRANTS: Dict[str, Dict[str, bool]] = {
    "acp": _DENY,
    "admin": _DENY,
    "agents": _ALL_OPEN,
    "audit": _READ_ONLY,
    "backups": _READ_ONLY,
    "channels": _ALL_OPEN,
    "chat": _ALL_OPEN,
    "cron-jobs": _ALL_OPEN,
    "debug": _DENY,
    "evolution": _DENY,
    "heartbeat": _ALL_OPEN,
    "mcp": _READ_ONLY,
    "models": _READ_ONLY,
    "profile": _RWU,
    "scene": _READ_ONLY,
    "security": _READ_ONLY,
    "skills": _ALL_OPEN,
    "tag": _READ_ONLY,
    "tools": _READ_ONLY,
}

# 高级用户：普通用户 + 技能池/智能体配置/备份/模型的写权限
_ADVANCED_GRANTS: Dict[str, Dict[str, bool]] = {
    **_USER_GRANTS,
    "evolution": _READ_ONLY,
    "acp": _READ_ONLY,
    "backups": _RWU,
    "models": _RWU,
}


def _build_role_matrix(grants: Dict[str, Dict[str, bool]], role: str) -> Dict[str, Dict[str, bool]]:
    """按权威模块清单补齐授权矩阵。

    - 未声明的模块 → 默认拒绝（不会漏授权）
    - 声明了清单外的模块 → 记 error 日志（后端会静默拒绝，必须暴露出来）
    """
    unknown = sorted(set(grants) - set(PERMISSION_MODULE_KEYS))
    if unknown:
        logger.error(
            "角色 %s 声明了不存在的权限模块 %s（后端 has_permission 会静默拒绝）",
            role, unknown,
        )
    return {key: grants.get(key, _DENY) for key in PERMISSION_MODULE_KEYS}


_DEFAULT_ROLES_FALLBACK: Dict[str, Dict[str, Any]] = {
    "user": {
        "name": "普通用户",
        "description": "普通用户，可使用基础功能",
        "modules": _build_role_matrix(_USER_GRANTS, "user"),
    },
    "advanced": {
        "name": "高级用户",
        "description": "高级用户，可使用高级功能",
        "modules": _build_role_matrix(_ADVANCED_GRANTS, "advanced"),
    },
    "admin": {
        "name": "管理员",
        "description": "系统管理员，拥有所有权限",
        "modules": {key: _ALL_OPEN for key in PERMISSION_MODULE_KEYS},
    },
}

def _load_roles() -> Dict[str, Dict[str, Any]]:
    from .data_loader import load_roles
    return load_roles("zh") or {}


DEFAULT_ROLES: Dict[str, Dict[str, Any]] = _load_from_pack(_load_roles, _DEFAULT_ROLES_FALLBACK)

# ═══════════════════════════════════════════════════════════════════
# 默认权限配置 (v2.0 格式)
# ═══════════════════════════════════════════════════════════════════

_DEFAULT_PERMISSIONS_FALLBACK: Dict[str, Any] = {
    "version": "2.0",
    "description": "CoApis 权限配置（硬编码兜底，键名与后端 require_permission 对齐）",
    "roles": {role: cfg["modules"] for role, cfg in _DEFAULT_ROLES_FALLBACK.items()},
    "user_overrides": {},
    "modules": dict(_MODULE_DEFINITIONS),
}

def _load_permissions() -> Dict[str, Any]:
    from .data_loader import load_permissions
    return load_permissions() or {}


DEFAULT_PERMISSIONS: Dict[str, Any] = _load_from_pack(_load_permissions, _DEFAULT_PERMISSIONS_FALLBACK)

# ═══════════════════════════════════════════════════════════════════
# 默认管理员用户
# ═══════════════════════════════════════════════════════════════════

_DEFAULT_ADMIN_FALLBACK: Dict[str, Any] = {
    "username": "admin",
    "display_name": "管理员",
    "password": "admin123",
    "role": "admin",
    "is_active": True,
}


def _load_admin() -> Dict[str, Any]:
    from .data_loader import load_admin_user
    return load_admin_user() or {}


DEFAULT_ADMIN_USER: Dict[str, Any] = _load_from_pack(_load_admin, _DEFAULT_ADMIN_FALLBACK)

# ═══════════════════════════════════════════════════════════════════
# 默认用户工作区模板
# ═══════════════════════════════════════════════════════════════════
DEFAULT_WORKSPACE_TEMPLATE: Dict[str, Any] = {
    "chats.json": {"version": 1, "chats": []},
}

DEFAULT_WORKSPACE_FILES: List[str] = ["AGENTS.md", "SOUL.md", "PROFILE.md", "HEARTBEAT.md"]

# ═══════════════════════════════════════════════════════════════════
# 环境变量默认值
# ═══════════════════════════════════════════════════════════════════

_DEFAULT_ENV_VARS_FALLBACK: Dict[str, str] = {"COAPIS_PORT": "8000"}


def _load_env_vars() -> Dict[str, str]:
    from .data_loader import load_pack_json
    return load_pack_json("system/env_vars.json") or {}


DEFAULT_ENV_VARS: Dict[str, str] = _load_from_pack(_load_env_vars, _DEFAULT_ENV_VARS_FALLBACK)
