# -*- coding: utf-8 -*-
"""Memory Timeline Repository abstraction layer.

Shared by Community (SQLite) and Enterprise (PostgreSQL) editions.
Schema: tech_docs/记忆系统整合设计方案.md §5.2.

Contract notes (binding for ALL implementations, community & enterprise):
- Every method is SYNCHRONOUS (``def``, never ``async def``); callers must
  NOT ``await`` them (same discipline as :class:`MemoryRepository`).
- ``append`` returns a plain ``int`` (the row id); duplicate signals
  (same user/session/signal_type/content) must NOT create a second row —
  it bumps importance (max-wins) and refreshes ``updated_at``.
- ``query`` returns ``(list[dict], total)`` ordered by
  ``created_at DESC, id DESC``; ``total`` is the pre-pagination count.
- Timestamps (``created_at`` / ``updated_at`` / ``deleted_at``) are Unix
  floats; ``deleted_at=None`` means alive.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class TimelineEntry:
    """In-memory representation of one memory_timelines row."""

    id: Optional[int] = None
    user_id: str = ""
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    signal_type: str = "conversation"
    content: Optional[str] = None
    source: Optional[str] = None
    dedup_key: Optional[str] = None
    importance: float = 0.5
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    deleted_at: Optional[float] = None
    promoted_at: Optional[float] = None  # None = 未晋升；非 None = 已写入 memories

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "signal_type": self.signal_type,
            "content": self.content,
            "source": self.source,
            "dedup_key": self.dedup_key,
            "importance": self.importance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
            "promoted_at": self.promoted_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TimelineEntry":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class MemoryTimelineRepository(ABC):
    """Abstract base class for memory timeline repositories."""

    # ── write ──

    @abstractmethod
    def append(self, entry: TimelineEntry) -> int:
        """Insert one timeline row (dedup-safe). Returns the row id."""

    # ── read ──

    @abstractmethod
    def query(
        self,
        *,
        user_id: str,
        signal_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict], int]:
        """Filtered listing (alive rows only), newest first.

        Returns ``(rows, total)`` where rows are plain dicts.
        """

    @abstractmethod
    def recent(self, *, user_id: str, hours: int = 24,
               limit: int = 100) -> List[Dict]:
        """Rows created within the trailing window, newest first."""

    # ── promotion (design §6: timeline → memories) ──

    @abstractmethod
    def promotion_candidates(
        self,
        *,
        user_id: str,
        min_importance: float = 0.6,
        max_age_days: int = 7,
        limit: int = 50,
    ) -> List[Dict]:
        """Unpromoted rows eligible for promotion into ``memories``.

        Eligibility (design §6): alive, ``signal_type`` in
        ``{decision, preference, goal}``, ``importance >= min_importance``,
        ``created_at`` within the trailing ``max_age_days``, and
        ``promoted_at IS NULL``. Newest first, capped at ``limit``.
        """

    @abstractmethod
    def mark_promoted(self, entry_ids: List[int], promoted_at: float) -> int:
        """Stamp ``promoted_at`` on the given rows. Returns rows touched."""

    # ── maintenance ──

    @abstractmethod
    def maintain(self, *, retention_days: int = 90) -> int:
        """Hard-delete rows older than the retention window.

        Returns the number of rows removed. Called nightly from the
        dream orchestration (design §5.2 step 5).
        """
