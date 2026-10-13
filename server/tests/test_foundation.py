# -*- coding: utf-8 -*-
"""Foundation layer tests: A 档/域迁移、tag/scene/user_scene 仓库、RepositoryFactory。

KB 存储层已移除（T1），本文件不再包含 KB 测试。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from coapis.foundation import RepositoryFactory
from coapis.foundation.migrations import (
    ensure_domain_migrated,
    ensure_migrated,
)
from coapis.foundation.scene_repository_sqlite import SqliteSceneRepository
from coapis.foundation.tag_repository_sqlite import SqliteTagRepository
from coapis.foundation.user_scene_repository_sqlite import SqliteUserSceneSettingsRepo


@pytest.fixture(autouse=True)
def _engine_isolation():
    """每个测试前后重置全局 SQLAlchemy engine，避免跨测试串库。"""
    from coapis.foundation.db.engine import reset_engine
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
def env(tmp_path):
    system_dir = tmp_path / "system"
    (system_dir / "data").mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = system_dir / "coapis.db"
    return SimpleNamespace(system_dir=system_dir, data_dir=data_dir, db_path=db_path)


def _init_test_engine(db_path: Path) -> None:
    """ensure_domain_migrated 里 SqlaExternalIdentityStore 走全局 engine，
    测试须先把 engine 指到目标临时库。"""
    from coapis.foundation.db.engine import init_engine
    init_engine(f"sqlite:///{db_path}")


def _query(db_path: Path, sql: str, params: tuple = ()) -> list:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ── A 档迁移 ──


class TestEnsureMigrated:
    def test_users_json_to_db(self, env):
        users = [
            {"id": "admin", "username": "admin", "name": "管理员", "role": "admin",
             "password": "x", "password_set_by_user": True},
            {"id": "u2", "username": "u2", "name": "用户2", "role": "user",
             "password": "y", "password_set_by_user": False},
        ]
        (env.system_dir / "users.json").write_text(
            json.dumps(users, ensure_ascii=False), encoding="utf-8")

        ensure_migrated(system_dir=env.system_dir, db_path=env.db_path)

        rows = _query(env.db_path, "SELECT username, role FROM users ORDER BY username")
        assert {r["username"] for r in rows} == {"admin", "u2"}
        flags = _query(env.db_path, "SELECT value FROM migration_state WHERE key='json_migration'")
        assert flags and flags[0]["value"] == "done"
        # 源文件已归档
        assert not (env.system_dir / "users.json").exists()

    def test_idempotent(self, env):
        users = [{"id": "a", "username": "a", "name": "A", "role": "user",
                  "password": "p", "password_set_by_user": True}]
        (env.system_dir / "users.json").write_text(
            json.dumps(users, ensure_ascii=False), encoding="utf-8")
        ensure_migrated(system_dir=env.system_dir, db_path=env.db_path)
        ensure_migrated(system_dir=env.system_dir, db_path=env.db_path)  # 第二次 no-op
        rows = _query(env.db_path, "SELECT username FROM users")
        assert len(rows) == 1


# ── 域迁移（tags / scenes / user_scene_settings） ──


class TestDomainMigrations:
    def test_seed_from_json(self, env):
        (env.data_dir / "tags.json").write_text(
            json.dumps({"tags": [{"id": "t1", "name": "办公", "description": "", "color": "#000",
                                  "icon": "briefcase", "category": "work", "system": True,
                                  "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}]}),
            encoding="utf-8")
        (env.data_dir / "scenes.json").write_text(
            json.dumps({"scenes": [{"scene_id": "s1", "name": "默认场景", "description": "", "icon": "x",
                                    "category": "work", "status": "active", "system_prompt": "",
                                    "welcome_message": "", "skills": [], "tags": [], "tag_ids": [],
                                    "primary_tag_id": "t1", "created_by": "admin",
                                    "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
                                    "usage_count": 0}]}),
            encoding="utf-8")
        (env.data_dir / "user_scenes.json").write_text(
            json.dumps({"user_scenes": [{"user_id": "admin", "enabled_scenes": ["s1"], "custom_scenes": [],
                                         "preferences": {"lang": "zh"},
                                         "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}]}),
            encoding="utf-8")

        _init_test_engine(env.db_path)
        ensure_domain_migrated(data_dir=env.data_dir, system_dir=env.system_dir, db_path=env.db_path)

        assert _query(env.db_path, "SELECT name FROM tags") == [{"name": "办公"}]
        assert _query(env.db_path, "SELECT scene_id FROM scenes") == [{"scene_id": "s1"}]
        rows = _query(env.db_path, "SELECT user_id, enabled_scenes FROM user_scene_settings")
        assert rows and json.loads(rows[0]["enabled_scenes"]) == ["s1"]
        flags = {r["key"]: r["value"] for r in _query(env.db_path, "SELECT key, value FROM migration_state")}
        assert flags.get("domain_migration") == "done"

    def test_idempotent(self, env):
        (env.data_dir / "tags.json").write_text(
            json.dumps({"tags": [{"id": "t1", "name": "办公"}]}), encoding="utf-8")
        _init_test_engine(env.db_path)
        ensure_domain_migrated(data_dir=env.data_dir, system_dir=env.system_dir, db_path=env.db_path)
        ensure_domain_migrated(data_dir=env.data_dir, system_dir=env.system_dir, db_path=env.db_path)
        assert len(_query(env.db_path, "SELECT id FROM tags")) == 1


# ── 域仓库 CRUD ──


class TestTagRepository:
    def test_crud_and_seed(self, env):
        _init_test_engine(env.db_path)
        ensure_domain_migrated(data_dir=env.data_dir, system_dir=env.system_dir, db_path=env.db_path)
        repo = SqliteTagRepository(env.db_path)
        try:
            # seed_many 幂等
            repo.seed_many([{"id": "t1", "name": "办公", "category": "work", "system": True}])
            repo.seed_many([{"id": "t1", "name": "办公", "category": "work", "system": True}])
            assert len(repo.list_tags()) == 1

            # save 新增 + 覆盖
            repo.save_tag({"id": "t2", "name": "生活", "description": "d", "color": "#f00",
                           "icon": "home", "category": "life", "system": False})
            assert repo.get_tag("t2") is not None
            repo.save_tag({"id": "t2", "name": "生活2"})
            assert repo.get_tag("t2")["name"] == "生活2"

            # save_many 是全量 reconcile（delete-not-in + upsert），须传完整列表
            repo.save_many([
                {"id": "t2", "name": "生活2"},
                {"id": "t3", "name": "A"},
            ])
            assert len(repo.list_tags()) == 2
            repo.delete_tag("t3")
            assert repo.get_tag("t3") is None
        finally:
            repo.close()


class TestSceneRepository:
    def test_crud(self, env):
        _init_test_engine(env.db_path)
        ensure_domain_migrated(data_dir=env.data_dir, system_dir=env.system_dir, db_path=env.db_path)
        repo = SqliteSceneRepository(env.db_path)
        try:
            repo.save_scene({"scene_id": "s1", "name": "场景1", "skills": ["sk1"], "tags": ["t1"],
                            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"})
            got = repo.get_scene("s1")
            assert got["skills"] == ["sk1"]
            repo.save_scene({"scene_id": "s2", "name": "场景2",
                             "created_at": "2026-01-02T00:00:00", "updated_at": "2026-01-02T00:00:00"})
            assert len(repo.list_scenes()) == 2
            repo.delete_scene("s2")
            assert repo.get_scene("s2") is None
        finally:
            repo.close()


class TestUserSceneRepository:
    def test_crud(self, env):
        _init_test_engine(env.db_path)
        ensure_domain_migrated(data_dir=env.data_dir, system_dir=env.system_dir, db_path=env.db_path)
        repo = SqliteUserSceneSettingsRepo(env.db_path)
        try:
            repo.save({"user_id": "u1", "enabled_scenes": ["s1"], "custom_scenes": [],
                       "preferences": {"lang": "zh"}})
            got = repo.get("u1")
            assert got["enabled_scenes"] == ["s1"]
            assert got["preferences"] == {"lang": "zh"}
            repo.save({"user_id": "u1", "enabled_scenes": []})
            assert repo.get("u1")["enabled_scenes"] == []
            repo.delete("u1")
            assert repo.get("u1") is None
        finally:
            repo.close()


# ── RepositoryFactory（community 初始化） ──


class TestFactoryCommunity:
    def test_initialize_and_getters(self, env, monkeypatch):
        import coapis.constant as constant

        monkeypatch.setattr(constant, "SYSTEM_DIR", env.system_dir)
        monkeypatch.setattr(constant, "WORKING_DIR", env.data_dir)
        # 社区版工厂走 resolve_db_path()（D-7/D-8/D-9）：用 COAPIS_DATABASE_URL
        # 把库指到 tmp（绝对路径 URL，必须落在 WORKING_DIR 内）。
        db_url = f"sqlite:///{env.data_dir / 'coapis.db'}"
        monkeypatch.setenv("COAPIS_DATABASE_URL", db_url)
        # 预置 A 档 + 域数据
        (env.system_dir / "users.json").write_text(
            json.dumps([{"id": "admin", "username": "admin", "name": "管理员", "role": "admin",
                         "password": "p", "password_set_by_user": True}]),
            encoding="utf-8")
        (env.data_dir / "tags.json").write_text(
            json.dumps({"tags": [{"id": "t1", "name": "办公"}]}), encoding="utf-8")

        RepositoryFactory.reset()
        try:
            RepositoryFactory.initialize(edition="community")
            assert RepositoryFactory.is_initialized()
            assert RepositoryFactory.get_edition() == "community"

            tag = RepositoryFactory.get_tag_repository()
            assert any(t["id"] == "t1" for t in tag.list_tags())
            user_repo = RepositoryFactory.get_user_repository()
            assert user_repo is not None
            assert RepositoryFactory.get_scene_repository() is not None
            assert RepositoryFactory.get_user_scene_repository() is not None
        finally:
            RepositoryFactory.reset()

    def test_enterprise_requires_injection(self):
        RepositoryFactory.reset()
        try:
            RepositoryFactory.initialize(edition="enterprise")
            assert RepositoryFactory.get_edition() == "enterprise"
            with pytest.raises(RuntimeError):
                RepositoryFactory.get_user_repository()
            # 注入后可用
            RepositoryFactory.inject_user_repository(object())
            assert RepositoryFactory.get_user_repository() is not None
        finally:
            RepositoryFactory.reset()

    def test_invalid_edition(self):
        RepositoryFactory.reset()
        try:
            with pytest.raises(ValueError):
                RepositoryFactory.initialize(edition="nope")
        finally:
            RepositoryFactory.reset()


# ---------------------------------------------------------------------------
# T3（bug① 治本）：遗留 JSON 解析失败必须显式报错，禁止静默跳过
#   - _load_json_list / token_usage.json / permissions.json → RuntimeError(带路径)
#   - ensure_runtime_domain_migrated 不再逐域 warn+continue（旧行为把 NameError
#     降级成 warning = bug① 长期未被发现的直接原因）
# ---------------------------------------------------------------------------

class TestT3LegacyJsonFailFast:
    """遗留 JSON：文件不存在=正常(返回[])；存在但损坏=显式失败。"""

    def _load_list(self, path):
        from coapis.foundation.migrations import _load_json_list
        return _load_json_list(path)

    def test_missing_file_returns_empty(self, tmp_path):
        assert self._load_list(tmp_path / "nope.json") == []

    def test_corrupt_json_raises_with_path_in_message(self, tmp_path):
        p = tmp_path / "token_usage_details.json"
        p.write_text("{ this is not valid json", encoding="utf-8")
        with pytest.raises(RuntimeError) as ei:
            self._load_list(p)
        assert str(p) in str(ei.value)

    def test_valid_payloads_still_work(self, tmp_path):
        (tmp_path / "a.json").write_text('[{"id": 1}]', encoding="utf-8")
        (tmp_path / "b.json").write_text('{"users": [{"u": 2}]}', encoding="utf-8")
        assert self._load_list(tmp_path / "a.json") == [{"id": 1}]
        assert self._load_list(tmp_path / "b.json") == [{"u": 2}]

    def test_ensure_runtime_domain_migrated_no_longer_swallows(self, tmp_path):
        """端到端：损坏的 permissions.json → RuntimeError（而非静默迁0行）。

        （原载体 token_usage_details.json 已于 2026-09-25 拍板不再迁移，
        改用同样 fail-fast 的 permissions.json 承载本用例。）
        """
        from sqlalchemy import create_engine
        from coapis.foundation.migrations import ensure_runtime_domain_migrated

        system_dir = tmp_path / "system"
        system_dir.mkdir(parents=True)
        (system_dir / "permissions.json").write_text("corrupt{{{", encoding="utf-8")

        engine = create_engine(f"sqlite:///{tmp_path}/t3.db")
        try:
            with pytest.raises(RuntimeError):
                with engine.begin() as conn:
                    ensure_runtime_domain_migrated(conn, system_dir)
        finally:
            engine.dispose()

    def test_details_json_not_migrated_and_never_crashes(self, tmp_path):
        """回归：遗留 details JSON 不再入库（2026-09-25 拍板）。

        即使文件含 user_id=null/0（曾致 NOT NULL IntegrityError → 容器
        exit(3) 重启循环），也必须平滑跳过、表保持 0 行。
        """
        from sqlalchemy import create_engine, text
        from coapis.foundation.migrations import ensure_runtime_domain_migrated

        system_dir = tmp_path / "system"
        system_dir.mkdir(parents=True)
        (system_dir / "token_usage_details.json").write_text(
            '{"records": ['
            '{"user_id": null, "username": "admin", "model": "m", '
            '"input_tokens": 1, "output_tokens": 2, "total_tokens": 3, '
            '"created_at": "2026-09-25T00:00:00"}, '
            '{"user_id": 0, "username": "anonymous", "model": "m", '
            '"input_tokens": 1, "output_tokens": 2, "total_tokens": 3, '
            '"created_at": "2026-09-25T00:00:01"}]}',
            encoding="utf-8",
        )

        engine = create_engine(f"sqlite:///{tmp_path}/t3b.db")
        try:
            with engine.begin() as conn:
                ensure_runtime_domain_migrated(conn, system_dir)
            with engine.connect() as conn:
                n = conn.execute(text("SELECT COUNT(*) FROM token_usage")).scalar()
            assert n == 0
        finally:
            engine.dispose()
