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

"""Progress Tracker — 让 LLM 拥有"进展感知"。

核心思想：不是拦截工具调用，而是告诉 LLM "做到了哪里"。
LLM 自己判断信息是否充分、是否该停止。

P0: 工具调用记录 + 进度摘要生成
P3: 结果质量反馈（空结果、重复结果检测）

集成方式：
- _acting() 末尾调用 tracker.record()
- _reasoning() 开头调用 tracker.inject_if_needed()
- reply() 开头调用 tracker.reset()
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── 默认配置 ──
_DEFAULT_INJECT_THRESHOLD = 4   # 开始注入摘要的调用次数
_DEFAULT_STRONG_THRESHOLD = 6   # 强烈建议停止的调用次数
_DEFAULT_HARD_LIMIT = 10        # 硬上限（安全兜底）
_DEFAULT_DUPLICATE_RATIO = 0.5  # 重复调用比例阈值
_DEFAULT_RESULT_MIN_LEN = 20    # 结果最小长度（低于此视为空结果）


@dataclass
class ToolCallRecord:
    """一次工具调用的记录。"""
    tool_name: str
    params_hash: str          # 参数哈希，用于去重检测
    params_summary: str       # 参数简短描述（如文件名、查询词）
    result_summary: str       # 结果简短描述
    result_quality: str       # good / empty / duplicate / error
    result_len: int           # 结果字符数
    timestamp: float          # 调用时间戳


@dataclass
class ProgressTrackerConfig:
    """进度追踪器配置。"""
    enabled: bool = False
    inject_threshold: int = _DEFAULT_INJECT_THRESHOLD
    strong_threshold: int = _DEFAULT_STRONG_THRESHOLD
    hard_limit: int = _DEFAULT_HARD_LIMIT
    duplicate_ratio_threshold: float = _DEFAULT_DUPLICATE_RATIO
    result_min_len: int = _DEFAULT_RESULT_MIN_LEN


def _hash_params(params: Any) -> str:
    """计算参数哈希。"""
    try:
        if params is None:
            return "none"
        s = json.dumps(params, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(s.encode()).hexdigest()[:8]
    except Exception:
        return str(hash(str(params)))[:8]


def _summarize_params(tool_name: str, params: Any) -> str:
    """生成参数的简短描述。"""
    if not params or not isinstance(params, dict):
        return ""
    # 提取最有信息量的参数
    for key in ("path", "file_path", "query", "pattern", "command", "url", "text"):
        val = params.get(key)
        if val:
            s = str(val)
            return s[:60] + "..." if len(s) > 60 else s
    # fallback: 第一个参数
    first_key = next(iter(params), None)
    if first_key:
        val = params[first_key]
        s = str(val)
        return f"{first_key}={s[:50]}" if len(s) > 50 else f"{first_key}={s}"
    return ""


def _summarize_result(result: Any) -> tuple[str, int]:
    """生成结果的简短描述和长度。返回 (summary, length)。"""
    if result is None:
        return "无结果", 0
    try:
        s = str(result)
        length = len(s)
        if length == 0:
            return "空结果", 0
        if length < 100:
            return s, length
        return f"{s[:80]}...({length}字符)", length
    except Exception:
        return "无法序列化", 0


class ProgressTracker:
    """工具调用进度追踪器。

    功能：
    1. 记录每轮对话中的工具调用
    2. 评估每次调用的结果质量（P3）
    3. 在适当时候生成进度摘要，注入到 LLM 上下文

    使用：
        tracker = ProgressTracker(config)
        tracker.reset()                          # 新对话开始
        tracker.record(tool_name, params, result) # 每次工具调用后
        if tracker.should_inject():              # reasoning 前检查
            summary = tracker.build_summary()
            # 注入到 memory
    """

    def __init__(self, config: ProgressTrackerConfig | None = None):
        self._config = config or ProgressTrackerConfig()
        self.records: list[ToolCallRecord] = []
        self._params_hashes: list[str] = []  # 所有参数哈希（用于去重）

    def reset(self):
        """新对话开始时重置。"""
        self.records.clear()
        self._params_hashes.clear()

    def record(
        self,
        tool_name: str,
        params: Any = None,
        result: Any = None,
    ):
        """记录一次工具调用。

        Args:
            tool_name: 工具名称
            params: 工具调用参数
            result: 工具执行结果
        """
        # 如果未启用，跳过记录
        if not self._config.enabled:
            return
        
        params_hash = _hash_params(params)
        params_summary = _summarize_params(tool_name, params)
        result_summary, result_len = _summarize_result(result)
        quality = self._evaluate_quality(params_hash, result_len)

        record = ToolCallRecord(
            tool_name=tool_name,
            params_hash=params_hash,
            params_summary=params_summary,
            result_summary=result_summary,
            result_quality=quality,
            result_len=result_len,
            timestamp=time.time(),
        )
        self.records.append(record)
        self._params_hashes.append(params_hash)

        logger.info(
            "[ProgressTracker] recorded: %s(%s) → %s (quality=%s, total=%d)",
            tool_name,
            params_summary[:30],
            result_summary[:30],
            quality,
            len(self.records),
        )

    def should_inject(self) -> bool:
        """是否应该注入进度摘要。"""
        # 先检查是否启用
        if not self._config.enabled:
            return False
        return len(self.records) >= self._config.inject_threshold

    def has_reached_hard_limit(self) -> bool:
        """是否达到硬上限（安全兜底）。"""
        return len(self.records) >= self._config.hard_limit

    def build_summary(self) -> str:
        """构建进度摘要文本。

        Returns:
            结构化的进度摘要字符串，用于注入到 LLM memory。
        """
        if not self.records:
            return ""

        n = len(self.records)
        cfg = self._config

        # ── 工具调用统计 ──
        tool_counts: dict[str, int] = {}
        for r in self.records:
            tool_counts[r.tool_name] = tool_counts.get(r.tool_name, 0) + 1

        # ── 多样性评估 ──
        unique_tools = len(tool_counts)
        unique_params = len(set(self._params_hashes))
        good_count = sum(1 for r in self.records if r.result_quality == "good")
        empty_count = sum(1 for r in self.records if r.result_quality == "empty")
        dup_count = sum(1 for r in self.records if r.result_quality == "duplicate")
        error_count = sum(1 for r in self.records if r.result_quality == "error")

        # ── 参数重复率 ──
        duplicate_ratio = 1 - (unique_params / n) if n > 0 else 0

        # ── 构建摘要 ──
        lines = [f"─── 进度摘要（{n}次工具调用）───"]

        # 工具调用明细
        for tool, count in tool_counts.items():
            # 找出该工具的参数摘要
            tool_params = [r.params_summary for r in self.records if r.tool_name == tool and r.params_summary]
            if tool_params and len(tool_params) <= 3:
                params_str = ", ".join(tool_params)
                lines.append(f"  {tool} × {count}（{params_str}）")
            else:
                lines.append(f"  {tool} × {count}")

        # 信息质量
        lines.append(f"  有效信息: {good_count}/{n}")

        if error_count > 0:
            lines.append(f"  ⚠️ 执行错误: {error_count}次")

        # ── 建议（渐进升级）──
        if n >= cfg.hard_limit:
            lines.append("")
            lines.append("🚫 已达到工具调用上限。请基于已有信息直接回答，不要再调用工具。")
        elif n >= cfg.strong_threshold:
            lines.append("")
            lines.append("⚠️ 已执行较多工具调用。强烈建议基于已有信息直接给出结论。")
        elif n >= cfg.inject_threshold:
            lines.append("")
            lines.append("💡 如果已有足够信息，请直接回答。")

        # ── 重复警告 ──
        if duplicate_ratio > cfg.duplicate_ratio_threshold:
            lines.append("")
            lines.append(
                f"⚠️ 检测到 {duplicate_ratio:.0%} 的调用参数重复。"
                "请避免重复调用相同参数的工具。"
            )

        if empty_count > 2:
            lines.append("")
            lines.append(f"⚠️ {empty_count} 次调用返回空结果，可能需要换个方向。")

        return "\n".join(lines)

    def _evaluate_quality(
        self,
        params_hash: str,
        result_len: int,
    ) -> str:
        """评估工具调用结果的质量（P3）。

        判断逻辑：
        1. 结果为空或极短 → "empty"
        2. 参数与最近3次调用完全重复 → "duplicate"
        3. 结果正常 → "good"
        """
        # 空结果检测
        if result_len < self._config.result_min_len:
            return "empty"

        # 参数重复检测（只检查最近3条记录）
        recent_hashes = self._params_hashes[-3:] if self._params_hashes else []
        if params_hash in recent_hashes:
            return "duplicate"

        return "good"

    def get_stats(self) -> dict:
        """获取统计信息（用于日志和调试）。"""
        if not self.records:
            return {"total_calls": 0}

        tool_counts: dict[str, int] = {}
        quality_counts: dict[str, int] = {}
        for r in self.records:
            tool_counts[r.tool_name] = tool_counts.get(r.tool_name, 0) + 1
            quality_counts[r.result_quality] = quality_counts.get(r.result_quality, 0) + 1

        return {
            "total_calls": len(self.records),
            "unique_tools": len(tool_counts),
            "unique_params": len(set(self._params_hashes)),
            "tool_counts": tool_counts,
            "quality_counts": quality_counts,
            "injected": len(self.records) >= self._config.inject_threshold,
        }
