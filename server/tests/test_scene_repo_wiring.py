# -*- coding: utf-8 -*-
"""场景服务「选仓接线」回归锁（2026-11-10「进入场景」全线 500 的治本测试）。

缺陷回顾：社区镜像同样打包 ``coapis/enterprise/`` 源码，
``is_enterprise_installed()`` 判的是「包能否 import」→ 在社区版里恒为 True。
旧选仓逻辑因此把 ``SqliteSceneRepository`` 当成企业版 PostgreSQL 仓使用，去调
PG 专属的 ``get_scene_by_id`` / ``create_scene`` / ``update_scene``，并在
``list_scenes`` 里传 PG 专属的 ``primary_tag_id=``：
``AttributeError: 'SqliteSceneRepository' object has no attribute 'get_scene_by_id'``
→ ``POST /api/scenes/{id}/enter``、``GET /api/scenes/workbench/scene/{id}``、
场景详情、新建/编辑/软删 全部 500；标签筛选被 ``except`` 吞成「返回全量」。

本文件锁四件事：
1. 社区版必须落到 ``_community_repo``，不得占用企业分支；
2. 企业版（注入 PG 仓 + edition=enterprise）仍走企业分支——企业行为零变化；
3. 判成企业分支却缺 PG 契约方法 → 启动即抛，不留到用户点击时才 500；
4. 社区版读写以 SQLite 表为真相源，且标签筛选真生效。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from coapis.foundation import RepositoryFactory
from coapis.models.scene import SceneConfigCreate, SceneConfigUpdate
from coapis.services.scene_agent_service import SceneAgentService


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _tmp_dirs(tmp_path, monkeypatch):
    """把 SYSTEM_DIR/WORKING_DIR 指向 tmp，并保证库路径落在 WORKING_DIR 内（D-9）。"""
    import coapis.constant as constant
    from coapis.foundation.db.engine import init_engine

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    system_dir = tmp_path / "system"
    (system_dir / "data").mkdir(parents=True)
    db_path = data_dir / "coapis.db"

    monkeypatch.setattr(constant, "SYSTEM_DIR", system_dir)
    monkeypatch.setattr(constant, "WORKING_DIR", data_dir)
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("COAPIS_DATABASE_URL", url)
    init_engine(url)
    (system_dir / "users.json").write_text(
        '[{"id": "admin", "username": "admin", "name": "管理员", "role": "admin",'
        ' "password": "p", "password_set_by_user": true}]',
        encoding="utf-8",
    )
    return data_dir, system_dir, db_path


@pytest.fixture(autouse=True)
def _engine_isolation():
    """每个用例前后重置全局 engine，避免跨用例串库。"""
    from coapis.foundation.db.engine import reset_engine

    reset_engine()
    RepositoryFactory.reset()
    yield
    RepositoryFactory.reset()
    reset_engine()


@pytest.fixture
def community(tmp_path, monkeypatch):
    """社区版现场：工厂已初始化 + SQLite 场景表里有 2 个场景。"""
    data_dir, system_dir, db_path = _tmp_dirs(tmp_path, monkeypatch)

    RepositoryFactory.initialize(edition="community")
    repo = RepositoryFactory.get_scene_repository()
    repo.save_scene({
        "scene_id": "s-a", "name": "场景A", "primary_tag_id": "tag-a", "status": "active",
        "tag_ids": ["tag-a", "tag-x"], "skills": [], "welcome_message": "欢迎A",
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
    })
    repo.save_scene({
        "scene_id": "s-b", "name": "场景B", "primary_tag_id": "tag-b", "status": "active",
        "tag_ids": ["tag-b"], "skills": [], "welcome_message": "欢迎B",
        "created_at": "2026-01-02T00:00:00", "updated_at": "2026-01-02T00:00:00",
    })
    return SimpleNamespace(data_dir=data_dir, system_dir=system_dir, db_path=db_path, repo=repo)


@pytest.fixture
def enterprise(tmp_path, monkeypatch):
    """企业版现场：edition=enterprise + 注入具备 PG 契约的仓储替身。"""
    data_dir, _system_dir, _db_path = _tmp_dirs(tmp_path, monkeypatch)
    RepositoryFactory.initialize(edition="enterprise")
    fake = FakePGRepo([_pg_row("s-1"), _pg_row("s-2")])
    RepositoryFactory.inject_scene_repository(fake)
    return SimpleNamespace(data_dir=data_dir, repo=fake)


class FakePGRepo:
    """企业版 PG 仓契约的最小替身（方法名与企业仓储一致，DTO 为 ORM 风格对象）。"""

    def __init__(self, rows=None, list_scenes_error=None):
        self._rows = {r["id"]: dict(r) for r in (rows or [])}
        self._list_scenes_error = list_scenes_error

    # ── PG 专属契约（SQLite 仓没有的那几个） ──
    def get_scene_by_id(self, scene_id):
        row = self._rows.get(scene_id)
        return SimpleNamespace(**row) if row else None

    def create_scene(self, payload):
        self._rows[payload["id"]] = dict(payload)
        return SimpleNamespace(**self._rows[payload["id"]])

    def update_scene(self, scene_id, payload):
        if scene_id not in self._rows:
            return None
        self._rows[scene_id].update(payload)
        return SimpleNamespace(**self._rows[scene_id])

    def list_scenes(self, status=None, primary_tag_id=None, limit=1000, offset=0):
        if self._list_scenes_error:
            raise self._list_scenes_error
        rows = list(self._rows.values())
        if primary_tag_id:
            rows = [r for r in rows if r.get("primary_tag_id") == primary_tag_id]
        return [SimpleNamespace(**r) for r in rows]

    # ── 两侧都有的通用方法 ──
    def get_scene(self, scene_id):
        return self._rows.get(scene_id)

    def get_all(self):
        return [dict(r) for r in self._rows.values()]

    def delete_scene(self, scene_id):
        return self._rows.pop(scene_id, None) is not None

    def increment_usage(self, scene_id):
        self._rows[scene_id]["usage_count"] = self._rows[scene_id].get("usage_count", 0) + 1

    def save_many(self, scenes):
        self._rows = {s["id"]: dict(s) for s in scenes}


def _pg_row(scene_id, **kw):
    row = {
        "id": scene_id, "name": f"企业场景{scene_id}", "icon": "📝",
        "description": "d", "short_description": "s", "primary_tag_id": "tag-pg",
        "tag_ids": ["tag-pg"], "skills": [], "system_prompt": "", "welcome_message": "hello",
        "status": "active", "usage_count": 0, "category": None, "tags": [],
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00", "created_by": "admin",
    }
    row.update(kw)
    return row


# ---------------------------------------------------------------------------
# 1. 选仓判据 = 版本 + 能力
# ---------------------------------------------------------------------------

class TestRepoSelection:
    def test_community_uses_sqlite_repo_not_enterprise_branch(self, community):
        svc = SceneAgentService(data_dir=community.data_dir)
        assert svc._enterprise_repo is None, (
            "社区版不得把 SqliteSceneRepository 当企业版 PG 仓——这正是 2026-11-10 "
            "「进入场景」500 的直接原因（get_scene_by_id 不存在）"
        )
        assert svc._community_repo is not None

    def test_enterprise_injection_still_uses_enterprise_branch(self, enterprise):
        svc = SceneAgentService(data_dir=enterprise.data_dir)
        assert svc._enterprise_repo is enterprise.repo
        assert svc._community_repo is None

    def test_startup_guard_rejects_repo_without_pg_contract(self, enterprise):
        """判成企业分支却缺 PG 契约方法 → 启动即抛，不留到用户点击时才 500。"""
        half_baked = SimpleNamespace(get_scene_by_id=lambda sid: None, get_scene=lambda sid: None)
        RepositoryFactory.inject_scene_repository(half_baked)
        with pytest.raises(RuntimeError, match="PG 契约方法"):
            SceneAgentService(data_dir=enterprise.data_dir)

    def test_factory_uninitialized_falls_back_to_json(self, tmp_path):
        svc = SceneAgentService(data_dir=tmp_path)
        assert svc._enterprise_repo is None
        assert svc._community_repo is None


# ---------------------------------------------------------------------------
# 2. 社区版全链路：读、进入、写都以 SQLite 为真相源
# ---------------------------------------------------------------------------

class TestCommunityFlow:
    def test_get_scene_has_no_attribute_error(self, community):
        svc = SceneAgentService(data_dir=community.data_dir)
        scene = svc.get_scene("s-a")
        assert scene is not None and scene.name == "场景A"

    def test_enter_scene_returns_session(self, community):
        svc = SceneAgentService(data_dir=community.data_dir)
        resp = svc.enter_scene("s-a", user_id="u1")
        assert resp.chat_id == "scene-s-a-u1"
        assert resp.session_id == "scene:s-a:user:u1"
        assert resp.welcome_message == "欢迎A"

    def test_list_scenes_tag_filter_really_filters(self, community):
        svc = SceneAgentService(data_dir=community.data_dir)
        assert svc.list_scenes().total == 2
        hit = svc.list_scenes(tag="tag-a")
        assert hit.total == 1 and hit.scenes[0].id == "s-a"
        # tag_ids（非 primary）也要能命中
        assert svc.list_scenes(tag="tag-x").total == 1
        assert svc.list_scenes(tag="no-such-tag").total == 0

    def test_create_update_delete_write_through_db(self, community):
        svc = SceneAgentService(data_dir=community.data_dir)
        created = svc.create_scene(
            SceneConfigCreate(id="s-new", name="新场景", primary_tag_id="tag-a",
                              tag_ids=["tag-a"], skills=[]),
            created_by="admin",
        )
        assert created.id == "s-new"
        assert community.repo.get_scene("s-new") is not None, "写入必须落库"

        updated = svc.update_scene("s-new", SceneConfigUpdate(name="改名"))
        assert updated is not None and updated.name == "改名"
        assert community.repo.get_scene("s-new")["name"] == "改名"

        assert svc.delete_scene("s-new") is True
        row = community.repo.get_scene("s-new")
        assert row is not None and row["status"] == "deleted"

        # 硬删：行从表里消失
        assert svc.delete_scene("s-new", hard_delete=True) is True
        assert community.repo.get_scene("s-new") is None

    def test_list_scenes_by_primary_tag_and_hot(self, community):
        svc = SceneAgentService(data_dir=community.data_dir)
        resp = svc.list_scenes_by_primary_tag("tag-a")
        assert [s.id for s in resp.scenes] == ["s-a"] and resp.total == 1
        svc.increment_usage("s-a")
        assert svc.get_hot_scenes(limit=5)[0]["id"] == "s-a"


# ---------------------------------------------------------------------------
# 3. 企业版分支不受影响（零行为变化）
# ---------------------------------------------------------------------------

class TestEnterpriseFlow:
    def test_get_scene_and_enter_via_pg_repo(self, enterprise):
        svc = SceneAgentService(data_dir=enterprise.data_dir)
        assert svc.get_scene("s-1").name == "企业场景s-1"
        assert svc.enter_scene("s-1", user_id="u1").session_id == "scene:s-1:user:u1"
        assert svc.list_scenes(tag="tag-pg").total == 2

    def test_tag_filter_never_silently_returns_full_list(self, enterprise):
        """D4：带标签筛选时不得吞异常回落全量（旧行为＝筛选静默失效）。"""
        enterprise.repo._list_scenes_error = TypeError(
            "list_scenes() got an unexpected keyword argument 'primary_tag_id'"
        )
        svc = SceneAgentService(data_dir=enterprise.data_dir)
        with pytest.raises(TypeError):
            svc.list_scenes(tag="tag-pg")
        # 无筛选时保留「全量兜底」，避免整页场景因仓储故障不可用
        assert svc.list_scenes().total == 2

    def test_null_category_does_not_break_dto_mapping(self, enterprise):
        """仓储列可为 NULL（category=None），映射到非空 str 字段时必须落回默认值。"""
        svc = SceneAgentService(data_dir=enterprise.data_dir)
        assert svc.get_scene("s-1").category == ""
        assert svc.list_scenes().scenes[0].category == ""
