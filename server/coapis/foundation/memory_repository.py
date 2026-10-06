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
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class MemoryRepository(ABC):
    """Abstract base class for memory repositories (12-method surface)."""

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

    # ── read ──

    @abstractmethod
    def get(self, entry_id: int) -> Optional[MemoryEntry]:
        """Alive entry by id, or None."""

    @abstractmethod
    def list_entries(
        self,
        *,
        scope: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        category: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MemoryEntry]:
        """Filtered listing (alive rows only), newest first."""

    @abstractmethod
    def count(self, *, scope: Optional[str] = None, user_id: Optional[str] = None,
              agent_id: Optional[str] = None, category: Optional[str] = None,
              q: Optional[str] = None) -> int:
        """Total matching alive rows (pre-pagination)."""

    @abstractmethod
    def find_similar(self, entry_id: int, limit: int = 5) -> List[MemoryEntry]:
        """Same-scope alive rows sharing >=1 word of the title (naive TF).

        Deterministic tie-break: importance DESC, created_at DESC, id ASC.
        """

    @abstractmethod
    def stats(self, *, scope: Optional[str] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Aggregate counts: total / by_category / by_source / avg_importance."""

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
