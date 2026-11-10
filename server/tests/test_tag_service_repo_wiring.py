# -*- coding: utf-8 -*-
"""标签服务「选仓接线」回归锁（与场景服务同一根因，2026-11-10 dev 实测）。

缺陷回顾：社区镜像打包了 ``coapis/enterprise/`` 源码，``is_enterprise_installed()``
判的是「包能否 import」→ 社区版恒为 True，旧选仓逻辑因此把
``SqliteTagRepository`` 当企业版 PostgreSQL 仓使用：

* ``list_tags(tag_type=…, parent_id=…, enabled=…, show_in_menu=…)``
  → ``TypeError: list_tags() got an unexpected keyword argument 'tag_type'``
* 对 SQLite 返回的 **dict 行**做 ``db_tag.type`` / ``db_tag.id`` 属性访问
  → ``AttributeError: 'dict' object has no attribute 'type'``

后果（dev 4300 实测，修复前）：
``GET /api/admin/tags`` 500、``GET /api/admin/tags/tree`` 500、
``GET /api/scenes/workbench/menu`` 500 —— 标签管理页与工作台左侧菜单整页打不开。

修复＝社区版改走 ``_load_tags_from_db`` / ``_save_tags_to_db``（真相源仍是 SQLite 表，
tags.json 只作只读备份），企业版分支一字未动。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

# 说明：tag_service 依赖 coapis.models.tags（TagCreate/TagUpdate/TagWithUsage），
# 该模块目前只在运行镜像里存在（仓库树里是 models/tag.py 的 TagCreateRequest），
# dev 容器靠 coapis 命名空间包把仓库树与快照基座合并后才可导入。仓库树单测环境
# 缺该模块时整体跳过，避免把「快照依赖」伪装成「测试通过」。
pytest.importorskip("coapis.models.tags")

from coapis.app.services.tag_service import TagService
from coapis.foundation import RepositoryFactory
from coapis.models.tags import TagCreate, TagUpdate


def _tmp_dirs(tmp_path, monkeypatch):
    """SYSTEM_DIR/WORKING_DIR 指向 tmp，库路径落在 WORKING_DIR 内（决策 D-9）。"""
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
    return data_dir, system_dir, db_path


@pytest.fixture(autouse=True)
def _isolation():
    from coapis.foundation.db.engine import reset_engine

    reset_engine()
    RepositoryFactory.reset()
    yield
    RepositoryFactory.reset()
    reset_engine()


def _seed(repo):
    repo.save_many([
        {"id": "tag-cat", "name": "分类A", "type": "category", "show_in_menu": True,
         "enabled": True, "sort_order": 1, "keywords": ["a"]},
        {"id": "tag-dim", "name": "维度B", "type": "dimension", "show_in_menu": False,
         "enabled": True, "sort_order": 2, "keywords": ["b"]},
    ])


@pytest.fixture
def community(tmp_path, monkeypatch):
    data_dir, _system_dir, _db_path = _tmp_dirs(tmp_path, monkeypatch)
    RepositoryFactory.initialize(edition="community")
    repo = RepositoryFactory.get_tag_repository()
    _seed(repo)
    return SimpleNamespace(data_dir=data_dir, repo=repo)


class FakePGTagRepo:
    """企业版 PG 标签仓替身：list_tags 用 tag_type/parent_id/enabled/show_in_menu 关键字。"""

    def __init__(self, rows=None):
        self._rows = {r["id"]: dict(r) for r in (rows or [])}
        self.calls = []

    def list_tags(self, tag_type=None, parent_id=None, enabled=None, show_in_menu=None):
        self.calls.append({"tag_type": tag_type, "parent_id": parent_id,
                           "enabled": enabled, "show_in_menu": show_in_menu})
        rows = list(self._rows.values())
        if tag_type:
            rows = [r for r in rows if r.get("type") == tag_type]
        if parent_id is not None:
            rows = [r for r in rows if r.get("parent_id") == parent_id]
        if show_in_menu is not None:
            rows = [r for r in rows if bool(r.get("show_in_menu")) == bool(show_in_menu)]
        return [SimpleNamespace(**r) for r in rows]

    def get_tag(self, tag_id):
        row = self._rows.get(tag_id)
        return SimpleNamespace(**row) if row else None

    def save_tag(self, obj):
        d = {k: getattr(obj, k, None) for k in ("id", "name", "type", "show_in_menu", "enabled")}
        self._rows[d["id"]] = {**self._rows.get(d["id"], {}), **d}

    def delete_tag(self, tag_id):
        return self._rows.pop(tag_id, None) is not None

    def get_all(self):
        return [dict(r) for r in self._rows.values()]


@pytest.fixture
def enterprise(tmp_path, monkeypatch):
    data_dir, _system_dir, _db_path = _tmp_dirs(tmp_path, monkeypatch)
    RepositoryFactory.initialize(edition="enterprise")
    fake = FakePGTagRepo([
        {"id": "pg-1", "name": "PG标签1", "type": "category", "show_in_menu": True,
         "enabled": True, "sort_order": 1},
        {"id": "pg-2", "name": "PG标签2", "type": "dimension", "show_in_menu": False,
         "enabled": True, "sort_order": 2},
    ])
    RepositoryFactory.inject_tag_repository(fake)
    return SimpleNamespace(data_dir=data_dir, repo=fake)


# ---------------------------------------------------------------------------


class TestTagRepoSelection:
    def test_community_never_uses_enterprise_branch(self, community):
        svc = TagService(data_dir=community.data_dir)
        assert svc._enterprise_repo is None, (
            "社区版把 SqliteTagRepository 当 PG 仓＝标签管理页/工作台菜单 500 的根因"
        )
        assert svc._community_repo is not None

    def test_enterprise_injection_keeps_enterprise_branch(self, enterprise):
        svc = TagService(data_dir=enterprise.data_dir)
        assert svc._enterprise_repo is enterprise.repo
        assert svc._community_repo is None

    def test_startup_guard_rejects_repo_without_pg_contract(self, enterprise):
        half_baked = SimpleNamespace(list_tags=lambda **kw: [])
        RepositoryFactory.inject_tag_repository(half_baked)
        with pytest.raises(RuntimeError, match="PG 契约方法"):
            TagService(data_dir=enterprise.data_dir)

    def test_factory_uninitialized_falls_back_to_json(self, tmp_path):
        svc = TagService(data_dir=tmp_path)
        assert svc._enterprise_repo is None and svc._community_repo is None


class TestCommunityTagFlow:
    def test_list_tags_no_signature_error(self, community):
        svc = TagService(data_dir=community.data_dir)
        tags = svc.list_tags()
        assert {t.id for t in tags} == {"tag-cat", "tag-dim"}
        assert svc.list_tags(tag_type="category")[0].id == "tag-cat"
        assert svc.list_tags(show_in_menu=True)[0].id == "tag-cat"
        assert svc.list_tags(tag_type="dimension")[0].id == "tag-dim"

    def test_get_tag_attribute_access(self, community):
        svc = TagService(data_dir=community.data_dir)
        tag = svc.get_tag("tag-cat")
        assert tag is not None and tag.name == "分类A" and tag.type == "category"

    def test_create_update_delete_write_through_db(self, community):
        svc = TagService(data_dir=community.data_dir)
        created = svc.create_tag(TagCreate(name="新建标签", type="category", keywords=["k"]))
        assert created.id
        assert community.repo.get_tag(created.id)["name"] == "新建标签"

        updated = svc.update_tag(created.id, TagUpdate(name="改名后"))
        assert updated is not None and updated.name == "改名后"
        assert community.repo.get_tag(created.id)["name"] == "改名后"

        assert svc.delete_tag(created.id) is True
        assert community.repo.get_tag(created.id) is None

    def test_tree_and_menu(self, community):
        svc = TagService(data_dir=community.data_dir)
        tree = svc.get_tag_tree()
        assert tree.get("category") and tree.get("dimension")
        assert svc.get_menu_tags(), "工作台菜单标签不应为空"

    def test_soft_deleted_tag_is_hidden(self, community):
        from coapis.foundation.db.models.scene import Tag
        from coapis.foundation.db.session import get_session

        with get_session() as session:
            row = session.get(Tag, "tag-dim")
            row.deleted_at = "2026-01-05T00:00:00"
        svc = TagService(data_dir=community.data_dir)
        assert {t.id for t in svc.list_tags()} == {"tag-cat"}, "软删标签不得复活"
        assert svc.get_tag("tag-dim") is None


class TestEnterpriseTagFlow:
    def test_pg_signature_is_used(self, enterprise):
        svc = TagService(data_dir=enterprise.data_dir)
        tags = svc.list_tags(tag_type="category", show_in_menu=True)
        assert [t.id for t in tags] == ["pg-1"]
        assert enterprise.repo.calls[-1]["tag_type"] == "category", "企业版必须走 PG 关键字过滤"

    def test_get_tag_and_tree_via_pg_repo(self, enterprise):
        svc = TagService(data_dir=enterprise.data_dir)
        assert svc.get_tag("pg-1").name == "PG标签1"
        assert svc.get_tag_tree().get("category")
        assert svc.get_menu_tags()
