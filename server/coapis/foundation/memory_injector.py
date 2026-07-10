# -*- coding: utf-8 -*-
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

"""Smart memory injector for hierarchical agent architecture.

核心功能: 解决"改变思路后基础设定丢失"的问题。

解决方案:
1. 基础记忆始终注入（不受思路改变影响）
2. 长期记忆按需检索注入（基于当前任务相关性）
3. 短期记忆按对话注入
4. 总容量受控（16K tokens）
5. P4: 记忆分段注入 — 核心段落始终注入，其他按查询相关性过滤
"""
from __future__ import annotations

import logging
import re as _re
from dataclasses import dataclass
from typing import Any

from .memory_entry import MemoryEntry
from .memory_quota import MemoryQuota

# ── P4: 始终注入的核心段落关键词 ──
_ALWAYS_INJECT_KEYWORDS = [
    "基础设定", "身份", "安全", "核心", "准则", "边界", "风格",
    "profile", "identity", "security", "core",
]

# ── P4: 意图→关键词映射（用于相关性过滤）──
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "recall":    ["记忆", "历史", "记录", "经验", "之前", "memory"],
    "greeting":  ["身份", "风格", "名字", "profile"],
    "code":      ["代码", "开发", "工具", "技术", "code", "dev", "tool"],
    "task":      ["任务", "工具", "技能", "部署", "配置", "task", "tool"],
    "analysis":  ["分析", "数据", "报告", "分析", "data"],
    "creative":  ["写作", "创作", "文案", "风格"],
    "meta":      ["智能体", "agent", "配置", "系统", "config"],
}

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

    根因: 当前系统是查询驱动的，改变思路 = 查询不匹配 = 记忆丢失。

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
        # P4: 如果有 query，按相关性过滤记忆段落
        if query and core_memory:
            sections = self._parse_memory_sections(core_memory)
            if sections:
                core_memory = self._filter_by_relevance(sections, query)

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

    # ── P4: 记忆分段注入 ──

    @staticmethod
    def _parse_memory_sections(text: str) -> list[dict[str, str]]:
        """将记忆文本按 ## 标题分段。

        Returns:
            段落列表，每个段落 {"heading": 标题, "body": 内容}
        """
        if not text or not text.strip():
            return []

        sections: list[dict[str, str]] = []
        current_heading = ""
        current_lines: list[str] = []

        for line in text.split("\n"):
            if line.startswith("## "):
                # 保存上一个段落
                if current_lines:
                    body = "\n".join(current_lines).strip()
                    if body:
                        sections.append({
                            "heading": current_heading,
                            "body": body,
                        })
                current_heading = line[3:].strip()
                current_lines = [line]
            else:
                current_lines.append(line)

        # 最后一个段落
        if current_lines:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append({
                    "heading": current_heading,
                    "body": body,
                })

        return sections

    @staticmethod
    def _filter_by_relevance(
        sections: list[dict[str, str]],
        query: str,
    ) -> str:
        """按查询相关性过滤记忆段落，拼接为文本。

        核心段落（匹配 _ALWAYS_INJECT_KEYWORDS）始终注入。
        其他段落根据查询意图关键词匹配。

        Args:
            sections: 段落列表
            query: 用户查询文本

        Returns:
            过滤后的记忆文本
        """
        if not sections:
            return ""
        if not query:
            # 无查询时注入全部
            return "\n\n".join(s["body"] for s in sections)

        query_lower = query.lower()

        # 收集匹配的意图类别，扩展为该类别的所有关键词
        # 例如查询含"代码" → 匹配"code"类别 → 收集 {"代码","开发","工具","技术",...}
        intent_kws: set[str] = set()
        matched_categories: set[str] = set()
        for category, kws in _INTENT_KEYWORDS.items():
            if any(kw in query_lower for kw in kws):
                matched_categories.add(category)
                intent_kws.update(kws)

        always_inject: list[str] = []
        optional: list[dict[str, str]] = []

        for section in sections:
            heading_lower = section["heading"].lower()
            body_lower = section["body"][:200].lower()

            # 检查是否始终注入
            is_always = any(
                kw in heading_lower or kw in body_lower
                for kw in _ALWAYS_INJECT_KEYWORDS
            )
            if is_always:
                always_inject.append(section["body"])
                continue

            # 检查相关性：段落标题/内容是否包含匹配意图类别的任何关键词
            section_text = heading_lower + " " + body_lower
            is_relevant = any(kw in section_text for kw in intent_kws)

            if is_relevant:
                optional.append(section)

        # 如果没有匹配到任何可选段落，回退到注入全部
        if not optional and not always_inject:
            return "\n\n".join(s["body"] for s in sections)

        result_parts = always_inject + [s["body"] for s in optional]
        filtered = "\n\n".join(result_parts)

        if len(result_parts) < len(sections):
            logger.info(
                "[MemoryInjector] P4: %d/%d sections selected by relevance",
                len(result_parts), len(sections),
            )

        return filtered

    def get_usage(self) -> dict[str, Any]:
        """获取当前注入使用情况。"""
        return {
            "current_injected": dict(self._current_injected),
            "total_tokens": self.quota.total_injected(self._current_injected),
            "max_tokens": self.quota.max_tokens,
            "remaining": self.quota.max_tokens - self.quota.total_injected(self._current_injected),
        }
