# -*- coding: utf-8 -*-
"""成果台账 deliverables 契约测试（F4：total 不再受 limit 截断）。

覆盖：
  A. count_deliverables 按 file_path 去重计数，不受 limit 影响；
  B. status 过滤作用于每个文件的最新行（当前状态）；
  C. session_id 过滤生效；
  D. list_deliverables 仍按 limit 截断且 total >= len(items)；
  E. chat_id 写入与「本会话」过滤（旧行 chat_id=NULL 不入选、他会话不入选、
     无过滤仍见全部、source+chat_id 组合过滤）。

注意：``file_path`` 是相对 ``<workspaces>/<user>/files`` 归一化的 POSIX 路径，
本测试的文件直接落在 ``files/`` 根下，因此期望值不带 ``media/`` 前缀。

独立运行：python tests/test_file_ledger_deliverables.py
"""

import importlib
import sys
import tempfile
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


_stub_agentscope_runtime()


def test_deliverables_contract():
    from coapis.constant import WORKSPACES_DIR
    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.engine import get_engine, init_engine
    from coapis.foundation.file_ledger import FileLedgerService

    tmp = Path(tempfile.mkdtemp(prefix="ledger_dlvr_test_"))
    (tmp / "system").mkdir(parents=True)
    db_path = tmp / "system" / "coapis.db"
    init_engine(f"sqlite:///{db_path}")
    BaseRow.metadata.create_all(get_engine())

    ws = tmp / "workspaces"
    (ws / "alice" / "files" / "report").mkdir(parents=True)

    led = FileLedgerService(workspaces_dir=ws)

    # 5 个不同文件，各写多次（追加行）
    paths = [f"report/doc{i}.md" for i in range(5)]
    for p in paths:
        (ws / "alice" / "files" / p).write_text("x", encoding="utf-8")
        led.record("alice", ws / "alice" / "files" / p, source="write_file")
        led.record("alice", ws / "alice" / "files" / p, source="append_file")
    # 第 6 个文件属于另一个 session
    (ws / "alice" / "files" / "other.txt").write_text("y", encoding="utf-8")
    led.record("alice", ws / "alice" / "files" / "other.txt", source="upload")

    # A. 去重计数：11 行 → 6 个文件
    total = led.count_deliverables("alice")
    check("count 按 file_path 去重（11行→6文件）", total == 6, f"total={total}")

    # D. limit 不影响 count
    items_small = led.list_deliverables("alice", limit=2)
    check("list limit=2 返回 2 条", len(items_small) == 2, f"got={len(items_small)}")
    check("total(6) >= len(items)(2)", led.count_deliverables("alice") >= len(items_small))

    # B. status 过滤作用于最新行
    first = led.list_deliverables("alice")[0]["file_path"]
    led.update_record_status("alice", first, "delivered")
    check("deliver 后该文件 status=delivered",
          any(d["file_path"] == first and d["status"] == "delivered"
              for d in led.list_deliverables("alice")))
    delivered_total = led.count_deliverables("alice", status="delivered")
    check("count(status=delivered)==1", delivered_total == 1, f"got={delivered_total}")
    draft_total = led.count_deliverables("alice", status="draft")
    check("count(status=draft)==5", draft_total == 5, f"got={draft_total}")

    # C. session 过滤
    other_count = led.count_deliverables("alice", session_id="__none__")
    check("未知 session 计数为 0", other_count == 0, f"got={other_count}")

    # 他人数据隔离
    check("其他用户计数为 0", led.count_deliverables("bob") == 0)


def test_chat_id_contract():
    """D1/D2: chat_id 写入台账，本会话过滤只覆盖新数据（旧行 chat_id=NULL 不入选）。"""
    from coapis.constant import WORKSPACES_DIR
    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.engine import get_engine, init_engine
    from coapis.foundation.file_ledger import FileLedgerService

    tmp = Path(tempfile.mkdtemp(prefix="ledger_chat_test_"))
    (tmp / "system").mkdir(parents=True)
    init_engine(f"sqlite:///{tmp / 'system' / 'coapis.db'}")
    BaseRow.metadata.create_all(get_engine())

    ws = tmp / "workspaces"
    (ws / "alice" / "files" / "media").mkdir(parents=True)
    led = FileLedgerService(workspaces_dir=ws)

    def write(p: str, **kw):
        f = ws / "alice" / "files" / p
        f.write_text("x", encoding="utf-8")
        return led.record("alice", f, **kw)

    # 旧数据：无 chat_id（迁移前的行）
    write("legacy.md", source="upload")
    # 本会话（chat A）：上传 + agent 生成
    write("a_upload.md", source="upload", chat_id="chat-A")
    write("a_gen.md", source="write_file", chat_id="chat-A")
    # 另一会话（chat B）
    write("b_upload.md", source="upload", chat_id="chat-B")

    check("chat_id 写入生效", write("ok.md", source="upload", chat_id="chat-A"))

    res_a = led.list_records("alice", chat_id="chat-A")
    paths_a = {r["file_path"] for r in res_a["items"]}
    check("chat-A 过滤命中 3 个文件", len(paths_a) == 3, f"got={sorted(paths_a)}")
    check("本会话包含上传文件", "a_upload.md" in paths_a, f"got={sorted(paths_a)}")
    check("本会话包含生成文件", "a_gen.md" in paths_a, f"got={sorted(paths_a)}")
    check("旧数据(chat_id=NULL)不入选本会话", "legacy.md" not in paths_a)
    check("其他会话文件不入选", "b_upload.md" not in paths_a)

    res_b = led.list_records("alice", chat_id="chat-B")
    check("chat-B 只命中自己的 1 个文件",
          {r["file_path"] for r in res_b["items"]} == {"b_upload.md"},
          f"got={ {r['file_path'] for r in res_b['items']} }")

    # 无过滤仍能看到全部（含旧数据）—— 保证「全部/最近使用」不受影响
    res_all = led.list_records("alice")
    check("无过滤覆盖全部 5 个文件", len({r["file_path"] for r in res_all["items"]}) == 5,
          f"got={len({r['file_path'] for r in res_all['items']})}")

    # source + chat_id 组合过滤（弹窗「我上传的」+ 本会话场景）
    # 注：ok.md 同样是 chat-A 的 upload，必须一起命中。
    res_up = led.list_records("alice", chat_id="chat-A", source="upload")
    check("chat_id+source 组合过滤",
          {r["file_path"] for r in res_up["items"]} == {"a_upload.md", "ok.md"},
          f"got={ {r['file_path'] for r in res_up['items']} }")


if __name__ == "__main__":
    test_deliverables_contract()
    test_chat_id_contract()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)
