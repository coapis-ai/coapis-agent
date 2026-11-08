#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识投影层（knowledge_export）+ 注入准入测试。

方案：docs/plans/2026-11-07-社区版知识沉淀-可行性核查与瘦身v3.md（批次 1/2/6）。

钉住的行为：
  1. 全量重建 + 幂等：内容字节级一字不差；签名未变则不写盘；
  2. 一把尺子：导出与启动自检共用准入条件（机器维护日志不入投影）；
  3. 删除会传播：软删的行 → 文件消失；**整用户/整分类清空**也要清干净
     （历史缺陷：只为"还有行"的目录收尾，空目录里的陈旧 .md 与旧 index.json
     计数永远留着，自检因此每轮启动都判数量不符、全量重建）；
  4. 静态骨架文件永不被投影覆盖；
  5. 分类配额按 importance 淘汰最弱；
  6. 共享层晋升保留 importance / agent_id（历史缺陷：写侧字段名错配把
     importance 写成 0、agent_id 写成 None → 共享层永远排最后）；分类统一
     记 "knowledge"（方案 D-2）；余弦去重与每轮上限生效；
  7. 注入：噪声源不占注入位，条数 ≤ TOP_N，正文字符 ≤ MAX_CHARS，
     注入账本与 citation 回填同源。

独立运行：python tests/test_knowledge_projection.py
"""

import importlib
import json
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
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f"  ({detail})" if detail and not cond else ""))


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


def _mem_files(kb_dir: Path) -> list:
    return sorted(p.name for p in kb_dir.rglob("mem-*.md"))


def _contents(kb_dir: Path) -> dict:
    return {p: p.read_bytes() for p in kb_dir.rglob("*.md")}


def _add(ke, Memory, scope, user, content, *, source="timeline", importance=0.7,
         category="fact", agent_id=None):
    with ke.get_session() as s:
        row = Memory(
            scope=scope, user_id=user, agent_id=agent_id, category=category,
            title=content[:40], content=content, source=source,
            importance=importance, created_at=time.time(), updated_at=time.time(),
            dedup_key=f"k{abs(hash((scope, user, content))) % 10**9}",
        )
        s.add(row)
        s.commit()
        return row.id


def test_projection(tmp_path: Path):
    from coapis.constant import KNOWLEDGE_NOISE_SOURCES
    from coapis.foundation import knowledge_export as ke
    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.engine import get_engine, init_engine, reset_engine
    from coapis.foundation.db.models.memory import Memory
    from coapis.foundation import foundation_manager as fmod
    from coapis.foundation.foundation_manager import FoundationManager
    from coapis.foundation.memory_repository import MemoryEntry
    from coapis.foundation.memory_repository_impl import SqlaMemoryRepository

    reset_engine()
    init_engine(f"sqlite:///{tmp_path / 'proj.db'}")
    BaseRow.metadata.create_all(get_engine())

    root = tmp_path / "foundation"
    ke.foundation_root = lambda: root  # 投影落临时目录，不碰运行时 WORKING_DIR

    id_bob = _add(ke, Memory, "user", "bob", "bob 的私人偏好，不该进 alice 的目录", importance=0.9)
    _add(ke, Memory, "user", "alice", "用户偏好深色主题与紧凑字号", importance=0.8)
    _add(ke, Memory, "user", "alice", "status=success; reason=consolidated",
         source="dream", importance=1.0)
    _add(ke, Memory, "agent", "alice", "status=success; summary=workspace=ok",
         source="dream", importance=1.0)
    _add(ke, Memory, "workspace", "", "共享层老墨迹", importance=0.2)

    # 1. 首次导出
    st = ke.export_from_db(force=True)
    noise = tuple(KNOWLEDGE_NOISE_SOURCES)
    with ke.get_session() as s:
        expect = s.query(Memory).filter(
            Memory.deleted_at.is_(None),
            Memory.source.is_(None) if not noise else Memory.source.notin_(noise),
        ).count()
    check("导出 total = 台账里该投影的行数（与自检同尺子）",
          st["total"] == expect, f"{st['total']} vs {expect} ({st})")
    check("机器维护日志不进投影（source=dream 被排除）",
          st["total"] == 3, f"{st}")
    check("投影文件数 == 导出条数",
          len(_mem_files(root)) == st["total"], f"{_mem_files(root)}")
    check("全局投影与个人投影分目录（global 与 users/<uid>，各自 <scope>/<category>/）",
          (ke.global_knowledge_dir() / "workspace").is_dir()
          and (ke.user_knowledge_dir("alice") / "user" / "fact").is_dir()
          and bool(_mem_files(ke.user_knowledge_dir("bob"))),
          str(ke.user_knowledge_dir("alice")))
    check("alice 的投影只含 alice 自己的条目",
          len(_mem_files(ke.user_knowledge_dir("alice"))) == 1,
          f"{_mem_files(ke.user_knowledge_dir('alice'))}")

    # 2. 幂等：签名一致 → 不写盘；强制重建 → 字节级一字不差
    st2 = ke.export_from_db()
    check("签名未变时不写盘（去抖）", st2.get("written") is False, f"{st2}")
    before = _contents(root)
    st3 = ke.export_from_db(force=True)
    check("全量重建内容字节级一字不差",
          st3.get("written") is True and before == _contents(root), f"{st3}")

    # 3. 启动自检与导出同尺子
    v = ke.verify_projection()
    check("自检通过：投影条目数 == 准入行数",
          v["ok"] is True and v["db"] == v["files"] == st["total"], f"{v}")
    next(iter(root.rglob("mem-*.md"))).unlink()
    v2 = ke.verify_projection()
    check("自检抓到缺文件（数量不符）",
          v2["ok"] is False and v2["reason"].startswith("count_mismatch"), f"{v2}")
    ke.export_from_db(force=True)
    check("全量重建可修复缺文件",
          ke.verify_projection()["ok"] is True, str(ke.verify_projection()))

    # 4. 删除会传播（单条 + 整用户清空）
    with ke.get_session() as s:
        row = s.get(Memory, id_bob)
        row.deleted_at = time.time()
        s.commit()
    st4 = ke.export_from_db(force=True)
    check("软删的行在投影里消失（有清扫计数）",
          st4["total"] == st["total"] - 1 and st4["pruned"] >= 1, f"{st4}")
    check("bob 整组清空后目录里没有残留文件",
          not _mem_files(ke.user_knowledge_dir("bob")),
          f"{_mem_files(ke.user_knowledge_dir('bob'))}")
    idx = json.loads((ke.user_knowledge_dir("bob") / "index.json").read_text(
        encoding="utf-8"))
    check("清空后 index.json 计数归零（自检不长期数量不符）",
          idx.get("count") == 0, str(idx))
    check("删除后自检仍自洽",
          ke.verify_projection()["ok"] is True, str(ke.verify_projection()))

    # 5. 静态骨架不被覆盖
    ke.ensure_static_templates()
    cp = root / "core_principles.md"
    cp.write_text("人工写下的原则，不许被机器覆盖", encoding="utf-8")
    ke.export_from_db(force=True)
    ke.ensure_static_templates()
    check("静态骨架文件不被投影覆盖",
          "人工写下的原则" in cp.read_text(encoding="utf-8"),
          cp.read_text(encoding="utf-8")[:60])

    # 6. 分类配额按 importance 淘汰最弱（配额上限打桩，不真灌 50 条）
    repo = SqlaMemoryRepository()
    fm = FoundationManager(str(root), memory_repo=repo)
    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet".split()
    for i in range(6):
        repo.add(MemoryEntry(
            scope="user", user_id="carol", category="quota",
            title=f"配额条目{i}",
            content=f"配额条目{i} " + " ".join(words[i % len(words)] for _ in range(6)),
            source="timeline", importance=0.1 * i,
        ))
    with ke.get_session() as s:
        seeded = s.query(Memory).filter(
            Memory.category == "quota", Memory.deleted_at.is_(None),
        ).count()
    check("配额类种子条数（内容互异，全部入库）", seeded >= 6, f"seeded={seeded}")
    saved_quota = fmod.KNOWLEDGE_CATEGORY_QUOTA
    fmod.KNOWLEDGE_CATEGORY_QUOTA = 4
    try:
        evicted = fm.enforce_category_quota(MemoryEntry(
            scope="user", user_id="carol", category="quota",
            title="触发配额", content="触发配额 独立 内容 不重复 xyz",
            source="timeline", importance=0.5,
        ))
    finally:
        fmod.KNOWLEDGE_CATEGORY_QUOTA = saved_quota
    check("分类配额淘汰掉最弱的 (种子数 - 上限) 条",
          evicted == seeded - 4, f"evicted={evicted} seeded={seeded}")
    with ke.get_session() as s:
        rows = s.query(Memory).filter(
            Memory.category == "quota", Memory.deleted_at.is_(None),
        ).all()
    check("配额后条数 = 上限且淘汰的是低分条目",
          len(rows) == 4 and min(r.importance for r in rows) >= 0.2,
          f"{[(r.id, r.importance) for r in rows]}")

    reset_engine()


def test_promote_shared(tmp_path: Path):
    from coapis.foundation import knowledge_export as ke
    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.engine import get_engine, init_engine, reset_engine
    from coapis.foundation.db.models.memory import Memory
    from coapis.foundation.memory_repository import MemoryEntry
    from coapis.foundation.memory_repository_impl import SqlaMemoryRepository

    reset_engine()
    init_engine(f"sqlite:///{tmp_path / 'promote.db'}")
    BaseRow.metadata.create_all(get_engine())
    ke.foundation_root = lambda: tmp_path / "foundation"
    repo = SqlaMemoryRepository()
    ke._repo = lambda: repo

    words = "苹果 香蕉 橙子 葡萄 西瓜 菠萝".split()
    for i in range(6):
        repo.add(MemoryEntry(
            scope="user", user_id="alice", category="fact",
            title=f"高分条目 {i}",
            content=f"高分条目{i} " + " ".join(words[i % len(words)] for _ in range(5)),
            source="timeline", importance=0.6 + i * 0.06,
            agent_id="coapis:default",
        ))
    with ke.get_session() as s:
        seeded = s.query(Memory).filter(Memory.scope == "user").count()
    check("晋升种子 6 条（内容互异不被去重吃掉）", seeded == 6, f"seeded={seeded}")

    res = ke.promote_to_shared(limit=3)
    check("共享层晋升有每轮上限（top_k）", res["promoted"] == 3, f"{res}")
    with ke.get_session() as s:
        shared = s.query(Memory).filter(Memory.scope == "workspace").all()
    check("共享层 importance 不为 0（写侧字段取 ORM 行本体）",
          bool(shared) and all(x.importance > 0 for x in shared),
          f"{[(x.id, x.importance) for x in shared]}")
    check("共享层 agent_id 保留来源智能体",
          bool(shared) and all(x.agent_id == "coapis:default" for x in shared),
          f"{[(x.id, x.agent_id) for x in shared]}")
    check("共享层 user_id 为空串哨兵（仓库读取侧口径）",
          bool(shared) and all(x.user_id == "" for x in shared),
          f"{[(x.id, repr(x.user_id)) for x in shared]}")
    check("共享层分类统一记 knowledge（方案 D-2 配额口径）",
          bool(shared) and all(x.category == "knowledge" for x in shared),
          f"{[(x.id, x.category) for x in shared]}")

    res2 = ke.promote_to_shared(limit=10)
    check("余弦去重生效（已晋升的不再重复）",
          res2["promoted"] == 3 and res2["dedup_skipped"] >= 3, f"{res2}")
    with ke.get_session() as s:
        total_shared = s.query(Memory).filter(Memory.scope == "workspace").count()
    check("两轮晋升后共享层 = 全部种子（不重复不膨胀）",
          total_shared == 6, f"total={total_shared}")
    check("top_k=0 即关闭共享层晋升",
          ke.promote_to_shared(limit=0)["promoted"] == 0, "")
    reset_engine()


def test_injection(tmp_path: Path):
    from coapis.constant import KNOWLEDGE_INJECT_MAX_CHARS, KNOWLEDGE_INJECT_TOP_N
    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.engine import get_engine, init_engine, reset_engine
    from coapis.foundation.foundation_manager import FoundationManager
    from coapis.foundation.memory_repository import MemoryEntry
    from coapis.foundation.memory_repository_impl import SqlaMemoryRepository

    reset_engine()
    init_engine(f"sqlite:///{tmp_path / 'inject.db'}")
    BaseRow.metadata.create_all(get_engine())
    repo = SqlaMemoryRepository()
    fm = FoundationManager(str(tmp_path / "foundation"), memory_repo=repo)

    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima".split()
    for i in range(12):
        repo.add(MemoryEntry(
            scope="user", user_id="alice", category="fact",
            title=f"知识 {i}", content=f"知识{i} {words[i]} {words[(i+3) % 12]} 记录",
            source="timeline", importance=0.9 - i * 0.01,
        ))
    for i in range(5):
        repo.add(MemoryEntry(
            scope="agent", user_id="alice", category="dream",
            title=f"dream:{i}", content=f"status=success {words[i]} 维护日志",
            source="dream", importance=1.0,
        ))
    for i in range(3):
        repo.add(MemoryEntry(
            scope="workspace", user_id="", category="knowledge",
            title=f"共享 {i}", content=f"共享{i} {words[i+5]} 团队知识",
            source="promote_shared", importance=0.6,
        ))

    items = fm.select_memories_for_injection(query="", user_id="alice")
    check("注入条数 ≤ KNOWLEDGE_INJECT_TOP_N",
          0 < len(items) <= KNOWLEDGE_INJECT_TOP_N,
          f"{len(items)} vs {KNOWLEDGE_INJECT_TOP_N}")
    check("机器维护日志不占注入位（source=dream 全被排除）",
          all("status=success" not in d["content"] for d in items),
          f"{[d['title'] for d in items]}")
    wide = fm.select_memories_for_injection(query="", user_id="alice", top_n=20)
    check("共享层条目可进注入（团队共享知识对全员可见）",
          any(d["scope"] == "workspace" for d in wide),
          f"{[d['scope'] for d in wide]}")
    items = fm.select_memories_for_injection(query="", user_id="alice")
    sec = fm.render_injection_section(items)
    check("注入段带固定标记", sec.startswith("## 已沉淀记忆"), sec[:30])
    check("注入段字符数不超上限",
          len(sec) <= KNOWLEDGE_INJECT_MAX_CHARS + 40,
          f"{len(sec)} vs {KNOWLEDGE_INJECT_MAX_CHARS}")
    capped = fm.select_memories_for_injection(
        query="", user_id="alice", top_n=6, max_chars=100)
    check("正文字符硬上限生效（超限即停）",
          0 < sum(len(d["content"]) for d in capped) <= 100,
          f"{sum(len(d['content']) for d in capped)}")
    ctx = fm.build_context(query="记录 alpha", user_id="alice",
                           agent_id="", is_initial=True)
    check("last_injected_items 与本轮注入同源（citation 回填用）",
          bool(fm.last_injected_items) and "## 已沉淀记忆" in ctx,
          f"{[d['id'] for d in fm.last_injected_items]}")
    check("build_context 非初始轮不带注入段（防每轮重复灌）",
          "## 已沉淀记忆" not in fm.build_context(
              query="x", user_id="alice", agent_id="", is_initial=False), "")
    fm.reset_injection_state()
    check("reset_injection_state 清空注入账本", fm.last_injected_items == [], "")
    check("top_n=0 关闭注入并清空注入账本",
          fm.select_memories_for_injection(query="", user_id="alice", top_n=0) == []
          and fm.last_injected_items == [],
          f"{[d['id'] for d in fm.last_injected_items]}")
    check("无用户且无智能体 → 不灌共享知识",
          fm.select_memories_for_injection(query="x", user_id="", agent_id="") == [], "")

    repo.add(MemoryEntry(scope="user", user_id="alice", category="fact",
                         title="季度报表口径", content="季度报表 口径 已确认 按 部门 汇总",
                         source="user_note", importance=0.95))
    hit = fm.select_memories_for_injection(
        query="帮我把季度报表做成PPT", user_id="alice", top_n=3)
    check("带查询时相关条目排第一",
          bool(hit) and "季度报表" in hit[0]["content"],
          f"{[d['title'] for d in hit]}")
    check("引用透传需要的字段齐全（id/scope/category/title/content/score）",
          all(k in hit[0] for k in ("id", "scope", "category", "title",
                                    "content", "score")), f"{hit[0]}")
    check("render_injection_section 容忍空注入",
          fm.render_injection_section([]) == "", "")
    reset_engine()


def main() -> int:
    _stub_agentscope_runtime()
    print("=" * 60)
    print("  知识投影层 + 注入准入测试")
    print("=" * 60)
    for fn in (test_projection, test_promote_shared, test_injection):
        tmp = Path(tempfile.mkdtemp(prefix=f"kproj_{fn.__name__}_"))
        try:
            fn(tmp)
        except Exception as exc:  # noqa: BLE001
            import traceback
            check(f"{fn.__name__} 抛出异常", False,
                  f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-600:]}")
    print("-" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"{passed}/{len(RESULTS)} passed")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL: {name}  {detail}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
