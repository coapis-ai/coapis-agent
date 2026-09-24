# -*- coding: utf-8 -*-
"""SQLAlchemy external-identity repository (SSO bindings + external systems).

The SQLAlchemy successor of ``external_identity_store_sqlite.py`` — same
public interface, same dict contracts, same DDL (``external_bindings`` /
``external_systems`` mirror ``community_schema.sql`` column-for-column).

Dialect-neutral (D-13): no ``sqlite3`` specifics, no ``ON CONFLICT`` —
upserts are select-then-update-or-insert inside one session transaction,
which behaves identically on SQLite and PostgreSQL.

Wiring: ``RepositoryFactory.initialize()`` creates this store for
community deployments. All reads/writes go through the shared global
engine (``coapis.foundation.db.engine``).

Binding row mapping (DB columns ↔ community JSON keys) — unchanged:
    external_system  ↔ provider
    external_user_id ↔ external_id
    display_name     ↔ external_name
    extra_data       ↔ original community dict (lossless round-trip)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select

from .db.engine import get_session
from .db.models.external import ExternalBinding, ExternalSystem

logger = logging.getLogger(__name__)

# ── 键名契约（与旧 SqliteExternalIdentityStore 完全一致）──────────────

_COLUMN_KEYS = (
    "user_id", "provider", "external_id",
    "external_name", "display_name", "email", "created_at",
)

# ── 域A：external_systems 表字段 ─────────────────────────────
_SYSTEMS_COLUMNS = (
    "provider_id", "name", "icon", "description", "login_type", "sso",
    "status", "show_on_login", "display_order", "user_mapping", "client_id",
    "credential", "auth_mode", "base_urls", "identity_token_ttl", "extra_data",
    "created_at", "updated_at",
)
# 顶层直接映射到列的字段；其余（如 shared_secret_use_global / shared_secret）进 extra_data
_SYSTEMS_DIRECT = {
    "provider_id", "name", "icon", "description", "login_type", "sso",
    "status", "show_on_login", "display_order", "user_mapping", "client_id",
    "credential", "auth_mode", "base_urls", "identity_token_ttl",
    "created_at", "updated_at",
}


def _sys_dumps(value: Any, kind: str) -> str:
    if value is None:
        value = [] if kind == "list" else {}
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps([] if kind == "list" else {}, ensure_ascii=False)


def _sys_loads(text: Optional[str], kind: str) -> Any:
    if text is None or text == "":
        return [] if kind == "list" else {}
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return [] if kind == "list" else {}


def _sys_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else str(value)


def _orm_mapping(row: Any) -> Dict[str, Any]:
    """Build a plain dict from a query result row.

    Works for both ``sqlalchemy.Row`` (exposes ``._mapping``) and ORM
    entities (declarative ``Base`` subclasses expose ``__table__``).
    ``select(Entity).scalars()`` yields ORM objects which do NOT have
    ``._mapping`` — so we branch and fall back to the table columns.
    """
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


class SqlaExternalIdentityStore:
    """SQLAlchemy-backed external identity store (community edition).

    Same public API as the legacy ``SqliteExternalIdentityStore``:
    ``load_systems`` / ``get_system_by_id`` / ``save_systems`` /
    ``seed_systems`` / ``load_bindings`` / ``save_bindings`` / ``close``.
    """

    def __init__(self, db_url: Optional[str] = None) -> None:
        # ``db_url`` accepted for interface parity with the legacy store
        # (which took a ``db_path``); the engine is global
        # (COAPIS_DATABASE_URL / test URL / community default).
        self._db_url = db_url

    # ------------------------------------------------------------------
    # External systems (SSO)
    # ------------------------------------------------------------------

    def load_systems(self) -> List[Dict[str, Any]]:
        with get_session() as session:
            rows = session.execute(
                select(ExternalSystem).order_by(ExternalSystem.display_order)
            ).scalars().all()
        return [self._system_row_to_dict(r) for r in rows]

    def get_system_by_id(self, provider_id: str) -> Optional[Dict[str, Any]]:
        if not provider_id:
            return None
        with get_session() as session:
            row = session.execute(
                select(ExternalSystem).where(ExternalSystem.provider_id == provider_id)
            ).scalar_one_or_none()
        return self._system_row_to_dict(row) if row else None

    def save_systems(self, systems: List[Dict[str, Any]]) -> None:
        """Full replace of the system list — upserts each provided system
        (duplicates allowed, last wins) and removes any ``provider_id``
        not present in the input.

        Dialect-neutral upsert: select-then-update-or-insert inside a
        single session transaction (no sqlite ON CONFLICT).
        """
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        clean = [
            self._system_dict_to_row(s)
            for s in systems
            if isinstance(s, dict) and s.get("provider_id")
        ]
        provider_ids = {row["provider_id"] for row in clean}
        with get_session() as session:
            if not provider_ids:
                session.execute(delete(ExternalSystem))
            else:
                session.execute(
                    delete(ExternalSystem).where(
                        ExternalSystem.provider_id.not_in(provider_ids)
                    )
                )
                for row in clean:
                    existing = session.execute(
                        select(ExternalSystem).where(
                            ExternalSystem.provider_id == row["provider_id"]
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        for key, val in row.items():
                            if key != "provider_id":
                                setattr(existing, key, val)
                    else:
                        session.add(ExternalSystem(**row))
            session.commit()
        logger.info("external_systems saved: %d rows", len(clean))

    def seed_systems(self, systems: List[Dict[str, Any]]) -> int:
        """Insert systems without touching existing rows. Returns count inserted."""
        count = 0
        for system in systems or []:
            if not isinstance(system, dict) or not system.get("provider_id"):
                continue
            row = self._system_dict_to_row(system)
            with get_session() as session:
                existing = session.execute(
                    select(ExternalSystem).where(
                        ExternalSystem.provider_id == row["provider_id"]
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    count += 1  # parity with legacy INSERT OR IGNORE semantics
                    continue
                session.add(ExternalSystem(**row))
                session.commit()
                count += 1
        return count

    @staticmethod
    def _system_dict_to_row(system: Dict[str, Any]) -> Dict[str, Any]:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        out: Dict[str, Any] = {}
        extra: Dict[str, Any] = {}
        for key in _SYSTEMS_COLUMNS:
            if key == "extra_data":
                continue
            if key == "provider_id":
                out[key] = str(system.get("provider_id") or "")
            elif key in _SYSTEMS_DIRECT and key in system:
                out[key] = system[key]
            elif key == "name":
                out[key] = ""  # NOT NULL 且无 server_default，缺省补空串
            else:
                out[key] = None
        out["sso"] = _sys_dumps(system.get("sso"), "object")
        out["user_mapping"] = _sys_dumps(system.get("user_mapping"), "object")
        out["credential"] = _sys_dumps(system.get("credential"), "object")
        out["base_urls"] = _sys_dumps(system.get("base_urls"), "list")
        out["status"] = int(system.get("status", 1) or 1)
        out["show_on_login"] = int(bool(system.get("show_on_login", True)))
        out["display_order"] = int(system.get("display_order") or 0)
        out["created_at"] = _sys_text(system.get("created_at"))
        out["updated_at"] = _sys_text(system.get("updated_at")) or now
        # 保真：未直接映射到列的字段进 extra_data
        for key, val in system.items():
            if key not in _SYSTEMS_DIRECT and key != "extra_data":
                extra[key] = val
        merged_extra = _sys_loads(system.get("extra_data"), "object")
        if isinstance(merged_extra, dict):
            merged_extra.update(extra)
        out["extra_data"] = _sys_dumps(merged_extra, "object")
        return out

    @staticmethod
    def _system_row_to_dict(row: ExternalSystem) -> Dict[str, Any]:
        d = _orm_mapping(row)
        d["sso"] = _sys_loads(d.get("sso"), "object")
        d["user_mapping"] = _sys_loads(d.get("user_mapping"), "object")
        d["credential"] = _sys_loads(d.get("credential"), "object")
        d["base_urls"] = _sys_loads(d.get("base_urls"), "list")
        d["show_on_login"] = bool(d.get("show_on_login"))
        d["status"] = 1 if d.get("status") is None else int(d["status"])
        d["display_order"] = int(d.get("display_order") or 0)
        d["created_at"] = _sys_text(d.get("created_at"))
        d["updated_at"] = _sys_text(d.get("updated_at"))
        extra = _sys_loads(d.pop("extra_data", None), "object")
        if isinstance(extra, dict):
            d.update(extra)
        return d

    # ------------------------------------------------------------------
    # External bindings
    # ------------------------------------------------------------------

    def load_bindings(self) -> List[Dict[str, Any]]:
        with get_session() as session:
            rows = session.execute(
                select(ExternalBinding).order_by(
                    ExternalBinding.created_at, ExternalBinding.id
                )
            ).scalars().all()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = _orm_mapping(r)
            extra = _sys_loads(d.get("extra_data"), "object")
            if not isinstance(extra, dict):
                extra = {}
            # 兼容旧数据：迁移/老版本写入的行 extra_data 可能为空，
            # 缺 status 会导致 find_binding_by_external 永远查不到。
            merged = {
                "status": 1,
                "source": "manual",
                "last_login_at": None,
                "login_count": 0,
            }
            merged.update(extra)
            out.append(
                {
                    "user_id": d.get("user_id"),
                    "provider": d.get("external_system"),
                    "external_id": d.get("external_user_id"),
                    "external_name": d.get("display_name"),
                    "email": d.get("email"),
                    "created_at": _sys_text(d.get("created_at")),
                    **merged,
                }
            )
        return out

    def save_bindings(self, bindings: List[Dict[str, Any]]) -> None:
        """Full replace of all bindings (single transaction)."""
        clean: List[Dict[str, Any]] = []
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        for b in bindings or []:
            if not isinstance(b, dict):
                continue
            row = {
                "user_id": _sys_text(b.get("user_id")),
                "provider": _sys_text(b.get("provider")),
                "external_id": _sys_text(b.get("external_id")),
                "external_name": _sys_text(b.get("external_name") or b.get("display_name")),
                "email": _sys_text(b.get("email")),
                "created_at": _sys_text(b.get("created_at")) or now,
            }
            if not (row["user_id"] and row["provider"] and row["external_id"]):
                continue
            extra: Dict[str, Any] = {
                k: v for k, v in b.items() if k not in _COLUMN_KEYS
            }
            clean.append(
                {
                    "user_id": row["user_id"],
                    "external_system": row["provider"],
                    "external_user_id": row["external_id"],
                    "display_name": row["external_name"],
                    "email": row["email"],
                    "created_at": row["created_at"],
                    "extra_data": _sys_dumps(extra, "object"),
                }
            )
        # 防呆：同一 (external_system, external_user_id) 只保留最后一条
        # （最新写入优先），否则全量替换会撞 UNIQUE 约束直接 500。
        deduped: Dict[tuple, Dict[str, Any]] = {}
        for row in clean:
            deduped[(row["external_system"], row["external_user_id"])] = row
        clean = list(deduped.values())
        with get_session() as session:
            session.execute(delete(ExternalBinding))
            for row in clean:
                session.add(ExternalBinding(**row))
            session.commit()
        logger.info("external_bindings saved: %d rows", len(clean))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        # Sessions are per-call from the global engine — nothing to close,
        # and the shared engine must NOT be disposed here.
        return None
