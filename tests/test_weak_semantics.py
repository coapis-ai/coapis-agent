#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch 2/3 verification: workspace scope hooks + hash weak semantics.

Covers:
  1. hash_similarity primitives (determinism, identity, disjoint, CJK)
  2. find_similar ranks by hash cosine (integration, temp sqlite)
  3. list_entries / count workspace_id filter (integration)
  4. scope=workspace entries are storable + filterable
  5. promotion near-duplicate reinforcement (stubbed repos, no app boot)
"""
import importlib
import os
import sys
import tempfile
import time
import traceback
import types
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
# Server dir: honor COAPIS_SERVER_DIR (container runs with /app layout),
# else fall back to the repo-local server/ directory.
SERVER_DIR = os.environ.get("COAPIS_SERVER_DIR", str(ROOT / "server"))
sys.path.insert(0, SERVER_DIR)

# Host-side shim: coapis.constant reads .env via python-dotenv, which is
# absent on bare hosts (present in the container). Provide a no-op module
# so the import chain succeeds everywhere.
try:
    import dotenv  # noqa: F401
except ImportError:
    _fake_dotenv = types.ModuleType("dotenv")
    _fake_dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = _fake_dotenv


def _stub_agentscope_runtime():
    """Register mock closures for every agentscope_runtime module the
    crons import chain touches (host lacks the wheel; container has it)."""
    try:
        importlib.import_module("agentscope_runtime.engine.schemas.exception")
        return
    except Exception:  # noqa: BLE001
        pass
    names = [
        "agentscope_runtime",
        "agentscope_runtime.engine",
        "agentscope_runtime.engine.app",
        "agentscope_runtime.engine.deployers",
        "agentscope_runtime.engine.deployers.adapter",
        "agentscope_runtime.engine.deployers.adapter.a2a",
        "agentscope_runtime.engine.deployers.adapter.a2a.a2a_protocol_adapter",
        "agentscope_runtime.engine.runner",
        "agentscope_runtime.engine.schemas",
        "agentscope_runtime.engine.schemas.agent_schemas",
        "agentscope_runtime.engine.schemas.exception",
    ]
    for name in names:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = []  # mark as package so deep imports resolve
            setattr(mod, "__getattr__", lambda attr, _n=name: MagicMock())
            sys.modules[name] = mod

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "-", name, ("" if cond else f"| {detail}"))


def main() -> int:
    # ---------- 1. hash similarity primitives ----------
    hs = importlib.import_module("coapis.foundation.hash_similarity")
    v_same_a = hs.feature_vector("用户偏好深色主题")
    v_same_b = hs.feature_vector("用户偏好深色主题")
    check("向量确定性", v_same_a == v_same_b)
    check("相同文本余弦=1.0", abs(hs.text_similarity("用户偏好深色主题", "用户偏好深色主题") - 1.0) < 1e-9)
    check("英文大小写不敏感", hs.text_similarity("Dark Theme", "dark theme") > 0.99)
    sim_close = hs.text_similarity("用户偏好深色主题", "用户很喜欢深色主题")
    sim_far = hs.text_similarity("用户偏好深色主题", "数据库连接池超时设置")
    check("近似文本得分高于相异", sim_close > sim_far, f"close={sim_close:.3f} far={sim_far:.3f}")
    check("相异中文文本低分", sim_far < 0.4, f"far={sim_far:.3f}")
    check("空文本得分为0", hs.text_similarity("", "任意文本") == 0.0)
    check("阈值常量=0.85(D2)", hs.PROMOTE_SIM_THRESHOLD == 0.85)
    vec = hs.feature_vector("some text 一些文本")
    check("向量维度=256", len(vec) == 256)
    check("向量L2归一化", abs(sum(x * x for x in vec) - 1.0) < 1e-9)

    # ---------- 2-4. integration on temp sqlite ----------
    importlib.import_module("coapis.foundation.db.engine")
    engine_mod = importlib.import_module("coapis.foundation.db.engine")
    base_mod = importlib.import_module("coapis.foundation.db.base")
    from coapis.foundation.memory_repository import MemoryEntry
    from coapis.foundation.memory_repository_impl import SqlaMemoryRepository

    tmp = Path(tempfile.mkdtemp(prefix="ws_sem_test_"))
    (tmp / "system").mkdir(parents=True)
    db_path = tmp / "system" / "coapis.db"
    engine_mod.init_engine(f"sqlite:///{db_path}")
    base_mod.BaseRow.metadata.create_all(engine_mod.get_engine())
    repo = SqlaMemoryRepository()

    repo.add(MemoryEntry(scope="user", user_id="u1", category="pref",
                         title="用户偏好深色主题", content="用户明确表示喜欢深色主题界面",
                         source="test", importance=0.7))
    repo.add(MemoryEntry(scope="user", user_id="u1", category="pref",
                         title="用户偏好深色主题界面", content="用户非常喜欢深色主题，尤其是夜间使用深色主题",
                         source="test", importance=0.7))
    repo.add(MemoryEntry(scope="user", user_id="u1", category="fact",
                         title="数据库连接池", content="数据库连接池最大连接数为50，超时30秒",
                         source="test", importance=0.5))
    repo.add(MemoryEntry(scope="user", user_id="u2", category="pref",
                         title="用户偏好深色主题", content="用户明确表示喜欢深色主题界面",
                         source="test", importance=0.7))
    repo.add(MemoryEntry(scope="workspace", user_id="u1", workspace_id="ws-org",
                         category="goal", title="团队共享规范",
                         content="团队统一采用深色主题设计规范", source="test", importance=0.8))
    repo.add(MemoryEntry(scope="user", user_id="u1", workspace_id="ws-other",
                         category="fact", title="另一个工作区",
                         content="属于 ws-other 的条目", source="test", importance=0.5))

    dark = next(e for e in repo.list_entries(user_id="u1") if e.title == "用户偏好深色主题")
    sims = repo.find_similar(dark.id, limit=3)
    check("find_similar 返回≤limit", len(sims) <= 3)
    check("find_similar 首条是最相似的同类条目",
          len(sims) > 0 and sims[0].title == "用户偏好深色主题界面",
          f"got={[s.title for s in sims]}")
    check("find_similar 不跨owner(u2同名条目被排除)",
          all(s.user_id == "u1" for s in sims))

    # workspace_id filter
    ws_hits = repo.list_entries(workspace_id="ws-org")
    check("workspace_id 过滤命中", len(ws_hits) == 1 and ws_hits[0].scope == "workspace")
    check("workspace_id 计数一致", repo.count(workspace_id="ws-org") == 1)
    check("workspace_id 过滤排除其它工作区",
          all(e.workspace_id == "ws-other" for e in repo.list_entries(workspace_id="ws-other")))
    check("无 workspace 的条目不受 workspace_id 过滤影响",
          len(repo.list_entries(user_id="u1", workspace_id="ws-none")) == 0)

    # ---------- 5. promotion near-duplicate reinforcement ----------
    _stub_agentscope_runtime()
    mgr_mod = importlib.import_module("coapis.app.crons.manager")
    rf_mod = importlib.import_module("coapis.foundation.repository_factory")

    class StubTL:
        def __init__(self, cands):
            self.cands = cands
            self.promoted = []

        def promotion_candidates(self, user_id):
            return self.cands

        def mark_promoted(self, ids, ts):
            self.promoted.extend(ids)

    class StubMem:
        def __init__(self, existing):
            self.existing = existing
            self.added = []
            self.reinforced = {}

        def list_entries(self, **kw):
            return self.existing

        def add(self, entry):
            self.added.append(entry)

        def update_importance(self, entry_id, importance):
            self.reinforced[entry_id] = importance
            for e in self.existing:  # mirror real repo: mutate in place
                if e.id == entry_id:
                    e.importance = importance

    existing = [MemoryEntry(id=1, scope="user", user_id="alice", category="decision",
                            title="选定PostgreSQL", content="经过评估最终选定 PostgreSQL 作为主数据库",
                            source="timeline:1", importance=0.6)]
    cands = [
        {"id": 101, "content": "经过评估最终选定 PostgreSQL 作为主数据库",
         "importance": 0.9, "signal_type": "decision", "agent_id": "a1"},
        {"id": 102, "content": "部署流水线切换到 GitLab CI，每周发布一次",
         "importance": 0.7, "signal_type": "decision", "agent_id": "a1"},
        {"id": 103, "content": "经过评估最终选定 PostgreSQL 作为主数据库！",
         "importance": 0.8, "signal_type": "decision", "agent_id": "a1"},
    ]
    tl_stub = StubTL(cands)
    mem_stub = StubMem(existing)
    orig_tl, orig_mem = rf_mod.RepositoryFactory.get_memory_timeline_repository, \
        rf_mod.RepositoryFactory.get_memory_repository
    rf_mod.RepositoryFactory.get_memory_timeline_repository = lambda: tl_stub
    rf_mod.RepositoryFactory.get_memory_repository = lambda: mem_stub
    try:
        mgr_obj = mgr_mod.CronManager.__new__(mgr_mod.CronManager)
        n = mgr_obj._promote_timeline_events("alice", "a1")
        check("晋升计数=3(含强化)", n == 3, f"n={n}")
        check("近重复不新增(101/103强化原有)", len(mem_stub.added) == 1,
              f"added={[a.title for a in mem_stub.added]}")
        check("强化取重要性max(0.6,0.9)=0.9", mem_stub.reinforced.get(1) == 0.9,
              f"reinforced={mem_stub.reinforced}")
        check("相异候选正常新增", mem_stub.added[0].content.startswith("部署流水线"))
        check("全部标记已晋升", sorted(tl_stub.promoted) == [101, 102, 103])
    finally:
        rf_mod.RepositoryFactory.get_memory_timeline_repository = orig_tl
        rf_mod.RepositoryFactory.get_memory_repository = orig_mem

    engine_mod.reset_engine()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n=== {passed}/{len(RESULTS)} checks passed ===")
    for name, ok, detail in RESULTS:
        if not ok:
            print("FAILED:", name, "|", detail)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        print("\n=== EXCEPTION ===")
        sys.exit(2)
