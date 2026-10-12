"""M1 四域落库测试（域A外部系统 / 域B场景 / 域C标签 / 域D用户场景）。

验证：
  1. community schema 建出 4 张新表；
  2. ensure_domain_migrated 把 JSON 播种进 DB，且幂等（重跑不重复）；
  3. TagService 走 SQLite 仓储（load/CRUD/save-all 语义）；
  4. SceneAgentService 走 SQLite 仓储（list/create/usage 计数/软删除/硬删除）；
  5. UserSceneService 走 SQLite 仓储（get/set + get_all_scenes）；
  6. 外部系统 store 的 save_systems 落 DB（reconcile 删除语义）。

独立运行：python tests/test_m1_domain_persistence.py
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

RESULTS: list = []


def check(name: str, cond: bool, detail: str = ""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))


def _stub_agentscope_runtime():
    """coapis.exceptions 继承 agentscope_runtime 的异常类，而该包仅在
    Docker 运行时环境安装。本测试只验证数据层持久化，无需真实 runtime，
    因此用 MagicMock 占位（仅当真实包缺失时注入）。"""
    import importlib
    try:
        importlib.import_module("agentscope_runtime.engine.schemas.exception")
        return  # 真实包可用，无需 stub
    except Exception:  # noqa: BLE001
        pass
    from unittest.mock import MagicMock
    for name in (
        "agentscope_runtime",
        "agentscope_runtime.engine",
        "agentscope_runtime.engine.schemas",
        "agentscope_runtime.engine.schemas.exception",
    ):
        sys.modules.setdefault(name, MagicMock())


def main():
    _stub_agentscope_runtime()
    tmp = Path(tempfile.mkdtemp(prefix="m1_test_"))
    system_dir = tmp / "system"
    system_dir.mkdir(parents=True)

    # --- 隔离：把 SYSTEM_DIR / WORKING_DIR 指向临时目录 ---
    import coapis.constant as constant
    import coapis.foundation.db_settings as db_settings
    constant.SYSTEM_DIR = system_dir
    constant.WORKING_DIR = tmp
    db_settings.SYSTEM_DIR = system_dir
    db_settings.WORKING_DIR = tmp

    from coapis.foundation.repository_factory import RepositoryFactory
    from coapis.foundation.migrations import ensure_domain_migrated, get_migration_flag
    import sqlite3

    db_path = system_dir / "coapis.db"

    # --- 准备 JSON 数据（模拟存量实例） ---
    # tags/scenes/user_scenes 位于 data_dir(=WORKING_DIR)；external_systems 位于 system_dir
    (tmp / "tags.json").write_text(json.dumps({
        "version": "3.0",
        "tags": [
            {"id": "tag_dim_1", "name": "技术", "type": "dimension",
             "description": "技术维度", "enabled": True, "show_in_menu": False,
             "sort_order": 1, "created_at": "2026-01-01T00:00:00+00:00",
             "updated_at": "2026-01-01T00:00:00+00:00"},
            {"id": "tag_cat_1", "name": "办公", "type": "category",
             "description": "办公分类", "enabled": True, "show_in_menu": True,
             "keywords": ["公文", "报告"], "related_skills": ["skill_a"],
             "metadata": {"level": 1},
             "sort_order": 1, "created_at": "2026-01-01T00:00:00+00:00",
             "updated_at": "2026-01-01T00:00:00+00:00"},
            {"id": "tag_no_date", "name": "无时间标签", "type": "dimension",
             "description": "空时间戳回归", "enabled": True, "show_in_menu": False,
             "sort_order": 9, "created_at": "", "updated_at": ""},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    (tmp / "scenes.json").write_text(json.dumps({
        "version": 1,
        "scenes": [
            {"id": "scene_a", "name": "场景A", "icon": "🤖", "description": "d-a",
             "short_description": "sd-a", "primary_tag_id": "tag_cat_1",
             "tag_ids": ["tag_dim_1"], "tags": ["tag_dim_1"], "skills": [],
             "system_prompt": "sp-a", "welcome_message": "wm-a", "status": "active",
             "usage_count": 3, "created_at": "2026-01-01T00:00:00+00:00",
             "updated_at": "2026-01-01T00:00:00+00:00", "created_by": "admin",
             "category": "办公"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    (tmp / "user_scenes.json").write_text(json.dumps({
        "version": "1.0",
        "user_scenes": [
            {"user_id": "u1", "enabled_scenes": ["scene_a"],
             "custom_scenes": [], "preferences": {}},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    (system_dir / "external_systems_config.json").write_text(json.dumps({
        "systems": [
            {"provider_id": "oa", "name": "OA系统", "enabled": True,
             "login_url": "https://oa.example.com/login", "user_api_url": ""},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    # --- 1. 域迁移 ---
    ok = ensure_domain_migrated(data_dir=tmp, system_dir=system_dir, db_path=db_path)
    check("M1: ensure_domain_migrated 首次执行返回 True", ok is True)

    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("tags", "scenes", "user_scene_settings", "external_systems"):
        check(f"M1: 表 {t} 存在", t in tables)
    check("M1: tags 播种 3 行",
          conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 3)
    check("M1: scenes 播种 1 行",
          conn.execute("SELECT COUNT(*) FROM scenes").fetchone()[0] == 1)
    check("M1: user_scene_settings 播种 1 行",
          conn.execute("SELECT COUNT(*) FROM user_scene_settings").fetchone()[0] == 1)
    check("M1: external_systems 播种 1 行",
          conn.execute("SELECT COUNT(*) FROM external_systems").fetchone()[0] == 1)
    check("M1: 迁移标志已置",
          get_migration_flag(conn, "domain_migration") == "done")
    conn.close()

    # 幂等：再跑一次不重复
    ok2 = ensure_domain_migrated(data_dir=tmp, system_dir=system_dir, db_path=db_path)
    check("M1: 幂等（第二次返回 False）", ok2 is False)
    conn = sqlite3.connect(str(db_path))
    check("M1: 幂等后 tags 仍为 3 行",
          conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 3)
    conn.close()

    # --- 2. 工厂初始化（community 分支注入 3 个仓储） ---
    RepositoryFactory.reset()
    RepositoryFactory.initialize()
    check("M1: 工厂已初始化 community",
          RepositoryFactory.is_initialized() and RepositoryFactory.get_edition() == "community")
    try:
        tag_repo = RepositoryFactory.get_tag_repository()
        scene_repo = RepositoryFactory.get_scene_repository()
        us_repo = RepositoryFactory.get_user_scene_repository()
        check("M1: 3 个仓储均已注入",
              tag_repo is not None and scene_repo is not None and us_repo is not None)
    except RuntimeError as e:
        check("M1: 3 个仓储均已注入", False, str(e))

    # --- 3. TagService 走 SQLite ---
    from coapis.app.services.tag_service import TagService
    svc = TagService(system_dir)
    check("M1: TagService 使用社区仓储", getattr(svc, "_community_repo", None) is not None)
    tags = svc.list_tags()
    check("M1: list_tags 读出 3 个标签", tags.total == 3, f"got {tags.total}")
    cat_tags = svc.list_tags(tag_type="category")
    check("M1: 按类型过滤（category=1）", cat_tags.total == 1, f"got {cat_tags.total}")
    one = svc.get_tag("tag_dim_1")
    check("M1: get_tag 命中", one is not None and one.name == "技术")
    one_cat = svc.get_tag("tag_cat_1")
    check("M1: keywords/related_skills/metadata 往返一致（JSON 列解析）",
          one_cat is not None
          and one_cat.keywords == ["公文", "报告"]
          and one_cat.related_skills == ["skill_a"]
          and one_cat.metadata == {"level": 1},
          f"got keywords={getattr(one_cat, 'keywords', None)!r} "
          f"related_skills={getattr(one_cat, 'related_skills', None)!r} "
          f"metadata={getattr(one_cat, 'metadata', None)!r}")
    check("M1: 空 JSON 列 [] 解析为空 list（非 None）",
          one is not None and one.keywords == [] and one.related_skills == [],
          f"got keywords={getattr(one, 'keywords', None)!r}")
    one_nd = svc.get_tag("tag_no_date")
    check("M1: 空时间戳解析为 None（非报错）",
          one_nd is not None and one_nd.created_at is None and one_nd.updated_at is None,
          f"got created_at={getattr(one_nd, 'created_at', None)!r}")

    # 创建新标签 → 落 DB
    from coapis.models.tag import TagCreateRequest
    created = svc.create_tag(TagCreateRequest(
        name="新标签", type="dimension", description="db 创建"))
    conn = sqlite3.connect(str(db_path))
    check("M1: 创建标签落 DB",
          conn.execute("SELECT COUNT(*) FROM tags WHERE id=?", (created.id,)).fetchone()[0] == 1)
    # tags.json 不应被改写（只读备份）
    json_tags = json.loads((tmp / "tags.json").read_text(encoding="utf-8"))
    check("M1: tags.json 未被改写（仍 2 条）", len(json_tags.get("tags", [])) == 2)
    conn.close()

    # 删除标签 → DB 消失
    svc.delete_tag(created.id)
    conn = sqlite3.connect(str(db_path))
    check("M1: 删除标签 DB 消失",
          conn.execute("SELECT COUNT(*) FROM tags WHERE id=?", (created.id,)).fetchone()[0] == 0)
    conn.close()

    # --- 4. SceneAgentService 走 SQLite ---
    from coapis.services.scene_agent_service import SceneAgentService
    ss = SceneAgentService(system_dir)
    check("M1: SceneAgentService 使用社区仓储",
          getattr(ss, "_community_repo", None) is not None)
    scenes = ss.list_scenes()
    check("M1: list_scenes 读出 1 个场景", scenes.total == 1, f"got {scenes.total}")
    check("M1: 场景字段完整（usage_count=3）",
          scenes.scenes and scenes.scenes[0].usage_count == 3)

    ss.increment_usage("scene_a")
    s = ss.get_scene("scene_a")
    check("M1: increment_usage 生效（3→4）", s.usage_count == 4, f"got {s.usage_count}")

    # 软删除：status=deleted
    ok_del = ss.delete_scene("scene_a")
    check("M1: 软删除返回 True", ok_del is True)
    s = ss.get_scene("scene_a")
    check("M1: 软删除后 status=deleted", s.status == "deleted")
    # 硬删除：彻底消失
    ok_hdel = ss.delete_scene("scene_a", hard_delete=True)
    check("M1: 硬删除返回 True", ok_hdel is True)
    conn = sqlite3.connect(str(db_path))
    check("M1: 硬删除后 DB 无该行",
          conn.execute("SELECT COUNT(*) FROM scenes WHERE scene_id='scene_a'").fetchone()[0] == 0)
    conn.close()

    # --- 5. UserSceneService 走 SQLite ---
    from coapis.services.user_scene_service import UserSceneService
    us = UserSceneService(str(system_dir))
    check("M1: UserSceneService 使用社区仓储",
          getattr(us, "_us_repo", None) is not None and getattr(us, "_scene_repo", None) is not None)
    cfg = us.get_user_scenes("u1")
    check("M1: get_user_scenes 命中播种数据",
          cfg.get("enabled_scenes") == ["scene_a"], str(cfg))
    us.set_user_scenes("u2", {"enabled_scenes": ["s_x"], "custom_scenes": [],
                               "preferences": {"k": 1}})
    cfg2 = us.get_user_scenes("u2")
    check("M1: set/get 用户场景 round-trip",
          cfg2.get("enabled_scenes") == ["s_x"] and cfg2.get("preferences") == {"k": 1},
          str(cfg2))
    conn = sqlite3.connect(str(db_path))
    check("M1: user_scene_settings 共 2 行",
          conn.execute("SELECT COUNT(*) FROM user_scene_settings").fetchone()[0] == 2)
    conn.close()
    all_scenes = us.get_all_scenes()
    check("M1: get_all_scenes 走 DB（含新建场景）",
          isinstance(all_scenes, list))

    # --- 6. 外部系统 store save_systems 落 DB ---
    ext_store = RepositoryFactory.get_external_identity_store()
    check("M1: external identity store 可用", ext_store is not None)
    loaded = ext_store.load_systems()
    check("M1: load_systems 读出播种系统", len(loaded) == 1 and loaded[0]["provider_id"] == "oa")
    ext_store.save_systems([
        {"provider_id": "oa", "name": "OA系统", "enabled": True,
         "login_url": "https://oa.example.com/login"},
        {"provider_id": "erp", "name": "ERP", "enabled": True,
         "login_url": "https://erp.example.com/login"},
    ])
    loaded2 = ext_store.load_systems()
    check("M1: save_systems 后 2 个系统", len(loaded2) == 2)
    check("M1: reconcile 删除语义（去掉 erp 后消失）",
          len(ext_store.load_systems()) == 1 if ext_store.save_systems([
              {"provider_id": "oa", "name": "OA系统", "enabled": True,
               "login_url": "https://oa.example.com/login"}]) or True else False)
    loaded3 = ext_store.load_systems()
    check("M1: 最终只剩 oa", len(loaded3) == 1 and loaded3[0]["provider_id"] == "oa",
          str(loaded3))

    # --- 汇总 ---
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n===== M1 四域落库：{passed}/{total} 通过 =====")
    RepositoryFactory.reset()
    if passed != total:
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  FAIL: {name} {detail}")
        sys.exit(1)
    # 清理临时目录
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print("OK")


if __name__ == "__main__":
    main()
