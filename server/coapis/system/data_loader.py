# -*- coding: utf-8 -*-
"""Data Pack Loader — 从 data/packs/ 按语言加载初始化数据.

加载优先级:
1. {WORKING_DIR}/data/packs/{lang}/{path}     ← 用户自定义（最高优先级）
2. {PACKAGE_DIR}/data/packs/{lang}/{path}      ← 内置语言包
3. {PACKAGE_DIR}/data/packs/zh/{path}           ← 中文回退
4. {PACKAGE_DIR}/data/packs/base/{path}         ← 基础数据
5. 代码硬编码兜底                                ← 最后防线

用法:
    from coapis.system.data_loader import load_pack_json, load_pack_template

    # 加载系统配置
    config = load_pack_json("system/config.json")

    # 加载角色定义（带语言文本）
    roles = load_roles("zh")

    # 加载模板文件
    soul = load_pack_template("SOUL.md", level="user", language="zh")
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# 内置数据包根目录（跟随代码包）
_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "data" / "packs"


def _get_working_dir() -> Path:
    """获取运行时工作目录."""
    from ..constant import WORKING_DIR
    return Path(WORKING_DIR)


def _candidate_paths(relative_path: str, language: str = "zh") -> List[Path]:
    """按优先级生成候选路径列表."""
    working_dir = _get_working_dir()
    return [
        working_dir / "data" / "packs" / language / relative_path,   # 用户自定义语言包
        _PACKAGE_DIR / language / relative_path,                      # 内置语言包
        _PACKAGE_DIR / "zh" / relative_path,                          # 中文回退
        _PACKAGE_DIR / "base" / relative_path,                        # 基础数据
    ]


def load_pack_json(relative_path: str, language: str = "zh") -> Optional[Dict[str, Any]]:
    """按语言优先级加载 JSON 数据包文件.

    Args:
        relative_path: 相对于 packs/ 的路径，如 "system/config.json"
        language: 语言代码，默认 "zh"

    Returns:
        解析后的 dict/list，找不到返回 None
    """
    for path in _candidate_paths(relative_path, language):
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load %s: %s", path, e)
                continue
    return None


def load_pack_text(relative_path: str, language: str = "zh") -> Optional[str]:
    """按语言优先级加载文本文件（Markdown 等）.

    Args:
        relative_path: 相对于 packs/{lang}/ 的路径，如 "templates/user_level/SOUL.md"
        language: 语言代码，默认 "zh"

    Returns:
        文件内容字符串，找不到返回 None
    """
    for path in _candidate_paths(relative_path, language):
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning("Failed to read %s: %s", path, e)
                continue
    return None


def load_pack_template(filename: str, level: str = "user", language: str = "zh") -> Optional[str]:
    """加载模板文件.

    Args:
        filename: 模板文件名，如 "SOUL.md"
        level: 模板层级 "user" 或 "agent"
        language: 语言代码

    Returns:
        模板内容，找不到返回 None
    """
    relative_path = f"templates/{level}_level/{filename}"
    return load_pack_text(relative_path, language)


def load_roles(language: str = "zh") -> Dict[str, Any]:
    """加载角色定义（合并 base 结构 + 语言文本覆盖）.

    Returns:
        完整的角色定义字典，如 {"user": {"name": "用户", ...}, "admin": {...}}
    """
    # 基础结构（modules/level/is_default）
    base_roles = load_pack_json("auth/roles.json") or {}
    # 语言文本覆盖（name/description）
    lang_roles = load_pack_json("roles.json", language=language) or {}

    merged = {}
    for role_id, base_def in base_roles.items():
        role = base_def.copy()
        if role_id in lang_roles:
            role.update(lang_roles[role_id])
        merged[role_id] = role
    return merged


def load_permissions(language: str = "zh") -> Dict[str, Any]:
    """加载权限配置（合并 base 结构 + 语言模块名）.

    Returns:
        完整的 permissions 字典
    """
    base = load_pack_json("auth/permissions.json") or {}
    lang_modules = load_pack_json("permissions_modules.json", language=language) or {}

    # 合并模块名称
    modules = base.get("modules", {})
    for mod_id, lang_def in lang_modules.items():
        if mod_id in modules:
            modules[mod_id].update(lang_def)

    # 合并角色
    base["roles"] = load_roles(language)
    base["modules"] = modules
    return base


def load_directories() -> List[str]:
    """加载目录结构列表."""
    return load_pack_json("system/directories.json") or []


def load_system_config() -> Dict[str, Any]:
    """加载系统默认配置."""
    return load_pack_json("system/config.json") or {}


def load_admin_user() -> Dict[str, Any]:
    """加载默认管理员用户定义."""
    return load_pack_json("auth/admin.json") or {"username": "admin", "password": "admin123"}


def load_workspace_defaults() -> List[Dict[str, Any]]:
    """加载 workspace 默认 JSON 文件定义."""
    return load_pack_json("workspace/json_defaults.json") or []


def load_workspace_dirs() -> List[str]:
    """加载用户 workspace 默认子目录列表."""
    return load_pack_json("workspace/file_list.json") or []


def load_memory_init(language: str = "zh", username: str = "") -> str:
    """加载 MEMORY.md 初始内容.

    Args:
        language: 语言代码
        username: 用户名（用于替换模板中的 {username} 占位符）

    Returns:
        MEMORY.md 初始内容
    """
    content = load_pack_text("workspace/memory_init.md", language=language)
    if content and username:
        content = content.replace("{username}", username)
    if not content:
        content = f"# {username}'s Memory\n\n> Auto-created during initialization.\n" if username else "# Memory\n"
    return content
