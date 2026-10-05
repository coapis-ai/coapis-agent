# -*- coding: utf-8 -*-
"""记忆台账（统一长期记忆）G0 契约 + 集成测试。

覆盖：
  A. 契约层：MemoryRepository ABC 12 方法面、全同步、不完整子类不可实例化、
     factory 注入/getter/reset 行为；
  B. 集成层：SqlaMemoryRepository 增删改查/去重/分页/软删/合并/相似/统计/
     dream outcome upsert（临时 SQLite 库，独立运行）。

独立运行：python tests/test_memory_repository.py
"""

import importlib
import inspect
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

RESULTS: list = []


def check(name: str, cond: bool, detail: str = ""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))


def _stub_agentscope_runtime():
    try:
        importlib.import_module("agentscope_runtime.engine.schemas.exception")
        return
    except Exception:  # noqa: BLE001
        pass
    for name in (
        "agentscope_runtime",
        "agentscope_runtime.engine",
        "agentscope_runtime.engine.schemas",
        "agentscope_runtime.engine.schemas.exception",
    ):
        sys.modules.setdefault(name, MagicMock())


EXPECTED_METHODS = {
    "add", "update_importance", "merge", "delete", "hard_delete",
    "get", "list_entries", "count", "find_similar", "stats", "record_outcome",
}


class _FakeMemoryRepository:
    """Complete fake for factory injection tests (implements all 12)."""

    def add(self, entry):
        return 1

    def update_importance(self, entry_id, importance):
        return True

    def merge(self, entry_ids):
        return entry_ids[0] if entry_ids else 0

    def delete(self, entry_id):
        return True

    def hard_delete(self, entry_id):
        return True

    def get(self, entry_id):
        return None

    def list_entries(self, **kw):
        return []

    def count(self, **kw):
        return 0

    def find_similar(self, entry_id, limit=5):
        return []

    def stats(self, **kw):
        return {}

    def record_outcome(self, **kw):
        return 1


def test_contract():
    from coapis.foundation.memory_repository import MemoryEntry, MemoryRepository

    # 1. ABC 方法面 == 12
    abstracts = set(MemoryRepository.__abstractmethods__)
    check("ABC 恰有 12 个抽象方法", abstracts == EXPECTED_METHODS,
          f"got {sorted(abstracts)}")

    # 2. 全同步（def，非 async def）
    async_bad = [
        m for m in EXPECTED_METHODS
        if inspect.iscoroutinefunction(getattr(MemoryRepository, m))
    ]
    check("12 方法全为同步 def", not async_bad, f"async: {async_bad}")

    # 3. 不完整子类不可实例化
    class Incomplete(MemoryRepository):
        def add(self, entry):
            return 1

    try:
        Incomplete()
        check("不完整子类实例化应抛 TypeError", False)
    except TypeError:
        check("不完整子类实例化应抛 TypeError", True)

    # 4. MemoryEntry to_dict/from_dict 往返
    e = MemoryEntry(id=7, scope="user", user_id="u1", category="fact",
                    title="t", content="c", importance=0.8)
    d = e.to_dict()
    e2 = MemoryEntry.from_dict({"id": 7, "scope": "user", "user_id": "u1",
                                "category": "fact", "title": "t", "content": "c",
                                "importance": 0.8, "unexpected": 1})
    check("MemoryEntry to_dict 含 14 键", len(d) == 14, f"got {len(d)}")
    check("MemoryEntry from_dict 忽略未知键", e2.id == 7 and e2.importance == 0.8)

    # 5. factory 注入 / getter / reset
    from coapis.foundation.repository_factory import RepositoryFactory
    RepositoryFactory.reset()
    try:
        RepositoryFactory.get_memory_repository()
        check("未初始化时 getter 应抛 RuntimeError", False)
    except RuntimeError:
        check("未初始化时 getter 应抛 RuntimeError", True)

    RepositoryFactory.initialize(edition="enterprise")
    RepositoryFactory.inject_memory_repository(_FakeMemoryRepository())
    check("注入后 getter 返回 fake",
          isinstance(RepositoryFactory.get_memory_repository(), _FakeMemoryRepository))
    RepositoryFactory.reset()
    check("reset 后 memory_repo 归零",
          RepositoryFactory._memory_repo is None)


def test_integration():
    from coapis.foundation.db.engine import init_engine, get_engine, reset_engine
    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.memory_repository import MemoryEntry
    from coapis.foundation.memory_repository_impl import SqlaMemoryRepository

    tmp = Path(tempfile.mkdtemp(prefix="mem_repo_test_"))
    (tmp / "system").mkdir(parents=True)
    db_path = tmp / "system" / "coapis.db"
    init_engine(f"sqlite:///{db_path}")
    BaseRow.metadata.create_all(get_engine())
    repo = SqlaMemoryRepository()

    # 1. add + 去重
    e1 = MemoryEntry(scope="user", user_id="u1", category="fact",
                     title="用户偏好深色主题", content="用户喜欢深色主题",
                     importance=0.6, source="conversation")
    id1 = repo.add(e1)
    check("add 返回正整数 id", isinstance(id1, int) and id1 > 0, f"id={id1}")

    dup = MemoryEntry(scope="user", user_id="u1", category="fact",
                      title="用户偏好深色主题", content="用户喜欢深色主题",
                      importance=0.9, source="conversation")
    id_dup = repo.add(dup)
    check("重复内容不产生第二行", id_dup == id1, f"{id_dup} vs {id1}")
    check("重复后 importance 取 max",
          abs((repo.get(id1).importance) - 0.9) < 1e-9, f"imp={repo.get(id1).importance}")
    check("count(user)=1", repo.count(scope="user", user_id="u1") == 1)

    # 2. update_importance clamp
    check("update_importance 正常", repo.update_importance(id1, 0.7))
    check("clamp 上限 1.0", repo.update_importance(id1, 5.0)
          and abs(repo.get(id1).importance - 1.0) < 1e-9)
    check("clamp 下限 0.0", repo.update_importance(id1, -3.0)
          and repo.get(id1).importance == 0.0)

    # 3. 批量插入用于过滤/分页
    for i in range(6):
        repo.add(MemoryEntry(scope="user", user_id="u1",
                             category="decision" if i % 2 == 0 else "preference",
                             title=f"第{i}条记忆 数据库选型",
                             content=f"关于数据库选型的第{i}条记录",
                             importance=0.3 + i * 0.05, source="dream"))
    check("count 全部 = 7", repo.count(user_id="u1") == 7,
          f"got {repo.count(user_id='u1')}")
    check("category 过滤", repo.count(user_id="u1", category="decision") == 3)
    check("q 模糊过滤(6 条循环行命中)", repo.count(user_id="u1", q="数据库选型") == 6)
    check("q 不命中 = 0", repo.count(user_id="u1", q="不存在的内容xyz") == 0)

    lst = repo.list_entries(user_id="u1", limit=3, offset=0)
    check("分页 limit=3 返回 3 条", len(lst) == 3)
    offsets_ok = all(len(repo.list_entries(user_id="u1", limit=3, offset=o)) <= 3
                     for o in (0, 3, 6))
    check("分页 offset 遍历不越界", offsets_ok)
    newest_first = all(lst[i].created_at >= lst[i + 1].created_at for i in range(len(lst) - 1))
    check("list 按 created_at 倒序", newest_first)

    # 4. 软删 / 硬删
    victim = repo.list_entries(user_id="u1", category="preference")[0]
    check("soft delete 成功", repo.delete(victim.id))
    check("soft delete 幂等返回 False", not repo.delete(victim.id))
    check("软删后 count -1", repo.count(user_id="u1") == 6)
    check("软删后 get 返回 None", repo.get(victim.id) is None)
    check("hard delete 成功", repo.hard_delete(victim.id))
    check("对已软删行硬删不再二次递减", repo.count(user_id="u1") == 6)
    check("hard delete 幂等返回 False", not repo.hard_delete(victim.id))

    # 5. merge
    pair = repo.list_entries(user_id="u1", category="decision")[:2]
    kept = repo.merge([pair[0].id, pair[1].id])
    kept_row = repo.get(kept)
    check("merge 保留最小 id", kept == min(pair[0].id, pair[1].id))
    check("merge 后另一行软删", repo.get(max(pair[0].id, pair[1].id)) is None)
    check("merge 内容拼接", kept_row is not None and kept_row.content.count("\n\n") >= 1)
    check("merge 单元素直通", repo.merge([pair[0].id]) == pair[0].id)

    # 6. find_similar
    sims = repo.find_similar(kept, limit=5)
    check("find_similar 不含自身", all(s.id != kept for s in sims))
    check("find_similar 同 scope", all(s.scope == kept_row.scope for s in sims))
    check("find_similar 限长", len(sims) <= 5)

    # 7. stats
    st = repo.stats(user_id="u1")
    check("stats.total 与实际一致", st["total"] == repo.count(user_id="u1"),
          f"{st['total']} vs {repo.count(user_id='u1')}")
    check("stats.by_category 合计 = total", sum(st["by_category"].values()) == st["total"])
    check("stats.by_source 含 dream/conversation",
          "dream" in st["by_source"] and "conversation" in st["by_source"])
    check("stats.avg_importance 在 [0,1]", 0.0 <= st["avg_importance"] <= 1.0)

    # 8. record_outcome upsert
    now_day = time.strftime("%Y-%m-%d")
    oid1 = repo.record_outcome(user_id="u1", day=now_day, status="success",
                               reason="ok", summary="s1")
    oid2 = repo.record_outcome(user_id="u1", day=now_day, status="partial",
                               reason="low", summary="s2")
    check("outcome 同日 upsert 同 id", oid1 == oid2, f"{oid1} vs {oid2}")
    oc = repo.get(oid1)
    check("outcome 内容覆盖为最新", oc is not None and "status=partial" in oc.content)
    check("outcome category=dream", oc is not None and oc.category == "dream")
    oid3 = repo.record_outcome(user_id="u1", day="2020-01-01", status="failed",
                               reason="boom", summary="s3")
    check("outcome 不同日新建行", oid3 != oid1)

    reset_engine()


def main():
    _stub_agentscope_runtime()
    test_contract()
    test_integration()
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n===== {passed}/{total} passed =====")
    if passed != total:
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  FAIL: {name} {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
