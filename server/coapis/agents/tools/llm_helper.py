# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""LLM helper — unified tool for LLM operations and prompt template management.

Merges llm_ops + prompt_builder into a single tool via action parameter.
Capabilities: summarize/translate/classify/extract, token cost tracking,
prompt template CRUD, variable rendering, A/B testing.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# ── Model pricing (USD per 1K tokens) ──
MODEL_PRICING = {
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "qwen-max": {"input": 0.002, "output": 0.006},
    "qwen-plus": {"input": 0.0004, "output": 0.0012},
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
}

_cost_tracker: dict[str, Any] = {
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "total_cost_usd": 0.0,
    "calls": 0,
    "by_model": {},
}

# ── Prompt templates storage ──
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
    (TEMPLATES_DIR / "index.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _render(template: str, variables: dict[str, str]) -> str:
    result = template
    for k, v in variables.items():
        result = result.replace(f"{{{{{k}}}}}", str(v))
    result = re.sub(r"\{\{[^}]+\}\}", "", result)
    return result.strip()


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, {"input": 0.002, "output": 0.006})
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1000


def _record_usage(model: str, input_tokens: int, output_tokens: int) -> dict[str, Any]:
    cost = _estimate_cost(model, input_tokens, output_tokens)
    _cost_tracker["total_input_tokens"] += input_tokens
    _cost_tracker["total_output_tokens"] += output_tokens
    _cost_tracker["total_cost_usd"] += cost
    _cost_tracker["calls"] += 1
    if model not in _cost_tracker["by_model"]:
        _cost_tracker["by_model"][model] = {"calls": 0, "input": 0, "output": 0, "cost": 0.0}
    m = _cost_tracker["by_model"][model]
    m["calls"] += 1
    m["input"] += input_tokens
    m["output"] += output_tokens
    m["cost"] += cost
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
        "cumulative_cost_usd": round(_cost_tracker["total_cost_usd"], 6),
    }


# ── LLM operation prompts ──
_LLM_PROMPTS = {
    "summarize": "请对以下内容进行简洁总结：\n\n{text}",
    "translate": "请将以下内容翻译为{target_lang}：\n\n{text}",
    "classify": "请将以下内容分类，可选类别: {categories}\n\n内容：{text}",
    "extract": "请从以下内容中提取{extract_type}：\n\n{text}",
}


async def llm_helper(
    action: str = "summarize",
    text: str = "",
    target_lang: str = "英文",
    categories: str = "",
    extract_type: str = "关键信息",
    model: str = "gpt-4o",
    # Prompt template params
    name: str = "",
    template: str = "",
    variables: str = "",
    description: str = "",
    tags: str = "",
    version: int = 0,
    # Cost tracking params
    input_tokens: int = 0,
    output_tokens: int = 0,
    limit: int = 50,
    **kwargs: Any,
) -> dict[str, Any]:
    """LLM 辅助统一工具。

    Args:
        action: 操作类型:
            LLM 操作: summarize/translate/classify/extract/cost_status/cost_reset
            Prompt 模板: template_list/template_get/template_create/template_update/
                          template_delete/template_render/template_ab_test
        text: 输入文本（LLM 操作时使用）
        target_lang: 翻译目标语言
        categories: 分类选项（逗号分隔）
        extract_type: 提取类型
        model: 模型名称
        name: 模板名称
        template: 模板内容
        variables: 渲染变量 JSON
        description: 模板描述
        tags: 标签（逗号分隔）
        version: 模板版本号
        input_tokens/output_tokens: token 计数
        limit: 查询限制

    Returns:
        操作结果
    """
    # ── LLM operations ──
    if action in ("summarize", "translate", "classify", "extract"):
        if not text.strip():
            return {"error": "text 不能为空"}

        prompt = _LLM_PROMPTS[action].format(
            text=text,
            target_lang=target_lang,
            categories=categories,
            extract_type=extract_type,
        )

        # Estimate tokens (rough: 1 token ≈ 4 chars)
        est_input = len(prompt) // 4
        usage = _record_usage(model, est_input, 0)

        return {
            "action": action,
            "model": model,
            "prompt_preview": prompt[:200] + "..." if len(prompt) > 200 else prompt,
            "estimated_tokens": usage,
            "note": "此工具返回构建好的 prompt，请将 prompt 传给实际 LLM 调用。",
        }

    elif action == "cost_status":
        return {
            "action": "cost_status",
            "total_calls": _cost_tracker["calls"],
            "total_input_tokens": _cost_tracker["total_input_tokens"],
            "total_output_tokens": _cost_tracker["total_output_tokens"],
            "total_cost_usd": round(_cost_tracker["total_cost_usd"], 6),
            "by_model": _cost_tracker["by_model"],
        }

    elif action == "cost_reset":
        _cost_tracker.update({
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0.0,
            "calls": 0,
            "by_model": {},
        })
        return {"action": "cost_reset", "status": "ok"}

    # ── Prompt template operations ──
    elif action == "template_list":
        templates = _load_templates()
        return {
            "action": "template_list",
            "count": len(templates),
            "templates": [
                {"name": k, "description": v.get("description", ""), "tags": v.get("tags", []),
                 "versions": len(v.get("versions", []))}
                for k, v in templates.items()
            ],
        }

    elif action == "template_get":
        if not name.strip():
            return {"error": "name 不能为空"}
        templates = _load_templates()
        if name not in templates:
            return {"error": f"模板不存在: {name}"}
        return {"action": "template_get", "name": name, **templates[name]}

    elif action == "template_create":
        if not name.strip():
            return {"error": "name 不能为空"}
        if not template.strip():
            return {"error": "template 不能为空"}
        templates = _load_templates()
        if name in templates:
            return {"error": f"模板已存在: {name}"}
        tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        templates[name] = {
            "description": description,
            "tags": tags_list,
            "versions": [{
                "version": 1,
                "template": template,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }],
            "current_version": 1,
        }
        _save_templates(templates)
        return {"action": "template_create", "status": "ok", "name": name}

    elif action == "template_update":
        if not name.strip():
            return {"error": "name 不能为空"}
        templates = _load_templates()
        if name not in templates:
            return {"error": f"模板不存在: {name}"}
        t = templates[name]
        if description:
            t["description"] = description
        if tags:
            t["tags"] = [s.strip() for s in tags.split(",") if s.strip()]
        if template.strip():
            new_ver = len(t.get("versions", [])) + 1
            t.setdefault("versions", []).append({
                "version": new_ver,
                "template": template,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            t["current_version"] = new_ver
        _save_templates(templates)
        return {"action": "template_update", "status": "ok", "name": name}

    elif action == "template_delete":
        if not name.strip():
            return {"error": "name 不能为空"}
        templates = _load_templates()
        if name not in templates:
            return {"error": f"模板不存在: {name}"}
        del templates[name]
        _save_templates(templates)
        return {"action": "template_delete", "status": "ok", "name": name}

    elif action == "template_render":
        if not name.strip():
            return {"error": "name 不能为空"}
        templates = _load_templates()
        if name not in templates:
            return {"error": f"模板不存在: {name}"}
        t = templates[name]
        ver = version if version > 0 else t.get("current_version", 1)
        versions = t.get("versions", [])
        target = None
        for v in versions:
            if v.get("version") == ver:
                target = v
                break
        if not target:
            return {"error": f"版本 {ver} 不存在"}
        vars_dict = {}
        if variables.strip():
            try:
                vars_dict = json.loads(variables)
            except Exception:
                pass
        rendered = _render(target["template"], vars_dict)
        return {
            "action": "template_render", "name": name,
            "version": ver, "rendered": rendered,
            "variables_used": vars_dict,
        }

    elif action == "template_ab_test":
        if not name.strip():
            return {"error": "name 不能为空"}
        templates = _load_templates()
        if name not in templates:
            return {"error": f"模板不存在: {name}"}
        t = templates[name]
        versions = t.get("versions", [])
        if len(versions) < 2:
            return {"error": "至少需要2个版本才能做 A/B 测试"}
        vars_dict = {}
        if variables.strip():
            try:
                vars_dict = json.loads(variables)
            except Exception:
                pass
        results = []
        for v in versions:
            rendered = _render(v["template"], vars_dict)
            results.append({"version": v["version"], "rendered": rendered})
        return {"action": "template_ab_test", "name": name, "variants": results}

    else:
        return {"error": f"未知操作: {action}。LLM: summarize/translate/classify/extract/cost_status/cost_reset; Template: template_list/template_get/template_create/template_update/template_delete/template_render/template_ab_test"}


# ── Aliases for backward compatibility ──
llm_ops = llm_helper
prompt_builder = llm_helper
