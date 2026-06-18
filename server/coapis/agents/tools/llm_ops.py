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

"""LLM ops — LLM call wrapper with token cost tracking.

Provides summarize/translate/classify/extract operations using LLM,
with token usage tracking and cost estimation. Integrates with
resource_guard for budget enforcement.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any


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

# ── Global cost tracker ──
_cost_tracker: dict[str, Any] = {
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "total_cost_usd": 0.0,
    "calls": 0,
    "by_model": {},
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD."""
    pricing = MODEL_PRICING.get(model, {"input": 0.002, "output": 0.006})
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1000


def _record_usage(model: str, input_tokens: int, output_tokens: int) -> dict[str, Any]:
    """Record token usage and return cost info."""
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


# ── Prompt templates ──
PROMPTS = {
    "summarize": "请对以下文本进行简洁摘要，保留关键信息：\n\n{text}",
    "translate": "请将以下文本翻译为{target_lang}：\n\n{text}",
    "classify": "请将以下文本分类为以下类别之一：{categories}\n\n文本：{text}\n\n仅输出类别名称：",
    "extract": "请从以下文本中提取{target}信息，以 JSON 格式输出：\n\n{text}",
    "rewrite": "请将以下文本改写为{style}风格：\n\n{text}",
    "analyze": "请分析以下文本的主题、情感和关键观点：\n\n{text}",
}


async def llm_ops(
    action: str = "summarize",
    text: str = "",
    target_lang: str = "英文",
    categories: str = "",
    target: str = "",
    style: str = "简洁专业",
    model: str = "gpt-4o-mini",
    custom_prompt: str = "",
) -> dict[str, Any]:
    """LLM 调用封装。

    提供常见 NLP 操作，追踪 token 成本。

    Args:
        action: 操作类型 (summarize/translate/classify/extract/rewrite/analyze/cost/custom)
        text: 输入文本
        target_lang: 翻译目标语言
        categories: 分类类别（逗号分隔）
        target: 提取目标（如"人名"、"地址"）
        style: 改写风格
        model: 模型名称
        custom_prompt: 自定义 prompt

    Returns:
        LLM 处理结果和成本信息
    """
    if not text.strip() and action != "cost":
        return {"error": "text 不能为空"}

    # Cost query - no LLM call needed
    if action == "cost":
        return {
            "action": "cost",
            "total_calls": _cost_tracker["calls"],
            "total_input_tokens": _cost_tracker["total_input_tokens"],
            "total_output_tokens": _cost_tracker["total_output_tokens"],
            "total_cost_usd": round(_cost_tracker["total_cost_usd"], 6),
            "by_model": _cost_tracker["by_model"],
        }

    # Build prompt
    if action == "custom":
        if not custom_prompt.strip():
            return {"error": "custom_prompt 不能为空"}
        prompt = custom_prompt.replace("{text}", text)
    elif action in PROMPTS:
        prompt = PROMPTS[action].replace("{text}", text)
        prompt = prompt.replace("{target_lang}", target_lang)
        prompt = prompt.replace("{categories}", categories or "正面,负面,中性")
        prompt = prompt.replace("{target}", target or "关键信息")
        prompt = prompt.replace("{style}", style)
    else:
        return {"error": f"未知操作: {action}，支持 summarize/translate/classify/extract/rewrite/analyze/cost/custom"}

    # Check resource_guard budget
    try:
        from .resource_guard import resource_guard
        check = await resource_guard(action="check")
        if check.get("check") == "violations":
            return {
                "error": "资源预算超限，建议降级",
                "violations": check.get("violations", []),
                "recommendation": check.get("recommendation", ""),
            }
    except Exception:
        pass

    # Estimate tokens (rough: 1 token ≈ 4 chars for English, 2 chars for Chinese)
    est_input_tokens = max(len(text) // 3, 100)
    est_output_tokens = min(est_input_tokens * 2, 2000)
    est_cost = _estimate_cost(model, est_input_tokens, est_output_tokens)

    # Record usage
    usage = _record_usage(model, est_input_tokens, est_output_tokens)

    # Note: actual LLM call would go through the framework's LLM provider
    # Here we return the constructed prompt and cost estimate
    return {
        "action": action,
        "model": model,
        "prompt": prompt[:1000],
        "usage": usage,
        "estimated_output": f"[LLM 调用将由框架 LLM Provider 执行，prompt 已准备就绪]",
        "note": "实际 LLM 调用需通过框架 LLM Provider，此工具负责 prompt 构建和成本追踪",
    }


# Expose cost tracker for other tools
def get_cost_tracker() -> dict[str, Any]:
    """Get the current cost tracker state."""
    return dict(_cost_tracker)
