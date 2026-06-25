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

"""Foundation layer manager for hierarchical agent architecture.

管理基础层内容，包括:
- 核心价值观 (core_principles.md)
- 通用思考模式 (thinking_patterns.md)
- 全局知识库 (knowledge_base/)
- 组织级记忆 (organizational_memory/)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .memory_entry import MemoryEntry
from .memory_injector import MemoryInjector, InjectionResult
from .memory_quota import MemoryQuota

logger = logging.getLogger(__name__)


@dataclass
class PendingMemory:
    """待审核的记忆条目。"""
    entry: MemoryEntry
    submitted_by: str
    submitted_at: datetime
    status: str = "pending"  # pending | approved | rejected
    review_comment: str = ""


class FoundationManager:
    """基础层管理器。

    职责:
    1. 加载基础记忆（核心价值观 + 思考模式）
    2. 管理全局知识库
    3. 处理记忆审核流程
    4. 提供记忆检索接口

    Attributes:
        foundation_dir: 基础层根目录
        quota: 容量配额
        injector: 记忆注入器
    """

    def __init__(self, foundation_dir: str | Path):
        self.foundation_dir = Path(foundation_dir)
        self.quota = MemoryQuota()
        self.injector = MemoryInjector(self.quota)

        # 缓存
        self._core_memory_cache: str | None = None
        self._thinking_patterns_cache: str | None = None

        # 待审核队列
        self._pending_memories: list[PendingMemory] = []

        # 注入状态追踪（防止基础记忆重复注入）
        self._core_injected: bool = False

        # 确保目录结构存在
        self._ensure_directory_structure()

    def reset_injection_state(self) -> None:
        """
        重置注入状态（新会话时调用）。

        注意: 新会话时应调用此方法重置状态，
        然后调用 build_context(is_initial=True) 重新注入基础记忆。
        """
        self._core_injected = False
        # Performance: clear caches for new session
        self._initial_context_cache = None
        self._knowledge_index_cache = None

    def _ensure_directory_structure(self) -> None:
        """确保基础层目录结构完整。"""
        dirs = [
            self.foundation_dir / "knowledge_base" / "general" / "coding",
            self.foundation_dir / "knowledge_base" / "general" / "research",
            self.foundation_dir / "knowledge_base" / "general" / "design",
            self.foundation_dir / "knowledge_base" / "system" / "architecture",
            self.foundation_dir / "knowledge_base" / "system" / "lessons",
            self.foundation_dir / "shared_skills",
        ]

        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        # Performance: cache knowledge index in memory
        self._knowledge_index_cache: dict[str, Any] | None = None
        self._initial_context_cache: str | None = None

    # =========================================================================
    # 基础记忆加载
    # =========================================================================

    def load_core_principles(self) -> str:
        """加载核心价值观。"""
        if self._core_memory_cache:
            return self._core_memory_cache

        path = self.foundation_dir / "core_principles.md"
        if path.exists():
            self._core_memory_cache = path.read_text(encoding="utf-8")
            return self._core_memory_cache

        logger.warning("core_principles.md not found")
        return ""

    def load_thinking_patterns(self) -> str:
        """加载通用思考模式。"""
        if self._thinking_patterns_cache:
            return self._thinking_patterns_cache

        path = self.foundation_dir / "thinking_patterns.md"
        if path.exists():
            self._thinking_patterns_cache = path.read_text(encoding="utf-8")
            return self._thinking_patterns_cache

        logger.warning("thinking_patterns.md not found")
        return ""

    def load_core_memory(self) -> str:
        """
        加载完整的基础记忆。

        返回核心价值观 + 思考模式的组合，
        始终注入，不受思路改变影响。
        """
        principles = self.load_core_principles()
        patterns = self.load_thinking_patterns()

        if principles and patterns:
            return f"{principles}\n\n{patterns}"
        return principles or patterns

    def clear_cache(self) -> None:
        """清除缓存（文件更新后调用）。"""
        self._core_memory_cache = None
        self._thinking_patterns_cache = None

    # =========================================================================
    # 知识库管理
    # =========================================================================

    def load_knowledge_index(self) -> dict[str, Any]:
        """加载知识索引（带缓存）。"""
        if self._knowledge_index_cache is not None:
            return self._knowledge_index_cache

        index_path = self.foundation_dir / "knowledge_base" / "index.json"
        if index_path.exists():
            self._knowledge_index_cache = json.loads(index_path.read_text(encoding="utf-8"))
            return self._knowledge_index_cache
        self._knowledge_index_cache = {"categories": [], "entries": []}
        return self._knowledge_index_cache

    def save_knowledge_index(self, index: dict[str, Any]) -> None:
        """保存知识索引。"""
        index_path = self.foundation_dir / "knowledge_base" / "index.json"
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    def search_knowledge(self, query: str, category: str | None = None) -> list[MemoryEntry]:
        """
        在知识库中搜索相关记忆（关键词匹配）。

        Args:
            query: 搜索查询
            category: 可选的分类过滤

        Returns:
            相关记忆条目列表（按优先级排序）
        """
        return self._search_with_keywords(query, category)

    def _search_with_keywords(self, query: str, category: str | None = None) -> list[MemoryEntry]:
        """关键词匹配搜索。"""
        index = self.load_knowledge_index()
        results = []

        for entry_data in index.get("entries", []):
            entry = MemoryEntry.from_dict(entry_data)

            # 分类过滤
            if category and entry.category != category:
                continue

            # 关键词匹配（查询词在内容中）
            if query.lower() in entry.content.lower():
                entry.access()
                results.append(entry)

        # 按优先级排序
        results.sort(key=lambda e: e.priority_score, reverse=True)
        return results

    # =========================================================================
    # 记忆审核流程
    # =========================================================================

    def submit_memory_for_review(
        self,
        entry: MemoryEntry,
        submitted_by: str,
    ) -> str:
        """
        提交记忆待审核。

        Args:
            entry: 记忆条目
            submitted_by: 提交者

        Returns:
            审核 ID
        """
        pending = PendingMemory(
            entry=entry,
            submitted_by=submitted_by,
            submitted_at=datetime.now(),
        )
        self._pending_memories.append(pending)
        return pending.entry.id

    def approve_memory(self, memory_id: str, comment: str = "") -> bool:
        """
        批准记忆入库。

        Args:
            memory_id: 记忆 ID
            comment: 审核意见

        Returns:
            True 如果找到并批准
        """
        for pending in self._pending_memories:
            if pending.entry.id == memory_id:
                pending.status = "approved"
                pending.review_comment = comment

                # 提升到基础记忆
                pending.entry.memory_type = "core"
                pending.entry.confirm()

                # 保存到知识库
                self._save_to_knowledge_base(pending.entry)

                return True

        return False

    def reject_memory(self, memory_id: str, comment: str = "") -> bool:
        """
        拒绝记忆。

        Args:
            memory_id: 记忆 ID
            comment: 拒绝理由

        Returns:
            True 如果找到并拒绝
        """
        for pending in self._pending_memories:
            if pending.entry.id == memory_id:
                pending.status = "rejected"
                pending.review_comment = comment
                return True

        return False

    def get_pending_memories(self) -> list[PendingMemory]:
        """获取待审核记忆列表。"""
        return [p for p in self._pending_memories if p.status == "pending"]

    def add_principle(
        self,
        principle: str,
        source_entry: Any = None,
        source_users: list[str] | None = None,
        category: str = "general",
        review_reason: str = "",
    ) -> MemoryEntry:
        """
        添加全局基础原则（由跨 Agent 进化引擎晋升调用）。

        Args:
            principle: 提炼的核心原则
            source_entry: 来源经验条目（可选）
            source_users: 来源用户列表（可选）
            category: 分类
            review_reason: 评审理由

        Returns:
            创建的 MemoryEntry
        """
        from .memory_entry import MemoryEntry

        # 构建内容：包含原则 + 来源信息
        content_parts = [f"【晋升原则】{principle}"]
        if source_entry:
            content_parts.append(f"来源经验: {getattr(source_entry, 'content', '')}")
        if source_users:
            content_parts.append(f"来源用户: {', '.join(source_users[:5])}")
        if review_reason:
            content_parts.append(f"评审理由: {review_reason}")

        content = "\n".join(content_parts)

        entry = MemoryEntry(
            content=content,
            category=category,
            source="cross_agent_evolution",
            tags=["promoted", "global_principle"],
        )

        # 检查配额
        if not self.quota.can_add(category):
            # 配额满时淘汰最低优先级条目
            self._evict_lowest_priority(category)
        
        # 保存到知识库
        self._save_to_knowledge_base(entry)

        # 清除缓存
        self._core_memory_cache = None
        self._initial_context_cache = None

        logger.info(
            "FoundationManager: added promoted principle (id=%s, category=%s, content=%s)",
            entry.id[:8], category, principle[:50],
        )

        return entry

    def _evict_lowest_priority(self, category: str) -> None:
        """淘汰指定分类中最低优先级的条目。"""
        index = self.load_knowledge_index()
        entries = index.get("entries", [])

        # 找到该分类中优先级最低的条目
        category_entries = [e for e in entries if e.get("category") == category]
        if not category_entries:
            return

        # 按 priority_score 排序，找到最低的
        category_entries.sort(key=lambda e: e.get("priority_score", 0))
        evicted = category_entries[0]

        # 从索引中移除
        index["entries"].remove(evicted)
        self.save_knowledge_index(index)

        # 删除文件
        category_dir = self.foundation_dir / "knowledge_base" / "general" / category
        entry_file = category_dir / f"{evicted.get('id', '')}.json"
        if entry_file.exists():
            entry_file.unlink()

        logger.info(
            "FoundationManager: evicted lowest priority entry (id=%s, score=%.2f)",
            evicted.get("id", "")[:8], evicted.get("priority_score", 0),
        )

    def _save_to_knowledge_base(self, entry: MemoryEntry) -> None:
        """将记忆保存到知识库。"""
        index = self.load_knowledge_index()
        index["entries"].append(entry.to_dict())
        self.save_knowledge_index(index)

        # 同时保存到分类目录
        category_dir = self.foundation_dir / "knowledge_base" / "general" / entry.category
        category_dir.mkdir(parents=True, exist_ok=True)

        entry_file = category_dir / f"{entry.id}.json"
        entry_file.write_text(json.dumps(entry.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    # =========================================================================
    # 记忆注入（核心接口）
    # =========================================================================

    def build_context(
        self,
        query: str,
        short_term_memory: str = "",
        category: str | None = None,
        is_initial: bool = False,
    ) -> str:
        """
        统一的上下文构建接口（推荐集成层使用此方法）。

        自动管理基础记忆注入状态，避免重复注入：
        - 如果 is_initial=True 或基础记忆未注入 → 调用 build_initial_context
        - 否则 → 调用 build_incremental_context

        Args:
            query: 用户查询
            short_term_memory: 短期记忆（对话上下文）
            category: 可选的分类过滤
            is_initial: 是否为初始调用（新会话时设为 True）

        Returns:
            上下文字符串

        Example:
            # 新会话
            ctx = fm.build_context("你好", is_initial=True)
            # 后续对话
            ctx = fm.build_context("继续上一个话题", short_term_memory="...")
        """
        if is_initial or not self._core_injected:
            # 初始注入：包含基础记忆
            result = self.build_initial_context(query, category)
            self._core_injected = True
            return result
        else:
            # 增量注入：不包含基础记忆
            return self.build_incremental_context(query, short_term_memory, category)

    def build_initial_context(
        self,
        query: str,
        category: str | None = None,
    ) -> str:
        """
        构建初始上下文（Agent 初始化时调用一次）。

        包含基础记忆 + 相关长期记忆，注入到 system prompt。
        后续对话不再重复注入基础记忆，只追加增量。

        注意: 推荐使用 build_context(is_initial=True) 替代直接调用此方法。

        Args:
            query: 初始查询（用于检索相关长期记忆）
            category: 可选的分类过滤

        Returns:
            完整的系统提示词（基础记忆 + 长期记忆）
        """
        # Performance: cache initial context per query
        cache_key = f"{query}::{category}"
        if hasattr(self, '_initial_context_cache') and self._initial_context_cache:
            if cache_key in self._initial_context_cache:
                return self._initial_context_cache[cache_key]

        # 1. 基础记忆（始终注入）
        core_memory = self.load_core_memory()

        # 2. 相关长期记忆（基于 query 检索）
        relevant_entries = self.search_knowledge(query, category)
        long_term_memories = [e.content for e in relevant_entries]

        # 3. 组合
        parts = [core_memory]
        if long_term_memories:
            parts.append("\n## 相关经验\n" + "\n\n".join(long_term_memories))

        result = "\n\n".join(parts)

        # Cache the result
        if not hasattr(self, '_initial_context_cache') or self._initial_context_cache is None:
            self._initial_context_cache = {}
        self._initial_context_cache[cache_key] = result
        return result

    def build_incremental_context(
        self,
        query: str,
        short_term_memory: str = "",
        category: str | None = None,
    ) -> str:
        """
        构建增量上下文（后续对话调用，不重复注入基础记忆）。

        基础记忆已在初始上下文注入，
        后续对话只注入增量部分（长期记忆 + 短期记忆 + 当前查询）。

        注意: 推荐使用 build_context(is_initial=False) 替代直接调用此方法。

        Args:
            query: 当前用户查询
            short_term_memory: 短期记忆（对话上下文）
            category: 可选的分类过滤

        Returns:
            增量上下文（不含基础记忆）
        """
        parts = []

        # 1. 相关长期记忆（基于 query 检索）
        relevant_entries = self.search_knowledge(query, category)
        if relevant_entries:
            parts.append("\n## 相关经验\n" + "\n\n".join(e.content for e in relevant_entries))

        # 2. 短期记忆（对话上下文）
        if short_term_memory:
            parts.append(f"\n## 对话上下文\n{short_term_memory}")

        # 3. 当前查询
        parts.append(f"\n## 当前任务\n{query}")

        return "\n\n".join(parts)

    # =========================================================================
    # 统计信息
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """获取基础层统计信息。"""
        index = self.load_knowledge_index()
        pending = self.get_pending_memories()

        return {
            "core_memory_size": len(self.load_core_memory()),
            "knowledge_entries": len(index.get("entries", [])),
            "pending_reviews": len(pending),
            "quota": self.quota.to_dict(),
            "injection_usage": self.injector.get_usage(),
        }
