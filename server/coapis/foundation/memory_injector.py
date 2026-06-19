# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
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

"""Smart memory injector for hierarchical agent architecture.

核心功能: 解决"改变思路后基础设定丢失"的问题。

解决方案:
1. 基础记忆始终注入（不受思路改变影响）
2. 长期记忆按需检索注入（基于当前任务相关性）
3. 短期记忆按对话注入
4. 总容量受控（16K tokens）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .memory_entry import MemoryEntry
from .memory_quota import MemoryQuota

logger = logging.getLogger(__name__)


@dataclass
class InjectionResult:
    """记忆注入结果。"""
    core_memory: str = ""
    long_term_memory: str = ""
    short_term_memory: str = ""
    ephemeral_memory: str = ""
    total_tokens: int = 0
    entries_used: int = 0

    def to_prompt(self) -> str:
        """转换为系统提示词格式。"""
        parts = []

        if self.core_memory:
            parts.append(f"## 基础设定\n{self.core_memory}")

        if self.long_term_memory:
            parts.append(f"## 相关经验\n{self.long_term_memory}")

        if self.short_term_memory:
            parts.append(f"## 对话上下文\n{self.short_term_memory}")

        if self.ephemeral_memory:
            parts.append(f"## 当前任务\n{self.ephemeral_memory}")

        return "\n\n".join(parts)


class MemoryInjector:
    """
    智能记忆注入器。

    核心问题: 改变思路后，基础设定就丢失了。

    根因: 当前系统（ReMeLight）是查询驱动的，改变思路 = 查询不匹配 = 记忆丢失。

    解决方案: 分层注入 + 始终注入基础记忆。

    注入顺序（优先级从高到低）:
    1. 基础记忆（固定注入，不受思路改变影响）
    2. 相关长期记忆（基于 query 检索）
    3. 当前对话短期记忆
    4. 临时记忆（当前消息）

    多用户支持:
    - 传入 role 参数后，注入容量按角色配额限制
    - 未传 role 时回退到全局限制（向后兼容）
    """

    def __init__(self, quota: MemoryQuota | None = None):
        self.quota = quota or MemoryQuota()
        self._current_injected: dict[str, int] = {
            "core": 0,
            "long_term": 0,
            "short_term": 0,
            "ephemeral": 0,
        }
        self._role: str = ""

    def _can_inject(self, memory_type: str, tokens: int) -> bool:
        """根据是否设置了 role，选择用户级或全局配额检查。"""
        if self._role:
            return self.quota.can_user_inject(
                self._role, memory_type, tokens, self._current_injected
            )
        return self.quota.can_inject(memory_type, tokens, self._current_injected)

    def build_context(
        self,
        core_memory: str,
        long_term_memories: list[str],
        short_term_memory: str,
        query: str,
        role: str = "",
    ) -> InjectionResult:
        """
        构建当前对话的完整上下文。

        Args:
            core_memory: 基础记忆（始终注入）
            long_term_memories: 长期记忆列表（按需检索）
            short_term_memory: 短期记忆（对话上下文）
            query: 当前用户查询
            role: 用户角色（传入后按角色配额限制注入容量）

        Returns:
            InjectionResult 包含各层记忆和总 token 数
        """
        result = InjectionResult()
        self._role = role

        # 1. 基础记忆（始终注入，容量限制 2K tokens）
        core_tokens = self._count_tokens(core_memory)
        if self._can_inject("core", core_tokens):
            result.core_memory = core_memory
            result.total_tokens += core_tokens
            self._current_injected["core"] = core_tokens
            logger.info(
                "[MemoryInjector] core: %d tokens (%d chars) [role=%s]",
                core_tokens, len(core_memory), role or "global",
            )
        else:
            logger.warning(
                "[MemoryInjector] core OVER QUOTA: %d tokens [role=%s]",
                core_tokens, role or "global",
            )

        # 2. 相关长期记忆（基于检索，容量限制 4K tokens）
        deduped_memories = self._deduplicate_memories(long_term_memories)
        injected_lt = 0
        for lt_mem in deduped_memories:
            lt_tokens = self._count_tokens(lt_mem)
            if self._can_inject("long_term", lt_tokens):
                if result.long_term_memory:
                    result.long_term_memory += "\n\n"
                result.long_term_memory += lt_mem
                result.total_tokens += lt_tokens
                self._current_injected["long_term"] += lt_tokens
                injected_lt += 1
            else:
                break
        if long_term_memories:
            logger.info(
                "[MemoryInjector] long_term: %d/%d entries injected (%d tokens)",
                injected_lt, len(long_term_memories),
                self._current_injected["long_term"],
            )

        # 3. 当前对话短期记忆（容量限制 8K tokens）
        st_tokens = self._count_tokens(short_term_memory)
        if self._can_inject("short_term", st_tokens):
            result.short_term_memory = short_term_memory
            result.total_tokens += st_tokens
            self._current_injected["short_term"] = st_tokens
            logger.info(
                "[MemoryInjector] short_term: %d tokens", st_tokens,
            )

        # 4. 临时记忆（当前消息，容量限制 2K tokens）
        ep_tokens = self._count_tokens(query)
        if self._can_inject("ephemeral", ep_tokens):
            result.ephemeral_memory = query
            result.total_tokens += ep_tokens
            self._current_injected["ephemeral"] = ep_tokens

        result.entries_used = sum(1 for v in self._current_injected.values() if v > 0)

        logger.info(
            "[MemoryInjector] total: %d tokens, %d layers used",
            result.total_tokens, result.entries_used,
        )

        return result

    def reset(self) -> None:
        """重置注入状态（新会话时调用）。"""
        self._current_injected = {
            "core": 0,
            "long_term": 0,
            "short_term": 0,
            "ephemeral": 0,
        }

    def _count_tokens(self, text: str) -> int:
        """
        粗略估算 token 数。

        注意: 这是简化估算，1 token ≈ 4 字符（中文）或 1.5 字符（英文）。
        生产环境应使用实际的 tokenizer。
        """
        if not text:
            return 0

        # 简化估算: 中文字符按 0.5 token/字符，英文按 0.66 token/字符
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        other_chars = len(text) - chinese_chars

        return int(chinese_chars * 0.5 + other_chars * 0.66)

    @staticmethod
    def _deduplicate_memories(memories: list[str], similarity_threshold: float = 0.4) -> list[str]:
        """去除重复的记忆片段。

        使用关键词 Jaccard 相似度 + 包含关系判断，超过阈值的较短片段被丢弃。
        """
        if len(memories) <= 1:
            return memories

        import re as _re

        def _extract_keywords(text: str) -> set[str]:
            # 2-gram 中文 + 英文单词
            zh = _re.findall(r'[\u4e00-\u9fff]', text)
            zh_bigrams = {zh[i] + zh[i + 1] for i in range(len(zh) - 1)} if len(zh) > 1 else set(zh)
            en = set(_re.findall(r'[a-zA-Z]{2,}', text.lower()))
            return zh_bigrams | en

        kept: list[str] = []
        kept_kw: list[set[str]] = []
        for mem in memories:
            kw = _extract_keywords(mem)
            if not kw:
                kept.append(mem)
                kept_kw.append(set())
                continue

            is_dup = False
            for i, existing_kw in enumerate(kept_kw):
                if not existing_kw:
                    continue
                # Jaccard 相似度
                intersection = len(kw & existing_kw)
                union = len(kw | existing_kw)
                jaccard = intersection / union if union > 0 else 0

                # 包含关系：一个的关键字完全包含另一个
                containment = intersection / min(len(kw), len(existing_kw)) if min(len(kw), len(existing_kw)) > 0 else 0

                if jaccard > similarity_threshold or containment > 0.7:
                    is_dup = True
                    # 保留较长的那条
                    if len(mem) > len(kept[i]):
                        kept[i] = mem
                        kept_kw[i] = kw
                    break

            if not is_dup:
                kept.append(mem)
                kept_kw.append(kw)

        if len(kept) < len(memories):
            logger.info(
                "[MemoryInjector] dedup: %d -> %d memories",
                len(memories), len(kept),
            )
        return kept

    def get_usage(self) -> dict[str, Any]:
        """获取当前注入使用情况。"""
        return {
            "current_injected": dict(self._current_injected),
            "total_tokens": self.quota.total_injected(self._current_injected),
            "max_tokens": self.quota.max_tokens,
            "remaining": self.quota.max_tokens - self.quota.total_injected(self._current_injected),
        }
