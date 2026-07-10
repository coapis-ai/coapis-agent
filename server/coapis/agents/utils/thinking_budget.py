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

    def get_budget_info(self, complexity: str) -> dict[str, Any]:
        """Get full budget info for logging/diagnostics."""
        return _BUDGET_MAP.get(complexity, _BUDGET_MAP[TaskComplexity.NORMAL])
