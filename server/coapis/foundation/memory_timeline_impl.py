# -*- coding: utf-8 -*-
"""SQLAlchemy implementation of :class:`MemoryTimelineRepository` (community).

Backed by the global engine (``COAPIS_DATABASE_URL`` or
``<DATA>/system/coapis.db``) — same discipline as
:class:`SqlaMemoryRepository`: synchronous methods, short-lived sessions,
``flush`` + explicit ``commit`` per operation.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Dict, List, Optional, Tuple

from sqlalchemy import delete, func, select, update

from .db.engine import get_session_factory
from .db.models.memory_timeline import MemoryTimeline
from .memory_timeline import MemoryTimelineRepository, TimelineEntry


def _normalize(text: Optional[str]) -> str:
    """Whitespace-free, lowercased normalization for dedup.

    All whitespace is dropped (not collapsed) so CJK text without meaningful
    spacing hashes identically: "决定 采用 方案A" == "决定采用方案A".
    """
    if not text:
        return ""
    return re.sub(r"\s+", "", text.strip()).lower()


def compute_timeline_dedup_key(user_id: str, session_id: Optional[str],
                               signal_type: str, content: Optional[str]) -> str:
    """sha256 over (user_id, session_id, signal_type, normalized content)."""
    raw = "|".join([
        user_id or "",
        session_id or "",
        signal_type,
        _normalize(content),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SqlaTimelineRepository(MemoryTimelineRepository):
    """Community-edition memory timeline repository (global engine)."""

    # ── write ──

    def append(self, entry: TimelineEntry) -> int:
        now = time.time()
        entry.dedup_key = compute_timeline_dedup_key(
            entry.user_id, entry.session_id, entry.signal_type, entry.content
        )
        sf = get_session_factory()
        with sf() as s:
            row = s.scalar(
                select(MemoryTimeline).where(
                    MemoryTimeline.dedup_key == entry.dedup_key
                ).limit(1)
            )
            if row is not None:
                # Dedup contract: bump importance (max-wins), touch updated_at.
                row.importance = max(float(row.importance or 0.0), entry.importance)
                row.updated_at = now
                row.deleted_at = None
                s.commit()
                return int(row.id)
            entry.created_at = entry.created_at or now
            entry.updated_at = now
            row = MemoryTimeline(**entry.to_dict())
            s.add(row)
            s.flush()
            s.commit()
            return int(row.id)

    # ── read ──

    def query(self, *, user_id: str, signal_type: Optional[str] = None,
              limit: int = 50, offset: int = 0) -> Tuple[List[Dict], int]:
        sf = get_session_factory()
        with sf() as s:
            stmt = select(MemoryTimeline).where(
                MemoryTimeline.user_id == user_id,
                MemoryTimeline.deleted_at.is_(None),
            )
            if signal_type:
                stmt = stmt.where(MemoryTimeline.signal_type == signal_type)
            total = int(
                s.scalar(
                    select(func.count()).select_from(stmt.subquery())
                ) or 0
            )
            rows = s.scalars(
                stmt.order_by(
                    MemoryTimeline.created_at.desc(), MemoryTimeline.id.desc()
                ).limit(max(1, int(limit))).offset(max(0, int(offset)))
            ).all()
            return ([r.to_dict() for r in rows], total)

    def recent(self, *, user_id: str, hours: int = 24,
               limit: int = 100) -> List[Dict]:
        cutoff = time.time() - max(1, int(hours)) * 3600.0
        sf = get_session_factory()
        with sf() as s:
            rows = s.scalars(
                select(MemoryTimeline).where(
                    MemoryTimeline.user_id == user_id,
                    MemoryTimeline.deleted_at.is_(None),
                    MemoryTimeline.created_at >= cutoff,
                ).order_by(
                    MemoryTimeline.created_at.desc(), MemoryTimeline.id.desc()
                ).limit(max(1, int(limit)))
            ).all()
            return [r.to_dict() for r in rows]

    # ── promotion (design §6: timeline → memories) ──

    #: Signal types that may be promoted into the memories ledger.
    PROMOTABLE_TYPES = ("decision", "preference", "goal")

    def promotion_candidates(
        self,
        *,
        user_id: str,
        min_importance: float = 0.6,
        max_age_days: int = 7,
        limit: int = 50,
    ) -> List[Dict]:
        cutoff = time.time() - max_age_days * 86400.0
        stmt = (
            select(MemoryTimeline)
            .where(
                MemoryTimeline.user_id == user_id,
                MemoryTimeline.deleted_at.is_(None),
                MemoryTimeline.promoted_at.is_(None),
                MemoryTimeline.signal_type.in_(self.PROMOTABLE_TYPES),
                MemoryTimeline.importance >= min_importance,
                MemoryTimeline.created_at >= cutoff,
            )
            .order_by(MemoryTimeline.created_at.desc(), MemoryTimeline.id.desc())
            .limit(max(1, int(limit)))
        )
        sf = get_session_factory()
        with sf() as s:
            rows = s.scalars(stmt).all()
        return [r.to_dict() for r in rows]

    def mark_promoted(self, entry_ids: List[int], promoted_at: float) -> int:
        if not entry_ids:
            return 0
        sf = get_session_factory()
        with sf() as s:
            res = s.execute(
                update(MemoryTimeline)
                .where(
                    MemoryTimeline.id.in_(list(entry_ids)),
                    MemoryTimeline.promoted_at.is_(None),
                )
                .values(promoted_at=promoted_at)
            )
            s.commit()
            return int(res.rowcount or 0)

    # ── maintenance ──

    def maintain(self, *, retention_days: int = 90) -> int:
        cutoff = time.time() - max(1, int(retention_days)) * 86400.0
        sf = get_session_factory()
        with sf() as s:
            res = s.execute(
                delete(MemoryTimeline).where(
                    MemoryTimeline.created_at < cutoff
                )
            )
            s.commit()
            return int(res.rowcount or 0)
