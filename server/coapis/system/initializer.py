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

"""System Initializer — 统一的系统初始化入口.

负责:
1. 创建目录结构
2. 生成默认配置文件
3. 初始化默认数据（用户、角色、权限）
4. 版本迁移
5. 确保系统可正常启动
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .defaults import (
    DEFAULT_ADMIN_USER,
    DEFAULT_CONFIG,
    DEFAULT_DIRECTORIES,
    DEFAULT_PERMISSIONS,
    DEFAULT_ROLES,
    DEFAULT_WORKSPACE_FILES,
    DEFAULT_WORKSPACE_TEMPLATE,
    INIT_SCHEMA_VERSION,
    SYSTEM_VERSION,
)

logger = logging.getLogger(__name__)


class SystemInitializer:
    """系统初始化器 — 单例模式."""

    _instance: Optional["SystemInitializer"] = None

    def __new__(cls) -> "SystemInitializer":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        from ..constant import WORKING_DIR
        self.working_dir = Path(WORKING_DIR)
        self.system_dir = self.working_dir / "system"
        self.workspaces_dir = self.working_dir / "workspaces"
        self._initialized = True

    # ═══════════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════════

    def initialize(self, force: bool = False) -> Dict[str, Any]:
        """执行完整的系统初始化.

        Args:
            force: 是否强制重新初始化（覆盖现有配置）

        Returns:
            初始化结果摘要
        """
        result = {
            "success": True,
            "version": SYSTEM_VERSION,
            "schema_version": INIT_SCHEMA_VERSION,
            "actions": [],
            "warnings": [],
        }

        try:
            # 1. 创建目录结构
            self._create_directories(result)

            # 2. 初始化配置文件
            self._init_config_files(force, result)

            # 3. 初始化权限系统
            self._init_permissions(force, result)

            # 4. 初始化用户系统
            self._init_users(force, result)

            # 5. 初始化 Token 统计文件
            self._init_token_usage(result)

            # 6. 初始化审计日志文件
            self._init_audit_logs(result)

            # 7. 版本迁移检查
            self._check_version_migration(result)

            logger.info("System initialization completed: %d actions", len(result["actions"]))

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            logger.error("System initialization failed: %s", e)

        return result

    def check_initialization_status(self) -> Dict[str, Any]:
        """检查系统初始化状态."""
        status = {
            "initialized": False,
            "version": None,
            "schema_version": None,
            "missing_files": [],
            "missing_dirs": [],
        }

        # 检查核心文件
        core_files = [
            self.system_dir / "config.json",
            self.system_dir / "permissions.json",
            self.system_dir / "users.json",
        ]
        for f in core_files:
            if not f.exists():
                status["missing_files"].append(str(f.relative_to(self.working_dir)))

        # 检查核心目录
        core_dirs = [
            self.system_dir,
            self.workspaces_dir,
            self.working_dir / "agents",
            self.working_dir / "skills",
        ]
        for d in core_dirs:
            if not d.exists():
                status["missing_dirs"].append(str(d.relative_to(self.working_dir)))

        # 检查版本
        config_file = self.system_dir / "config.json"
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                status["version"] = config.get("version")
                status["initialized"] = True
            except (json.JSONDecodeError, OSError):
                pass

        return status

    # ═══════════════════════════════════════════════════════════════
    # 目录创建
    # ═══════════════════════════════════════════════════════════════

    def _create_directories(self, result: Dict[str, Any]) -> None:
        """创建所有必要的目录结构."""
        for dir_name in DEFAULT_DIRECTORIES:
            dir_path = self.working_dir / dir_name
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                result["actions"].append(f"created_dir:{dir_name}")

    # ═══════════════════════════════════════════════════════════════
    # 配置文件初始化
    # ═══════════════════════════════════════════════════════════════

    def _init_config_files(self, force: bool, result: Dict[str, Any]) -> None:
        """初始化配置文件."""
        config_file = self.system_dir / "config.json"

        if config_file.exists() and not force:
            # 检查是否需要合并新字段
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)

                # 合并缺失的顶层字段
                merged = self._merge_config(existing, DEFAULT_CONFIG)
                if merged != existing:
                    self._save_json(config_file, merged)
                    result["actions"].append("merged_config:config.json")
            except (json.JSONDecodeError, OSError) as e:
                result["warnings"].append(f"config.json merge failed: {e}")
            return

        # 创建新配置
        self._save_json(config_file, DEFAULT_CONFIG)
        result["actions"].append("created_config:config.json")

        # 生成随机 secret_key
        if DEFAULT_CONFIG["auth"]["secret_key"] == "CHANGE_ME_TO_RANDOM_STRING":
            config = DEFAULT_CONFIG.copy()
            config["auth"] = config["auth"].copy()
            config["auth"]["secret_key"] = secrets.token_hex(32)
            self._save_json(config_file, config)
            result["actions"].append("generated_secret_key")

    def _merge_config(self, existing: Dict, defaults: Dict) -> Dict:
        """合并配置，保留现有值，添加缺失字段."""
        result = existing.copy()
        for key, value in defaults.items():
            if key not in result:
                result[key] = value
            elif isinstance(value, dict) and isinstance(result[key], dict):
                result[key] = self._merge_config(result[key], value)
        return result

    # ═══════════════════════════════════════════════════════════════
    # 权限系统初始化
    # ═══════════════════════════════════════════════════════════════

    def _init_permissions(self, force: bool, result: Dict[str, Any]) -> None:
        """初始化权限配置."""
        perm_file = self.system_dir / "permissions.json"

        if perm_file.exists() and not force:
            # 检查版本
            try:
                with open(perm_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)

                if existing.get("version") != "2.0":
                    # 需要升级到 v2.0
                    upgraded = self._upgrade_permissions_v2(existing)
                    self._save_json(perm_file, upgraded)
                    result["actions"].append("upgraded_permissions:v2.0")
            except (json.JSONDecodeError, OSError) as e:
                result["warnings"].append(f"permissions.json check failed: {e}")
            return

        # 创建新权限配置
        self._save_json(perm_file, DEFAULT_PERMISSIONS)
        result["actions"].append("created_config:permissions.json")

    def _upgrade_permissions_v2(self, old_perms: Dict) -> Dict:
        """将旧版权限配置升级到 v2.0 格式."""
        new_perms = DEFAULT_PERMISSIONS.copy()

        # 尝试保留旧的 user_overrides
        if "user_overrides" in old_perms:
            new_perms["user_overrides"] = old_perms["user_overrides"]

        return new_perms

    # ═══════════════════════════════════════════════════════════════
    # 用户系统初始化
    # ═══════════════════════════════════════════════════════════════

    def _init_users(self, force: bool, result: Dict[str, Any]) -> None:
        """初始化用户数据."""
        users_file = self.system_dir / "users.json"

        if users_file.exists() and not force:
            # 检查是否有管理员用户
            try:
                with open(users_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                users = data.get("users", {})
                has_admin = any(
                    u.get("role") == "admin" for u in users.values()
                )

                if not has_admin:
                    # 添加默认管理员
                    admin_data = self._create_user_data(DEFAULT_ADMIN_USER)
                    users[admin_data["username"]] = admin_data
                    data["users"] = users
                    self._save_json(users_file, data)
                    result["actions"].append("added_admin_user")
            except (json.JSONDecodeError, OSError) as e:
                result["warnings"].append(f"users.json check failed: {e}")
            return

        # 创建新用户文件
        admin_data = self._create_user_data(DEFAULT_ADMIN_USER)
        users_data = {
            "users": {admin_data["username"]: admin_data},
            "next_id": 2,
        }
        self._save_json(users_file, users_data)
        result["actions"].append("created_config:users.json")

    def _create_user_data(self, user_def: Dict[str, Any]) -> Dict[str, Any]:
        """创建用户数据（包含密码哈希）."""
        username = user_def.get("username", "user")
        password = user_def.get("password", "admin123")
        password_hash = self._hash_password(password)

        return {
            "username": username,
            "display_name": user_def.get("display_name", username),
            "password_hash": password_hash,
            "salt": "$2b$",
            "role": user_def.get("role", "user"),
            "is_active": user_def.get("is_active", True),
            "created_at": time.time(),
            "last_login": None,
        }

    def _hash_password(self, password: str) -> str:
        """生成密码哈希."""
        try:
            import bcrypt
            return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        except ImportError:
            # 回退到 SHA256（不推荐，但保证可用）
            return hashlib.sha256(password.encode()).hexdigest()

    # ═══════════════════════════════════════════════════════════════
    # Token 统计初始化
    # ═══════════════════════════════════════════════════════════════

    def _init_token_usage(self, result: Dict[str, Any]) -> None:
        """初始化 Token 统计文件."""
        token_file = self.system_dir / "token_usage.json"

        if not token_file.exists():
            self._save_json(token_file, {"version": 1, "daily": {}, "total": 0})
            result["actions"].append("created_config:token_usage.json")

        # 明细文件（JSON 模式）
        details_file = self.system_dir / "token_usage_details.json"
        if not details_file.exists():
            self._save_json(details_file, {"records": []})
            result["actions"].append("created_config:token_usage_details.json")

    # ═══════════════════════════════════════════════════════════════
    # 审计日志初始化
    # ═══════════════════════════════════════════════════════════════

    def _init_audit_logs(self, result: Dict[str, Any]) -> None:
        """初始化审计日志文件."""
        audit_dir = self.working_dir / "audit_log"
        if not audit_dir.exists():
            audit_dir.mkdir(parents=True, exist_ok=True)
            result["actions"].append("created_dir:audit_log")

        # JSON 模式的审计日志
        audit_file = self.system_dir / "audit_logs.json"
        if not audit_file.exists():
            self._save_json(audit_file, [])
            result["actions"].append("created_config:audit_logs.json")

    # ═══════════════════════════════════════════════════════════════
    # 版本迁移
    # ═══════════════════════════════════════════════════════════════

    def _check_version_migration(self, result: Dict[str, Any]) -> None:
        """检查并执行版本迁移."""
        config_file = self.system_dir / "config.json"
        if not config_file.exists():
            return

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)

            current_version = config.get("version", "0.0.0")
            if current_version != SYSTEM_VERSION:
                result["actions"].append(
                    f"version_upgrade:{current_version}->{SYSTEM_VERSION}"
                )

                # 更新版本号
                config["version"] = SYSTEM_VERSION
                self._save_json(config_file, config)
        except (json.JSONDecodeError, OSError):
            pass

    # ═══════════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════════

    def _save_json(self, file_path: Path, data: Any) -> None:
        """原子性保存 JSON 文件."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = file_path.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, file_path)

    def _load_json(self, file_path: Path) -> Any:
        """加载 JSON 文件."""
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════

def initialize_system(force: bool = False) -> Dict[str, Any]:
    """初始化系统（便捷入口）."""
    return SystemInitializer().initialize(force=force)


def check_system_status() -> Dict[str, Any]:
    """检查系统状态（便捷入口）."""
    return SystemInitializer().check_initialization_status()
