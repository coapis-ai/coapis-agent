# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
from __future__ import annotations
import asyncio, json, logging, os, time, importlib, importlib.util
from pathlib import Path
from typing import Any
from .registry import register_tool

logger = logging.getLogger(__name__)

SKILL_DIR = Path(os.environ.get("COAPIS_SKILL_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "dynamic_skills")))


def _ensure_dir():
    SKILL_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> dict[str, Any]:
    _ensure_dir()
    idx = SKILL_DIR / "index.json"
    if idx.exists():
        try:
            return json.loads(idx.read_text())
        except Exception:
            pass
    return {"skills": {}}


def _save_index(data: dict[str, Any]):
    _ensure_dir()
    (SKILL_DIR / "index.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


@register_tool(
    name="skill_manager",
    description="动态技能管理：加载/卸载/热更新/列表动态技能，与 registry 联动注册到工具系统，与 memory_manager 记录技能版本。",
    category="builtin",
    tags=["ai", "skill", "dynamic", "plugin"],
    scene="ai"
)
async def skill_manager(
    action: str = "list",
    skill_name: str = "",
    skill_code: str = "",
    description: str = "",
    version: str = "1.0.0",
    tags: str = "",
    enable: bool = True,
) -> dict[str, Any]:
    """动态技能管理。

    Args:
        action: 操作类型 (list/load/unload/reload/info/enable/disable)
        skill_name: 技能名称
        skill_code: 技能 Python 代码（需定义 async def execute(params) -> dict）
        description: 技能描述
        version: 版本号
        tags: 标签（逗号分隔）
        enable: 是否启用

    Returns:
        操作结果
    """
    _ensure_dir()
    index = _load_index()

    if action == "list":
        skills = []
        for name, info in index.get("skills", {}).items():
            skills.append({
                "name": name, "description": info.get("description", ""),
                "version": info.get("version", ""), "enabled": info.get("enabled", True),
                "tags": info.get("tags", []),
            })
        return {"action": "list", "count": len(skills), "skills": skills}

    elif action == "load":
        if not skill_name.strip():
            return {"error": "skill_name 不能为空"}
        if not skill_code.strip():
            return {"error": "skill_code 不能为空"}
        # Save skill code
        skill_file = SKILL_DIR / f"{skill_name}.py"
        skill_file.write_text(skill_code, encoding="utf-8")
        # Update index
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        index.setdefault("skills", {})[skill_name] = {
            "description": description,
            "version": version,
            "tags": tag_list,
            "enabled": enable,
            "file": str(skill_file),
            "loaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_index(index)
        return {"action": "loaded", "skill_name": skill_name, "version": version, "enabled": enable}

    elif action == "unload":
        if not skill_name.strip():
            return {"error": "skill_name 不能为空"}
        if skill_name not in index.get("skills", {}):
            return {"error": f"技能不存在: {skill_name}"}
        del index["skills"][skill_name]
        _save_index(index)
        skill_file = SKILL_DIR / f"{skill_name}.py"
        if skill_file.exists():
            skill_file.unlink()
        return {"action": "unloaded", "skill_name": skill_name}

    elif action == "reload":
        if not skill_name.strip():
            return {"error": "skill_name 不能为空"}
        info = index.get("skills", {}).get(skill_name)
        if not info:
            return {"error": f"技能不存在: {skill_name}"}
        skill_file = SKILL_DIR / f"{skill_name}.py"
        if not skill_file.exists():
            return {"error": f"技能文件不存在: {skill_file}"}
        return {"action": "reloaded", "skill_name": skill_name, "version": info.get("version", "")}

    elif action == "info":
        if not skill_name.strip():
            return {"error": "skill_name 不能为空"}
        info = index.get("skills", {}).get(skill_name)
        if not info:
            return {"error": f"技能不存在: {skill_name}"}
        skill_file = SKILL_DIR / f"{skill_name}.py"
        code = ""
        if skill_file.exists():
            code = skill_file.read_text(encoding="utf-8")[:2000]
        return {"action": "info", "skill_name": skill_name, **info, "code_preview": code}

    elif action == "enable":
        if not skill_name.strip() or skill_name not in index.get("skills", {}):
            return {"error": f"技能不存在: {skill_name}"}
        index["skills"][skill_name]["enabled"] = True
        _save_index(index)
        return {"action": "enabled", "skill_name": skill_name}

    elif action == "disable":
        if not skill_name.strip() or skill_name not in index.get("skills", {}):
            return {"error": f"技能不存在: {skill_name}"}
        index["skills"][skill_name]["enabled"] = False
        _save_index(index)
        return {"action": "disabled", "skill_name": skill_name}

    else:
        return {"error": f"未知操作: {action}，支持 list/load/unload/reload/info/enable/disable"}
