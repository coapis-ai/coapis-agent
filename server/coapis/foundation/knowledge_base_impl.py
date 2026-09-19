"""SQLite/SQLAlchemy 知识库仓储实现（社区版）。

替代 JsonKnowledgeBaseRepository：数据存 knowledge_bases 表，
通过 RepositoryFactory 注入，接口与 repository.py 的
KnowledgeBaseRepository 完全一致。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from .repository import KnowledgeBase

logger = logging.getLogger(__name__)

_TABLE = "knowledge_bases"

_COLS = (
    "id, name, description, scope, status, created_at, updated_at, "
    "metadata, department_id, visibility, tenant_id, created_by, updated_by"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqlaKnowledgeBaseRepository:
    """Community knowledge-base repository backed by the ``knowledge_bases`` table."""

    def __init__(self, session_factory=None) -> None:
        if session_factory is None:
            from .db.engine import get_session_factory

            session_factory = get_session_factory()
        self._sf = session_factory

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _row_to_kb(row) -> KnowledgeBase:
        d = dict(row)
        raw_md = d.get("metadata")
        try:
            metadata = json.loads(raw_md) if isinstance(raw_md, str) else (raw_md or {})
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        return KnowledgeBase(
            id=d["id"],
            name=d.get("name") or "",
            description=d.get("description") or "",
            scope=d.get("scope") or "user",
            status=d.get("status") or "active",
            created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(d["updated_at"]) if d.get("updated_at") else datetime.now(timezone.utc),
            metadata=metadata if isinstance(metadata, dict) else {},
            department_id=d.get("department_id"),
            visibility=d.get("visibility"),
            tenant_id=d.get("tenant_id"),
            created_by=d.get("created_by"),
            updated_by=d.get("updated_by"),
        )

    @staticmethod
    def _kb_params(kb: KnowledgeBase) -> dict:
        def _iso(v) -> str:
            if v is None:
                return _now()
            if isinstance(v, str):
                try:
                    return datetime.fromisoformat(v).isoformat()
                except ValueError:
                    return v
            return v.astimezone(timezone.utc).isoformat()

        return {
            "id": kb.id,
            "name": kb.name,
            "description": kb.description,
            "scope": kb.scope,
            "status": kb.status,
            "created_at": _iso(kb.created_at),
            "updated_at": _iso(kb.updated_at),
            "metadata": json.dumps(kb.metadata or {}, ensure_ascii=False),
            "department_id": kb.department_id,
            "visibility": kb.visibility,
            "tenant_id": kb.tenant_id,
            "created_by": kb.created_by,
            "updated_by": kb.updated_by,
        }

    # -- interface ----------------------------------------------------------

    def list(
        self,
        scope: str | None = None,
        status: str | None = None,
        department_id: str | None = None,
        visibility: str | None = None,
    ) -> list[KnowledgeBase]:
        where: list[str] = []
        params: dict = {}
        if scope is not None:
            where.append("scope = :scope")
            params["scope"] = scope
        if status is not None:
            where.append("status = :status")
            params["status"] = status
        if department_id is not None:
            where.append("department_id = :dept")
            params["dept"] = department_id
        if visibility is not None:
            where.append("visibility = :vis")
            params["vis"] = visibility
        sql = f"SELECT {_COLS} FROM {_TABLE}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC"
        with self._sf() as session:
            rows = session.execute(text(sql), params).mappings().all()
        return [self._row_to_kb(r) for r in rows]

    def get(self, kb_id: str) -> KnowledgeBase | None:
        with self._sf() as session:
            row = session.execute(
                text(f"SELECT {_COLS} FROM {_TABLE} WHERE id = :id"),
                {"id": kb_id},
            ).mappings().first()
        return self._row_to_kb(row) if row else None

    def create(self, kb: KnowledgeBase) -> KnowledgeBase:
        if not kb.id:
            kb.id = uuid.uuid4().hex
        now = _now()
        kb.created_at = kb.created_at or datetime.now(timezone.utc)
        kb.updated_at = kb.updated_at or kb.created_at
        p = self._kb_params(kb)
        p["created_at"] = p["created_at"] or now
        p["updated_at"] = p["updated_at"] or p["created_at"]
        with self._sf() as session:
            session.execute(
                text(
                    f"INSERT INTO {_TABLE} "
                    f"(id, name, description, scope, status, created_at, updated_at, "
                    f"metadata, department_id, visibility, tenant_id, created_by, updated_by) "
                    f"VALUES (:id, :name, :description, :scope, :status, :created_at, "
                    f":updated_at, :metadata, :department_id, :visibility, :tenant_id, "
                    f":created_by, :updated_by)"
                ),
                p,
            )
            session.commit()
        logger.info("Knowledge base created: id=%s name=%s", kb.id, kb.name)
        return kb

    def update(self, kb_id: str, updates: dict) -> KnowledgeBase | None:
        existing = self.get(kb_id)
        if existing is None:
            return None
        for key, value in updates.items():
            if value is None:
                continue
            if hasattr(existing, key):
                setattr(existing, key, value)
        existing.updated_at = datetime.now(timezone.utc)
        p = self._kb_params(existing)
        with self._sf() as session:
            session.execute(
                text(
                    f"UPDATE {_TABLE} SET name=:name, description=:description, "
                    f"scope=:scope, status=:status, updated_at=:updated_at, "
                    f"metadata=:metadata, department_id=:department_id, "
                    f"visibility=:visibility, tenant_id=:tenant_id, "
                    f"created_by=:created_by, updated_by=:updated_by WHERE id=:id"
                ),
                p,
            )
            session.commit()
        logger.info("Knowledge base updated: id=%s fields=%s", kb_id, list(updates.keys()))
        return existing

    def delete(self, kb_id: str) -> bool:
        with self._sf() as session:
            result = session.execute(
                text(f"DELETE FROM {_TABLE} WHERE id = :id"),
                {"id": kb_id},
            )
            session.commit()
        deleted = result.rowcount > 0
        if deleted:
            logger.info("Knowledge base deleted: id=%s", kb_id)
        return deleted

    def count(self) -> int:
        with self._sf() as session:
            row = session.execute(
                text(f"SELECT COUNT(*) AS c FROM {_TABLE}")
            ).mappings().first()
        return int(row["c"]) if row else 0
