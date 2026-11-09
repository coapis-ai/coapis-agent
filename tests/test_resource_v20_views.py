# -*- coding: utf-8 -*-
"""聊天资源 v20 · A 期验收：抽屉三视图（W5）+ 台账筛选（W2）+ 散文件治理（W6）。

对齐方案 v20 §7 的验收项，逐条实测：

  14) 资源抽屉「本聊天 / 其他来源」两个分组**互斥且并集 = 全部引用**；
  15) 默认视图与老行为一字不差（``list_resources_for_chat`` 同尺子）；
      ``ref_kinds`` 只在要的时候出；
  13) 台账列表按来源 / 关键词筛，**总数与清单同一份过滤集**；
      台账出参时间 = epoch 毫秒（一把尺子）；
  W6) 散文件归位到 ``files/_inbox/``：文件真搬、台账跟着走、引用不断链、
      重名加 ``(n)`` 不覆盖、系统目录/越界路径拒绝、巡检只报告不搬。

独立运行：python tests/test_resource_v20_views.py
"""

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

RESULTS: list = []


def check(name: str, cond: bool, detail: str = ""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f"  ({detail})" if detail and not cond else ""))


def _setup():
    tmp = Path(tempfile.mkdtemp(prefix="resource_v20_"))
    (tmp / "system").mkdir(parents=True)
    db_path = tmp / "system" / "coapis.db"

    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.engine import get_engine, init_engine, get_session

    import coapis.foundation.db.models  # noqa: F401  (registers all models)

    init_engine(f"sqlite:///{db_path}")
    BaseRow.metadata.create_all(get_engine())

    ws = tmp / "workspaces"
    for u in ("alice", "bob", "carl", "dora"):
        (ws / u).mkdir(parents=True)

    from coapis.foundation.db.models.user import User as _U

    with get_session() as s:
        for u in ("alice", "bob", "carl", "dora"):
            s.add(_U(id=f"u_{u}", username=u, password_hash="x", salt="x",
                     created_at=time.time()))
    return tmp, ws


def main():
    tmp, ws = _setup()
    from coapis.foundation.resource_ledger import ResourceLedger

    rl = ResourceLedger(workspaces_dir=ws)

    # ── 数据：一个会话两个聊天 + 三种引用口径 ─────────────────────
    ka = rl.register(owner_scope="user", owner_id="alice", kind="file",
                     path="media/a.md", title="a.md", source="hook")
    kb = rl.register(owner_scope="user", owner_id="alice", kind="file",
                     path="media/b.md", title="b.md", source="backfill")
    kc = rl.register(owner_scope="user", owner_id="alice", kind="file",
                     path="media/c.md", title="c.md", source="reconcile")
    rl.attach_ref(resource_key=ka, referrer_kind="chat",
                  referrer_id="c1", role="producer")
    rl.attach_ref(resource_key=kb, referrer_kind="session",
                  referrer_id="sess-1", role="consumer")
    rl.attach_ref(resource_key=kc, referrer_kind="agent",
                  referrer_id="user:alice", role="consumer")

    kw = dict(owner_scope="user", owner_id="alice", chat_id="c1",
              session_id="sess-1", peer_ids=["c1"], agent_ids=["user:alice"])
    names = lambda rows: sorted(r["title"] for r in rows)  # noqa: E731

    chat = rl.list_chat_view_resources(view="chat", **kw)
    other = rl.list_chat_view_resources(view="other", **kw)
    alls = rl.list_chat_view_resources(view="all", **kw)

    check("14 · 本聊天分组只含 chat 引用过的行", names(chat) == ["a.md"], names(chat))
    check("14 · 其他来源 = 会话/智能体引用", names(other) == ["b.md", "c.md"],
          names(other))
    check("14 · 两分组互斥", set(names(chat)) & set(names(other)) == set())
    check("14 · 两分组并集 = 全部引用", names(alls) == ["a.md", "b.md", "c.md"],
          names(alls))

    check("14 · 总数与清单同源（chat）",
          rl.count_chat_view_resources(view="chat", **kw) == 1,
          rl.count_chat_view_resources(view="chat", **kw))
    check("14 · 总数与清单同源（other）",
          rl.count_chat_view_resources(view="other", **kw) == 2,
          rl.count_chat_view_resources(view="other", **kw))
    check("14 · 总数与清单同源（all）",
          rl.count_chat_view_resources(view="all", **kw) == 3,
          rl.count_chat_view_resources(view="all", **kw))

    check("15 · 默认视图不带 ref_kinds",
          "ref_kinds" not in rl.list_chat_view_resources(view="chat", **kw)[0])
    kinds = {r["title"]: r["ref_kinds"] for r in alls}
    check("15 · ref_kinds 口径正确",
          kinds == {"a.md": ["chat"], "b.md": ["session"], "c.md": ["agent"]}, kinds)
    check("15 · 其他来源里不得出现 chat 口径",
          all("chat" not in r["ref_kinds"] for r in other))

    legacy = rl.list_resources_for_chat(owner_scope="user", owner_id="alice",
                                        chat_id="c1", limit=50, offset=0,
                                        include_deleted=True)
    check("15 · 默认视图与老函数一字同", names(legacy) == names(chat),
          f"{names(legacy)} vs {names(chat)}")

    # 非法视图取值当 chat（永不因参数把清单变空）
    check("15 · 非法 view 取值回落 chat",
          names(rl.list_chat_view_resources(view="xyz", **kw)) == ["a.md"])
    check("15 · 空 chat_id 不炸", rl.list_chat_view_resources(
        **{**kw, "chat_id": ""}) == [])

    # ── 13 · 台账列表筛选 + 时间尺子 ──────────────────────────────
    rl.register(owner_scope="user", owner_id="bob", kind="file",
                path="media/report-2024.md", title="report-2024.md",
                source="hook")
    rl.register(owner_scope="user", owner_id="bob", kind="file",
                path="media/notes.md", title="notes.md", source="backfill")

    items = rl.list_resources(owner_scope="user", owner_id="bob", source="hook")
    total = rl.count_resources(owner_scope="user", owner_id="bob", source="hook")
    check("13 · source 过滤生效（清单与总数同步）",
          len(items) == 1 and total == 1, f"{len(items)}/{total}")

    items = rl.list_resources(owner_scope="user", owner_id="bob", q="NOTE")
    total = rl.count_resources(owner_scope="user", owner_id="bob", q="NOTE")
    check("13 · 关键词不区分大小写", len(items) == 1 and total == 1,
          f"{len(items)}/{total}")

    items = rl.list_resources(owner_scope="user", owner_id="bob", q="media")
    total = rl.count_resources(owner_scope="user", owner_id="bob", q="media")
    check("13 · 关键词也匹配路径", len(items) == 2 and total == 2, f"{len(items)}/{total}")

    items = rl.list_resources(owner_scope="user", owner_id="bob", q="zzz-not-exist")
    total = rl.count_resources(owner_scope="user", owner_id="bob", q="zzz-not-exist")
    check("13 · 筛不到就是空（不是报错）", len(items) == 0 and total == 0)

    items = rl.list_resources(owner_scope="user", owner_id="bob")
    check("一把尺子 · 台账出参时间 = epoch 毫秒",
          all(it["updated_at"] > 1e12 and it["last_seen_at"] > 1e12 for it in items),
          [it["updated_at"] for it in items][:2])

    # ── W6 · 散文件治理 ───────────────────────────────────────────
    carl = ws / "carl"
    (carl / "loose.md").write_text("x", encoding="utf-8")
    (carl / "files").mkdir()
    (carl / "files" / "one.txt").write_text("y", encoding="utf-8")
    (carl / ".trash").mkdir()
    (carl / ".trash" / "ghost.md").write_text("z", encoding="utf-8")
    kc2 = rl.register(owner_scope="user", owner_id="carl", kind="file",
                      path="loose.md", title="loose.md", source="collector",
                      path_form="workspace")
    rl.attach_ref(resource_key=kc2, referrer_kind="chat",
                  referrer_id="c9", role="producer")

    out = rl.move_to_inbox(owner_id="carl", paths=[
        "loose.md", "files/one.txt", ".trash/ghost.md",
        "../escape.md", "/abs/path.md", "nope.md", "files/_inbox/in.md",
    ])
    check("W6 · 散文件归位成功 2 个", out.get("moved_count") == 2, out)
    moved = {r["path"]: r["to"] for r in out["moved"]}
    check("W6 · 归位目标目录 = files/_inbox/",
          moved.get("loose.md") == "files/_inbox/loose.md"
          and moved.get("files/one.txt") == "files/_inbox/one.txt", moved)
    check("W6 · 文件真搬走（原位置不留）",
          (carl / "files" / "_inbox" / "loose.md").is_file()
          and not (carl / "loose.md").exists())
    check("W6 · 系统目录 .trash 不碰", (carl / ".trash" / "ghost.md").is_file())
    check("W6 · 越界/绝对/不存在路径进 failed 不当成功",
          len(out["failed"]) >= 3, out["failed"])

    rows = rl.list_resources(owner_scope="user", owner_id="carl", limit=50)
    row = next((r for r in rows if r["path"] == "files/_inbox/loose.md"), None)
    check("W6 · 台账路径跟着搬家", row is not None,
          [r["path"] for r in rows])
    check("W6 · 搬家后引用不断链（refs 跟着换 key，不留孤儿）",
          row is not None and row.get("ref_count", 0) >= 1, row)
    check("W6 · 台账走的是 key 迁移分支（moved）",
          out["moved"][0]["ledger"] == "moved", out["moved"][0])

    inbox = carl / "files" / "_inbox"
    (inbox / "dup.md").write_text("existing", encoding="utf-8")
    (carl / "dup.md").write_text("first", encoding="utf-8")
    out2 = rl.move_to_inbox(owner_id="carl", paths=["dup.md"])
    check("W6 · 重名加 (n) 不覆盖",
          out2["moved_count"] == 1
          and out2["moved"][0]["to"] == "files/_inbox/dup(2).md"
          and (inbox / "dup.md").read_text(encoding="utf-8") == "existing",
          out2["moved"])
    check("W6 · 已在 _inbox 的不重复搬",
          all("files/_inbox" not in r["path"] for r in out2["skipped"])
          and out2["skipped"] == [])

    check("W6 · 空归属用户/不存在用户都返回 ok=False（不抛）",
          rl.move_to_inbox(owner_id="", paths=["a"])["ok"] is False
          and rl.move_to_inbox(owner_id="ghost", paths=["a"])["ok"] is False)

    # 目标位置已有台账行 → 合并成一行（refs 迁过去，旧行消失）
    (carl / "clash.md").write_text("new", encoding="utf-8")
    kclash = rl.register(owner_scope="user", owner_id="carl", kind="file",
                         path="_inbox/clash.md", title="clash.md",
                         source="backfill", path_form="files_root")
    rl.attach_ref(resource_key=kclash, referrer_kind="chat",
                  referrer_id="c10", role="consumer")
    ksrc = rl.register(owner_scope="user", owner_id="carl", kind="file",
                       path="clash.md", title="clash.md", source="collector",
                       path_form="workspace")
    rl.attach_ref(resource_key=ksrc, referrer_kind="chat",
                  referrer_id="c11", role="producer")
    out3 = rl.move_to_inbox(owner_id="carl", paths=["clash.md"])
    rows = rl.list_resources(owner_scope="user", owner_id="carl", limit=100)
    clash_rows = [r for r in rows if r["path"].endswith("clash.md")]
    check("W6 · 同位置已有行时合并成一行", len(clash_rows) == 1,
          [(r["path"], r["resource_key"][:6]) for r in clash_rows])
    check("W6 · 合并后两边引用都在（无孤儿引用）",
          out3["moved"][0]["ledger"] == "merged"
          and clash_rows and clash_rows[0].get("ref_count", 0) >= 2,
          clash_rows[0] if clash_rows else None)

    # 巡检铁律：只报告不搬（散文件 = files/ 根下的非 media 文件）
    dora = ws / "dora"
    (dora / "files").mkdir()
    (dora / "files" / "loose-root.md").write_text("x", encoding="utf-8")
    (dora / "files" / "known.md").write_text("y", encoding="utf-8")
    rl.register(owner_scope="user", owner_id="dora", kind="file",
                path="known.md", title="known.md", source="backfill",
                path_form="files_root")
    sw = rl.sweep(full=True)
    check("巡检 · 只报告不搬（散文件仍在原位）",
          (dora / "files" / "loose-root.md").is_file())
    check("巡检 · 散文件进 unledgered 清单",
          any("loose-root.md" in str(x) for x in sw.get("unledgered_list", [])),
          sw.get("unledgered_list"))
    # 管理页把巡检报告直接喂给归位：报告里的路径是 files/ 相对的
    out4 = rl.move_to_inbox(owner_id="dora", paths=["loose-root.md"])
    check("W6 · 巡检报告路径（files/ 相对）直接可归位",
          out4["moved_count"] == 1
          and out4["moved"][0]["to"] == "files/_inbox/loose-root.md",
          out4["moved"])
    check("W6 · 已在收件箱的不重复搬",
          rl.move_to_inbox(owner_id="dora", paths=["_inbox/loose-root.md"])["skipped"]
          and rl.move_to_inbox(owner_id="dora", paths=["_inbox/loose-root.md"])["moved_count"] == 0)

    bad = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n通过 {len(RESULTS) - len(bad)}/{len(RESULTS)}")
    if bad:
        print("失败项：", bad)
    return bad


def test_resource_v20_view_checks():
    """pytest 入口：把上面整套验收接进全量基线。

    本文件是脚本式验收（与 tests/test_resource_contract.py 同一形态），只写
    ``check()`` 的话 pytest 一条也收不到 —— 全量基线会把这个文件当"通过"，
    等于零覆盖。这条包装函数就是把这个漏洞堵上：脚本跑完，失败项清零才算绿。
    """
    RESULTS.clear()
    bad = main()
    try:
        from coapis.foundation.db.engine import reset_engine

        reset_engine()
    except Exception:  # pragma: no cover - 引擎已回收时无所谓
        pass
    assert not bad, "v20 A 期验收失败：" + "；".join(bad)


if __name__ == "__main__":
    sys.exit(0 if not main() else 1)
