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
from typing import Any, Dict, Optional, Tuple

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
# 形状家族 —— 单一真源在 foundation，本模块只向下取用（v14 R1）
# ------------------------------------------------------------------ #
# 形状表住在 :mod:`coapis.foundation.thinking_shape`（纯标准库层，不会拉起应用
# 树）：判官与主链共用同一张表。**不得**在本模块重写表项——两处各抄一张表就是
# dev 台账里「主链按端点判定生效、判官按 provider_type 判定失效 -> 思考没关
# -> 单次 12~18 秒 -> 连吃熔断」的真因。
from ...foundation.thinking_shape import (
    FAMILIES,
    FAMILY_ANTHROPIC,
    FAMILY_CHAT_TEMPLATE,
    FAMILY_ENABLE_THINKING,
    FAMILY_GEMINI,
    FAMILY_NONE,
    FAMILY_REASONING_EFFORT,
    family_request_kwargs,
    host_of,
    shape_family,
    thinking_request_kwargs,
)


def provider_slot_of_model(model: Any) -> Tuple[str, str, str]:
    """从模型对象取 ``(provider_type, base_url, provider_id)``；取不到 → 三个空串。

    主链按模型自己携带的配置判厂形：厂形判定与模型绑定，不受调用点临时拼出来
    的参数影响。
    """
    try:
        from ..context.window_source import model_slot_of
        from ..providers.provider_manager import ProviderManager
    except Exception:  # noqa: BLE001 - 循环导入保护
        return ("", "", "")
    pid, _name = model_slot_of(model)
    if not pid:
        return ("", "", "")
    try:
        provider = ProviderManager.get_instance().get_provider(pid)
    except Exception:  # noqa: BLE001 - 取不到 provider 只说明厂形不知道
        provider = None
    return (
        str(getattr(provider, "provider_type", "") or ""),
        str(getattr(provider, "base_url", "") or ""),
        str(pid),
    )


def model_slot_of(model: Any) -> Dict[str, str]:
    """从模型对象取思考形状需要的槽位字典 ``{pid, ptype, base_url, model}``。

    形状判定要同时知道「模型是谁」与「挂在哪个厂形上」，这两件事过去分散在
    两处各查各的，导致同一个模型在不同调用点判出不同形状。这里收成一处，
    调用点只拿一个字典。
    """
    ptype, base_url, pid = provider_slot_of_model(model)
    return {
        "pid": pid,
        "ptype": ptype,
        "base_url": base_url,
        "model": str(getattr(model, "model", "") or ""),
    }


def effort_shape(
    effort: Optional[str],
    provider_type: Optional[str] = None,
    base_url: Optional[str] = None,
    provider_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """把四档 effort 翻成厂商形状；effort 为空/非法 → None（调用方跳过下发）。

    厂形取自 :func:`shape_family`（与判官同源）。传了 base_url/provider_id 就按
    端点判（与判官完全一致）；不传则退回按 provider_type 判——老调用点零改动。
    返回值键（主链契约，勿改）：``effort`` / ``reasoning_effort`` /
    ``thinking_budget_hint`` / ``generate_kwargs`` / ``model_attrs``。
    """
    eff = (effort or "").strip().lower()
    if eff not in _EFFORT_BUDGET:
        return None
    fam = shape_family(provider_type or "", base_url or "", provider_id or "")
    budget = int(_EFFORT_BUDGET[eff]["thinking_budget_hint"] or 0)
    # 家族级键位翻译只有一处实现（中枢层），主链与判官同源：主链认得的形状
    # 判官就能用，判官也绝不用主链不认的私有键位。
    generate_kwargs, model_attrs, reasoning_effort = family_request_kwargs(
        fam,
        budget,
        eff,
        _EFFORT_BUDGET[eff]["reasoning_effort"],
    )
    return {
        "effort": eff,
        "reasoning_effort": reasoning_effort,
        "thinking_budget_hint": budget,
        "generate_kwargs": generate_kwargs,
        "model_attrs": model_attrs,
    }


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
    base_url: Optional[str] = None,
    provider_id: Optional[str] = None,
    model_label: Optional[str] = None,
) -> Dict[str, Any]:
    """把档位写到真模型上，返回本轮结束后还原所需的状态。

    厂形判定与判官同源：provider_type/base_url/provider_id 缺哪个就从模型自带
    的配置里补哪个（调用点零改动即可吃到端点级判定）。
    """
    target = resolve_thinking_target(model)
    slot = model_slot_of(model)
    slot_type = provider_type or slot["ptype"]
    slot_url = base_url or slot["base_url"]
    slot_id = provider_id or slot["pid"]
    shape = effort_shape(
        effort,
        slot_type,
        slot_url,
        slot_id,
    )
    if shape is None:
        # 档位越界（上游传了四档之外的值）：不能演变成 ``shape["effort"]`` 的
        # KeyError 把整段思考控制打回「不控预算」，也不能凭空发明第五档——
        # 落最小档 = 关思考，与 complexity_to_effort 的兜底口径一致。
        logger.warning("[thinking] 非法档位 %r，按最小档（关思考）执行", effort)
        shape = effort_shape(
            EFFORT_MINIMAL,
            slot_type,
            slot_url,
            slot_id,
        )
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
