# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""基础层记忆管理模块（v3：数据库是唯一真相层）。

**真相层 = ``memories`` 表。** 磁盘上的 ``knowledge_base/`` 只是投影
（``knowledge_export`` 全量幂等重建的导出物），供 kb 面发现与人工审阅，
**永远不是数据源**。

写入只有三条通道，都写 DB 并立刻刷新投影：

* 跨 Agent 晋升 → ``add_principle``（scope=workspace，全 workspace 共享）
* 进化/聊天侧条目 → ``add_memory``（接受注入层或仓库层条目）
* 用户"记下来" → ``add_note``（importance=1.0）

注入只有一条通道：``select_memories_for_injection`` → ``build_context``，
尺子用 ``agents.resources.contract.score_match``（与 kb 面同一把，含 CJK 二元组）。

人工审核岗已按"晋升全自动"铁律下线：机器决定准入/生效/淘汰，人只做
**事后可撤销**（软删 ``deleted_at``），撤销后该条既不进注入也不进投影。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..constant import (
    KNOWLEDGE_CATEGORY_QUOTA,
    KNOWLEDGE_INJECT_MAX_CHARS,
    KNOWLEDGE_INJECT_MIN_SCORE,
    KNOWLEDGE_INJECT_TOP_N,
    KNOWLEDGE_NOISE_SOURCES,
)
from . import knowledge_export
from .memory_entry import MemoryEntry
from .memory_injector import MemoryInjector
from .memory_quota import MemoryQuota
from .memory_repository import MemoryEntry as RepoMemoryEntry
from .memory_repository import ScopeType

logger = logging.getLogger(__name__)


class FoundationManager:
    """管理思维框架、共享知识与记忆注入。

    Args:
        foundation_dir: 记忆层根目录（运行时可写，实测
            ``WORKING_DIR/foundation``）。传代码目录会在容器重建时把写入清零，
            调用方负责传对（``agents/workspace.py``）。
        memory_repo: 注入用仓库实现（测试可替换）；默认走 ``RepositoryFactory``。
    """

    def __init__(self, foundation_dir: str, memory_repo: Any = None):
        self.foundation_dir = Path(foundation_dir)
        # 投影目录（只读导出物，允许被覆盖）
        self.knowledge_dir = self.foundation_dir / "knowledge_base"

        self._memory_repo = memory_repo
        self.quota = MemoryQuota()
        self.injector = MemoryInjector(self.quota)

        self._core_memory_cache: str | None = None
        self._thinking_patterns_cache: str | None = None
        self._knowledge_index_cache: dict | None = None

        self._core_injected = False
        self._initial_injected = False
        self._last_injection_time: datetime | None = None
        self._injection_count = 0
        #: 本轮实际注入的条目（引用溯源卡片用它回填）
        self._last_injected_items: list[dict[str, Any]] = []

        self._ensure_directory_structure()
        self._seed_static_templates()

    # ── 基础设施 ────────────────────────────────────────────────────

    @property
    def memory_repo(self) -> Any:
        """记忆仓库（懒取，取不到返回 None）。

        ``RepositoryFactory`` 未初始化时回落到 SQLite 实现；两条都失败时返回
        ``None``，调用方**必须**判空——记忆层坏了不能把聊天带崩。
        """
        if self._memory_repo is None:
            try:
                from .repository_factory import RepositoryFactory

                self._memory_repo = RepositoryFactory.get_memory_repository()
            except Exception:
                logger.debug("Foundation repo: factory unavailable", exc_info=True)
                try:
                    from .memory_repository_impl import SqlaMemoryRepository

                    self._memory_repo = SqlaMemoryRepository()
                except Exception:
                    logger.debug("Foundation repo: sqlite impl unavailable", exc_info=True)
                    self._memory_repo = None
        return self._memory_repo

    def _ensure_directory_structure(self) -> None:
        """建目录骨架（幂等）。分类子目录由投影自己建，这里不预设。"""
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        (self.foundation_dir / "shared_skills").mkdir(parents=True, exist_ok=True)

    def _seed_static_templates(self) -> None:
        """把仓库内的思维框架复制进运行时记忆层（存在即跳过）。"""
        if self.foundation_dir != knowledge_export.foundation_root():
            return  # 传的不是运行时根目录（测试/临时目录），不写模板
        try:
            knowledge_export.ensure_static_templates()
        except Exception:
            logger.debug("Foundation template seeding failed", exc_info=True)

    def reset_injection_state(self) -> None:
        """重置注入状态（新会话开始时调用）。"""
        self._core_injected = False
        self._initial_injected = False
        self._last_injection_time = None
        self._injection_count = 0
        self._last_injected_items = []

    @property
    def last_injected_items(self) -> list[dict[str, Any]]:
        """本轮实际注入的条目（引用溯源卡片用它回填）。"""
        return self._last_injected_items

    # ── 静态框架（仓库模板，非真相层） ──────────────────────────────

    def load_core_principles(self) -> str:
        """加载核心原则（``core_principles.md``）。"""
        if self._core_memory_cache is not None:
            return self._core_memory_cache

        path = self.foundation_dir / "core_principles.md"
        if path.exists():
            self._core_memory_cache = path.read_text(encoding="utf-8")
            return self._core_memory_cache
        return ""

    def load_thinking_patterns(self) -> str:
        """加载思维模式（``thinking_patterns.md``）。"""
        if self._thinking_patterns_cache is not None:
            return self._thinking_patterns_cache

        path = self.foundation_dir / "thinking_patterns.md"
        if path.exists():
            self._thinking_patterns_cache = path.read_text(encoding="utf-8")
            return self._thinking_patterns_cache
        return ""

    # ── 投影读侧（kb 面 / 知识索引） ────────────────────────────────

    def load_knowledge_index(self) -> dict:
        """读取投影索引（``knowledge_base/index.json``）。"""
        if self._knowledge_index_cache is not None:
            return self._knowledge_index_cache

        index_path = self.knowledge_dir / "index.json"
        if index_path.exists():
            try:
                self._knowledge_index_cache = json.loads(
                    index_path.read_text(encoding="utf-8"),
                )
                return self._knowledge_index_cache
            except (json.JSONDecodeError, OSError):
                logger.warning("Knowledge index load failed: %s", index_path)
        self._knowledge_index_cache = {"version": 1, "entries": []}
        return self._knowledge_index_cache

    def save_knowledge_index(self, index: dict) -> None:
        """写投影索引（仅供投影层自测/外部工具用；正常由导出负责）。"""
        self._knowledge_index_cache = index
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        index_path = self.knowledge_dir / "index.json"
        tmp = index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(index_path)

    def search_knowledge(
        self,
        query: str = "",
        category: str | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """在投影里检索知识（同一把尺子：``score_match``）。

        注意调用方历史上传的是 ``search_knowledge(category, limit=5)``
        （进化层向下同步），所以 ``limit`` 必须是关键字参数、第一位当查询用。
        """
        from ..agents.resources.contract import score_match

        index = self.load_knowledge_index()
        results: list[MemoryEntry] = []
        q = (query or "").strip()
        scored: list[tuple[float, dict]] = []
        for item in index.get("entries", []):
            if category and item.get("category") != category:
                continue
            text = f"{item.get('title', '')} {item.get('content', '')}"
            scored.append((score_match(q, text) if q else 1.0, item))
        scored.sort(key=lambda kv: kv[0], reverse=True)
        for score, item in scored[: max(1, int(limit))]:
            if q and score <= 0:
                continue
            results.append(MemoryEntry.from_dict(item))
        return results

    # ── 写入侧（唯一真相 = DB） ─────────────────────────────────────

    @staticmethod
    def _dedup_key(content: str) -> str:
        return hashlib.sha256((content or "").strip().encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _title_from(content: str) -> str:
        return (content or "").strip()[:60]

    def export_projection(self, force: bool = False) -> dict[str, Any]:
        """刷新文件投影（失败只记日志——投影坏了不影响主流程）。"""
        try:
            stats = knowledge_export.export_from_db(force=force)
            self.clear_cache()
            logger.info("Knowledge projection: %s", stats)
            return stats
        except Exception:
            logger.warning("Knowledge projection failed", exc_info=True)
            return {"error": "projection_failed"}

    def _write_memory(self, entry: RepoMemoryEntry) -> int | None:
        """写一行记忆并刷新投影。返回行 id，失败返回 None。"""
        repo = self.memory_repo
        if repo is None:
            logger.warning("Foundation write skipped (no memory repo): source=%s", entry.source)
            return None
        if not entry.dedup_key:
            entry.dedup_key = self._dedup_key(entry.content or entry.title or "")
        try:
            new_id = repo.add(entry)
        except Exception:
            logger.warning("Foundation memory write failed: source=%s", entry.source, exc_info=True)
            return None
        self.enforce_category_quota(entry)
        self.export_projection()
        return new_id

    def enforce_category_quota(self, entry: RepoMemoryEntry) -> int:
        """单用户单分类配额（D-3）：超限按 importance 归档最弱的。

        淘汰 = 归档（软删 ``deleted_at``），不是物理删除——撤销与审计都还看得见。
        只用仓库既有方法（list_entries + delete），不给 ABC 加新面。
        """
        quota = int(KNOWLEDGE_CATEGORY_QUOTA or 0)
        if quota <= 0:
            return 0
        repo = self.memory_repo
        if repo is None:
            return 0
        try:
            rows = repo.list_entries(
                scope=entry.scope,
                user_id=entry.user_id or "",
                category=entry.category,
                limit=quota + 100,
            )
        except Exception:
            logger.debug("Category quota read failed", exc_info=True)
            return 0
        if len(rows) <= quota:
            return 0
        rows.sort(key=lambda r: (float(r.importance or 0.0), r.id or 0))
        evicted = 0
        for row in rows[: len(rows) - quota]:
            if row.id is None:
                continue
            try:
                if repo.delete(row.id):
                    evicted += 1
            except Exception:
                logger.debug("Category quota evict failed (id=%s)", row.id, exc_info=True)
        if evicted:
            logger.info(
                "Category quota evicted: scope=%s user=%s cat=%s quota=%d -> %d archived",
                entry.scope, entry.user_id or "-", entry.category, quota, evicted,
            )
        return evicted

    def add_principle(
        self,
        principle: str,
        source_entry: Any = None,
        source_users: list[str] | None = None,
        category: str = "general",
        review_reason: str = "",
        session_id: str | None = None,
    ) -> int | None:
        """添加基础原则（跨 Agent 晋升 → workspace 共享层）。

        历史上这条通路是崩的：它写的是文件台账，且构造 ``MemoryEntry`` 时传了
        ``source=`` 这种注入层条目没有的参数（TypeError）。现在只写 DB 一行。
        """
        content = (principle or "").strip()
        if not content:
            logger.debug("add_principle: empty principle ignored")
            return None

        importance = self._importance_from_entry(source_entry)
        agent_id = (
            getattr(source_entry, "source_agent", None)
            or getattr(source_entry, "agent_id", None)
        )
        title = self._title_from(content)
        users = ",".join((source_users or [])[:5])
        logger.info(
            "add_principle: category=%s users=%s reason=%s",
            category, users or "-", review_reason or "-",
        )

        entry = RepoMemoryEntry(
            scope=ScopeType.WORKSPACE,
            user_id="",
            agent_id=agent_id,
            category=category,
            title=title,
            content=content,
            source="cross_agent_evolution",
            dedup_key=self._dedup_key(content),
            importance=importance,
            session_id=session_id or getattr(source_entry, "session_id", None),
        )
        new_id = self._write_memory(entry)
        logger.info(
            "add_principle: %s (id=%s, importance=%.2f)", title, new_id, importance,
        )
        return new_id

    @staticmethod
    def _importance_from_entry(source_entry: Any) -> float:
        """晋升强度取高：置信度 / 重要性 / 管理员确认，三者取最大。"""
        cands = [0.8]  # 人工审核已下线，机器晋升默认 0.8
        for attr in ("confidence", "importance", "priority_score"):
            v = getattr(source_entry, attr, None)
            if isinstance(v, (int, float)):
                cands.append(float(v))
        if source_entry is not None and (
            getattr(source_entry, "admin_confirmed", False)
            or getattr(source_entry, "status", "") == "promoted"
        ):
            cands.append(0.9)
        return max(0.0, min(1.0, max(cands)))

    def add_memory(self, entry: Any) -> int | None:
        """接受一条记忆并落库（兼容注入层 / 仓库层 / 进化层三种字段集）。

        历史上调用方传的是 ``foundation.memory_entry.MemoryEntry``，而本类
        **没有** ``add_memory`` → AttributeError → 审核通过必 500。这里做
        写入侧收敛：按名字逐个认字段，认不出的忽略，落 DB。
        """
        if isinstance(entry, RepoMemoryEntry):
            return self._write_memory(entry)

        content = str(getattr(entry, "content", "") or "").strip()
        if not content:
            logger.debug("add_memory: empty entry ignored")
            return None

        importance = self._importance_from_entry(entry)
        scope = ScopeType.AGENT if getattr(entry, "source_agent", "") else ScopeType.USER
        new_entry = RepoMemoryEntry(
            scope=str(getattr(entry, "scope", scope) or scope),
            user_id=str(getattr(entry, "source_user", getattr(entry, "user_id", "")) or ""),
            agent_id=getattr(entry, "source_agent", None) or None,
            category=str(getattr(entry, "category", "general") or "general"),
            title=self._title_from(content),
            content=content,
            source=str(getattr(entry, "source", "evolution") or "evolution"),
            dedup_key=self._dedup_key(content),
            importance=importance,
            session_id=(
                getattr(entry, "source_session", None)
                or getattr(entry, "session_id", None)
            ),
        )
        logger.debug(
            "add_memory: mapped source=%s type=%s",
            new_entry.source, getattr(entry, "memory_type", "?"),
        )
        return self._write_memory(new_entry)

    def add_note(
        self,
        content: str,
        user_id: str,
        agent_id: str | None = None,
        session_id: str | None = None,
        category: str = "notes",
    ) -> int | None:
        """"记下来"：用户显式要求沉淀的一条记忆（importance=1.0）。

        用户亲手点的条目是全库最强的信号，所以给满权重、不参与机器门槛。
        """
        text = (content or "").strip()
        if not text:
            return None
        return self._write_memory(RepoMemoryEntry(
            scope=ScopeType.USER,
            user_id=user_id,
            agent_id=agent_id,
            category=category,
            title=self._title_from(text),
            content=text,
            source="user_note",
            dedup_key=self._dedup_key(text),
            importance=1.0,
            session_id=session_id,
        ))

    def get_recent_memories(self, limit: int = 10) -> list[MemoryEntry]:
        """最近沉淀的记忆（转成注入层条目，供进化层向下同步）。"""
        repo = self.memory_repo
        if repo is None:
            return []
        out: list[MemoryEntry] = []
        try:
            for scope in (ScopeType.USER, ScopeType.AGENT, ScopeType.WORKSPACE):
                rows = repo.list_entries(scope=scope, user_id="", limit=limit)
                for row in rows:
                    out.append(MemoryEntry(
                        id=f"mem-{row.id}",
                        content=row.content or "",
                        memory_type="core",
                        category=row.category,
                        tags=[str(row.scope), row.category],
                        priority_score=float(row.importance or 0.0),
                        created_at=datetime.fromtimestamp(row.created_at or time.time()),
                        last_accessed_at=datetime.fromtimestamp(row.updated_at or time.time()),
                        source_agent=row.agent_id or "",
                        source_user=row.user_id or "",
                        source_session=row.session_id or "",
                    ))
        except Exception:
            logger.debug("get_recent_memories failed", exc_info=True)
            return []
        out.sort(key=lambda e: e.priority_score, reverse=True)
        return out[: max(1, int(limit))]

    # ── 注入（v3 的核心缺口：165 条沉淀此前对智能体完全隐形） ──────

    def select_memories_for_injection(
        self,
        query: str = "",
        user_id: str = "",
        agent_id: str | None = None,
        top_n: int | None = None,
        max_chars: int | None = None,
        min_score: float | None = None,
    ) -> list[dict[str, Any]]:
        """挑要注入的记忆：相关性（同一把尺子）× importance，配额裁剪。

        Returns:
            ``[{id, title, content, importance, score, scope, category, source,
            session_id}, ...]``，综合分降序；条数 ≤ ``KNOWLEDGE_INJECT_TOP_N``，
            正文总字符 ≤ ``KNOWLEDGE_INJECT_MAX_CHARS``。
        """
        repo = self.memory_repo
        if repo is None:
            return []

        top_n = int(top_n if top_n is not None else KNOWLEDGE_INJECT_TOP_N)
        max_chars = int(max_chars if max_chars is not None else KNOWLEDGE_INJECT_MAX_CHARS)
        min_score = float(min_score if min_score is not None else KNOWLEDGE_INJECT_MIN_SCORE)
        if top_n <= 0 or max_chars <= 0:
            # 引用账本与本轮注入必须同源：不注入就要清空，否则 citation 回填
            # 会拿到上一轮的条目（跨会话串味）。
            self._last_injected_items = []
            return []
        if not user_id and not agent_id:
            # 系统级调用（cron/心跳）没有归属用户：不灌共享知识，免得每条系统
            # 提示词都带上团队记忆，噪声且不可控。
            self._last_injected_items = []
            return []

        from ..agents.resources.contract import score_match

        q = (query or "").strip()
        try:
            rows = repo.list_injection_candidates(
                user_id=user_id or "", agent_id=agent_id, limit=max(top_n * 5, 30),
            )
        except Exception:
            logger.debug("Injection candidates load failed", exc_info=True)
            return []

        scored: list[tuple[float, Any]] = []
        for row in rows:
            # 机器维护日志（source=dream 的 status=success 那类）不是知识，不占
            # 注入位。与文件投影共用 KNOWLEDGE_NOISE_SOURCES 这一把尺子。
            if str(row.source or "") in KNOWLEDGE_NOISE_SOURCES:
                continue
            imp = float(row.importance or 0.0)
            if q:
                rel = score_match(q, f"{row.title or ''} {row.content or ''}")
                if rel < min_score:
                    continue
                score = rel * 0.7 + imp * 0.3
            else:
                score = imp
            scored.append((score, row))
        scored.sort(key=lambda kv: kv[0], reverse=True)

        picked: list[dict[str, Any]] = []
        budget = max_chars
        for score, row in scored:
            if len(picked) >= top_n:
                break
            content = (row.content or "").strip()
            if not content or len(content) > budget:
                continue
            budget -= len(content)
            picked.append({
                "id": row.id,
                "title": row.title or self._title_from(content),
                "content": content,
                "importance": imp,
                "score": round(score, 4),
                "scope": str(row.scope),
                "category": row.category,
                "source": row.source or "",
                "session_id": row.session_id or "",
            })
        # 引用账本与本轮注入同源：谁调这个函数，谁拿到的就是这一批（citation
        # 回填读 last_injected_items，不能只在 build_context 里记账）。
        self._last_injected_items = list(picked)
        if picked:
            logger.info(
                "Memory injection picked: %d of %d candidates (query=%r, chars_left=%d)",
                len(picked), len(rows), q[:24], budget,
            )
        return picked

    @staticmethod
    def render_injection_section(items: list[dict[str, Any]]) -> str:
        """注入段文本（引用溯源卡片同源回填）。"""
        if not items:
            return ""
        lines = [
            "## 已沉淀记忆",
            "",
            "以下为长期记忆中与当前任务最相关的条目（机器晋升，用户可撤销）：",
            "",
        ]
        for i, it in enumerate(items, 1):
            title = (it.get("title") or "").strip()
            body = (it.get("content") or "").strip()
            lines.append(f"{i}. {title}" if title else f"{i}. {body[:80]}")
            lines.append(f"   {body}")
        lines.append("")
        return "\n".join(lines)

    # ── 上下文构建 ──────────────────────────────────────────────────

    def build_context(
        self,
        is_initial: bool = False,
        query: str = "",
        user_id: str = "",
        agent_id: str | None = None,
    ) -> str:
        """构建记忆上下文（静态框架 + 开局注入的沉淀记忆）。"""
        parts: list[str] = []

        if is_initial and not self._core_injected:
            core = self.load_core_principles()
            patterns = self.load_thinking_patterns()
            if core:
                parts.append(f"# 基础原则\n{core}")
            if patterns:
                parts.append(f"# 思维模式\n{patterns}")
            self._core_injected = True
            self._injection_count += 1

        if is_initial and not self._initial_injected:
            picked = self.select_memories_for_injection(
                query=query, user_id=user_id, agent_id=agent_id,
            )
            section = self.render_injection_section(picked)
            if section:
                parts.append(section)
            self._last_injected_items = picked
            self._initial_injected = True

        if parts:
            self._last_injection_time = datetime.now()

        return "\n\n".join(parts) if parts else ""

    def build_initial_context(
        self,
        role: str = "user",
        user_id: str = "",
        agent_id: str | None = None,
    ) -> str:
        """构建首轮上下文（静态框架 + 知识库概览 + 沉淀记忆）。"""
        parts: list[str] = []

        core = self.load_core_principles()
        if core:
            parts.append(f"# 基础原则\n{core}")

        entries = self.load_knowledge_index().get("entries", [])
        if entries:
            parts.append(f"# 知识库概览 ({len(entries)} 条)")
            cats: dict[str, int] = {}
            for e in entries:
                cat = e.get("category", "general")
                cats[cat] = cats.get(cat, 0) + 1
            for cat, cnt in sorted(cats.items(), key=lambda kv: -kv[1]):
                parts.append(f"- {cat}: {cnt} 条")

        section = self.render_injection_section(
            self.select_memories_for_injection(user_id=user_id, agent_id=agent_id),
        )
        if section:
            parts.append(section)

        return "\n\n".join(parts) if parts else ""

    def build_incremental_context(self, query: str = "") -> str:
        """构建增量上下文（按查询相关性）。"""
        from ..agents.resources.contract import score_match

        q = (query or "").strip()
        relevant = []
        for item in self.load_knowledge_index().get("entries", []):
            text = f"{item.get('title', '')} {item.get('content', '')}"
            if q and score_match(q, text) > 0:
                relevant.append(item)
        relevant = relevant[:5]

        parts: list[str] = []
        for item in relevant:
            parts.append(f"## {item.get('title', '无标题')}")
            parts.append(item.get("content", ""))
        return "\n\n".join(parts) if parts else ""

    # ── 统计 / 缓存 ─────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """记忆层统计（DB 真相 + 投影状态 + 注入计数）。"""
        repo = self.memory_repo
        ledger: dict[str, Any] = {}
        if repo is not None:
            try:
                ledger = repo.stats(user_id="")
            except Exception:
                logger.debug("Ledger stats failed", exc_info=True)
        return {
            "core_memory_loaded": self._core_memory_cache is not None,
            "knowledge_entries": len(self.load_knowledge_index().get("entries", [])),
            "core_injected": self._core_injected,
            "injection_count": self._injection_count,
            "ledger": ledger,
            "projection": knowledge_export.verify_projection(),
        }

    def clear_cache(self) -> None:
        """清缓存（投影刷新后调用，避免读到旧 index）。"""
        self._core_memory_cache = None
        self._thinking_patterns_cache = None
        self._knowledge_index_cache = None


__all__ = ["FoundationManager", "get_foundation_manager"]


_shared_manager: FoundationManager | None = None


def get_foundation_manager(foundation_dir: str | None = None) -> FoundationManager:
    """进程内共享的 FoundationManager（读侧/注入侧用）。

    Workspace 各自持有实例（注入状态按 Agent 隔离），但聊天侧需要一条不依赖
    workspace 生命周期的读取通路，故提供单例；单例只做读与导出，不做业务写。
    """
    global _shared_manager
    if _shared_manager is None or (
        foundation_dir is not None
        and Path(foundation_dir) != _shared_manager.foundation_dir
    ):
        _shared_manager = FoundationManager(
            foundation_dir or knowledge_export.foundation_root(),
        )
    return _shared_manager
