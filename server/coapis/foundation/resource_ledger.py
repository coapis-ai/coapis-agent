# -*- coding: utf-8 -*-
"""Resource ledger (R1, 清单面).

State table + reference table for the resource contract. See
``db/models/resources.py`` for why this is **not** merged into
``file_records`` (event stream vs. state table) and why ``resource_key``
carries the owner component.

Design rules (same as ``file_ledger``):

* **Fire-and-forget** — every public method swallows its own exceptions; a
  broken ledger must never break the message path.
* **Counts are derived** — reference counts come from ``resource_refs`` only;
  there is no stored counter.
* **Sweep is one-way (FS → DB)** — the sweep may mark ``fs_present`` and move
  statuses, it **never deletes filesystem files**. A reverse sweep would let
  the database delete user files, which is unacceptable.

Lifecycle (frozen, §6 of the contract):

    draft ──(用户确认/交付)──► official
      │                          │
      │                          ├──(会话删除 → refs 清空)──► orphan
      ├──(refs 空 + FS 存在)────► orphan
      └──(归档)─────────────────► archived
    orphan ──(被重新引用)────────► draft
    任意 ──(软删)────────────────► deleted (deleted_at 置位，FS 不动)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select

from ..constant import WORKSPACES_DIR
from .db.engine import get_session
from .db.models.resources import (
    VALID_KINDS,
    VALID_OWNER_SCOPES,
    VALID_REFERRER_KINDS,
    VALID_ROLES,
    VALID_STATUSES,
    Resource,
    ResourceRef,
    make_resource_key,
)

logger = logging.getLogger(__name__)


class ResourceLedger:
    def __init__(self, workspaces_dir: Optional[Path] = None) -> None:
        self._ws = Path(workspaces_dir) if workspaces_dir else WORKSPACES_DIR

    # ── internals ─────────────────────────────────────────────────────

    def _files_root(self, owner_id: str) -> Path:
        """Absolute root a ``kind=file`` path is relative to.

        Only ``user`` owners have a workspace files root; agent/workspace
        scoped resources keep their path as given and are not FS-verified.
        """
        return self._ws / owner_id / "files"

    def _abs_path(self, res: Resource) -> Optional[Path]:
        if res.kind != "file" or res.owner_scope != "user":
            return None
        return self._files_root(res.owner_id) / res.path

    def _count_refs(self, s, resource_key: str) -> int:
        return s.execute(
            select(func.count())
            .select_from(ResourceRef)
            .where(ResourceRef.resource_key == resource_key)
        ).scalar_one()

    # ── write ─────────────────────────────────────────────────────────

    def register(
        self,
        *,
        owner_scope: str,
        owner_id: str,
        kind: str,
        path: str,
        title: Optional[str] = None,
        source: str = "hook",
    ) -> str:
        """Register (or re-see) a resource; returns ``resource_key``.

        Idempotent: re-registering the same owner/kind/path refreshes
        ``last_seen_at`` / ``size_bytes`` and never creates a second row.
        Never raises — returns ``""`` on failure.
        """
        try:
            if owner_scope not in VALID_OWNER_SCOPES or kind not in VALID_KINDS:
                return ""
            owner_id = (owner_id or "").strip()
            path = (path or "").strip()
            if not owner_id or not path:
                return ""
            key = make_resource_key(owner_scope, owner_id, kind, path)
            now = time.time()
            with get_session() as s:
                res = s.execute(
                    select(Resource).where(Resource.resource_key == key)
                ).scalar_one_or_none()
                if res is None:
                    size = 0
                    p = self._abs_path_kind(kind, owner_id, path)
                    if p is not None and p.exists():
                        size = p.stat().st_size
                    s.add(
                        Resource(
                            resource_key=key,
                            owner_scope=owner_scope,
                            owner_id=owner_id,
                            kind=kind,
                            path=path,
                            title=title or None,
                            status="draft",
                            size_bytes=size,
                            fs_present=1,
                            first_seen_at=now,
                            last_seen_at=now,
                            updated_at=now,
                        )
                    )
                else:
                    res.last_seen_at = now
                    res.updated_at = now
                    if title:
                        res.title = title
                    if res.status == "deleted":
                        # Soft-deleted rows are resurrected on re-registration.
                        res.deleted_at = None
                        res.status = "draft"
            return key
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger register failed (ignored): %s", exc)
            return ""

    def _abs_path_kind(self, kind: str, owner_id: str, path: str) -> Optional[Path]:
        if kind == "file" and owner_id:
            return self._files_root(owner_id) / path
        return None

    def attach_ref(
        self,
        *,
        resource_key: str,
        referrer_kind: str,
        referrer_id: str,
        role: str = "reference",
    ) -> bool:
        """Attach a referrer. Idempotent (unique key). Never raises."""
        try:
            if referrer_kind not in VALID_REFERRER_KINDS or role not in VALID_ROLES:
                return False
            if not resource_key or not referrer_id:
                return False
            with get_session() as s:
                res = s.execute(
                    select(Resource).where(Resource.resource_key == resource_key)
                ).scalar_one_or_none()
                if res is None:
                    return False
                existing = s.execute(
                    select(ResourceRef)
                    .where(ResourceRef.resource_key == resource_key)
                    .where(ResourceRef.referrer_kind == referrer_kind)
                    .where(ResourceRef.referrer_id == referrer_id)
                ).scalar_one_or_none()
                if existing is None:
                    s.add(
                        ResourceRef(
                            resource_key=resource_key,
                            referrer_kind=referrer_kind,
                            referrer_id=referrer_id,
                            role=role,
                            created_at=time.time(),
                        )
                    )
                # orphan → draft on re-reference (frozen lifecycle).
                if res.status == "orphan":
                    res.status = "draft"
                    res.updated_at = time.time()
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger attach_ref failed (ignored): %s", exc)
            return False

    def detach_ref(
        self,
        *,
        resource_key: str,
        referrer_kind: str,
        referrer_id: str,
    ) -> bool:
        """Remove one referrer; moves the resource to ``orphan`` if refs empty.

        Unlike the file ledger, DELETE is allowed here: a reference is a
        relation, not an append-only event. The resource row itself is never
        deleted (soft delete only).
        """
        try:
            with get_session() as s:
                row = s.execute(
                    select(ResourceRef)
                    .where(ResourceRef.resource_key == resource_key)
                    .where(ResourceRef.referrer_kind == referrer_kind)
                    .where(ResourceRef.referrer_id == referrer_id)
                ).scalar_one_or_none()
                if row is None:
                    return False
                s.delete(row)
                # 必须 flush 再计数：同一 session 里 DELETE 尚未下发到 DB，
                # 直接 count 会把刚删掉的行算进去，refs 清空也判不出 orphan。
                s.flush()
                remaining = self._count_refs(s, resource_key)
                if remaining == 0:
                    res = s.execute(
                        select(Resource).where(Resource.resource_key == resource_key)
                    ).scalar_one_or_none()
                    if res is not None and res.status in ("draft", "official"):
                        res.status = "orphan"
                        res.updated_at = time.time()
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger detach_ref failed (ignored): %s", exc)
            return False

    def detach_refs_by_referrer(self, referrer_kind: str, referrer_id: str) -> int:
        """R2: release **all** refs of one referrer (a deleted chat/session).

        Returns the number of refs removed. Every resource left with zero refs
        moves to ``orphan`` (frozen lifecycle: 会话删除 → refs 清空 → orphan).
        Resource rows are never deleted here — only the relation goes away.
        Never raises.
        """
        if referrer_kind not in VALID_REFERRER_KINDS or not referrer_id:
            return 0
        try:
            with get_session() as s:
                rows = s.execute(
                    select(ResourceRef)
                    .where(ResourceRef.referrer_kind == referrer_kind)
                    .where(ResourceRef.referrer_id == referrer_id)
                ).scalars().all()
                if not rows:
                    return 0
                keys = {r.resource_key for r in rows}
                for r in rows:
                    s.delete(r)
                s.flush()  # DELETE must reach the DB before counting
                for key in keys:
                    if self._count_refs(s, key) == 0:
                        res = s.execute(
                            select(Resource).where(Resource.resource_key == key)
                        ).scalar_one_or_none()
                        if res is not None and res.status in ("draft", "official"):
                            res.status = "orphan"
                            res.updated_at = time.time()
                return len(rows)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger detach_refs failed (ignored): %s", exc)
            return 0

    def mark_status(self, resource_key: str, status: str) -> bool:
        """Move a resource to ``status``. Never raises."""
        try:
            if status not in VALID_STATUSES:
                return False
            with get_session() as s:
                res = s.execute(
                    select(Resource).where(Resource.resource_key == resource_key)
                ).scalar_one_or_none()
                if res is None:
                    return False
                res.status = status
                res.updated_at = time.time()
                if status == "deleted":
                    res.deleted_at = time.time()
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger mark_status failed (ignored): %s", exc)
            return False

    # ── sweep (FS → DB, one-way) ─────────────────────────────────────

    def sweep(self, *, full: bool = False) -> dict:
        """Reconcile the ledger against the filesystem. **Never deletes files.**

        Report keys:
        * ``fs_missing`` — ledger rows whose file is gone (``fs_present=0``)
        * ``fs_present`` — rows verified present
        * ``orphans`` — resources with zero refs (status moved to orphan)
        * ``unledgered`` — files on FS with no ledger row
        * ``fs_missing_list`` / ``orphan_list`` / ``unledgered_list`` — the
          three lists the contract requires the report to be able to *enumerate*
          (§6), capped at ``report_cap`` entries so the response stays bounded.
        """
        report = {
            "fs_missing": 0,
            "fs_present": 0,
            "orphans": 0,
            "unledgered": 0,
            "fs_missing_list": [],
            "orphan_list": [],
            "unledgered_list": [],
        }
        cap = 200
        try:
            with get_session() as s:
                rows = s.execute(
                    select(Resource)
                    .where(Resource.kind == "file")
                    .where(Resource.owner_scope == "user")
                    .where(Resource.deleted_at.is_(None))
                ).scalars().all()
                seen: dict[str, set[str]] = {}
                for res in rows:
                    p = self._abs_path(res)
                    present = p is not None and p.exists()
                    flag = 1 if present else 0
                    if res.fs_present != flag:
                        res.fs_present = flag
                        res.updated_at = time.time()
                    if present:
                        report["fs_present"] += 1
                        seen.setdefault(res.owner_id, set()).add(res.path)
                    else:
                        report["fs_missing"] += 1
                        if len(report["fs_missing_list"]) < cap:
                            report["fs_missing_list"].append(
                                {"owner_id": res.owner_id, "path": res.path,
                                 "resource_key": res.resource_key}
                            )
                    if self._count_refs(s, res.resource_key) == 0:
                        if res.status in ("draft", "official"):
                            res.status = "orphan"
                            res.updated_at = time.time()
                        report["orphans"] += 1
                        if len(report["orphan_list"]) < cap:
                            report["orphan_list"].append(
                                {"owner_id": res.owner_id, "path": res.path,
                                 "status": res.status,
                                 "resource_key": res.resource_key}
                            )

                if full:
                    for owner_id, root in self._user_file_roots():
                        if not root.exists():
                            continue
                        known = seen.get(owner_id, set())
                        for f in root.rglob("*"):
                            if f.is_file():
                                rel = f.relative_to(root).as_posix()
                                if rel not in known:
                                    report["unledgered"] += 1
                                    if len(report["unledgered_list"]) < cap:
                                        report["unledgered_list"].append(
                                            {"owner_id": owner_id, "path": rel}
                                        )
            return report
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger sweep failed (ignored): %s", exc)
            return report

    def _user_file_roots(self):
        """Yield (username, files_root) for every workspace on disk."""
        if not self._ws.exists():
            return
        for d in sorted(self._ws.iterdir()):
            if d.is_dir():
                yield d.name, d / "files"

    # ── read ──────────────────────────────────────────────────────────

    def list_resources(
        self,
        *,
        owner_scope: str,
        owner_id: str,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        chat_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Resources with derived ref counts. Never raises (returns []).

        ``chat_id`` filters through ``resource_refs`` (the only source of
        reference truth) instead of a denormalised column: a resource shows up
        for a chat only if that chat actually references it.
        """
        try:
            with get_session() as s:
                stmt = select(Resource).where(
                    Resource.owner_scope == owner_scope
                ).where(Resource.owner_id == owner_id)
                # 软删行不进默认清单（与 memories 的 deleted_at 惯例一致）。
                stmt = stmt.where(Resource.deleted_at.is_(None))
                if kind:
                    stmt = stmt.where(Resource.kind == kind)
                if status:
                    stmt = stmt.where(Resource.status == status)
                if chat_id:
                    ref_keys = (
                        select(ResourceRef.resource_key)
                        .where(ResourceRef.referrer_kind == "chat")
                        .where(ResourceRef.referrer_id == chat_id)
                    )
                    stmt = stmt.where(Resource.resource_key.in_(ref_keys))
                stmt = stmt.order_by(Resource.last_seen_at.desc()).limit(limit).offset(offset)
                rows = s.execute(stmt).scalars().all()
                out = []
                for r in rows:
                    d = r.to_dict()
                    d["ref_count"] = self._count_refs(s, r.resource_key)
                    out.append(d)
                return out
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger list failed (ignored): %s", exc)
            return []

    def count_resources(
        self,
        *,
        owner_scope: str,
        owner_id: str,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> int:
        """Total matching rows (pre-pagination). Filters mirror ``list_resources``.

        The paginated read面 returns ``limit`` rows; the UI needs the unpaginated
        total to render "还有 N 项未加载". If the two filter sets ever diverge the
        tail row lies, so this method is deliberately a copy of the same clauses.
        """
        try:
            with get_session() as s:
                stmt = select(func.count()).select_from(Resource).where(
                    Resource.owner_scope == owner_scope
                ).where(Resource.owner_id == owner_id).where(
                    Resource.deleted_at.is_(None)
                )
                if kind:
                    stmt = stmt.where(Resource.kind == kind)
                if status:
                    stmt = stmt.where(Resource.status == status)
                if chat_id:
                    ref_keys = (
                        select(ResourceRef.resource_key)
                        .where(ResourceRef.referrer_kind == "chat")
                        .where(ResourceRef.referrer_id == chat_id)
                    )
                    stmt = stmt.where(Resource.resource_key.in_(ref_keys))
                return int(s.execute(stmt).scalar() or 0)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger count failed (ignored): %s", exc)
            return 0

    def stats(self, *, owner_scope: str, owner_id: str) -> dict:
        """Status/kind breakdown plus orphan and FS-missing counts."""
        try:
            with get_session() as s:
                rows = s.execute(
                    select(Resource)
                    .where(Resource.owner_scope == owner_scope)
                    .where(Resource.owner_id == owner_id)
                    .where(Resource.deleted_at.is_(None))
                ).scalars().all()
                by_status: dict[str, int] = {}
                by_kind: dict[str, int] = {}
                orphans = 0
                for r in rows:
                    by_status[r.status] = by_status.get(r.status, 0) + 1
                    by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
                    if self._count_refs(s, r.resource_key) == 0:
                        orphans += 1
                return {
                    "total": len(rows),
                    "by_status": by_status,
                    "by_kind": by_kind,
                    "orphans": orphans,
                    "fs_missing": sum(1 for r in rows if r.fs_present == 0),
                }
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger stats failed (ignored): %s", exc)
            return {"total": 0, "by_status": {}, "by_kind": {}, "orphans": 0, "fs_missing": 0}


_LEDGER: Optional[ResourceLedger] = None


def get_resource_ledger() -> ResourceLedger:
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = ResourceLedger()
    return _LEDGER
