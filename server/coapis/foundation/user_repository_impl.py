# -*- coding: utf-8 -*-
"""SQLAlchemy implementation of ``UserRepository`` (community edition).

Drop-in replacement for the hand-written ``user_repository_sqlite.py``:
same ABC, same dict contract (every user method returns the raw ``users``
row as a dict — password hash and all, consumers depend on it), same
semantics (hard delete, no ``is_active`` filter on list/users_exists,
audit ``details`` stored as JSON, token usage keyed by username/agent).

Persistence layer is the only difference: one short-lived SQLAlchemy
session per call instead of a long-lived ``sqlite3`` connection, which
also removes the ``check_same_thread`` / cross-thread connection problem.
Database-agnostic per D-13: no sqlite3, no ``executescript``.
"""

from __future__ import annotations

import json
import logging
import time
import uuid as uuid_mod
from typing import Any, Dict, List, Optional

import hashlib

from sqlalchemy import delete, func, insert, or_, select, update

from .db.engine import get_session_factory, init_engine
from .db.models.user import AuditLog, User, UserPreference, UserSetting
from .db.models.usage import PointTransaction, TokenUsage
from .user_repository import UserRepository

logger = logging.getLogger(__name__)


def _gen_user_id() -> str:
    """Generate a new UUID hex string for a user."""
    return str(uuid_mod.uuid4())


def _hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hash password.

    New passwords use bcrypt (salt embedded in the hash, no separate salt
    column required); the legacy SHA-256 path is kept for verifying
    pre-existing records. Mirrors ``user_system/service.py::_hash_password``
    — the two implementations must stay in sync.
    """
    if salt is None:
        import bcrypt

        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        return hashed.decode("utf-8"), "$2b$"
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return h, salt


def _normalize_id(user_id: Any) -> str:
    """Convert int (legacy) or str to UUID hex string."""
    if user_id is None:
        return ""
    if isinstance(user_id, int):
        return str(uuid_mod.UUID(int=user_id))
    return str(user_id)


# Columns in the users table (for filtering INSERT/UPDATE)
_USER_COLUMNS = frozenset(c.name for c in User.__table__.columns)




class SqlaUserRepository(UserRepository):
    """SQLAlchemy-backed user repository (community default)."""

    def __init__(self, db_url: Optional[str] = None) -> None:
        # ``db_url``: optional override (tests / multi-DB). ``None`` →
        # engine default (COAPIS_DATABASE_URL or <data_dir>/system/coapis.db).
        self._db_url = db_url
        self._sf_cache: Optional["sessionmaker[Session]"] = None

    # ------------------------------------------------------------------
    # Session plumbing
    # ------------------------------------------------------------------

    @property
    def _sf(self):
        """The bound session factory (a ``sessionmaker``).

        Callers use it as ``with self._sf() as session:`` — each call
        creates a fresh ``Session``; the session is closed on block exit.
        """
        if self._sf_cache is None:
            if self._db_url:
                init_engine(self._db_url)
            self._sf_cache = get_session_factory()
        return self._sf_cache

    def _session_factory(self) -> "sessionmaker[Session]":
        """Return the bound ``sessionmaker`` (test/external contract).

        Usable as ``repo._session_factory()()`` to open a fresh Session.
        """
        return self._sf

    @staticmethod
    def _row_dict(row: Any) -> Dict[str, Any]:
        """Full-column dict for a ``users`` row (same shape as ``SELECT *``).

        SQLAlchemy 2.0 gotcha: ``Session.execute(select(Entity))`` returns
        *ORM-enabled* rows whose ``_mapping`` is keyed by the **entity class**
        (``{User: <User>}``), not by column name — a naive ``dict(row._mapping)``
        yields ``{'User': ...}`` and every ``row["id"]`` lookup KeyErrors.
        Plain ORM instances (``.scalars()`` results) have no ``_mapping`` at
        all. So: instance → map via ``__mapper__.column_attrs``; Row → core
        string keys pass through, ORM rows extract the entity first.
        """
        if row is None:
            return None
        if hasattr(row, "_sa_instance_state"):  # plain ORM instance
            inst = row
        elif hasattr(row, "_mapping"):
            m = row._mapping
            # ORM-enabled single-entity row: _mapping is keyed by the entity
            # class name (a *string*, e.g. 'User'), value = the instance.
            vals = list(m.values())
            if len(vals) == 1 and hasattr(vals[0], "_sa_instance_state"):
                inst = vals[0]
            else:  # core Row with string column keys
                d = dict(m)
                d["password"] = None
                return d
        else:
            d = dict(row)
            d["password"] = None
            return d
        if inst is None:
            return None
        d = {c.key: getattr(inst, c.key) for c in inst.__mapper__.column_attrs}
        # 明文密码永不入库；对外统一置 None，消费方不得依赖明文。
        d["password"] = None
        return d

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_user(self, user_data: Dict[str, Any]) -> str:
        user_id = user_data.get("id") or _gen_user_id()
        user_id = _normalize_id(user_id)
        now = time.time()

        # Handle plaintext password → hash. Uniformly bcrypt (salt embedded
        # in the hash) via the module-local _hash_password, matching
        # app/user_store.py and the enterprise PG repository. Legacy
        # SHA-256 rows remain verifiable by the dual-mode verify_password.
        if "password" in user_data and "password_hash" not in user_data:
            pw_hash, salt_marker = _hash_password(user_data.pop("password"))
            user_data["password_hash"] = pw_hash
            user_data["salt"] = salt_marker
        # Remove plaintext password if present alongside hash
        user_data.pop("password", None)
        user_data.setdefault("created_at", now)
        user_data.setdefault("updated_at", now)
        user_data["id"] = user_id
        user_data["is_active"] = 1 if user_data.get("is_active", True) else 0

        data = {k: v for k, v in user_data.items() if k in _USER_COLUMNS}
        with self._sf() as session:
            session.execute(insert(User).values(data))
            session.commit()
        return user_id

    def get_user_by_id(self, user_id: Any) -> Optional[Dict[str, Any]]:
        uid = _normalize_id(user_id)
        if not uid:
            return None
        with self._sf() as session:
            row = session.execute(select(User).where(User.id == uid)).first()
            return self._row_dict(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        with self._sf() as session:
            row = session.execute(select(User).where(User.username == username)).first()
            return self._row_dict(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        if not email:
            return None
        with self._sf() as session:
            row = session.execute(select(User).where(User.email == email)).first()
            return self._row_dict(row) if row else None

    def update_user(self, username: str, update_data: Dict[str, Any]) -> bool:
        """Update a user's fields by username."""
        if not username:
            return False
        user = self.get_user_by_username(username)
        if not user:
            return False
        return self._update_user_fields(user["id"], update_data)

    def update_user_by_id(self, user_id: Any, update_data: Dict[str, Any]) -> bool:
        """Update a user's fields by user_id."""
        uid = _normalize_id(user_id)
        if not uid:
            return False
        return self._update_user_fields(uid, update_data)

    def _update_user_fields(self, uid: str, update_data: Dict[str, Any]) -> bool:
        fields: Dict[str, Any] = {}
        for key, value in update_data.items():
            if key not in _USER_COLUMNS or key == "id":
                continue
            if key == "is_active":
                value = 1 if value else 0
            fields[key] = value
        if not fields:
            return False
        fields["updated_at"] = time.time()
        with self._sf() as session:
            result = session.execute(update(User).where(User.id == uid).values(**fields))
            session.commit()
        return result.rowcount > 0

    def delete_user(self, username: str) -> bool:
        user = self.get_user_by_username(username)
        if not user:
            return False
        return self._delete_by_id(user["id"])

    def delete_user_by_id(self, user_id: Any) -> bool:
        return self._delete_by_id(_normalize_id(user_id))

    def _delete_by_id(self, uid: str) -> bool:
        if not uid:
            return False
        with self._sf() as session:
            result = session.execute(delete(User).where(User.id == uid))
            session.commit()
        return result.rowcount > 0

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_users(self) -> List[Dict[str, Any]]:
        with self._sf() as session:
            rows = (
                session.execute(select(User).order_by(User.created_at.desc()))
                .scalars()
                .all()
            )
            return [self._row_dict(r) for r in rows]

    def list_users_page(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
    ) -> tuple:
        """Return (users, total) for the given page.

        ``search`` matches username, email, and display_name (case-insensitive
        via SQLite's LIKE on ASCII; full-text search would need FTS).
        """
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size

        stmt = select(User)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(
                or_(
                    User.username.like(like),
                    User.email.like(like),
                    User.display_name.like(like),
                )
            )

        with self._sf() as session:
            total = session.execute(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            ).scalar() or 0
            rows = (
                session.execute(
                    stmt.order_by(User.created_at.desc()).offset(offset).limit(page_size)
                )
                .scalars()
                .all()
            )
        return [self._row_dict(r) for r in rows], total

    def user_exists(self, username: str) -> bool:
        with self._sf() as session:
            return (
                session.execute(
                    select(func.count()).select_from(User).where(User.username == username)
                ).scalar()
                or 0
            ) > 0

    def email_exists(self, email: str) -> bool:
        if not email:
            return False
        with self._sf() as session:
            return (
                session.execute(
                    select(func.count()).select_from(User).where(User.email == email)
                ).scalar()
                or 0
            ) > 0

    def count_users(self) -> int:
        with self._sf() as session:
            return session.execute(select(func.count()).select_from(User)).scalar() or 0

    def count_active_users(self) -> int:
        with self._sf() as session:
            return (
                session.execute(
                    select(func.count()).select_from(User).where(User.is_active == 1)
                ).scalar()
                or 0
            )

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------

    def insert_audit_log(
        self,
        user_id: Any,
        username: str,
        action: str,
        resource_type: str = "",
        resource_id: str = "",
        details: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
        user_agent: str = "",
    ) -> None:
        with self._sf() as session:
            session.execute(
                insert(AuditLog).values(
                    user_id=_normalize_id(user_id) or None,
                    username=username,
                    action=action,
                    resource_type=resource_type or None,
                    resource_id=resource_id or None,
                    details=json.dumps(details, ensure_ascii=False) if details else None,
                    ip_address=ip_address or None,
                    user_agent=user_agent or None,
                    created_at=time.time(),
                )
            )
            session.commit()

    def insert_point_transaction(
        self,
        user_id: Any,
        amount: int,
        balance_after: int,
        transaction_type: str,
        description: str = "",
        reference_id: str = "",
    ) -> None:
        with self._sf() as session:
            session.execute(
                insert(PointTransaction).values(
                    user_id=_normalize_id(user_id),
                    amount=amount,
                    balance_after=balance_after,
                    transaction_type=transaction_type,
                    description=description,
                    reference_id=reference_id,
                    created_at=time.time(),
                )
            )
            session.commit()

    def insert_token_usage(
        self,
        user_id: Any,
        username: str,
        agent_id: Optional[str],
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cost_cents: float = 0.0,
    ) -> None:
        with self._sf() as session:
            session.execute(
                insert(TokenUsage).values(
                    user_id=_normalize_id(user_id),
                    username=username,
                    agent_id=agent_id,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cost_cents=cost_cents,
                    created_at=time.time(),
                )
            )
            session.commit()

    # ------------------------------------------------------------------
    # Token usage
    # ------------------------------------------------------------------

    def get_user_token_usage(
        self,
        username: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        from datetime import datetime

        stmt = select(TokenUsage).where(TokenUsage.username == username)
        if start_date:
            stmt = stmt.where(TokenUsage.created_at >= datetime.strptime(start_date, "%Y-%m-%d").timestamp())
        if end_date:
            end_ts = datetime.strptime(end_date, "%Y-%m-%d").timestamp() + 86399.999
            stmt = stmt.where(TokenUsage.created_at < end_ts)

        with self._sf() as session:
            records = (
                session.execute(stmt)
                .scalars()
                .all()
            )

        if not records:
            return {"username": username, "total_input_tokens": 0, "total_output_tokens": 0,
                    "total_tokens": 0, "total_cost_cents": 0.0, "total_calls": 0, "top_models": []}

        total_in = sum(r.input_tokens for r in records)
        total_out = sum(r.output_tokens for r in records)
        total = sum(r.total_tokens for r in records)
        total_cost = sum(r.cost_cents for r in records)

        model_counts: Dict[str, int] = {}
        for r in records:
            model_counts[r.model or "unknown"] = model_counts.get(r.model or "unknown", 0) + r.total_tokens
        top_models = [
            {"model": m, "tokens": t}
            for m, t in sorted(model_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        return {"username": username, "total_input_tokens": total_in, "total_output_tokens": total_out,
                "total_tokens": total, "total_cost_cents": total_cost,
                "total_calls": len(records), "top_models": top_models}

    def get_agent_token_usage(
        self,
        agent_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        from datetime import datetime

        stmt = select(TokenUsage).where(TokenUsage.agent_id == agent_id)
        if start_date:
            stmt = stmt.where(TokenUsage.created_at >= datetime.strptime(start_date, "%Y-%m-%d").timestamp())
        if end_date:
            end_ts = datetime.strptime(end_date, "%Y-%m-%d").timestamp() + 86399.999
            stmt = stmt.where(TokenUsage.created_at < end_ts)

        with self._sf() as session:
            records = session.execute(stmt).scalars().all()

        if not records:
            return {"agent_id": agent_id, "total_input_tokens": 0, "total_output_tokens": 0,
                    "total_tokens": 0, "total_calls": 0}

        total_in = sum(r.input_tokens for r in records)
        total_out = sum(r.output_tokens for r in records)
        total = sum(r.total_tokens for r in records)

        return {"agent_id": agent_id, "total_input_tokens": total_in,
                "total_output_tokens": total_out, "total_tokens": total,
                "total_calls": len(records)}

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    def get_user_preferences(self, username: str) -> Optional[Dict[str, Any]]:
        user = self.get_user_by_username(username)
        if not user:
            return None
        with self._sf() as session:
            # .scalars() → plain ORM instance (Row attribute access on
            # ORM-enabled rows is keyed by entity class, not column name)
            inst = session.execute(
                select(UserPreference).where(UserPreference.user_id == user["id"])
            ).scalars().first()
            if not inst:
                return None
            settings = {}
            if inst.settings:
                try:
                    settings = json.loads(inst.settings)
                except (json.JSONDecodeError, TypeError):
                    settings = {}
            result: Dict[str, Any] = dict(settings)
            result["username"] = inst.username
            result["updated_at"] = inst.updated_at
            return result

    def save_user_preferences(self, username: str, prefs_data: Dict[str, Any]) -> None:
        user = self.get_user_by_username(username)
        if not user:
            return None
        settings: Dict[str, Any] = dict(prefs_data)
        updated_at = settings.pop("updated_at", time.time())
        if not isinstance(updated_at, (int, float)):
            updated_at = time.time()
        settings_json = json.dumps(settings, ensure_ascii=False)
        with self._sf() as session:
            # .scalars() → mutable ORM instance (a Row would be immutable
            # and the attribute writes below would be lost)
            existing = session.execute(
                select(UserPreference).where(UserPreference.user_id == user["id"])
            ).scalars().first()
            if existing:
                existing.settings = settings_json
                existing.updated_at = updated_at
            else:
                session.add(
                    UserPreference(
                        user_id=user["id"],
                        username=username,
                        settings=settings_json,
                        updated_at=updated_at,
                    )
                )
            session.commit()

    def get_user_preference(self, user_id: Any, key: str) -> Optional[str]:
        uid = _normalize_id(user_id)
        if not uid:
            return None
        with self._sf() as session:
            inst = session.execute(
                select(UserSetting).where(
                    UserSetting.user_id == uid, UserSetting.setting_key == key
                )
            ).scalars().first()
            return inst.setting_value if inst else None

    def set_user_preference(self, user_id: Any, key: str, value: str) -> bool:
        uid = _normalize_id(user_id)
        if not uid:
            return False
        now = time.time()
        # D-13: dialect-neutral upsert (no sqlite ON CONFLICT) — identical
        # behaviour on SQLite and PostgreSQL.
        with self._sf() as session:
            existing = session.execute(
                select(UserSetting).where(
                    UserSetting.user_id == uid,
                    UserSetting.setting_key == key,
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.setting_value = value
                existing.updated_at = now
            else:
                session.add(
                    UserSetting(
                        user_id=uid,
                        setting_key=key,
                        setting_value=value,
                        updated_at=now,
                    )
                )
            session.commit()
        return True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        # No per-instance connections to close — every call opens its own
        # session from the *global* engine. The engine is shared by all
        # repositories in the process, so it must NOT be disposed here
        # (that would break every other live repository). Clearing the
        # cached reference is enough; the next call re-resolves it.
        self._sf_cache = None
