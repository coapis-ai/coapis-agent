"""TagService 社区版仓储接线 + 标签台账（GET /api/admin/tags/stats）。

锁死三件事（2026-11-10 重写）：

1. 社区版工厂就绪时，TagService 的读/写/删必须走 SQLite 仓储，不得回落到
   tags.json —— 否则「标签管理页改了不生效」「重启后标签消失」。
2. 工厂未就绪时（单测/裸启动），JSON 兜底路径必须继续可用。
3. 台账 `/stats`：计数 + 引用健康度（零引用标签、悬空 parent_id）+ 路由顺序
   （/stats 必须早于 /{tag_id}，否则 "stats" 被当成标签 ID → 404。2026-11-10
   实测该端点恒 404 的根因就是路由压根没实现）。

**为什么重写**：上一版整份文件卡在 `pytest.importorskip("coapis.models.tags")`
（复数）上——那个模块在宿主 .venv-test 与 dev 容器里都不存在（仓库树是
`coapis/models/tag.py` 单数），于是本文件此前 100% 跳过 = 标签仓储接线从未有
测试覆盖（假绿）。

**两条纪律**（都是这轮踩出来的）：
- 绝不往工厂解析出的共享库（宿主上是 /root/.coapis/system/coapis.db）写/删数据。
  上一版夹具做「清空标签表」，把那个库里测试期迁移出来的数据真删了。
- 台账类断言用 JSON 兜底路径 + tmp_path，宿主与容器都跑、结果确定；依赖工厂
  初始化的仓储用例在宿主会因 `coapis.foundation.db_engine` 只存在于合并命名空间
  （dev 容器）而跳过，这是既有 TestCommunityFlow 的同一条边界，注释里写明。
"""

import json
import pathlib
from types import SimpleNamespace

import pytest

pytest.importorskip("coapis.foundation.tag_repository_sqlite")
pytest.importorskip("coapis.app.services.tag_service")

from coapis.foundation.repository_factory import RepositoryFactory
from coapis.foundation.tag_repository_sqlite import SqliteTagRepository
from coapis.models.tag import TagCreateRequest, TagUpdateRequest
from coapis.app.services.tag_service import TagService

BASE_ROWS = [
    {
        "id": "tag-cat", "name": "分类A", "type": "category",
        "description": "系统分类", "parent_id": None, "keywords": [],
        "related_skills": [], "sort_order": 1, "show_in_menu": True, "enabled": True,
    },
    {
        "id": "tag-dim", "name": "维度B", "type": "dimension",
        "description": None, "parent_id": None, "keywords": [],
        "related_skills": [], "sort_order": 2, "show_in_menu": False, "enabled": True,
    },
]


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """隔离：cwd 进临时目录 + 工厂保持未初始化（不碰任何共享库）。"""
    monkeypatch.chdir(tmp_path)
    RepositoryFactory.reset()
    yield
    RepositoryFactory.reset()


def _json_service(tmp_path, rows=None):
    """JSON 兜底路径上的 TagService：台账类断言用它，结果确定。"""
    data_dir = tmp_path / "coapis"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "tags.json").write_text(
        json.dumps({"tags": list(rows if rows is not None else BASE_ROWS)}),
        encoding="utf-8")
    return TagService(data_dir=data_dir)


def _add_json_tag(tmp_path, row: dict) -> None:
    """往 JSON 里追加一条标签（不依赖仓储）。

    先建板后追加的写法更顺，所以文件不存在时用基线两行起板。
    """
    f = tmp_path / "coapis" / "tags.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"tags": list(BASE_ROWS)}
    data["tags"].append(row)
    f.write_text(json.dumps(data), encoding="utf-8")


class TestCommunityRepositoryFlow:
    """社区版：工厂就绪 → 读写落在 coapis_tag 表，绝不碰 tags.json。

    注：`RepositoryFactory.initialize(edition="community")` 依赖
    `coapis.foundation.db_engine`，该模块只在 dev 容器的合并命名空间里存在；
    宿主 .venv-test 下本类整体跳过（与 TestCommunityFlow 同一边界），
    dev 容器 E2E 里真跑。
    """

    @pytest.fixture()
    def community(self, tmp_path):
        try:
            RepositoryFactory.reset()
            RepositoryFactory.initialize(edition="community")
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.skip(f"RepositoryFactory 社区版初始化在本环境不可用: {exc}")
        repo = RepositoryFactory.get_tag_repository()
        if not isinstance(repo, SqliteTagRepository):
            pytest.skip("coapis.foundation.tag_repository_sqlite 在合并命名空间中不可导入")
        return SimpleNamespace(
            service=TagService(data_dir=tmp_path / "coapis"),
            repo=repo,
            data_dir=tmp_path / "coapis",
        )

    def test_service_uses_sqlite_repository_not_enterprise(self, community):
        assert community.service._enterprise_repo is None
        assert community.service._community_repo is not None

    def test_reads_come_from_repository(self, community):
        response = community.service.list_tags()
        names = {t.name for t in response.tags}
        assert {"分类A", "维度B"} <= names, names

    def test_create_update_delete_hit_repository(self, community):
        created = community.service.create_tag(TagCreateRequest(
            # 业务规则：category 标签必须挂在 dimension 之下
            name="新建标签", type="category", parent_id="tag-dim",
        ))
        assert community.repo.get_tag(created.id) is not None
        assert (community.data_dir / "tags.json").exists() is False

        updated = community.service.update_tag(
            created.id, TagUpdateRequest(name="改名后", enabled=False),
        )
        assert updated.name == "改名后"
        assert updated.enabled is False
        stored = community.repo.get_tag(created.id)
        assert stored["name"] == "改名后"
        assert not stored["enabled"]

        assert community.service.delete_tag(created.id) is True
        assert community.repo.get_tag(created.id) is None

    def test_json_file_is_never_touched_in_community_flow(self, community):
        community.service.list_tags()
        assert list(community.data_dir.glob("tags.json")) == []

    def test_json_fallback_when_factory_not_initialized(self, tmp_path):
        """工厂未初始化（单测/裸启动）时不得崩，且必须继续读写 <data_dir>/tags.json。"""
        service = _json_service(tmp_path, [BASE_ROWS[0]])
        response = service.list_tags()
        assert response.total == 1
        assert response.tags[0].id == "tag-cat"
        assert service._community_repo is None and service._enterprise_repo is None


class TestTagStats:
    """标签台账：GET /api/admin/tags/stats（2026-11-10 前这条路由不存在 → 恒 404）。"""

    def test_counts_and_reference_health(self, tmp_path):
        service = _json_service(tmp_path)
        stats = service.get_tag_stats(
            scene_refs={"tag-cat": 3, "tag-dim": 1},
            scenes_scanned=5,
        )
        assert stats["total"] == 2
        assert stats["by_type"] == {"category": 1, "dimension": 1}
        assert stats["enabled"] == 2 and stats["disabled"] == 0
        assert stats["in_menu"] == 1  # 只有 tag-cat 勾了 show_in_menu
        assert stats["scenes_scanned"] == 5
        assert stats["referenced"] == 2
        assert stats["unused"] == 0
        assert stats["top_used"][0]["id"] == "tag-cat"
        assert stats["top_used"][0]["scene_count"] == 3

    def test_without_scene_refs_skips_reference_dimension(self, tmp_path):
        """引用关系由路由层传入；不传时引用维度归零而不是崩。"""
        stats = _json_service(tmp_path).get_tag_stats()
        assert stats["total"] == 2
        assert stats["referenced"] == 0
        assert stats["unused"] == 2
        assert stats["top_used"] == []

    def test_zero_reference_tags_are_counted(self, tmp_path):
        """零引用标签是标签体系腐化的信号，必须数得出来。"""
        service = _json_service(tmp_path)   # 先建板
        _add_json_tag(tmp_path, {           # 再追加（服务每次调用都重读文件）
            "id": "tag-quiet", "name": "没人用", "type": "category",
            "parent_id": None, "description": None, "keywords": [],
            "related_skills": [], "sort_order": 9, "show_in_menu": False,
            "enabled": True,
        })
        stats = service.get_tag_stats(scene_refs={"tag-cat": 2}, scenes_scanned=1)
        assert stats["total"] == 3
        assert stats["referenced"] == 1
        assert stats["unused"] == 2

    def test_dangling_parent_is_counted(self, tmp_path):
        """parent_id 指着不存在的标签 = 子标签在菜单树上凭空消失，必须被看见。"""
        service = _json_service(tmp_path)   # 先建板
        _add_json_tag(tmp_path, {           # 再追加
            "id": "tag-orphan", "name": "孤儿", "type": "category",
            "parent_id": "tag-gone", "description": None, "keywords": [],
            "related_skills": [], "sort_order": 99, "show_in_menu": False,
            "enabled": True,
        })
        stats = service.get_tag_stats()
        assert stats["dangling_parent"] == 1
        assert stats["with_children"] == 0

    def test_stats_route_registered_before_tag_id_route(self):
        """路由顺序铁律：/stats 必须注册在 /{tag_id} **之前**。

        FastAPI 按注册顺序匹配；写在后面时 "stats" 会被当成标签 ID 落进
        get_tag → 404。本次实测 `/api/admin/tags/stats` 恒 404 的根因就是路由
        压根没实现，故用路由表把顺序锁死，防止后人「顺手」把 /stats 挪到末尾。
        """
        router_src = (
            pathlib.Path(__file__).resolve().parents[1]
            / "coapis" / "app" / "routers" / "tags.py"
        )
        if not router_src.exists():
            pytest.skip("repo-tree layout mismatch")
        from coapis.app.routers.tags import router
        paths = [getattr(r, "path", "") for r in router.routes]
        assert "/admin/tags/stats" in paths, paths
        i_stats = paths.index("/admin/tags/stats")
        i_param = paths.index("/admin/tags/{tag_id}")
        assert i_stats < i_param, (
            f"路由顺序：/admin/tags/stats 必须早于 /admin/tags/{{tag_id}}，"
            f"实测 stats@{i_stats}, tag_id@{i_param}"
        )
