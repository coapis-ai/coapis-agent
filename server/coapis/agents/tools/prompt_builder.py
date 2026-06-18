# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
from __future__ import annotations
import asyncio, json, logging, os, time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(os.environ.get("COAPIS_TEMPLATES_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "templates")))


def _ensure_dir():
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def _load_templates() -> dict[str, Any]:
    _ensure_dir()
    index_file = TEMPLATES_DIR / "index.json"
    if index_file.exists():
        try:
            return json.loads(index_file.read_text())
        except Exception:
            pass
    return {}


def _save_templates(data: dict[str, Any]):
    _ensure_dir()
    index_file = TEMPLATES_DIR / "index.json"
    index_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _render(template: str, variables: dict[str, str]) -> str:
    """Simple variable substitution: {{key}} -> value."""
    result = template
    for k, v in variables.items():
        result = result.replace(f"{{{{{k}}}}}", str(v))
    # Strip unresolved placeholders
    import re
    result = re.sub(r"\{\{[^}]+\}\}", "", result)
    return result.strip()


async def prompt_builder(
    action: str = "list",
    name: str = "",
    template: str = "",
    variables: str = "",
    description: str = "",
    tags: str = "",
    version: int = 0,
) -> dict[str, Any]:
    """Prompt 模板管理。

    Args:
        action: 操作类型 (list/get/create/update/delete/render/a_b_test)
        name: 模板名称
        template: 模板内容（含 {{variable}} 占位符）
        variables: 渲染变量 JSON
        description: 模板描述
        tags: 标签（逗号分隔）
        version: 版本号

    Returns:
        操作结果
    """
    templates = _load_templates()

    if action == "list":
        return {
            "action": "list",
            "count": len(templates),
            "templates": [{"name": k, "description": v.get("description", ""), "tags": v.get("tags", []),
                           "versions": len(v.get("versions", []))}
                          for k, v in templates.items()],
        }

    elif action == "get":
        if name not in templates:
            return {"error": f"模板不存在: {name}"}
        t = templates[name]
        return {"action": "get", "name": name, **t}

    elif action == "create":
        if not name.strip():
            return {"error": "name 不能为空"}
        if not template.strip():
            return {"error": "template 不能为空"}
        if name in templates:
            return {"error": f"模板已存在: {name}，请用 update"}
        tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        templates[name] = {
            "description": description,
            "tags": tags_list,
            "versions": [{"version": 1, "template": template, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}],
            "current_version": 1,
        }
        _save_templates(templates)
        return {"action": "created", "name": name, "version": 1}

    elif action == "update":
        if name not in templates:
            return {"error": f"模板不存在: {name}"}
        if not template.strip():
            return {"error": "template 不能为空"}
        t = templates[name]
        new_ver = len(t.get("versions", [])) + 1
        t["versions"].append({"version": new_ver, "template": template,
                              "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        t["current_version"] = new_ver
        if description:
            t["description"] = description
        if tags:
            t["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        _save_templates(templates)
        return {"action": "updated", "name": name, "version": new_ver}

    elif action == "delete":
        if name not in templates:
            return {"error": f"模板不存在: {name}"}
        del templates[name]
        _save_templates(templates)
        return {"action": "deleted", "name": name}

    elif action == "render":
        if name not in templates:
            return {"error": f"模板不存在: {name}"}
        t = templates[name]
        ver = version if version > 0 else t.get("current_version", 1)
        versions = t.get("versions", [])
        target = None
        for v in versions:
            if v["version"] == ver:
                target = v
                break
        if not target:
            return {"error": f"版本 {ver} 不存在"}
        vars_dict = {}
        if variables.strip():
            try:
                vars_dict = json.loads(variables)
            except Exception:
                return {"error": "variables JSON 解析失败"}
        rendered = _render(target["template"], vars_dict)
        return {"action": "rendered", "name": name, "version": ver, "rendered": rendered,
                "unresolved_vars": [k for k in ["text", "context", "query"] if f"{{{{{k}}}}}" in target["template"] and k not in vars_dict]}

    elif action == "a_b_test":
        if name not in templates:
            return {"error": f"模板不存在: {name}"}
        t = templates[name]
        versions = t.get("versions", [])
        if len(versions) < 2:
            return {"error": "A/B 测试至少需要 2 个版本"}
        vars_dict = {}
        if variables.strip():
            try:
                vars_dict = json.loads(variables)
            except Exception:
                pass
        rendered_a = _render(versions[-2]["template"], vars_dict)
        rendered_b = _render(versions[-1]["template"], vars_dict)
        return {"action": "a_b_test", "name": name,
                "version_a": {"version": versions[-2]["version"], "rendered": rendered_a},
                "version_b": {"version": versions[-1]["version"], "rendered": rendered_b}}

    else:
        return {"error": f"未知操作: {action}，支持 list/get/create/update/delete/render/a_b_test"}
