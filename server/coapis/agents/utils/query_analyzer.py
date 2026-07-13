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

"""统一查询分析器 — 基于 ThinkingBudget 的独立实现。

核心思想："理解查询"只做一次，结果共享给所有下游。

输出 QueryAnalysis 包含：
- intent: 意图分类（greeting/recall/search/code/...）
- complexity: 复杂度（SIMPLE/NORMAL/COMPLEX）
- thinking_effort: 思考力度（low/medium/high）
- confidence: 置信度（0-1）
- suggested_tools: 建议工具列表
- pruned_tools: 裁剪后的工具列表（置信度 > 阈值时生效，否则 None）
- needs_tools: 是否需要工具

P1: 统一分析入口
P2: 工具 Schema 按需裁剪（置信度阈值通过 TOOL_PRUNE_THRESHOLD 环境变量配置，默认0.3）
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── 环境变量：工具裁剪置信度阈值 ──
_TOOL_PRUNE_THRESHOLD_ENV = "TOOL_PRUNE_THRESHOLD"
_DEFAULT_TOOL_PRUNE_THRESHOLD = 0.3


def _get_prune_threshold() -> float:
    """从环境变量读取工具裁剪置信度阈值。未设置时默认 0.3。"""
    val = os.environ.get(_TOOL_PRUNE_THRESHOLD_ENV)
    if val is not None:
        try:
            t = float(val)
            if 0.0 <= t <= 1.0:
                return t
            logger.warning(
                "[QueryAnalyzer] %s=%s 不在 [0,1] 范围，使用默认 %s",
                _TOOL_PRUNE_THRESHOLD_ENV, val, _DEFAULT_TOOL_PRUNE_THRESHOLD,
            )
        except ValueError:
            logger.warning(
                "[QueryAnalyzer] %s=%s 无法解析为浮点数，使用默认 %s",
                _TOOL_PRUNE_THRESHOLD_ENV, val, _DEFAULT_TOOL_PRUNE_THRESHOLD,
            )
    return _DEFAULT_TOOL_PRUNE_THRESHOLD


# ── 复杂度→thinking_effort 映射 ──
_EFFORT_MAP = {
    "SIMPLE": "low",
    "NORMAL": "medium",
    "COMPLEX": "high",
}

# ── 意图关键词模式 ──
_INTENT_PATTERNS: dict[str, list[str]] = {
    "greeting": [
        r"^(你好|hello|hi|hey|嗨|早|晚安|早上好|下午好|晚上好|吃了吗|在吗|在不在)\b",
        r"^(thanks|thank|谢谢|感谢|辛苦|棒|好的|ok|嗯|行)\b",
    ],
    "recall": [
        r"(刚才|刚刚|之前|上次|前面|聊了什么|说了什么|记不记得|回忆|总结.*对话)",
        r"(我们.*聊|你.*记得|对话.*记录|历史.*消息)",
    ],
    "search": [
        r"(搜索|查找|查询|找一下|搜一下|帮我查|帮我搜)",
        r"(新闻|天气|温度|股价|汇率|最新|最近)",
        r"(什么是|是什么|介绍|解释|定义|含义)",
    ],
    "code": [
        r"(代码|编程|函数|变量|类|方法|bug|调试|debug|报错|异常|堆栈|stack)",
        r"(python|java|javascript|typescript|golang|rust|c\+\+|sql|html|css)",
        r"(写.*代码|实现.*功能|修复.*bug|重构|优化.*性能)",
    ],
    "analysis": [
        r"(分析|评估|对比|比较|研究|调查|诊断|审查|review)",
        r"(数据|统计|趋势|指标|报告|图表)",
    ],
    "creative": [
        r"(写|创作|编写|撰写|起草|润色|修改.*文|改写)",
        r"(文章|文案|邮件|信|诗|故事|小说|剧本|摘要|总结)",
    ],
    "task": [
        r"(帮我|请|麻烦|能不能|可以.*吗|执行|运行|启动|停止|重启|部署|安装|配置)",
        r"(创建|新建|删除|修改|更新|上传|下载|发送|备份)",
    ],
    "meta": [
        r"(智能体|agent|技能|skill|工具|tool|配置|设置|系统|状态|健康)",
        r"(有哪些|列表|显示|查看|检查|测试|验证)",
    ],
}

# ── 意图→工具需求映射 ──
_INTENT_TOOL_MAP: dict[str, list[str]] = {
    "recall":     [],  # 回忆不需要工具
    "greeting":   [],  # 问候不需要工具
    "search":     ["web_search", "browser_use", "get_current_time"],
    "code":       ["execute_shell_command", "read_file", "write_file",
                   "edit_file", "grep_search", "glob_search"],
    "analysis":   ["read_file", "grep_search", "glob_search",
                   "execute_shell_command", "web_search"],
    "creative":   ["write_file", "edit_file", "read_file"],
    "task":       ["execute_shell_command", "read_file", "write_file",
                   "edit_file", "grep_search", "glob_search",
                   "browser_use", "web_search", "get_current_time"],
    "meta":       ["read_file", "execute_shell_command", "list_agents",
                   "chat_with_agent", "submit_to_agent", "check_agent_task",
                   "get_token_usage"],
}

# ── 始终保留的工具（不管什么意图都发送） ──
_ALWAYS_TOOLS = {
    "get_current_time",
    "send_file_to_user",
}

# ── 复杂度关键词 ──
_COMPLEX_PATTERNS = [
    r"(详细|深入|全面|系统|完整|多步|复杂|综合|对比.*分析)",
    r"(方案|设计|架构|规划|重构|迁移|升级|优化)",
    r"(所有|全部|多个|批量|批量处理|自动化)",
]
_SIMPLE_PATTERNS = [
    r"^.{0,15}$",  # 短查询
    r"(你好|hi|hello|ok|好的|嗯|谢谢|thanks)",
    r"(几点|日期|时间|天气|温度)",
]


@dataclass
class QueryAnalysis:
    """一次查询分析的完整结果。"""
    # ── 基础分类 ──
    query: str = ""
    intent: str = "task"             # greeting / recall / search / code / ...
    complexity: str = "NORMAL"       # SIMPLE / NORMAL / COMPLEX
    thinking_effort: str = "medium"  # low / medium / high
    confidence: float = 0.0          # 0-1，意图分类的置信度

    # ── 工具相关 ──
    needs_tools: bool = True
    suggested_tools: list[str] = field(default_factory=list)
    pruned_tools: list[str] | None = None  # None = 不裁剪，使用全部工具

    # ── 资源相关 ──
    needs_skills: bool = True
    needs_memory: bool = True
    needs_experiences: bool = True

    # ── 性能指标 ──
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "complexity": self.complexity,
            "thinking_effort": self.thinking_effort,
            "confidence": round(self.confidence, 3),
            "needs_tools": self.needs_tools,
            "suggested_tools": self.suggested_tools,
            "pruned_tools": self.pruned_tools,
            "latency_ms": round(self.latency_ms, 2),
        }


class QueryAnalyzer:
    """统一查询分析器。

    基于规则引擎分析查询意图和复杂度，不依赖外部模块。

    用法：
        analyzer = QueryAnalyzer()
        analysis = analyzer.analyze(query, recent_messages)
        # analysis.thinking_effort → 控制 thinking budget
        # analysis.pruned_tools    → 控制工具 schema 裁剪
        # analysis.intent          → 控制经验过滤
    """

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._prune_threshold = _get_prune_threshold()

        if self._enabled:
            logger.info(
                "[QueryAnalyzer] initialized, prune_threshold=%.2f",
                self._prune_threshold,
            )

    def analyze(
        self,
        query: str,
        recent_messages: list[dict] | None = None,
    ) -> QueryAnalysis:
        """分析查询，返回完整分析结果。

        Args:
            query: 用户查询文本
            recent_messages: 最近的消息列表（可选，用于上下文分析）

        Returns:
            QueryAnalysis 包含意图、复杂度、工具建议等
        """
        t0 = time.monotonic()

        # ── 未启用时返回默认值 ──
        if not self._enabled:
            return QueryAnalysis(
                query=query,
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        try:
            return self._analyze_internal(query, recent_messages, t0)
        except Exception as e:
            logger.warning("[QueryAnalyzer] analysis failed: %s", e)
            return QueryAnalysis(
                query=query,
                latency_ms=(time.monotonic() - t0) * 1000,
            )

    def _analyze_internal(
        self,
        query: str,
        recent_messages: list[dict] | None,
        t0: float,
    ) -> QueryAnalysis:
        """内部分析逻辑 — 基于规则引擎。"""
        query_lower = query.lower().strip()

        # ── Step 1: 意图分类 ──
        intent, confidence = self._classify_intent(query_lower)

        # ── Step 2: 复杂度评估 ──
        complexity = self._estimate_complexity(query_lower, intent)

        # ── Step 3: thinking_effort 映射 ──
        thinking_effort = _EFFORT_MAP.get(complexity, "medium")

        # ── Step 4: 工具需求判断 ──
        needs_tools = intent not in ("greeting", "recall")
        suggested_tools = list(_INTENT_TOOL_MAP.get(intent, []))
        for t in _ALWAYS_TOOLS:
            if t not in suggested_tools:
                suggested_tools.append(t)

        # 需要工具的查询至少 medium，防止模型因 effort=low 跳过工具调用
        if needs_tools and thinking_effort == "low":
            thinking_effort = "medium"

        # ── Step 5: 工具裁剪（P2）──
        pruned_tools = self._apply_pruning(
            suggested_tools, confidence, needs_tools,
        )

        # ── 构建结果 ──
        latency_ms = (time.monotonic() - t0) * 1000

        analysis = QueryAnalysis(
            query=query,
            intent=intent,
            complexity=complexity,
            thinking_effort=thinking_effort,
            confidence=confidence,
            needs_tools=needs_tools,
            suggested_tools=suggested_tools,
            pruned_tools=pruned_tools,
            needs_skills=needs_tools,
            needs_memory=True,
            needs_experiences=True,
            latency_ms=latency_ms,
        )

        logger.info(
            "[QueryAnalyzer] query=%s → intent=%s, complexity=%s, "
            "effort=%s, confidence=%.2f, pruned=%s, latency=%.1fms",
            query[:40],
            analysis.intent,
            analysis.complexity,
            analysis.thinking_effort,
            analysis.confidence,
            "yes" if pruned_tools is not None else "no",
            latency_ms,
        )

        return analysis

    def _classify_intent(self, query: str) -> tuple[str, float]:
        """基于规则的意图分类。

        Returns:
            (intent, confidence) 元组
        """
        # 按优先级检查各意图的关键词模式
        # greeting 和 recall 优先级最高（短匹配）
        priority_order = ["greeting", "recall", "meta", "code", "search",
                          "analysis", "creative", "task"]

        for intent in priority_order:
            patterns = _INTENT_PATTERNS.get(intent, [])
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    # 短查询匹配置信度更高
                    if len(query) <= 10:
                        return intent, 0.9
                    return intent, 0.75

        # 默认：task
        return "task", 0.5

    def _estimate_complexity(self, query: str, intent: str) -> str:
        """评估查询复杂度。"""
        # 简单模式
        for pattern in _SIMPLE_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                return "SIMPLE"

        # 复杂模式
        for pattern in _COMPLEX_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                return "COMPLEX"

        # 意图相关的默认复杂度
        if intent in ("greeting", "recall"):
            return "SIMPLE"
        if intent in ("analysis", "creative"):
            return "NORMAL"

        return "NORMAL"

    def _apply_pruning(
        self,
        suggested_tools: list[str],
        confidence: float,
        needs_tools: bool,
    ) -> list[str] | None:
        """应用工具裁剪（P2）。

        裁剪逻辑：
        1. 不需要工具的意图 → 返回始终保留的工具
        2. 置信度 > 阈值 → 返回建议工具列表
        3. 置信度 ≤ 阈值 → 返回 None（不裁剪，使用全部工具）

        Args:
            suggested_tools: 建议的工具列表
            confidence: 意图分类置信度
            needs_tools: 是否需要工具

        Returns:
            裁剪后的工具列表，或 None（不裁剪）
        """
        # 不需要工具 → 返回始终保留的工具
        if not needs_tools:
            if confidence > self._prune_threshold:
                return list(_ALWAYS_TOOLS)
            # 低置信度：保守，不裁剪
            return None

        # 需要工具 + 高置信度 → 裁剪到建议列表
        if confidence > self._prune_threshold and suggested_tools:
            return suggested_tools

        # 低置信度 → 不裁剪
        return None

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def prune_threshold(self) -> float:
        return self._prune_threshold
