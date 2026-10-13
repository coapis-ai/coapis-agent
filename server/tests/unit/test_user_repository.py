"""Unit tests for the user repository (unified data layer, Phase 1).

The community edition uses a single SQLAlchemy implementation
(``SqlaUserRepository`` on the unified engine) behind the ``UserRepository``
ABC — the legacy ``user_repository_sqlite.py`` was removed in Phase 1.

Covers:

1. **Contract** — an in-memory repository implementing the full 23-method
   ABC, verifying the interface semantics every impl must uphold.
2. **SqlaUserRepository scenarios** — CRUD on the real engine, password
   hashing, int→UUID legacy id mapping (D-6), paging/search/counts,
   audit/points/token-usage inserts, preferences, persistence.
3. **Legacy migration** — ``migrations.ensure_migrated`` (users.json →
   coapis.db, the raw sqlite3 path the factory still calls) + idempotency.
4. **Factory wiring** — community edition initialization end-to-end
   (needs alembic; skipped when alembic is unavailable).
"""

from __future__ import annotations

import hashlib
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from coapis.foundation import migrations
from coapis.foundation.user_repository import User, UserRepository
from coapis.foundation.user_repository_impl import SqlaUserRepository
from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import get_engine, init_engine
from coapis.foundation.repository_factory import RepositoryFactory


# ── helpers ──────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _password_hash(password: str, salt: str) -> str:
    return hashlib.sha256(f"{password}:{salt}".encode()).hexdigest()


def _new_id() -> str:
    return str(_uuid.uuid4())


# ── in-memory contract repository (full 23-method ABC) ──────────────────────


class InMemoryUserRepository(UserRepository):
    """In-memory implementation used to verify the ABC contract."""

    def __init__(self) -> None:
        self._users: Dict[str, User] = {}          # id -> User
        self._username_index: Dict[str, str] = {}  # username -> id
        self._email_index: Dict[str, str] = {}     # email -> id
        self._prefs: Dict[str, Dict[str, Any]] = {}
        self._settings: Dict[str, Dict[str, str]] = {}  # user_id -> {key: value}
        self._audit: List[Dict[str, Any]] = []
        self._points: List[Dict[str, Any]] = []
        self._usage: List[Dict[str, Any]] = []

    # ── CRUD ───────────────────────────────────────────────────────────────

    def create_user(self, user_data: Dict[str, Any]) -> str:
        user = User(
            id=user_data.get("id", _new_id()),
            username=user_data["username"],
            password_hash=user_data.get("password_hash", ""),
            salt=user_data.get("salt", ""),
            display_name=user_data.get("display_name", user_data["username"]),
            email=user_data.get("email", ""),
            role=user_data.get("role", "user"),
            is_active=user_data.get("is_active", True),
        )
        self._users[user.id] = user
        self._username_index[user.username] = user.id
        if user.email:
            self._email_index[user.email] = user.id
        return user.id

    def _to_dict(self, user: User) -> Dict[str, Any]:
        return {
            "id": user.id,
            "username": user.username,
            "password_hash": user.password_hash,
            "salt": user.salt,
            "display_name": user.display_name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at,
        }

    def get_user_by_id(self, user_id: Any) -> Optional[Dict[str, Any]]:
        if isinstance(user_id, int):
            user_id = str(_uuid.UUID(int=user_id))
        user = self._users.get(str(user_id))
        return self._to_dict(user) if user else None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        uid = self._username_index.get(username)
        return self._to_dict(self._users[uid]) if uid else None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        uid = self._email_index.get(email)
        return self._to_dict(self._users[uid]) if uid else None

    def update_user(self, username: str, update_data: Dict[str, Any]) -> bool:
        uid = self._username_index.get(username)
        if not uid:
            return False
        user = self._users[uid]
        for key, value in update_data.items():
            if hasattr(user, key):
                setattr(user, key, value)
        return True

    def update_user_by_id(self, user_id: Any, update_data: Dict[str, Any]) -> bool:
        uid = str(_uuid.UUID(int=user_id)) if isinstance(user_id, int) else str(user_id)
        user = self._users.get(uid)
        if not user:
            return False
        for key, value in update_data.items():
            if hasattr(user, key):
                setattr(user, key, value)
        return True

    def delete_user(self, username: str) -> bool:
        uid = self._username_index.pop(username, None)
        if not uid:
            return False
        user = self._users.pop(uid, None)
        if user and user.email:
            self._email_index.pop(user.email, None)
        return user is not None

    def delete_user_by_id(self, user_id: Any) -> bool:
        uid = str(_uuid.UUID(int=user_id)) if isinstance(user_id, int) else str(user_id)
        user = self._users.pop(uid, None)
        if not user:
            return False
        self._username_index.pop(user.username, None)
        if user.email:
            self._email_index.pop(user.email, None)
        return True

    # ── queries ────────────────────────────────────────────────────────────

    def list_users(self) -> List[Dict[str, Any]]:
        return [self._to_dict(u) for u in self._users.values()]

    def list_users_page(
        self, page: int, page_size: int, search: str = ""
    ) -> tuple[List[Dict[str, Any]], int]:
        rows = list(self._users.values())
        if search:
            s = search.lower()
            rows = [
                u for u in rows
                if s in u.username.lower()
                or s in u.display_name.lower()
                or s in u.email.lower()
            ]
        total = len(rows)
        start = (page - 1) * page_size
        return [self._to_dict(u) for u in rows[start:start + page_size]], total

    def user_exists(self, username: str) -> bool:
        return username in self._username_index

    def email_exists(self, email: str) -> bool:
        return email in self._email_index

    def count_users(self) -> int:
        return len(self._users)

    def count_active_users(self) -> int:
        return sum(1 for u in self._users.values() if u.is_active)

    # ── audit / points / usage ─────────────────────────────────────────────

    def insert_audit_log(self, user_id, username, action, resource_type="",
                         resource_id="", details="", ip_address="",
                         user_agent="") -> None:
        self._audit.append({"user_id": user_id, "username": username, "action": action})

    def insert_point_transaction(self, user_id, amount, balance_after,
                                 transaction_type, description="",
                                 reference_id="") -> None:
        self._points.append({"user_id": user_id, "amount": amount})

    def insert_token_usage(self, user_id, username, agent_id, model,
                           input_tokens, output_tokens, total_tokens,
                           cost_cents=0) -> None:
        self._usage.append({
            "user_id": user_id, "username": username, "agent_id": agent_id,
            "model": model, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "total_tokens": total_tokens,
        })

    def get_user_token_usage(self, username: str,
                             start_date: Optional[str] = None,
                             end_date: Optional[str] = None) -> Dict[str, Any]:
        rows = [r for r in self._usage if r["username"] == username]
        return {
            "total_input_tokens": sum(r["input_tokens"] for r in rows),
            "total_output_tokens": sum(r["output_tokens"] for r in rows),
            "total_tokens": sum(r["total_tokens"] for r in rows),
        }

    def get_agent_token_usage(self, agent_id: str,
                              start_date: Optional[str] = None,
                              end_date: Optional[str] = None) -> Dict[str, Any]:
        rows = [r for r in self._usage if r["agent_id"] == agent_id]
        return {
            "total_input_tokens": sum(r["input_tokens"] for r in rows),
            "total_output_tokens": sum(r["output_tokens"] for r in rows),
            "total_tokens": sum(r["total_tokens"] for r in rows),
        }

    # ── preferences ────────────────────────────────────────────────────────

    def get_user_preferences(self, username: str) -> Optional[Dict[str, Any]]:
        return self._prefs.get(username)

    def save_user_preferences(self, username: str, prefs_data: Dict[str, Any]) -> None:
        self._prefs[username] = dict(prefs_data)

    def get_user_preference(self, user_id: Any, key: str) -> Optional[str]:
        uid = str(_uuid.UUID(int=user_id)) if isinstance(user_id, int) else str(user_id)
        return self._settings.get(uid, {}).get(key)

    def set_user_preference(self, user_id: Any, key: str, value: str) -> bool:
        uid = str(_uuid.UUID(int=user_id)) if isinstance(user_id, int) else str(user_id)
        if uid not in self._users:
            return False
        self._settings.setdefault(uid, {})[key] = value
        return True


# ── 1. contract tests (in-memory) ───────────────────────────────────────────


class TestContract:
    """The 23-method ABC semantics every implementation must uphold."""

    def setup_method(self) -> None:
        self.repo = InMemoryUserRepository()
        self.uid = self.repo.create_user({
            "username": "alice",
            "email": "alice@example.com",
            "display_name": "Alice",
            "password_hash": _password_hash("pw", "s1"),
            "salt": "s1",
            "role": "admin",
        })

    def test_create_returns_uuid(self) -> None:
        _uuid.UUID(self.uid)  # raises if not a valid UUID

    def test_get_by_username(self) -> None:
        row = self.repo.get_user_by_username("alice")
        assert row is not None and row["role"] == "admin"

    def test_get_by_email(self) -> None:
        assert self.repo.get_user_by_email("alice@example.com")["username"] == "alice"

    def test_get_missing_returns_none(self) -> None:
        assert self.repo.get_user_by_username("nobody") is None
        assert self.repo.get_user_by_email("nobody@x.com") is None
        assert self.repo.get_user_by_id(_new_id()) is None

    def test_update_by_username_and_id(self) -> None:
        assert self.repo.update_user("alice", {"display_name": "Alice W."}) is True
        assert self.repo.update_user_by_id(self.uid, {"role": "user"}) is True
        assert self.repo.get_user_by_username("alice")["display_name"] == "Alice W."
        assert self.repo.update_user("ghost", {"role": "x"}) is False
        assert self.repo.update_user_by_id(_new_id(), {"role": "x"}) is False

    def test_delete_by_username_and_id(self) -> None:
        assert self.repo.delete_user("alice") is True
        assert self.repo.get_user_by_username("alice") is None
        self.uid2 = self.repo.create_user({"username": "bob"})
        assert self.repo.delete_user_by_id(self.uid2) is True
        assert self.repo.delete_user("ghost") is False

    def test_list_and_counts(self) -> None:
        self.repo.create_user({"username": "carol", "is_active": False})
        assert self.repo.count_users() == 2
        assert self.repo.count_active_users() == 1
        assert self.repo.user_exists("alice")
        assert self.repo.email_exists("alice@example.com")
        assert len(self.repo.list_users()) == 2

    def test_paging_and_search(self) -> None:
        self.repo.create_user({"username": "bob", "email": "bob@x.com"})
        rows, total = self.repo.list_users_page(1, 10, "al")
        assert total == 1 and rows[0]["username"] == "alice"
        rows, total = self.repo.list_users_page(1, 1)
        assert total == 2 and len(rows) == 1

    def test_preferences(self) -> None:
        self.repo.save_user_preferences("alice", {"theme": "dark"})
        assert self.repo.get_user_preferences("alice")["theme"] == "dark"
        assert self.repo.set_user_preference(self.uid, "lang", "zh") is True
        assert self.repo.get_user_preference(self.uid, "lang") == "zh"
        assert self.repo.set_user_preference(_new_id(), "k", "v") is False

    def test_token_usage_aggregates(self) -> None:
        self.repo.insert_token_usage(self.uid, "alice", "agent-a", "qwen",
                                     10, 20, 30)
        self.repo.insert_token_usage(self.uid, "alice", "agent-b", "qwen",
                                     5, 5, 10)
        assert self.repo.get_user_token_usage("alice")["total_tokens"] == 40
        assert self.repo.get_agent_token_usage("agent-a")["total_tokens"] == 30


# ── 2. SqlaUserRepository scenarios (real engine + temp DB) ─────────────────


@pytest.fixture()
def repo(tmp_path):
    """A ``SqlaUserRepository`` on a fresh temp DB file (schema pre-created)."""
    db_path = tmp_path / "coapis.db"
    init_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(get_engine())
    r = SqlaUserRepository()
    yield r
    r.close()


def _create(repo: SqlaUserRepository, username: str = "carol", **kw: Any) -> str:
    data = {
        "username": username,
        "email": f"{username}@example.com",
        "display_name": username.title(),
        "password": "secret-pw",
        **kw,
    }
    return repo.create_user(data)


class TestSqlaScenario:
    def test_full_crud_cycle(self, repo) -> None:
        uid = _create(repo)
        row = repo.get_user_by_username("carol")
        assert row is not None and row["id"] == uid
        assert repo.get_user_by_id(uid)["email"] == "carol@example.com"
        assert repo.update_user("carol", {"display_name": "Carol X"}) is True
        assert repo.get_user_by_username("carol")["display_name"] == "Carol X"
        assert repo.delete_user_by_id(uid) is True
        assert repo.get_user_by_username("carol") is None

    def test_plaintext_password_is_hashed(self, repo) -> None:
        _create(repo, password="plain123")
        row = repo.get_user_by_username("carol")
        assert row["password"] is None  # plaintext never stored
        assert row["password_hash"] and row["salt"]
        # 新密码走 bcrypt（salt 内嵌在 hash 里），不能再用 sha256 重算比对，
        # 用 checkpw 验证「存的是可校验的哈希、且对应原密码」。
        import bcrypt

        assert bcrypt.checkpw("plain123".encode(), row["password_hash"].encode())

    def test_legacy_int_id_maps_to_deterministic_uuid(self, repo) -> None:
        legacy_int = 42
        expected = str(_uuid.UUID(int=legacy_int))
        uid = repo.create_user({
            "id": expected,
            "username": "legacy-user",
            "password_hash": "h",
            "salt": "s",
        })
        assert uid == expected
        assert repo.get_user_by_id(legacy_int)["username"] == "legacy-user"

    def test_missing_user_returns_false(self, repo) -> None:
        assert repo.update_user("ghost", {"role": "x"}) is False
        assert repo.delete_user("ghost") is False
        assert repo.delete_user_by_id(_new_id()) is False

    def test_token_usage_user_and_agent(self, repo) -> None:
        uid = _create(repo)
        repo.insert_token_usage(uid, "carol", "agent-a", "qwen", 10, 20, 30)
        repo.insert_token_usage(uid, "carol", "agent-b", "qwen", 5, 5, 10)
        assert repo.get_user_token_usage("carol")["total_tokens"] == 40
        assert repo.get_agent_token_usage("agent-a")["total_tokens"] == 30

    def test_audit_and_point_inserts(self, repo) -> None:
        from sqlalchemy import select

        from coapis.foundation.db.models import (
            AuditLog,
            PointTransaction,
        )

        uid = _create(repo)
        repo.insert_audit_log(uid, "carol", "login", ip_address="1.2.3.4")
        repo.insert_point_transaction(uid, 100, 100, "recharge", reference_id="r1")
        with repo._session_factory()() as session:
            audit = session.execute(select(AuditLog).where(AuditLog.user_id == uid)).scalar_one()
            assert audit.action == "login" and audit.ip_address == "1.2.3.4"
            pt = session.execute(
                select(PointTransaction).where(PointTransaction.user_id == uid)
            ).scalar_one()
            assert pt.amount == 100 and pt.reference_id == "r1"

    def test_preferences_roundtrip(self, repo) -> None:
        uid = _create(repo)
        repo.save_user_preferences("carol", {"theme": "dark", "lang": "zh"})
        prefs = repo.get_user_preferences("carol")
        assert prefs["theme"] == "dark"
        assert repo.set_user_preference(uid, "lang", "en") is True
        assert repo.get_user_preference(uid, "lang") == "en"

    def test_persistence_across_instances(self, repo) -> None:
        _create(repo)
        repo2 = SqlaUserRepository()
        try:
            assert repo2.get_user_by_username("carol") is not None
        finally:
            repo2.close()

    def test_db_file_created_on_disk(self, repo, tmp_path) -> None:
        _create(repo)
        assert (tmp_path / "coapis.db").exists()


# ── 3. legacy migration (users.json → coapis.db) ────────────────────────────


class TestMigration:
    """``migrations.ensure_migrated`` — the raw sqlite3 path the factory calls."""

    def test_migrate_users_json_to_db(self, tmp_path) -> None:
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "users.json").write_text(
            '[{"username": "legacy1", "email": "l1@x.com", "display_name": "L1", '
            '"password": "oldpw", "role": "admin"}]',
            encoding="utf-8",
        )
        db_path = system_dir / "coapis.db"
        migrations.ensure_migrated(system_dir, db_path)
        init_engine(f"sqlite:///{db_path}")
        r = SqlaUserRepository()
        try:
            row = r.get_user_by_username("legacy1")
            assert row is not None
            assert row["role"] == "admin"
            assert row["password_hash"]  # plaintext migrated to salt+hash
            assert (system_dir / "users.json").exists() is False  # renamed away
        finally:
            r.close()

    def test_migration_is_idempotent(self, tmp_path) -> None:
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "users.json").write_text(
            '[{"username": "legacy2", "email": "l2@x.com", "display_name": "L2"}]',
            encoding="utf-8",
        )
        db_path = system_dir / "coapis.db"
        migrations.ensure_migrated(system_dir, db_path)
        migrations.ensure_migrated(system_dir, db_path)  # second run: no-op
        init_engine(f"sqlite:///{db_path}")
        r = SqlaUserRepository()
        try:
            assert r.get_user_by_username("legacy2") is not None
            assert r.count_users() == 1
        finally:
            r.close()


# ── 4. factory wiring (community edition, end-to-end) ───────────────────────


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("alembic") is None,
    reason="alembic not installed",
)
class TestFactoryWiring:
    """RepositoryFactory.initialize wires the unified SQLAlchemy stack."""

    def test_community_init_end_to_end(self, monkeypatch, tmp_path) -> None:
        import coapis.constant as constant
        import coapis.foundation.db_settings as db_settings

        workdir = tmp_path / "work"
        sysdir = workdir / "system"
        sysdir.mkdir(parents=True)

        # Isolate every binding of the layout constants: the factory imports
        # them at call time (constant), db_settings binds them at import time.
        monkeypatch.setattr(constant, "WORKING_DIR", workdir)
        monkeypatch.setattr(constant, "SYSTEM_DIR", sysdir)
        monkeypatch.setattr(db_settings, "WORKING_DIR", workdir)
        monkeypatch.setattr(db_settings, "SYSTEM_DIR", sysdir)
        monkeypatch.delenv("COAPIS_DATABASE_URL", raising=False)

        RepositoryFactory.initialize(edition="community", data_dir=workdir)
        try:
            repo = RepositoryFactory.get_user_repository()
            assert isinstance(repo, UserRepository)
            uid = repo.create_user({
                "username": "eve",
                "email": "eve@x.com",
                "display_name": "Eve",
                "password": "x",
            })
            assert uid
            assert repo.get_user_by_username("eve")["display_name"] == "Eve"
            assert repo.update_user("eve", {"display_name": "Eve 2"}) is True
            assert repo.delete_user("eve") is True
            assert repo.get_user_by_username("eve") is None
            # alembic stamped the schema
            assert (sysdir / "coapis.db").exists()
        finally:
            RepositoryFactory.reset()
