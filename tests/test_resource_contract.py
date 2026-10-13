# -*- coding: utf-8 -*-
"""资源契约 R1 验收测试（清单面 ResourceLedger + 与 file_ledger 的接线）。

对齐方案文档 §7 的 DoD，逐条实测：

  1. 清单表能列出全部资源（含 kind/status/引用者计数）；
  2. 巡检发现孤儿文件（FS 有、refs 空）；
  3. 会话删除后资源状态正确流转为 orphan（R2 验收项）；
  4. ``resource_key`` 含 owner，多用户同路径同名资源**各自独立成行**
     （吸取 memories.dedup_key 事故的必测项）；
  5. 既有 ``file_records`` 读路径（chat_id 过滤、deliverables、stats）零回归。

独立运行：python tests/test_resource_contract.py
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

RESULTS: list = []


def check(name: str, cond: bool, detail: str = ""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))


def _setup():
    tmp = Path(tempfile.mkdtemp(prefix="resource_contract_"))
    (tmp / "system").mkdir(parents=True)
    db_path = tmp / "system" / "coapis.db"

    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.engine import get_engine, init_engine

    # 必须先导入 models 包：create_all 读的是 BaseRow.metadata，
    # 只 import base 时 metadata 是空的（表一张都不会建）。
    import coapis.foundation.db.models  # noqa: F401  (registers all models)

    init_engine(f"sqlite:///{db_path}")
    BaseRow.metadata.create_all(get_engine())

    ws = tmp / "workspaces"
    for u in ("alice", "bob"):
        (ws / u / "files" / "report").mkdir(parents=True)
    # 巡检有归属闸门：owner 不在用户表里的目录划入 unowned（只报告、不补登记）。
    # alice/bob 必须是真用户，否则 full sweep 的 unledgered 口径根本测不到。
    import time as _t

    from coapis.foundation.db.engine import get_session as _gs
    from coapis.foundation.db.models.user import User as _U

    with _gs() as s:
        for u in ("alice", "bob"):
            s.add(_U(id=f"u_{u}", username=u, password_hash="x", salt="x",
                     created_at=_t.time()))
    return tmp, ws


def main():
    tmp, ws = _setup()

    from coapis.foundation.file_ledger import FileLedgerService
    from coapis.foundation.resource_ledger import ResourceLedger
    from coapis.foundation.db.models.resources import make_resource_key

    fl = FileLedgerService(workspaces_dir=ws)
    rl = ResourceLedger(workspaces_dir=ws)

    # ── 1. register + list（kind/status/引用计数） ────────────────────
    p_alice = ws / "alice" / "files" / "report" / "doc.md"
    p_alice.write_text("alice doc")
    key_a = rl.register(owner_scope="user", owner_id="alice", kind="file",
                        path="report/doc.md", title="Alice 报告")
    check("register 返回 key", bool(key_a), key_a)
    rl.attach_ref(resource_key=key_a, referrer_kind="chat",
                  referrer_id="chat-1", role="producer")
    rl.attach_ref(resource_key=key_a, referrer_kind="session",
                  referrer_id="console:alice")

    lst = rl.list_resources(owner_scope="user", owner_id="alice")
    check("清单可列出资源", len(lst) == 1, f"got {len(lst)}")
    if lst:
        r = lst[0]
        check("列出含 kind/status", r["kind"] == "file" and r["status"] == "draft",
              f"kind={r['kind']} status={r['status']}")
        check("引用计数由 refs 派生", r["ref_count"] == 2, f"ref_count={r['ref_count']}")
        check("title 落库", r["title"] == "Alice 报告", f"title={r['title']}")

    # register 幂等：同 owner/kind/path 再注册不产生第二行
    key_a2 = rl.register(owner_scope="user", owner_id="alice", kind="file",
                         path="report/doc.md")
    check("register 幂等（key 相同）", key_a2 == key_a, f"{key_a2} vs {key_a}")
    check("幂等不产生第二行", len(rl.list_resources(owner_scope="user",
          owner_id="alice")) == 1)

    # ── 4. 必测项：key 含 owner，多用户同路径各自独立成行 ─────────────
    p_bob = ws / "bob" / "files" / "report" / "doc.md"
    p_bob.write_text("bob doc")
    key_b = rl.register(owner_scope="user", owner_id="bob", kind="file",
                        path="report/doc.md")
    check("多用户同路径 key 不同", key_b != key_a, f"{key_b[:8]} vs {key_a[:8]}")
    check("多用户各自独立成行",
          len(rl.list_resources(owner_scope="user", owner_id="bob")) == 1
          and len(rl.list_resources(owner_scope="user", owner_id="alice")) == 1)
    check("bob 的 refs 不受 alice 影响",
          rl.list_resources(owner_scope="user", owner_id="bob")[0]["ref_count"] == 0)
    # 大小写/分隔符归一：同 owner 同文件不应产生第二行
    key_a3 = rl.register(owner_scope="user", owner_id="alice", kind="file",
                         path="Report\\DOC.md")
    check("路径归一后仍同一行", key_a3 == key_a and
          len(rl.list_resources(owner_scope="user", owner_id="alice")) == 1,
          f"key_a3={key_a3[:8]}")

    # ── 2. 巡检发现孤儿（FS 有、refs 空） ────────────────────────────
    rep = rl.sweep()
    check("巡检报告含计数键（含 unowned/noise_skipped/backfilled）",
          {"fs_missing", "fs_present", "orphans", "unledgered",
           "unowned", "noise_skipped", "backfilled"} <= set(rep), str(rep))
    check("巡检报告可列出四类清单（§6）",
          {"fs_missing_list", "orphan_list", "unledgered_list", "unowned_list"}
          <= set(rep), str(sorted(rep)))
    check("refs 空的资源判为孤儿", rep["orphans"] == 1, f"orphans={rep['orphans']}")
    bob = rl.list_resources(owner_scope="user", owner_id="bob")[0]
    check("孤儿状态流转为 orphan", bob["status"] == "orphan", f"status={bob['status']}")
    check("alice 有 refs 不判孤儿",
          rl.list_resources(owner_scope="user", owner_id="alice")[0]["status"] == "draft")

    # full sweep 发现 FS 有但无 ledger 行的文件
    (ws / "alice" / "files" / "loose.txt").write_text("loose")
    rep_full = rl.sweep(full=True)
    check("full sweep 发现未登记文件", rep_full["unledgered"] == 1,
          f"unledgered={rep_full['unledgered']}")
    check("unledgered_list 列出未登记文件",
          any(x["owner_id"] == "alice" and x["path"] == "loose.txt"
              for x in rep_full["unledgered_list"]), str(rep_full["unledgered_list"]))
    check("orphan_list 列出孤儿资源",
          any(x["owner_id"] == "bob" and x["path"] == "report/doc.md"
              for x in rep_full["orphan_list"]), str(rep_full["orphan_list"]))

    # FS 删除 → fs_present=0，行保留（不自动删行，保留审计）
    p_bob.unlink()
    rep2 = rl.sweep()
    check("FS 缺失置 fs_present=0", rep2["fs_missing"] == 1, f"fs_missing={rep2['fs_missing']}")
    check("fs_missing_list 列出该行",
          any(x["owner_id"] == "bob" and x["path"] == "report/doc.md"
              for x in rep2["fs_missing_list"]), str(rep2["fs_missing_list"]))
    check("FS 缺失不删行", len(rl.list_resources(owner_scope="user", owner_id="bob")) == 1)
    check("FS 缺失后行标记 fs_present=0",
          rl.list_resources(owner_scope="user", owner_id="bob")[0]["fs_present"] == 0)

    # 巡检不得删 FS 文件（单向 FS→DB）
    check("巡检不删 FS 文件", not p_alice.exists() is False and p_alice.exists(),
          "alice doc 应仍在")

    # ── 3. 会话删除 → refs 解除 → orphan（R2 验收项） ────────────────
    rl.detach_ref(resource_key=key_a, referrer_kind="chat", referrer_id="chat-1")
    check("detach 后仍剩 1 ref 不判孤儿",
          rl.list_resources(owner_scope="user", owner_id="alice")[0]["status"] == "draft")
    rl.detach_ref(resource_key=key_a, referrer_kind="session",
                  referrer_id="console:alice")
    check("refs 清空后流转为 orphan",
          rl.list_resources(owner_scope="user", owner_id="alice")[0]["status"] == "orphan",
          f"status={rl.list_resources(owner_scope='user', owner_id='alice')[0]['status']}")
    # orphan 被重新引用 → draft
    rl.attach_ref(resource_key=key_a, referrer_kind="chat", referrer_id="chat-2")
    check("孤儿被重新引用回到 draft",
          rl.list_resources(owner_scope="user", owner_id="alice")[0]["status"] == "draft")

    # ── R2 会话删除：按 referrer 批量解除引用（chat 删除钩子的底层） ──
    p1 = ws / "alice" / "files" / "chatdel" / "a.md"
    p2 = ws / "alice" / "files" / "chatdel" / "b.md"
    p1.parent.mkdir(parents=True, exist_ok=True)
    p1.write_text("a"); p2.write_text("b")
    k1 = rl.register(owner_scope="user", owner_id="alice", kind="file",
                     path="chatdel/a.md")
    k2 = rl.register(owner_scope="user", owner_id="alice", kind="file",
                     path="chatdel/b.md")
    rl.attach_ref(resource_key=k1, referrer_kind="chat", referrer_id="chatX",
                  role="producer")
    rl.attach_ref(resource_key=k2, referrer_kind="chat", referrer_id="chatX")
    rl.attach_ref(resource_key=k2, referrer_kind="session", referrer_id="console:alice")
    n = rl.detach_refs_by_referrer("chat", "chatX")
    check("按 referrer 解除返回删除数", n == 2, f"n={n}")
    check("k1 refs 清空流转 orphan",
          [r for r in rl.list_resources(owner_scope="user", owner_id="alice")
           if r["path"] == "chatdel/a.md"][0]["status"] == "orphan")
    check("k2 仍有 session ref 不判孤儿",
          [r for r in rl.list_resources(owner_scope="user", owner_id="alice")
           if r["path"] == "chatdel/b.md"][0]["status"] == "draft")
    check("按 referrer 解除不误删他人 ref",
          [r for r in rl.list_resources(owner_scope="user", owner_id="alice")
           if r["path"] == "chatdel/b.md"][0]["ref_count"] == 1)
    check("非法 referrer_kind 被拒",
          rl.detach_refs_by_referrer("bogus", "chatX") == 0)
    check("空 referrer_id 被拒",
          rl.detach_refs_by_referrer("chat", "") == 0)

    # ── 状态机其余分支 ───────────────────────────────────────────────
    check("mark_status 官方", rl.mark_status(key_a, "official"))
    check("mark_status 归档", rl.mark_status(key_a, "archived"))
    check("非法状态被拒", not rl.mark_status(key_a, "bogus"))
    check("软删置 deleted_at", rl.mark_status(key_a, "deleted"))
    check("软删后默认清单不含该行",
          all(r["status"] != "deleted"
              for r in rl.list_resources(owner_scope="user", owner_id="alice")))
    # 软删行被重新注册时复活
    rl.register(owner_scope="user", owner_id="alice", kind="file", path="report/doc.md")
    check("软删后重新注册复活为 draft",
          rl.list_resources(owner_scope="user", owner_id="alice")[0]["status"] == "draft")

    # ── stats ────────────────────────────────────────────────────────
    st = rl.stats(owner_scope="user", owner_id="alice")
    # key_a + chatdel/a.md + chatdel/b.md = 3 行（软删行不计入）
    check("stats total 正确", st["total"] == 3, f"total={st['total']}")
    check("stats by_kind", st["by_kind"].get("file") == 3, str(st["by_kind"]))
    check("stats 含 fs_missing", st["fs_missing"] == 0, str(st))

    # ── 5. 既有 file_records 读路径零回归 ────────────────────────────
    f2 = ws / "alice" / "files" / "report" / "new.md"
    f2.write_text("new")
    ok = fl.record("alice", str(f2), session_id="console:alice",
                   chat_id="chat-9", agent_id="user:alice", source="write_file")
    check("file_ledger record 仍成功", ok)
    # list_records 返回的是 dict（items/total/limit/offset），不是列表——
    # 直接 len() 得到的是键数量 4，会把断言全部写歪。取 items/total。
    recs = fl.list_records("alice", chat_id="chat-9")
    check("chat_id 过滤仍生效", recs["total"] == 1, f"total={recs['total']}")
    check("本会话过滤不误收他 chat",
          fl.list_records("alice", chat_id="chat-1")["total"] == 0)
    check("无过滤仍见全部", len(fl.list_records("alice")["items"]) >= 1,
          f"items={len(fl.list_records('alice')['items'])}")
    st_fl = fl.stats("alice")
    check("file_ledger stats 零回归", st_fl.get("total_files") == 1, str(st_fl))

    # 接线：record 应同步登记资源并挂上 chat/session/agent refs
    lst_a = rl.list_resources(owner_scope="user", owner_id="alice")
    newrow = [r for r in lst_a if r["path"] == "report/new.md"]
    check("record 接线登记资源", len(newrow) == 1, f"got {len(newrow)}")
    if newrow:
        check("record 接线挂 3 refs (chat/session/agent)",
              newrow[0]["ref_count"] == 3, f"ref_count={newrow[0]['ref_count']}")

    # archive_file 接线 → archived
    fl.archive_file("alice", "report/new.md")
    check("archive_file 接线流转 archived",
          [r for r in rl.list_resources(owner_scope="user", owner_id="alice")
           if r["path"] == "report/new.md"][0]["status"] == "archived")

    # attach_chat 接线：chat_id=NULL 的行被标记后应挂 chat ref
    f3 = ws / "bob" / "files" / "report" / "late.md"
    f3.write_text("late")
    fl.record("bob", str(f3), session_id="console:bob", source="upload")
    n = fl.attach_chat("bob", session_id="console:bob", chat_id="chat-77",
                       source="upload")
    check("attach_chat 仍返回行数", n == 1, f"n={n}")
    bobrow = [r for r in rl.list_resources(owner_scope="user", owner_id="bob")
             if r["path"] == "report/late.md"]
    # record 时挂 session ref，attach_chat 再挂 chat ref → 共 2 个。
    check("attach_chat 接线挂 chat ref（session+chat 共2）",
          len(bobrow) == 1 and bobrow[0]["ref_count"] == 2,
          f"ref_count={bobrow[0]['ref_count'] if bobrow else 'no row'}")
    from coapis.foundation.db.engine import get_session
    from coapis.foundation.db.models.resources import ResourceRef
    from sqlalchemy import select as _sel
    with get_session() as s:
        roles = {
            (r.referrer_kind, r.referrer_id)
            for r in s.execute(
                _sel(ResourceRef).where(ResourceRef.resource_key == bobrow[0]["resource_key"])
            ).scalars()
        }
    check("refs 明细含 session 与 chat",
          ("session", "console:bob") in roles and ("chat", "chat-77") in roles,
          str(roles))

    # ── R3 消费面：chat_id 过滤 + 分页前总数（前端尾巴行的正确性依赖它） ──
    only = rl.list_resources(owner_scope="user", owner_id="bob", chat_id="chat-77")
    check("chat_id 过滤只返回被该会话引用过的资源",
          len(only) == 1 and only[0]["path"] == "report/late.md",
          str([r["path"] for r in only]))
    empty = rl.list_resources(owner_scope="user", owner_id="bob", chat_id="chat-none")
    check("无引用的 chat_id 返回空（不是全量兜底）", empty == [], str(empty))

    listed_all = rl.list_resources(owner_scope="user", owner_id="bob", limit=500)
    total_bob = rl.count_resources(owner_scope="user", owner_id="bob")
    check("count_resources 与 list_resources 过滤集一致（尾巴行不撒谎）",
          total_bob == len(listed_all),
          f"count={total_bob} listed={len(listed_all)}")
    check("count_resources 的 chat 过滤与 list 一致",
          rl.count_resources(owner_scope="user", owner_id="bob", chat_id="chat-77")
          == len(only),
          f"count={rl.count_resources(owner_scope='user', owner_id='bob', chat_id='chat-77')} list={len(only)}")
    check("分页截断可见：limit=1 只返回 1 行但 total 仍是全量",
          len(rl.list_resources(owner_scope="user", owner_id="bob", limit=1)) == 1
          and total_bob > 1,
          f"total={total_bob}")

    # ── 巡检口径：噪音目录 / 无主目录 / 补登记 ─────────────────────
    import time as _t2

    from coapis.foundation.db.engine import get_session as _gs2
    from coapis.foundation.db.models.user import User as _U2

    with _gs2() as s:
        s.add(_U2(id="u_carol", username="carol", password_hash="x", salt="x",
                  created_at=_t2.time()))
    carol = ws / "carol" / "files"
    carol.mkdir(parents=True)
    (carol / "legacy.md").write_text("legacy")          # 台账上线前的存量
    (carol / ".trash").mkdir()
    (carol / ".trash" / "deleted.md").write_text("x")   # 软删归档：不是资源
    (ws / "eval_sandbox" / "files").mkdir(parents=True)
    (ws / "eval_sandbox" / "files" / "clone.md").write_text("clone")

    rep_b = rl.sweep(full=True, backfill=True)
    check("噪音目录(.trash)不计入 unledgered", rep_b["noise_skipped"] >= 1,
          f"noise_skipped={rep_b['noise_skipped']}")
    check("无主目录划入 unowned 而不是 unledgered",
          any(x["owner_id"] == "eval_sandbox" for x in rep_b["unowned_list"]),
          str(rep_b["unowned_list"]))
    check("补登记只补真用户（alice/loose.txt + carol/legacy.md）",
          rep_b["backfilled"] == 2
          and any(r["path"] == "legacy.md"
                  for r in rl.list_resources(owner_scope="user", owner_id="carol")),
          f"backfilled={rep_b['backfilled']}")
    check("补登记不给无主目录造行",
          rl.list_resources(owner_scope="user", owner_id="eval_sandbox") == [])
    check("补登记的行带 source=backfill",
          rl.list_resources(owner_scope="user", owner_id="carol")[0]["source"]
          == "backfill",
          str(rl.list_resources(owner_scope="user", owner_id="carol")))
    rep_c = rl.sweep(full=True, backfill=True)
    check("补登记幂等（第二轮不再产生新行）", rep_c["backfilled"] == 0,
          f"backfilled={rep_c['backfilled']}")

    # ── 汇总 ─────────────────────────────────────────────────────────
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n总计: {len(RESULTS)} | 通过: {len(RESULTS) - len(failed)} | 失败: {len(failed)}")
    for name, _, detail in failed:
        print(f"  ❌ {name}" + (f"  ({detail})" if detail else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
