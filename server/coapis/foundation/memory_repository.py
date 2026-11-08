# -*- coding: utf-8 -*-
"""Memory Repository abstraction layer (unified long-term memory ledger).

Shared by Community (SQLite) and Enterprise (PostgreSQL) editions.
Schema: tech_docs/记忆能力升级-社区版可执行方案_v1.md §3.2.

Contract notes (binding for ALL implementations, community & enterprise):
- Every method is SYNCHRONOUS (``def``, never ``async def``); callers must
  NOT ``await`` them (same discipline as :class:`UserRepository`).
- ``add`` returns a plain ``int`` (the row id); duplicate content (same
  scope/category/title/content) must NOT create a second row — it bumps
  importance (max-wins) and refreshes ``updated_at`` (dedup contract).
- ``list_entries`` returns a plain ``list[dict]`` ordered by
  ``created_at DESC, id DESC``; ``total`` is the pre-pagination count.
- Timestamps (``created_at`` / ``updated_at`` / ``deleted_at``) are Unix
  floats; ``deleted_at=None`` means alive.
- Scope semantics:
  * ``user``      — personal memory (user_id required);
  * ``agent``     — shared by a user with one agent (user_id + agent_id);
  * ``workspace`` — shared across all users of a workspace (user_id=""
    sentinel; callers must pass ``""``).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class ScopeType(str, Enum):
    """Memory scope vocabulary (persisted as plain strings in ``scope``).

    ``str`` mixin keeps equality / SQL binding compatible with the
    string-valued column. See module docstring for scope semantics.
    """
    USER = "user"
    AGENT = "agent"
    WORKSPACE = "workspace"
    GLOBAL = "global"


@dataclass
class MemoryEntry:
    """In-memory representation of one memory row.

    Mirrors the ``memories`` table column-for-column.
    """
    id: Optional[int] = None
    scope: str = "user"
    user_id: str = ""
    agent_id: Optional[str] = None
    workspace_id: Optional[str] = None
    category: str = "fact"
    title: Optional[str] = None
    content: Optional[str] = None
    source: Optional[str] = None
    dedup_key: Optional[str] = None
    importance: float = 0.5
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    deleted_at: Optional[float] = None
    #: 溯源（迁移 0023）：这条记忆来自哪次会话。晋升链自带，聊天侧"记下来"自带。
    session_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scope": self.scope,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "workspace_id": self.workspace_id,
            "category": self.category,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "dedup_key": self.dedup_key,
            "importance": self.importance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class MemoryRepository(ABC):
    """Abstract base class for memory repositories (15-method surface)."""

    # ── write ──

    @abstractmethod
    def add(self, entry: MemoryEntry) -> int:
        """Insert a memory; dedup on (scope, category, title, content).

        Returns the row id (existing row when duplicated).
        """

    @abstractmethod
    def update_importance(self, entry_id: int, importance: float) -> bool:
        """Set importance (clamped 0..1 by callers); False if row gone."""

    @abstractmethod
    def merge(self, entry_ids: List[int]) -> int:
        """Merge several memories into one (kept = smallest id).

        Content concatenated in id order; importance = max; created_at =
        min; others soft-deleted. Returns the kept row id.
        """

    @abstractmethod
    def delete(self, entry_id: int) -> bool:
        """Soft-delete (sets deleted_at); False if row gone/already dead."""

    @abstractmethod
    def hard_delete(self, entry_id: int) -> bool:
        """Physically remove the row (admin escape hatch)."""

    @abstractmethod
    def restore(self, entry_id: int) -> bool:
        """Undo a soft delete (clears ``deleted_at``); False if not archived.

        治理页的「撤销归档」——人是事后撤销者，不是审批者。
        """

    # ── read ──

    @abstractmethod
    def get(self, entry_id: int, *, include_archived: bool = False) -> Optional[MemoryEntry]:
        """Entry by id, or None.

        ``include_archived=True`` 时软删记录也返回 —— 治理页撤销前要先看清
        「这条是谁的、在不在」，权限判断不能只看活着的行。
        """

    @abstractmethod
    def list_entries(
        self,
        *,
        scope: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        category: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MemoryEntry]:
        """Filtered listing (alive rows only), newest first.

        ``workspace_id`` (batch 2): restrict to entries owned by a
        workspace — the hook for organization-shared memory.
        """

    @abstractmethod
    def count(self, *, scope: Optional[str] = None, user_id: Optional[str] = None,
              agent_id: Optional[str] = None, workspace_id: Optional[str] = None,
              category: Optional[str] = None, q: Optional[str] = None) -> int:
        """Total matching alive rows (pre-pagination)."""

    @abstractmethod
    def find_similar(self, entry_id: int, limit: int = 5) -> List[MemoryEntry]:
        """Same-scope alive rows sharing >=1 word of the title (naive TF).

        Deterministic tie-break: importance DESC, created_at DESC, id ASC.
        """

    @abstractmethod
    def stats(self, *, scope: Optional[str] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Aggregate counts: total / by_category / by_source / avg_importance."""

    # ── 知识沉淀（方案 v3）──

    @abstractmethod
    def list_injection_candidates(
        self,
        *,
        user_id: str,
        agent_id: Optional[str] = None,
        limit: int = 300,
    ) -> List[MemoryEntry]:
        """本用户可注入的存活记忆全集（注入尺子的候选池）。

        口径 = 用户面 ∪ 自己拥有的智能体面 ∪ 全局面。全局面默认进池（它是
        机器晋升出来的公共知识，不是别人私有的），个人面严格隔离。
        """

    @abstractmethod
    def list_for_governance(
        self,
        *,
        user_id: str,
        scope: str | None = None,
        include_archived: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """治理列表：本人条目 + 共享层条目，含已撤销（``deleted_at``）记录。

        返回扁平 dict（治理页直接吃）：``id/scope/user_id/agent_id/session_id/
        category/title/content/importance/source/created_at/updated_at/
        deleted_at/archived``。``include_archived`` 默认 True —— "事后撤销"
        必须配"事后看得见"，否则撤销等于失忆。
        """

    @abstractmethod
    def count_for_governance(self, *, user_id: str, scope: str | None = None) -> int:
        """:meth:`list_for_governance` 的总数（分页页脚用）。"""

    # ── dream integration ──

    @abstractmethod
    def record_outcome(self, *, user_id: str, day: str, status: str,
                       reason: str, summary: str,
                       agent_id: str | None = None) -> int:
        """Upsert today's dream outcome row (category=dream, source=dream).

        Keyed by (user_id, day): re-running the same day overwrites
        status/reason/summary (updated_at bumped), never duplicates.
        Returns the row id.
        """
