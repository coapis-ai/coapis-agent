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

"""PermissionManager v2.0 — CRUD Matrix permission system.

Loads permissions from config/permissions.json, supports hot-reload.
Provides role-based access control with per-module CRUD matrices.

Data model:
  roles.{role}.modules = { "chat": {"read":true,"create":true,"update":false,"delete":false}, ... }
  user_overrides.{username} = { "skills": {"create": true} }
  modules.{key} = { "name":"聊天", "icon":"💬", "operations":["read","create","update","delete"] }

Usage:
    from app.permissions import PermissionManager
    
    PermissionManager.initialize(config_path)
    if PermissionManager.has_permission("testuser", "chat:send"):
        pass
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Action → CRUD mapping ────────────────────────────────────────────────
# Legacy permission strings ("chat:send") map to CRUD booleans.
_ACTION_TO_CRUD: Dict[str, List[str]] = {
    "read":              ["read"],
    "send":              ["create", "update"],
    "history":           ["create", "update"],
    "configure":         ["create", "update"],
    "create":            ["create"],
    "write":             ["create", "update"],
    "update":            ["update"],
    "delete":            ["delete"],
    "execute":           ["create", "update", "delete"],
}


class PermissionManager:
    """Config-driven permission manager with CRUD matrix support."""

    _instance: Optional["PermissionManager"] = None
    _config: Dict[str, Any] = {}
    _config_path: Optional[Path] = None
    _last_modified: float = 0

    # ── Singleton ─────────────────────────────────────────────────────

    @classmethod
    def initialize(cls, config_path: str | Path) -> "PermissionManager":
        if cls._instance is not None:
            logger.warning("PermissionManager already initialized, reloading config")
        cls._config_path = Path(config_path)
        cls._instance = cls()
        cls._instance._load_config()
        logger.info(f"PermissionManager initialized from {config_path}")
        return cls._instance

    @classmethod
    def get_instance(cls) -> "PermissionManager":
        if cls._instance is None:
            raise RuntimeError("PermissionManager not initialized. Call initialize() first.")
        return cls._instance

    # ── Config loading ────────────────────────────────────────────────

    def _load_config(self) -> None:
        if self._config_path is None:
            logger.error("PermissionManager: config_path not set")
            return
        try:
            stat = self._config_path.stat()
            if stat.st_mtime <= self._last_modified:
                return
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            migrated = self._maybe_migrate_v1()
            if migrated:
                self.save_config()
                logger.info("PermissionManager: migrated v1 → v2.0 CRUD matrix")
            self._last_modified = stat.st_mtime
            logger.info(f"PermissionManager: config reloaded from {self._config_path}")
        except FileNotFoundError:
            logger.warning(f"PermissionManager: config file not found {self._config_path}, using default")
            self._config = self._get_default_config()
        except json.JSONDecodeError as e:
            logger.error(f"PermissionManager: invalid JSON: {e}")
            self._config = self._get_default_config()

    def _maybe_migrate_v1(self) -> bool:
        """Auto-migrate v1 string-list format to v2.0 CRUD matrix."""
        version = self._config.get("version", "")
        if version.startswith("2"):
            return False
        roles = self._config.get("roles", {})
        migrated = False
        for role_name, role_data in roles.items():
            if role_name == "admin":
                continue
            modules_list = role_data.get("modules", [])
            permissions_list = role_data.get("permissions", [])
            if not isinstance(modules_list, list):
                continue
            perm_set = set(permissions_list)
            matrix: Dict[str, Dict[str, bool]] = {}
            for mod in modules_list:
                has_read = f"{mod}:read" in perm_set or f"{mod}:*" in perm_set or "*" in perm_set
                has_write = f"{mod}:write" in perm_set or f"{mod}:create" in perm_set or f"{mod}:*" in perm_set or "*" in perm_set
                for old in (f"{mod}:send", f"{mod}:history", f"{mod}:configure"):
                    if old in perm_set:
                        has_write = True
                has_delete = f"{mod}:delete" in perm_set or f"{mod}:*" in perm_set or "*" in perm_set
                has_execute = f"{mod}:execute" in perm_set or f"{mod}:*" in perm_set or "*" in perm_set
                matrix[mod] = {"read": has_read, "create": has_write, "update": has_write or has_execute, "delete": has_delete}
            role_data["modules"] = matrix
            role_data.pop("permissions", None)
            migrated = True
        if migrated:
            self._config["version"] = "2.0"
            self._config.setdefault("user_overrides", {})
            self._config.setdefault("modules", {})
        return migrated

    def _get_default_config(self) -> Dict[str, Any]:
        return {
            "version": "2.0",
            "roles": {
                "user": {
                    "name": "用户",
                    "modules": {
                        "chat":    {"read": True, "create": True, "update": True, "delete": False},
                        "myspace": {"read": True, "create": True, "update": True, "delete": True},
                        "skills":  {"read": True, "create": False, "update": False, "delete": False},
                    },
                },
                "admin": {"name": "管理员", "modules": "*"},
            },
            "user_overrides": {},
            "modules": {},
        }

    # ── CRUD matrix helpers ───────────────────────────────────────────

    def _get_user_matrix(self, username: str, role: str) -> Dict[str, Dict[str, bool]]:
        """Effective CRUD matrix = role matrix + user overrides."""
        roles = self._config.get("roles", {})
        role_config = roles.get(role, {})
        raw = role_config.get("modules", {})
        if isinstance(raw, str) and raw == "*":
            return {"*": True}
        if not isinstance(raw, dict):
            return {}
        matrix: Dict[str, Dict[str, bool]] = {}
        for mod, crud in raw.items():
            if isinstance(crud, dict):
                matrix[mod] = dict(crud)
        overrides = self._config.get("user_overrides", {}).get(username, {})
        for mod, crud in overrides.items():
            if isinstance(crud, dict):
                if mod in matrix:
                    matrix[mod].update(crud)
                else:
                    matrix[mod] = dict(crud)
        return matrix

    def _expand_matrix_to_permissions(self, module: str, crud: Dict[str, bool]) -> List[str]:
        """Expand CRUD matrix to legacy permission strings for backward compat."""
        perms: List[str] = []
        if crud.get("read"):
            perms.append(f"{module}:read")
        if crud.get("create") or crud.get("update"):
            perms.extend([f"{module}:write", f"{module}:send", f"{module}:history", f"{module}:configure"])
        if crud.get("delete"):
            perms.append(f"{module}:delete")
        if crud.get("create") or crud.get("update") or crud.get("delete"):
            perms.append(f"{module}:execute")
        return perms

    # ── Core API ──────────────────────────────────────────────────────

    def has_permission(self, username: str, permission: str, role: str = "user") -> bool:
        """Check if user has a specific permission string."""
        if role == "admin":
            return True
        if permission == "*":
            return True
        if ":" not in permission:
            return False
        module, action = permission.split(":", 1)
        matrix = self._get_user_matrix(username, role)
        if matrix.get("*"):
            return True
        crud = matrix.get(module, {})
        if not crud:
            return False
        crud_keys = _ACTION_TO_CRUD.get(action, [])
        if not crud_keys:
            return False
        return any(crud.get(k, False) for k in crud_keys)

    def get_allowed_modules(self, role: str = "user") -> List[str]:
        """Get modules where any CRUD bit is true AND not adminOnly (unless admin)."""
        if role == "admin":
            return ["all"]
        roles = self._config.get("roles", {})
        role_config = roles.get(role, {})
        raw = role_config.get("modules", {})
        if isinstance(raw, str) and raw == "*":
            return ["all"]
        if not isinstance(raw, dict):
            return []
        all_modules = self._config.get("modules", {})
        allowed = []
        for mod, crud in raw.items():
            if not isinstance(crud, dict) or not any(crud.values()):
                continue
            # Filter out adminOnly modules for non-admin roles
            mod_def = all_modules.get(mod, {})
            if mod_def.get("adminOnly", False):
                continue
            allowed.append(mod)
        return allowed

    def get_user_effective_permissions(self, username: str, role: str = "user") -> Dict[str, Any]:
        """Full effective permission info for a user."""
        if role == "admin":
            return {"modules": "*", "permissions": ["*"], "role": "admin", "overrides": {}}
        matrix = self._get_user_matrix(username, role)
        overrides = self._config.get("user_overrides", {}).get(username, {})
        all_perms: List[str] = []
        for mod, crud in matrix.items():
            if isinstance(crud, dict):
                all_perms.extend(self._expand_matrix_to_permissions(mod, crud))
        return {"modules": matrix, "permissions": all_perms, "role": role, "overrides": overrides}

    def get_role_config(self, role: str = "user") -> Dict[str, Any]:
        return self._config.get("roles", {}).get(role, {})

    def get_module_operations(self, module: str) -> List[str]:
        """Get available operations for a module from modules definition."""
        mod_def = self._config.get("modules", {}).get(module, {})
        return mod_def.get("operations", ["read", "create", "update", "delete"])

    def get_all_roles(self) -> List[str]:
        return list(self._config.get("roles", {}).keys())

    def get_menu_config(self, role: str = "user", username: str = "") -> Dict[str, Any]:
        """Menu-visible module configs with adminOnly markers.
        
        When username is provided, user-level permission overrides are merged
        with the role defaults so that per-user grants/revocations are reflected.
        """
        all_modules = self._config.get("modules", {})
        if role == "admin":
            allowed_keys = list(all_modules.keys())
        else:
            if username:
                matrix = self._get_user_matrix(username, role)
                allowed_keys = [
                    mod for mod, crud in matrix.items()
                    if isinstance(crud, dict) and any(crud.values())
                ]
            else:
                allowed_keys = self.get_allowed_modules(role)
        modules_detail: Dict[str, Any] = {}
        for key in allowed_keys:
            if key in all_modules:
                mod = all_modules[key].copy()
                mod["adminOnly"] = all_modules[key].get("adminOnly", False)
                modules_detail[key] = mod
        all_admin_only = [k for k in all_modules if all_modules[k].get("adminOnly", False)]
        admin_only_keys = all_admin_only if role == "admin" else [k for k in all_admin_only if k not in allowed_keys]
        return {"modules": allowed_keys, "adminOnly": admin_only_keys, "modules_detail": modules_detail, "role": role}

    # ── Config persistence ────────────────────────────────────────────

    def get_config(self) -> Dict[str, Any]:
        return self._config.copy()

    def save_config(self) -> bool:
        if self._config_path is None:
            logger.error("PermissionManager: cannot save, config_path not set")
            return False
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            self._last_modified = self._config_path.stat().st_mtime
            logger.info(f"PermissionManager: config saved to {self._config_path}")
            return True
        except OSError as e:
            logger.error(f"PermissionManager: failed to save: {e}")
            return False

    def reload(self) -> None:
        self._last_modified = 0
        self._load_config()

    # ── Role management ───────────────────────────────────────────────

    def update_role_config(self, role: str, modules: Dict[str, Dict[str, bool]]) -> bool:
        """Update role with CRUD matrix format."""
        if "roles" not in self._config:
            self._config["roles"] = {}
        existing = self._config["roles"].get(role, {})
        self._config["roles"][role] = {
            "name": existing.get("name", role),
            "description": existing.get("description", ""),
            "modules": modules,
        }
        logger.info(f"PermissionManager: updated role '{role}' with CRUD matrix")
        return self.save_config()

    def update_role_config_legacy(self, role: str, modules_list: List[str], permissions_list: List[str]) -> bool:
        """Update role with legacy format (for backward compat during migration)."""
        if "roles" not in self._config:
            self._config["roles"] = {}
        self._config["roles"][role] = {
            "modules": modules_list,
            "permissions": permissions_list,
        }
        return self.save_config()

    # ── User overrides ────────────────────────────────────────────────

    def update_user_overrides(self, username: str, overrides: Dict[str, Dict[str, bool]]) -> bool:
        """Update per-user permission overrides."""
        if "user_overrides" not in self._config:
            self._config["user_overrides"] = {}
        self._config["user_overrides"][username] = overrides
        logger.info(f"PermissionManager: updated overrides for '{username}'")
        return self.save_config()

    def get_user_overrides(self, username: str) -> Dict[str, Dict[str, bool]]:
        return self._config.get("user_overrides", {}).get(username, {})

    def delete_user_overrides(self, username: str) -> bool:
        overrides = self._config.get("user_overrides", {})
        if username in overrides:
            del overrides[username]
            return self.save_config()
        return True

    # ── Shell permissions ─────────────────────────────────────────────

    def update_shell_permissions(self, role: str, whitelist: List[str], blacklist: List[str], dangerous_patterns: List[str]) -> bool:
        if "shell_permissions" not in self._config:
            self._config["shell_permissions"] = {"roles": {}}
        if "roles" not in self._config["shell_permissions"]:
            self._config["shell_permissions"]["roles"] = {}
        self._config["shell_permissions"]["roles"][role] = {
            "whitelist": whitelist,
            "blacklist": blacklist,
            "dangerous_patterns": dangerous_patterns,
        }
        logger.info(f"PermissionManager: updated shell permissions for role '{role}'")
        return self.save_config()

    def get_shell_whitelist(self, role: str = "user") -> List[str]:
        return self._config.get("shell_permissions", {}).get("roles", {}).get(role, {}).get("whitelist", [])

    def get_shell_blacklist(self) -> List[str]:
        return self._config.get("shell_permissions", {}).get("blacklist", [])

    def get_dangerous_patterns(self) -> List[str]:
        return self._config.get("shell_permissions", {}).get("dangerous_patterns", [])

    def get_command_levels(self) -> Dict[str, List[str]]:
        """Get command level classification from config.

        Returns:
            Dict mapping level name (L0-L5) to list of base commands.
            Returns empty dict if not configured (caller should use fallback).
        """
        return self._config.get("shell_permissions", {}).get("command_levels", {})

    def update_command_levels(self, command_levels: Dict[str, List[str]]) -> bool:
        """Update command level classification in config.

        Args:
            command_levels: Dict mapping level name (L0-L5) to list of base commands.

        Returns:
            True if saved successfully.
        """
        if "shell_permissions" not in self._config:
            self._config["shell_permissions"] = {}
        self._config["shell_permissions"]["command_levels"] = command_levels
        logger.info("PermissionManager: updated command levels")
        return self.save_config()

    def is_shell_command_allowed(self, role: str, command: str) -> bool:
        import fnmatch, re
        cmd = command.strip()
        if not cmd:
            return False

        # ── 1. Blacklist check ──
        for p in self.get_shell_blacklist():
            if fnmatch.fnmatch(cmd, p):
                return False

        # ── 2. Dangerous patterns check ──
        for p in self.get_dangerous_patterns():
            try:
                if re.compile(p).search(cmd):
                    return False
            except re.error:
                pass

        # ── 3. Command levels check (L0-L5, takes priority over whitelist) ──
        command_levels = self.get_command_levels()
        if command_levels:
            base = cmd.split()[0]
            for level, commands in command_levels.items():
                for level_cmd in commands:
                    if level_cmd == base or fnmatch.fnmatch(base, level_cmd):
                        if level == "L5":
                            return False  # L5: permanently denied
                        return True  # L0-L4: allowed (L3/L4 approval handled upstream)
            # Command not found in any level — fall through to whitelist

        # ── 4. Whitelist fallback (legacy, used when command_levels not configured) ──
        whitelist = self.get_shell_whitelist(role)
        if "*" in whitelist:
            return True
        base = cmd.split()[0]
        for allowed in whitelist:
            parts = allowed.split()
            if not fnmatch.fnmatch(base, parts[0]):
                continue
            if len(parts) > 1:
                if fnmatch.fnmatch(cmd, " ".join(parts)):
                    return True
                if fnmatch.fnmatch(cmd, f"{parts[0]} *"):
                    args = cmd.split()[1:]
                    if args and not args[0].startswith("-"):
                        return True
                continue
            return True
        return False
