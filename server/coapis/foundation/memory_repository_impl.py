# -*- coding: utf-8 -*-
"""SQLAlchemy implementation of :class:`MemoryRepository` (community edition).

Backed by the global engine (``COAPIS_DATABASE_URL`` or
``<DATA>/system/coapis.db``) — same discipline as
:class:`SqlaUserRepository`: synchronous methods, short-lived sessions,
``flush`` + explicit ``commit`` per operation.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select

from .db.engine import get_session_factory
from .db.models.memory import Memory
from .memory_repository import MemoryEntry, MemoryRepository


def _normalize(text: Optional[str]) -> str:
    """Whitespace-collapsed, lowercased normalization for dedup/tokens."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip()).lower()


def compute_dedup_key(scope: str, category: str, title: Optional[str],
                      content: Optional[str]) -> str:
    """sha256 over normalized (scope, category, title, content)."""
    raw = "|".join([
        scope,
        category,
        _normalize(title),
        _normalize(content),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_TOKEN_RE = re.compile(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{2,}")


def _tokens(text: Optional[str]) -> List[str]:
    """Naive tokenizer: latin/digit runs (len>=2) and CJK runs (len>=2)."""
    return _TOKEN_RE.findall(_normalize(text))


class SqlaMemoryRepository(MemoryRepository):
    """Community-edition memory repository (SQLite via global engine)."""

    # ── write ──

    def add(self, entry: MemoryEntry) -> int:
        now = time.time()
        entry.dedup_key = compute_dedup_key(
            entry.scope, entry.category, entry.title, entry.content
        )
        sf = get_session_factory()
        with sf() as s:
            row = s.scalar(select(Memory).where(Memory.dedup_key == entry.dedup_key))
            if row is not None:
                # Dedup contract: no second row — bump importance (max),
                # refresh updated_at, resurrect if soft-deleted.
                row.importance = max(row.importance or 0.0, entry.importance or 0.5)
                row.updated_at = now
                row.deleted_at = None
                row.source = entry.source or row.source
                row.title = entry.title or row.title
                row.content = entry.content or row.content
                s.commit()
                return int(row.id)
            row = Memory(
                scope=entry.scope,
                user_id=entry.user_id or "",
                agent_id=entry.agent_id,
                workspace_id=entry.workspace_id,
                category=entry.category,
                title=entry.title,
                content=entry.content,
                source=entry.source,
                dedup_key=entry.dedup_key,
                importance=float(entry.importance if entry.importance is not None else 0.5),
                created_at=entry.created_at or now,
                updated_at=now,
                deleted_at=None,
            )
            s.add(row)
            s.flush()
            s.commit()
            entry.id = row.id
            return int(row.id)

    def update_importance(self, entry_id: int, importance: float) -> bool:
        sf = get_session_factory()
        with sf() as s:
            row = s.get(Memory, int(entry_id))
            if row is None or row.deleted_at is not None:
                return False
            row.importance = max(0.0, min(1.0, float(importance)))
            row.updated_at = time.time()
            s.commit()
            return True

    def merge(self, entry_ids: List[int]) -> int:
        ids = sorted({int(i) for i in entry_ids if i is not None})
        if len(ids) < 2:
            return ids[0] if ids else 0
        sf = get_session_factory()
        with sf() as s:
            rows = [s.get(Memory, i) for i in ids]
            rows = [r for r in rows if r is not None and r.deleted_at is None]
            if len(rows) < 2:
                return rows[0].id if rows else (ids[0] if ids else 0)
            rows.sort(key=lambda r: r.id)
            kept = rows[0]
            merged_content = "\n\n".join(r.content or "" for r in rows).strip()
            kept.content = merged_content
            kept.importance = max(r.importance or 0.0 for r in rows)
            kept.created_at = min(r.created_at or time.time() for r in rows)
            kept.updated_at = time.time()
            for r in rows[1:]:
                r.deleted_at = time.time()
            s.commit()
            return int(kept.id)

    def delete(self, entry_id: int) -> bool:
        sf = get_session_factory()
        with sf() as s:
            row = s.get(Memory, int(entry_id))
            if row is None or row.deleted_at is not None:
                return False
            row.deleted_at = time.time()
            s.commit()
            return True

    def hard_delete(self, entry_id: int) -> bool:
        sf = get_session_factory()
        with sf() as s:
            row = s.get(Memory, int(entry_id))
            if row is None:
                return False
            s.delete(row)
            s.commit()
            return True

    # ── read ──

    def get(self, entry_id: int) -> Optional[MemoryEntry]:
        sf = get_session_factory()
        with sf() as s:
            row = s.get(Memory, int(entry_id))
            if row is None or row.deleted_at is not None:
                return None
            return self._to_entry(row)

    def _apply_filters(self, stmt, *, scope=None, user_id=None, agent_id=None,
                       category=None, q=None):
        """Append the alive-row filter set onto any SELECT over Memory."""
        stmt = stmt.where(Memory.deleted_at.is_(None))
        if scope is not None:
            stmt = stmt.where(Memory.scope == scope)
        if user_id is not None:
            stmt = stmt.where(Memory.user_id == user_id)
        if agent_id is not None:
            stmt = stmt.where(Memory.agent_id == agent_id)
        if category is not None:
            stmt = stmt.where(Memory.category == category)
        if q:
            like = f"%{_normalize(q)}%"
            stmt = stmt.where(or_(
                func.lower(Memory.title).like(like),
                func.lower(Memory.content).like(like),
            ))
        return stmt

    def list_entries(self, *, scope=None, user_id=None, agent_id=None,
                     category=None, q=None, limit=50, offset=0) -> List[MemoryEntry]:
        stmt = self._apply_filters(
            select(Memory), scope=scope, user_id=user_id, agent_id=agent_id,
            category=category, q=q)
        stmt = stmt.order_by(Memory.created_at.desc(), Memory.id.desc())
        stmt = stmt.limit(int(limit)).offset(int(offset))
        sf = get_session_factory()
        with sf() as s:
            rows = s.scalars(stmt).all()
            return [self._to_entry(r) for r in rows]

    def count(self, *, scope=None, user_id=None, agent_id=None,
              category=None, q=None) -> int:
        stmt = self._apply_filters(
            select(func.count()).select_from(Memory),
            scope=scope, user_id=user_id, agent_id=agent_id,
            category=category, q=q)
        sf = get_session_factory()
        with sf() as s:
            return int(s.scalar(stmt) or 0)

    def find_similar(self, entry_id: int, limit: int = 5) -> List[MemoryEntry]:
        sf = get_session_factory()
        with sf() as s:
            src = s.get(Memory, int(entry_id))
            if src is None:
                return []
            toks = _tokens(src.title)
            if not toks:
                return []
            conds = [Memory.title.ilike(f"%{t}%") for t in toks[:8]]
            stmt = (
                select(Memory)
                .where(Memory.deleted_at.is_(None))
                .where(Memory.id != src.id)
                .where(Memory.scope == src.scope)
                .where(or_(*conds))
                .order_by(Memory.importance.desc(), Memory.created_at.desc(),
                          Memory.id.asc())
                .limit(int(limit))
            )
            rows = s.scalars(stmt).all()
            return [self._to_entry(r) for r in rows]

    def stats(self, *, scope=None, user_id=None) -> Dict[str, Any]:
        sf = get_session_factory()
        with sf() as s:
            total = s.scalar(self._apply_filters(
                select(func.count()).select_from(Memory),
                scope=scope, user_id=user_id)) or 0
            by_cat = {}
            for cat, n in s.execute(self._apply_filters(
                    select(Memory.category, func.count()).select_from(Memory)
                    .group_by(Memory.category),
                    scope=scope, user_id=user_id)).all():
                by_cat[cat] = int(n)
            by_src = {}
            for src_val, n in s.execute(self._apply_filters(
                    select(Memory.source, func.count()).select_from(Memory)
                    .group_by(Memory.source),
                    scope=scope, user_id=user_id)).all():
                by_src[src_val or "unknown"] = int(n)
            avg_imp = s.scalar(self._apply_filters(
                select(func.avg(Memory.importance)), scope=scope, user_id=user_id))
            return {
                "total": int(total),
                "by_category": by_cat,
                "by_source": by_src,
                "avg_importance": round(float(avg_imp), 3) if avg_imp is not None else 0.0,
            }

    # ── dream integration ──

    def record_outcome(self, *, user_id: str, day: str, status: str,
                       reason: str, summary: str) -> int:
        now = time.time()
        title = f"dream:{day}"
        dedup = compute_dedup_key("user", "dream", title, f"{status}|{reason}")
        sf = get_session_factory()
        with sf() as s:
            row = s.scalar(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.category == "dream",
                    Memory.title == title,
                ).order_by(Memory.id.desc()).limit(1)
            )
            # status/reason ride in content (stable columns only).
            payload = f"status={status}; reason={reason}; summary={summary}"
            if row is not None:
                row.content = payload
                row.source = "dream"
                row.dedup_key = dedup
                row.importance = 1.0 if status == "success" else 0.5
                row.updated_at = now
                row.deleted_at = None
                s.commit()
                return int(row.id)
            row = Memory(
                scope="user",
                user_id=user_id,
                agent_id=None,
                workspace_id=None,
                category="dream",
                title=title,
                content=payload,
                source="dream",
                dedup_key=dedup,
                importance=1.0 if status == "success" else 0.5,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            s.add(row)
            s.flush()
            s.commit()
            return int(row.id)

    # ── helpers ──

    @staticmethod
    def _to_entry(row: Memory) -> MemoryEntry:
        return MemoryEntry(
            id=row.id,
            scope=row.scope,
            user_id=row.user_id,
            agent_id=row.agent_id,
            workspace_id=row.workspace_id,
            category=row.category,
            title=row.title,
            content=row.content,
            source=row.source,
            dedup_key=row.dedup_key,
            importance=row.importance,
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
        )
