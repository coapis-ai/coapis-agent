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

"""System Initializer — 统一的系统初始化入口.

两种安装方式共享同一个初始化逻辑：

- **Docker 首次启动**：entrypoint.sh → `coapis init --defaults` → `initialize()`
- **非 Docker 安装**：用户手动 `coapis init` → `initialize()`
- **日常重启**：`_app.py` lifespan → `ensure_ready()`（增量检查，< 100ms）

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
    INIT_SCHEMA_VERSION,
    SYSTEM_VERSION,
)

logger = logging.getLogger(__name__)


class SystemInitializer:
    """系统初始化器 — 单例模式.

    使用方式:
        # 首次初始化（Docker 或 coapis init）
        result = SystemInitializer().initialize()

        # 日常重启增量检查（_app.py lifespan）
        SystemInitializer().ensure_ready()
    """

    _instance: Optional["SystemInitializer"] = None

    def __new__(cls) -> "SystemInitializer":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._inited = False
        return cls._instance

    def __init__(self) -> None:
        if self._inited:
            return
        from ..constant import WORKING_DIR
        self.working_dir = Path(WORKING_DIR)
        self.system_dir = self.working_dir / "system"
        self.workspaces_dir = self.working_dir / "workspaces"
        self._inited = True

    # ═══════════════════════════════════════════════════════════════
    # 公共 API
    # ═══════════════════════════════════════════════════════════════

    def initialize(self, force: bool = False) -> Dict[str, Any]:
        """执行完整的系统初始化（幂等）.

        调用场景:
        - Docker 首次启动：entrypoint.sh → coapis init --defaults → 此方法
        - 非 Docker 安装：coapis init → 此方法

        Args:
            force: 是否强制重新初始化（覆盖现有配置）

        Returns:
            初始化结果摘要 {"success", "version", "actions", "warnings"}
        """
        result: Dict[str, Any] = {
            "success": True,
            "version": SYSTEM_VERSION,
            "schema_version": INIT_SCHEMA_VERSION,
            "actions": [],
            "warnings": [],
        }

        try:
            self._ensure_directories(result)
            self._ensure_config_files(force, result)
            self._ensure_permissions(force, result)
            self._ensure_default_user(force, result)
            self._ensure_token_usage(result)
            self._ensure_audit_logs(result)
            self._run_migrations(result)
            self._write_init_marker(result)

            logger.info(
                "System initialization completed: %d actions, %d warnings",
                len(result["actions"]),
                len(result["warnings"]),
            )
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            logger.error("System initialization failed: %s", e, exc_info=True)

        return result

    def ensure_ready(self) -> bool:
        """增量检查：确保系统已初始化（用于日常重启，< 100ms）.

        调用场景:
        - _app.py lifespan 启动时调用

        检查逻辑:
        1. .initialized 标记文件不存在 → 运行完整 initialize()
        2. 核心文件缺失 → 运行完整 initialize()
        3. 版本不一致 → 只运行迁移
        4. 一切正常 → 跳过

        Returns:
            True 如果系统已就绪
        """
        marker_file = self.working_dir / ".initialized"
        config_file = self.system_dir / "config.json"

        # 检查 1：标记文件存在且核心文件完整
        if marker_file.exists() and config_file.exists():
            # 检查版本是否需要迁移
            try:
                with open(marker_file, "r", encoding="utf-8") as f:
                    marker = json.load(f)
                marker_version = marker.get("version", "0.0.0")
                if marker_version == SYSTEM_VERSION:
                    # 一切正常，跳过
                    logger.debug("System already initialized (v%s), skipping.", SYSTEM_VERSION)
                    return True

                # 版本不一致，只需运行迁移
                logger.info(
                    "Version changed (%s → %s), running migrations...",
                    marker_version,
                    SYSTEM_VERSION,
                )
                migrate_result: Dict[str, Any] = {
                    "success": True,
                    "actions": [],
                    "warnings": [],
                }
                self._run_migrations(migrate_result)
                self._write_init_marker(migrate_result)
                if migrate_result["actions"]:
                    logger.info("Migrations applied: %s", migrate_result["actions"])
                return True
            except Exception as e:
                logger.warning("Error reading init marker: %s", e)

        # 检查 2：核心文件是否存在（无标记文件或标记读取失败）
        core_files = [
            self.system_dir / "config.json",
            self.system_dir / "permissions.json",
            self.system_dir / "users.json",
        ]
        missing = [str(f.relative_to(self.working_dir)) for f in core_files if not f.exists()]
        if missing:
            logger.warning("Core files missing: %s — running full initialization.", missing)
            result = self.initialize()
            return result["success"]

        # 核心文件都在但没有标记 → 补写标记
        logger.info("Core files present but no .initialized marker — writing marker.")
        self._write_init_marker({"actions": [], "warnings": []})
        return True

    def check_initialization_status(self) -> Dict[str, Any]:
        """检查系统初始化状态（只读，不修改任何文件）."""
        status: Dict[str, Any] = {
            "initialized": False,
            "version": SYSTEM_VERSION,
            "schema_version": INIT_SCHEMA_VERSION,
            "missing_files": [],
            "missing_dirs": [],
        }

        core_files = [
            self.system_dir / "config.json",
            self.system_dir / "permissions.json",
            self.system_dir / "users.json",
        ]
        for f in core_files:
            if not f.exists():
                status["missing_files"].append(str(f.relative_to(self.working_dir)))

        core_dirs = [
            self.system_dir,
            self.workspaces_dir,
            self.working_dir / "agents",
            self.working_dir / "skills",
        ]
        for d in core_dirs:
            if not d.exists():
                status["missing_dirs"].append(str(d.relative_to(self.working_dir)))

        marker_file = self.working_dir / ".initialized"
        if marker_file.exists() and not status["missing_files"]:
            status["initialized"] = True

        return status

    # ═══════════════════════════════════════════════════════════════
    # 1. 目录创建
    # ═══════════════════════════════════════════════════════════════

    def _ensure_directories(self, result: Dict[str, Any]) -> None:
        """创建所有必要的目录结构（幂等）."""
        for dir_name in DEFAULT_DIRECTORIES:
            dir_path = self.working_dir / dir_name
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                result["actions"].append(f"created_dir:{dir_name}")
                logger.debug("Created directory: %s", dir_name)

    # ═══════════════════════════════════════════════════════════════
    # 2. 配置文件
    # ═══════════════════════════════════════════════════════════════

    def _ensure_config_files(self, force: bool, result: Dict[str, Any]) -> None:
        """确保配置文件存在且完整（幂等）."""
        config_file = self.system_dir / "config.json"

        if config_file.exists() and not force:
            # 合并缺失的顶层字段
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                merged = self._merge_dict(existing, DEFAULT_CONFIG)
                if merged != existing:
                    self._save_json(config_file, merged)
                    result["actions"].append("merged_config:config.json")
                    logger.info("Merged missing fields into config.json")
            except (json.JSONDecodeError, OSError) as e:
                result["warnings"].append(f"config.json merge failed: {e}")
            return

        # 创建新配置
        config = DEFAULT_CONFIG.copy()
        # 生成随机 secret_key
        if config.get("auth", {}).get("secret_key") == "CHANGE_ME_TO_RANDOM_STRING":
            config["auth"] = config["auth"].copy()
            config["auth"]["secret_key"] = secrets.token_hex(32)
            result["actions"].append("generated_secret_key")
        self._save_json(config_file, config)
        result["actions"].append("created:config.json")

    # ═══════════════════════════════════════════════════════════════
    # 3. 权限系统
    # ═══════════════════════════════════════════════════════════════

    def _ensure_permissions(self, force: bool, result: Dict[str, Any]) -> None:
        """确保权限配置存在（幂等）."""
        perm_file = self.system_dir / "permissions.json"

        if perm_file.exists() and not force:
            return

        self._save_json(perm_file, DEFAULT_PERMISSIONS)
        result["actions"].append("created:permissions.json")

    # ═══════════════════════════════════════════════════════════════
    # 4. 用户系统
    # ═══════════════════════════════════════════════════════════════

    def _ensure_default_user(self, force: bool, result: Dict[str, Any]) -> None:
        """确保默认管理员用户存在（幂等）."""
        users_file = self.system_dir / "users.json"

        if users_file.exists() and not force:
            # 检查是否有管理员用户
            try:
                with open(users_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                users = data.get("users", {})
                has_admin = any(u.get("role") == "admin" for u in users.values())
                if not has_admin:
                    admin_data = self._build_user_data(DEFAULT_ADMIN_USER)
                    users[admin_data["username"]] = admin_data
                    data["users"] = users
                    self._save_json(users_file, data)
                    result["actions"].append("added_admin_user")
            except (json.JSONDecodeError, OSError) as e:
                result["warnings"].append(f"users.json check failed: {e}")
            return

        # 创建新用户文件
        admin_data = self._build_user_data(DEFAULT_ADMIN_USER)
        users_data = {
            "users": {admin_data["username"]: admin_data},
            "next_id": 2,
        }
        self._save_json(users_file, users_data)
        result["actions"].append("created:users.json")

    def _build_user_data(self, user_def: Dict[str, Any]) -> Dict[str, Any]:
        """构建用户数据（包含密码哈希）."""
        username = user_def.get("username", "user")
        password = user_def.get("password", "admin123")
        try:
            import bcrypt
            password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        except ImportError:
            password_hash = hashlib.sha256(password.encode()).hexdigest()

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

    # ═══════════════════════════════════════════════════════════════
    # 5. Token 统计
    # ═══════════════════════════════════════════════════════════════

    def _ensure_token_usage(self, result: Dict[str, Any]) -> None:
        """确保 Token 统计文件存在（幂等）."""
        token_file = self.system_dir / "token_usage.json"
        if not token_file.exists():
            self._save_json(token_file, {"version": 1, "daily": {}, "total": 0})
            result["actions"].append("created:token_usage.json")

        details_file = self.system_dir / "token_usage_details.json"
        if not details_file.exists():
            self._save_json(details_file, {"records": []})
            result["actions"].append("created:token_usage_details.json")

    # ═══════════════════════════════════════════════════════════════
    # 6. 审计日志
    # ═══════════════════════════════════════════════════════════════

    def _ensure_audit_logs(self, result: Dict[str, Any]) -> None:
        """确保审计日志目录和文件存在（幂等）."""
        # 目录已在 _ensure_directories 中创建，这里只需确保文件
        audit_file = self.system_dir / "audit_logs.json"
        if not audit_file.exists():
            self._save_json(audit_file, [])
            result["actions"].append("created:audit_logs.json")

    # ═══════════════════════════════════════════════════════════════
    # 7. 版本迁移
    # ═══════════════════════════════════════════════════════════════

    def _run_migrations(self, result: Dict[str, Any]) -> None:
        """运行版本迁移（仅在版本升级时执行）."""
        config_file = self.system_dir / "config.json"
        if not config_file.exists():
            return

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        current_version = config.get("version", "0.0.0")
        if current_version == SYSTEM_VERSION:
            return

        logger.info("Migrating config from %s to %s", current_version, SYSTEM_VERSION)

        # 按版本递增执行迁移（在此追加新版本迁移函数）
        # migrations = [
        #     ("0.8.50", self._migrate_to_0_8_50),
        #     ("0.8.55", self._migrate_to_0_8_55),
        # ]
        # for version, fn in migrations:
        #     if _version_lt(current_version, version):
        #         try:
        #             fn(result)
        #             result["actions"].append(f"migration:{version}")
        #         except Exception as e:
        #             result["warnings"].append(f"migration:{version} failed: {e}")

        # 更新 config.json 中的版本号
        config["version"] = SYSTEM_VERSION
        self._save_json(config_file, config)
        result["actions"].append(f"version_upgrade:{current_version}->{SYSTEM_VERSION}")

    # ═══════════════════════════════════════════════════════════════
    # 8. 初始化标记
    # ═══════════════════════════════════════════════════════════════

    def _write_init_marker(self, result: Dict[str, Any]) -> None:
        """写入初始化完成标记文件."""
        marker_file = self.working_dir / ".initialized"
        marker = {
            "initialized_at": time.time(),
            "version": SYSTEM_VERSION,
            "schema_version": INIT_SCHEMA_VERSION,
            "actions_count": len(result.get("actions", [])),
        }
        self._save_json(marker_file, marker)
        logger.debug("Wrote init marker: %s", marker_file)

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

    @staticmethod
    def _merge_dict(existing: Dict, defaults: Dict) -> Dict:
        """递归合并字典，保留 existing 的值，补充 defaults 中缺失的 key."""
        result = existing.copy()
        for key, value in defaults.items():
            if key not in result:
                result[key] = value
            elif isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = SystemInitializer._merge_dict(result[key], value)
        return result


# ═══════════════════════════════════════════════════════════════════
# 便捷函数（供外部 import）
# ═══════════════════════════════════════════════════════════════════

def initialize_system(force: bool = False) -> Dict[str, Any]:
    """初始化系统（便捷入口）."""
    return SystemInitializer().initialize(force=force)


def check_system_status() -> Dict[str, Any]:
    """检查系统状态（便捷入口）."""
    return SystemInitializer().check_initialization_status()
