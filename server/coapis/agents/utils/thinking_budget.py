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

"""Thinking budget control — reduce unnecessary reasoning overhead.

Classifies task complexity and sets appropriate thinking budget:
- Simple tasks (greetings, simple questions): low effort, ~500 tokens
- Normal tasks (standard Q&A, tool usage): medium effort, ~2000 tokens
- Complex tasks (code review, multi-step analysis): high effort, unlimited

This replaces the "one size fits all" approach where every query
consumed maximum thinking budget regardless of complexity.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class TaskComplexity:
    """Task complexity classification."""
    SIMPLE = "simple"
    NORMAL = "normal"
    #: 规则层（plan_gate）用的词就是这个，不是 normal
    MEDIUM = "medium"
    COMPLEX = "complex"


# Mapping: complexity → (reasoning_effort, thinking_budget_hint)
_BUDGET_MAP = {
    TaskComplexity.SIMPLE: {
        "reasoning_effort": "low",
        "thinking_budget_hint": 1024,
    },
    TaskComplexity.NORMAL: {
        "reasoning_effort": "medium",
        "thinking_budget_hint": 4096,
    },
    TaskComplexity.COMPLEX: {
        "reasoning_effort": "high",
        "thinking_budget_hint": 8192,
    },
}

# ── reasoning_effort 四档（v14 §4.4④）──────────────────────────────────
# 网关的 effort 输出是思考开支的唯一来源；minimal 显式关闭思考。
EFFORT_MINIMAL = "minimal"
EFFORT_LOW = "low"
EFFORT_MEDIUM = "medium"
EFFORT_HIGH = "high"
EFFORTS = (EFFORT_MINIMAL, EFFORT_LOW, EFFORT_MEDIUM, EFFORT_HIGH)

# effort → 思考开支（hint=0 表示显式关思考）
_EFFORT_BUDGET = {
    EFFORT_MINIMAL: {"reasoning_effort": "low", "thinking_budget_hint": 0},
    EFFORT_LOW: {"reasoning_effort": "low", "thinking_budget_hint": 1024},
    EFFORT_MEDIUM: {"reasoning_effort": "medium", "thinking_budget_hint": 4096},
    EFFORT_HIGH: {"reasoning_effort": "high", "thinking_budget_hint": 8192},
}

# effort ↔ 复杂度档（旧消费方只认复杂度档；规则层降级时反推 effort）
_EFFORT_TO_COMPLEXITY = {
    EFFORT_MINIMAL: TaskComplexity.SIMPLE,
    EFFORT_LOW: TaskComplexity.SIMPLE,
    EFFORT_MEDIUM: TaskComplexity.NORMAL,
    EFFORT_HIGH: TaskComplexity.COMPLEX,
}
_COMPLEXITY_TO_EFFORT = {
    TaskComplexity.SIMPLE: EFFORT_MINIMAL,
    TaskComplexity.NORMAL: EFFORT_LOW,
    #: 规则层用的词是 medium（不是 normal）：漏了这一档会让 medium 直接掉到
    #: minimal = **整个 medium 档永不思考**
    TaskComplexity.MEDIUM: EFFORT_LOW,
    "high": EFFORT_HIGH,
    TaskComplexity.COMPLEX: EFFORT_HIGH,
}


def effort_to_complexity(effort: str) -> str:
    """effort 档 → 复杂度档；未知 effort 按 minimal（不开思考）。"""
    return _EFFORT_TO_COMPLEXITY.get(
        (effort or "").strip().lower(),
        TaskComplexity.SIMPLE,
    )


def complexity_to_effort(complexity: str) -> str:
    """复杂度档 → effort 档；未知档按 minimal（§4.4④默认不思考）。"""
    key = (complexity or "").strip().lower()
    return _COMPLEXITY_TO_EFFORT.get(key, EFFORT_MINIMAL)


# ── Keyword patterns for classification ──

_SIMPLE_PATTERNS = [
    r"^(你好|hi|hello|hey|嗨|哈喽|谢谢|thanks|thank you|再见|bye|ok|好的|嗯|对)$",
    r"^(现在几点|几点了|what time|日期|今天)$",
    r"^(测试|test|ping|echo)$",
    r"^(你是谁|who are you|自我介绍)$",
    r"^[\U0001F600-\U0001F9FF\U00002702-\U000027B0\u2600-\u26FF\u2700-\u27BF]+$",  # emoji only
    # ── 回忆/上下文类问题：应直接从对话历史回答，不需要工具 ──
    r"^(刚才|刚刚|之前|上一[次轮]|last|previous).{0,10}(聊|说|讨论|谈|问|回答|做了|干了|说了什么|聊了什么)",
    r"^(我们|咱|你).{0,5}(刚才|刚刚|之前|上一[次轮]).{0,8}(聊|说|讨论|谈|做了|干了)",
    r"^(what|where|when|who).{0,15}(did we|was that|were we|just now|earlier|before)",
    r"^(remind|recall|remember).{0,15}(we|you|I|that|what)",
    r"^(你?还记得?|你还?记得|想起来了|回忆一?下)",
    r"^(我刚才说了什么|我说了啥|我问了什么|你回答了什么|你的回答是什么)",
]

_COMPLEX_PATTERNS = [
    # Code-related
    r"代码审查|code review|代码走读|重构|refactor",
    r"分析.*代码|分析.*架构|analyze.*code|analyze.*architect",
    r"帮我看看这段代码|帮我检查|帮我审查|look at this code|review this",
    r"bug|错误|报错|异常|error|exception|traceback|stack\s*trace",
    r"优化|optimize|性能|performance|瓶颈|bottleneck",
    r"debug|调试|排查|定位.*问题|troubleshoot",
    # Multi-step / planning
    r"方案设计|架构设计|整体规划|技术选型",
    r"需求分析|需求梳理|问题拆解",
    r"写.*报告|编制|report|调研",
    r"对比.*方案|比较.*优劣|trade.?off",
    # Complex operations
    r"批量|batch|批量.*处理",
    r"迁移|migrat|升级|upgrade",
    r"部署|deploy|容器|docker|k8s",
    r"安全.*审计|security.*audit|漏洞",
    # Long context tasks
    r"总结.*文件|总结.*文档|summarize.*file|summarize.*doc",
    r"读.*文件.*然后|read.*file.*then|分析.*文件",
    r"翻译.*整篇|translate.*entire",
]

_COMPILED_SIMPLE = [re.compile(p, re.IGNORECASE) for p in _SIMPLE_PATTERNS]
_COMPILED_COMPLEX = [re.compile(p, re.IGNORECASE) for p in _COMPLEX_PATTERNS]


# ------------------------------------------------------------------ #
# §4.4④ 主链侧形状映射：判档结论 → 各家 provider 的思考形状
# ------------------------------------------------------------------ #

#: agentscope 的 OpenAI 适配器把 generate_kwargs 平铺进请求体，所以形状键用
#: 各家认的键。官方 OpenAI 只认 reasoning_effort（发别的键会被判 400）；
#: 未知 provider 不发形状键——宁可不关思考，也不能把主链打挂。
_CHAT_TEMPLATE_PROVIDERS = frozenset(
    {"ollama", "vllm", "sglang", "lmstudio", "local", "local_file"},
)
_ENABLE_THINKING_PROVIDERS = frozenset(
    {
        "dashscope",
        "dashscope_compatible",
        "aliyun",
        "deepseek",
        "moonshot",
        "xai",
        "zai",
        "einstein",
        "alienchat",
    },
)
#: Ollama 的思考是开关 + 预算，不是 OpenAI 的四档：minimal 落到 low
_EFFORT_TO_OLLAMA = {"minimal": "low", "low": "low", "medium": "medium", "high": "high"}


def effort_shape(
    effort: str,
    provider_type: Optional[str] = None,
) -> Dict[str, Any]:
    """档位 → 请求形状（§4.4④）。判档与思考开支从此是同一个结论。

    Returns:
        dict: ``effort`` / ``reasoning_effort`` / ``thinking_budget_hint``，
        加 ``generate_kwargs``（合并进模型的 generate_kwargs，OpenAI 兼容系）
        与 ``model_attrs``（agentscope 直接认的属性形状：Anthropic 的
        ``thinking``、Gemini 的 ``thinking_config``）。
    """
    budget = ThinkingBudgetManager().apply_effort(effort)
    hint = int(budget["thinking_budget_hint"])
    pt = (provider_type or "").strip().lower()
    shape: Dict[str, Any] = {
        "effort": budget["effort"],
        "reasoning_effort": budget["reasoning_effort"],
        "thinking_budget_hint": hint,
        "generate_kwargs": {},
        "model_attrs": {},
    }
    if pt in _CHAT_TEMPLATE_PROVIDERS:
        kwargs: Dict[str, Any] = {"enable_thinking": hint > 0}
        if hint > 0:
            kwargs["thinking_budget"] = hint
        shape["generate_kwargs"]["chat_template_kwargs"] = kwargs
        if pt == "ollama":
            # Ollama 只认 low/medium/high：minimal 落 low，关思考由
            # chat_template_kwargs 的开关负责
            shape["reasoning_effort"] = _EFFORT_TO_OLLAMA.get(budget["effort"], "low")
    elif pt in _ENABLE_THINKING_PROVIDERS:
        # 阿里云百炼兼容模式 / DeepSeek 等：顶层 enable_thinking + thinking_budget
        shape["generate_kwargs"]["enable_thinking"] = hint > 0
        if hint > 0:
            shape["generate_kwargs"]["thinking_budget"] = hint
    elif pt == "anthropic":
        shape["model_attrs"]["thinking"] = (
            {"type": "enabled", "budget_tokens": max(1024, min(hint, 128000))}
            if hint > 0
            else {"type": "disabled"}
        )
    elif pt == "gemini":
        shape["model_attrs"]["thinking_config"] = {
            "thinking_budget": max(0, hint),
            "include_thoughts": hint > 0,
        }
    # 官方 OpenAI / 未知 provider：只带 reasoning_effort，不发形状键
    return shape


def resolve_thinking_target(model: Any) -> Any:
    """找到真正承载请求参数的模型对象。

    主链的模型被层层包装（窗口包装 → 用量包装 → agentscope 模型）。
    ``self.model.reasoning_effort = x`` 落在包装层上是**没人读的键**——
    必须落到带 ``generate_kwargs`` 的那个对象上才进得了请求体。
    """
    seen: set[int] = set()
    current = model
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if hasattr(current, "generate_kwargs"):
            return current
        current = getattr(current, "_model", None) or getattr(current, "model", None)
    return model


def apply_thinking_shape(
    model: Any,
    effort: str,
    provider_type: Optional[str] = None,
) -> Dict[str, Any]:
    """把档位写到真模型上，返回本轮结束后还原所需的状态。"""
    target = resolve_thinking_target(model)
    shape = effort_shape(effort, provider_type)
    prev_gk = getattr(target, "generate_kwargs", None)
    restore: Dict[str, Any] = {
        "target": target,
        "reasoning_effort": getattr(target, "reasoning_effort", None),
        "thinking": getattr(target, "thinking", None),
        "thinking_config": getattr(target, "thinking_config", None),
        "generate_kwargs": dict(prev_gk) if isinstance(prev_gk, dict) else None,
        "effort": shape["effort"],
        "hint": shape["thinking_budget_hint"],
    }
    try:
        target.reasoning_effort = shape["reasoning_effort"]
    except Exception:  # noqa: BLE001 - 包装层不接受就降级，不影响主链
        pass
    for key, value in shape["model_attrs"].items():
        try:
            setattr(target, key, value)
        except Exception:  # noqa: BLE001
            pass
    if isinstance(prev_gk, dict) and shape["generate_kwargs"]:
        for key, value in shape["generate_kwargs"].items():
            if (
                key == "chat_template_kwargs"
                and isinstance(prev_gk.get("chat_template_kwargs"), dict)
            ):
                merged = dict(prev_gk["chat_template_kwargs"])
                merged.update(value)
                prev_gk["chat_template_kwargs"] = merged
            else:
                prev_gk[key] = value
    return restore


def restore_thinking_shape(restore: Dict[str, Any]) -> None:
    """还原本轮改过的思考参数（跨轮不粘滞）。"""
    target = restore.get("target")
    if target is None:
        return
    for key in ("reasoning_effort", "thinking", "thinking_config"):
        value = restore.get(key)
        try:
            if value is None:
                if hasattr(target, key):
                    delattr(target, key)
            else:
                setattr(target, key, value)
        except Exception:  # noqa: BLE001
            pass
    saved = restore.get("generate_kwargs")
    if isinstance(saved, dict):
        try:
            target.generate_kwargs = saved
        except Exception:  # noqa: BLE001
            pass


def provider_type_of_model(model: Any) -> Optional[str]:
    """从模型包装上取 provider_type；取不到返回 None（就不发形状键）。"""
    try:
        from ..context.window_source import model_slot_of
        from ..providers.provider_manager import ProviderManager

        provider_id, _name = model_slot_of(model)
        if not provider_id:
            return None
        provider = ProviderManager.get_instance().get_provider(provider_id)
        return getattr(provider, "provider_type", None) if provider else None
    except Exception:  # noqa: BLE001 - 取不到就不发形状键
        return None


class ThinkingBudgetManager:
    """Per-request thinking budget controller.

    Usage::

        manager = ThinkingBudgetManager()
        complexity = manager.classify(query, message_history)
        kwargs = manager.apply_budget(complexity)
        # kwargs = {"reasoning_effort": "low"} or {} for default
    """

    def classify(
        self,
        query: str,
        message_history: list[dict[str, Any]] | None = None,
    ) -> str:
        """Classify task complexity from query text.

        Args:
            query: User's input text.
            message_history: Recent messages for context (optional).

        Returns:
            One of TaskComplexity.SIMPLE, NORMAL, COMPLEX.
        """
        if not query:
            return TaskComplexity.NORMAL

        query = query.strip()

        # ── Check simple patterns first ──
        for p in _COMPILED_SIMPLE:
            if p.search(query):
                return TaskComplexity.SIMPLE

        # ── Check complex patterns (before short-query shortcut) ──
        for p in _COMPILED_COMPLEX:
            if p.search(query):
                return TaskComplexity.COMPLEX

        # Queries with code blocks are usually complex
        if "```" in query or "    " in query:  # fenced or indented code
            return TaskComplexity.COMPLEX

        # ── Check history for context (before short-query shortcut) ──
        if message_history:
            recent = message_history[-3:]
            for msg in recent:
                content = msg.get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") in ("tool_use", "tool_call"):
                                return TaskComplexity.COMPLEX
                            if block.get("type") == "tool_result":
                                text = block.get("content", "")
                                if isinstance(text, str) and ("error" in text.lower() or "traceback" in text.lower()):
                                    return TaskComplexity.COMPLEX

        # Very short queries are usually simple (after complex + history check)
        if len(query) <= 5 and not any(
            c in query for c in "？?！!"
        ):
            return TaskComplexity.SIMPLE

        # Long queries (>200 chars) tend to be complex
        if len(query) > 200:
            return TaskComplexity.COMPLEX

        # Queries with file references
        if re.search(r"\.(py|js|ts|java|go|rs|cpp|c|sh|yaml|yml|json|xml|sql)\b", query):
            return TaskComplexity.COMPLEX

        return TaskComplexity.NORMAL

    def apply_budget(self, complexity: str) -> dict[str, Any]:
        """Get model kwargs for the given complexity level.

        Returns:
            Dict with reasoning_effort (and optionally thinking_budget_hint).
            Empty dict if using default behavior.
        """
        budget = _BUDGET_MAP.get(complexity, _BUDGET_MAP[TaskComplexity.NORMAL])

        result = {}
        effort = budget["reasoning_effort"]
        if effort:  # Only set if non-default
            result["reasoning_effort"] = effort

        return result

    def apply_effort(self, effort: str) -> dict[str, Any]:
        """Model kwargs for the gateway's effort verdict (v14 §4.4④).

        effort 是思考开支的唯一来源，minimal 显式关思考（hint=0 由适配层
        翻译成各家 provider 的关闭形状）。未知 effort 按 minimal 处理——
        判官不认识档位时绝不退回高开支，这条与 D9 的档位词表作废一致。
        """
        key = (effort or "").strip().lower()
        if key not in _EFFORT_BUDGET:
            key = EFFORT_MINIMAL
        self._last_effort = key
        budget = _EFFORT_BUDGET[key]
        result: dict[str, Any] = {"reasoning_effort": budget["reasoning_effort"]}
        # hint=0 是要显式关思考，必须把 0 传下去（不能被 falsy 吞掉）
        result["thinking_budget_hint"] = budget["thinking_budget_hint"]
        result["effort"] = key
        logger.debug(
            "Thinking effort: %s → effort=%s, hint=%s",
            key,
            budget["reasoning_effort"],
            budget["thinking_budget_hint"],
        )
        return result

    def get_budget_info(self, complexity: str) -> dict[str, Any]:
        """Get full budget info for logging/diagnostics."""
        return _BUDGET_MAP.get(complexity, _BUDGET_MAP[TaskComplexity.NORMAL])
