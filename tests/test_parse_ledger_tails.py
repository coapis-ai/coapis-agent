#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一期尾巴测试：A1 解析入台账 / A5 附件清单+解析状态 / U2 时区按用户。

对应方案 docs/智能判断中枢设计方案-定稿v13.md 第14章（D8 纳入一期）。
可独立运行：``python tests/test_parse_ledger_tails.py``
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("COAPIS_DISABLE_STANDALONE_DB_INIT", "1")

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

def _init_db(url: str) -> None:
    """按 URL 建一份干净的库（每个用例独立，互不污染）。

    ``create_all`` 只认已注册的表，所以必须先导入模型模块。
    每个用例都换一个新库，因此先 ``reset_engine`` 清掉上一个引擎，
    否则表会建到上一轮的库里，用例之间互相看见对方的数据。
    """
    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.engine import get_engine, init_engine, reset_engine
    from coapis.foundation.db.models import files  # noqa: F401
    import coapis.foundation.db.models  # noqa: F401

    reset_engine()
    init_engine(url)
    BaseRow.metadata.create_all(get_engine())


from coapis.foundation.file_ledger import (  # noqa: E402
    FileLedgerService,
    PARSE_STATUSES,
)

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")


# ---------------------------------------------------------------- A1 ----


def _case_a1_mark_parse(tmp, ws):
    from coapis.foundation.db.engine import get_session
    from coapis.foundation.db.models.files import FileRecord

    led = FileLedgerService(workspaces_dir=ws)
    u = "alice"
    f = ws / u / "files" / "a.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("hello", encoding="utf-8")

    check("A1 record 上传行", led.record(u, str(f), source="upload"))
    check(
        "A1 mark_parse 成功",
        led.mark_parse(u, str(f), status="ok", chars=1234, method="full/markdown"),
    )
    with get_session() as s:
        row = (
            s.query(FileRecord)
            .filter(FileRecord.user_id == u, FileRecord.file_path == "a.md")
            .order_by(FileRecord.created_at.desc())
            .first()
        )
    check("A1 状态落库", row is not None and row.parse_status == "ok")
    check("A1 字符数落库", row is not None and row.parse_chars == 1234)
    check("A1 方式落库", row is not None and row.parse_method == "full/markdown")
    check("A1 时间落库", row is not None and float(row.parse_at or 0) > 0)

    info = led.parse_status_of(u, str(f))
    check("A1 parse_status_of 可读回", bool(info) and info["status"] == "ok")
    check("A1 读回带字符数", bool(info) and info["chars"] == 1234)


def _case_a1_creates_row_when_absent(tmp, ws):
    from coapis.foundation.db.engine import get_session
    from coapis.foundation.db.models.files import FileRecord

    led = FileLedgerService(workspaces_dir=ws)
    u = "bob"
    f = ws / u / "files" / "sub" / "big.pdf"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"%PDF-1.4 stub")

    check(
        "A1 无台账行时补登",
        led.mark_parse(u, str(f), status="degraded", chars=99, method="index+head/pdf"),
    )
    with get_session() as s:
        row = (
            s.query(FileRecord)
            .filter(FileRecord.user_id == u, FileRecord.file_path == "sub/big.pdf")
            .first()
        )
    check("A1 补登行状态", row is not None and row.parse_status == "degraded")
    check("A1 补登行来源合法", row is not None and row.source == "other")


def _case_a1_guardrails(tmp, ws):
    led = FileLedgerService(workspaces_dir=ws)
    u = "carol"
    outside = Path(tmp) / "outside.md"
    outside.write_text("x", encoding="utf-8")
    check("A1 台账管不到的目录不记", led.mark_parse(u, str(outside), status="ok") is False)
    check("A1 空路径不记", led.mark_parse(u, "", status="ok") is False)
    check("A1 无用户名不炸", led.mark_parse(None, str(outside), status="ok") is False)
    check("A1 parse_status_of 无用户名返回 None", led.parse_status_of(None, str(outside)) is None)

    # 非法状态一律归入 fail，绝不写脏值
    f = ws / u / "files" / "d.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x", encoding="utf-8")
    led.record(u, str(f), source="upload")
    led.mark_parse(u, str(f), status="nonsense")
    info = led.parse_status_of(u, str(f))
    check("A1 非法状态归入 fail", bool(info) and info["status"] == "fail")
    check("A1 状态词表封闭", set(PARSE_STATUSES) == {"ok", "timeout", "fail", "degraded"})


def _case_a1_never_raises(tmp, ws):
    led = FileLedgerService(workspaces_dir=ws)
    # 目录当路径传、None 传、乱码路径：一律 False，不抛
    ok = True
    for arg in (None, str(ws), "not-a-path", str(ws / "u" / "files")):
        try:
            led.mark_parse("dave", arg, status="ok", chars=1, method="x")
            led.parse_status_of("dave", arg)
        except Exception as exc:  # pragma: no cover
            print("    raised:", exc)
            ok = False
    check("A1 永不抛异常", ok)


# ------------------------------------------------- doc_reader 包装 ----


def _case_doc_reader_ledger(tmp, ws):
    import coapis.foundation.file_ledger as fl
    from coapis.agents.tools import doc_reader as dr

    calls = []
    real = fl.record_parse_event

    def fake(username, abs_path, **kw):
        calls.append((username, abs_path, kw))
        return True

    fl.record_parse_event = fake
    try:
        p = "/work/files/a.pdf"

        # 全文成功
        dr._record_parse_ledger(
            ("read", p), {}, {"file": p, "mode": "full", "format": "pdf",
                              "content": "x" * 10}
        )
        check("DR 全文记 ok", calls[-1][2]["status"] == "ok")
        check("DR 全文记字符数", calls[-1][2]["chars"] == 10)

        # 截断 = 降级
        dr._record_parse_ledger(
            ("read", p), {}, {"file": p, "mode": "full", "format": "pdf",
                              "content": "x", "truncated": True,
                              "returned_chars": 4000}
        )
        check("DR 截断记 degraded", calls[-1][2]["status"] == "degraded")
        check("DR 截断用 returned_chars", calls[-1][2]["chars"] == 4000)

        # 分页读 = 降级
        dr._record_parse_ledger(
            ("read", p), {}, {"file": p, "mode": "pages", "format": "pdf",
                              "content": "x"}
        )
        check("DR 分页记 degraded", calls[-1][2]["status"] == "degraded")
        check("DR 方式带 mode", calls[-1][2]["method"] == "pages/pdf")

        # 超时
        dr._record_parse_ledger(
            ("read", p), {}, {"file": p, "error": "解析超时（120s）", "format": "pdf"}
        )
        check("DR 超时记 timeout", calls[-1][2]["status"] == "timeout")

        # 失败
        dr._record_parse_ledger(
            ("read", p), {}, {"file": p, "error": "文件不存在", "format": "pdf"}
        )
        check("DR 失败记 fail", calls[-1][2]["status"] == "fail")

        # 非 read 动作 / 直接喂内容 / 无路径 → 不记
        n = len(calls)
        dr._record_parse_ledger(("formats",), {}, {"formats": []})
        dr._record_parse_ledger(
            ("read", None), {"content": "abc"}, {"content": "abc", "mode": "full"}
        )
        dr._record_parse_ledger(("read", ""), {}, {"error": "no file"})
        check("DR 不该记的不记", len(calls) == n)

        # 结果不是 dict / 传垃圾 → 不抛
        dr._record_parse_ledger((), {}, None)
        dr._record_parse_ledger((), {}, "not-a-dict")
        dr._record_parse_ledger(("read", 1), {}, {"file": 1, "mode": "full"})
        check("DR 包装永不抛异常", True)
    finally:
        fl.record_parse_event = real


# ------------------------------------------------------- A5 附件清单 ----


def _case_a5_manifest(tmp, ws):
    import coapis.config.session_context as sc
    import coapis.foundation.file_ledger as fl
    from coapis.agents.utils.message_processing import _attachment_manifest

    class FakeLedger:
        def __init__(self, table):
            self._table = table

        def parse_status_of(self, username, path):
            return self._table.get(path)

    real_ledger = fl.get_file_ledger
    real_user = sc.get_current_username

    table = {
        "/w/ok.pdf": {"status": "ok", "chars": 5000, "method": "full/pdf"},
        "/w/part.pdf": {"status": "degraded", "chars": 800, "method": "pages/pdf"},
        "/w/to.pdf": {"status": "timeout", "chars": 0, "method": None},
        "/w/bad.pdf": {"status": "fail", "chars": 0, "method": None},
    }
    fl.get_file_ledger = lambda: FakeLedger(table)
    sc.get_current_username = lambda: "alice"
    try:
        out = _attachment_manifest(
            [("ok.pdf", "/w/ok.pdf"), ("part.pdf", "/w/part.pdf"),
             ("to.pdf", "/w/to.pdf"), ("bad.pdf", "/w/bad.pdf"),
             ("new.pdf", "/w/new.pdf")],
            "zh",
        )
        check("A5 清单含全部附件", all(n in out for n in
                                     ("ok.pdf", "part.pdf", "to.pdf",
                                      "bad.pdf", "new.pdf")))
        check("A5 已解析带字符数", "已解析（5000 字符）" in out)
        check("A5 部分解析带方式", "只解析了部分" in out and "pages/pdf" in out)
        check("A5 超时可见", "解析超时" in out)
        check("A5 失败可见", "解析失败" in out)
        check("A5 未解析可见", "未解析" in out)
        check("A5 带判据话术", "doc_reader" in out and "臆测" in out)

        en = _attachment_manifest([("ok.pdf", "/w/ok.pdf")], "en")
        check("A5 英文清单可用", "Attachment manifest" in en and "ok" in en)

        check("A5 空清单返回空串", _attachment_manifest([], "zh") == "")

        # 台账不可用 → 空串，绝不阻断消息路径
        def boom():
            raise RuntimeError("db down")

        fl.get_file_ledger = boom
        out2 = _attachment_manifest([("a.pdf", "/w/a.pdf")], "zh")
        check("A5 台账不可用时不产出", out2 == "")
    finally:
        fl.get_file_ledger = real_ledger
        sc.get_current_username = real_user


# ------------------------------------------------------- U2 时区 ----


def _case_u2_timezone(tmp, ws):
    import coapis.user_system.database as usd
    from coapis.app.runner.utils import _effective_timezone

    real = usd.UserSystemDB

    class FakeDB:
        def __init__(self, table):
            self._table = table

        def get_user_preferences(self, username):
            return self._table.get(username)

    table = {
        "sh": {"settings": {"timezone": "Asia/Shanghai"}},
        "json": {"settings": '{"timezone": "Europe/Paris"}'},
        "none": {"settings": {"timezone": ""}},
        "junk": {"settings": {"timezone": "Mars/Olympus"}},
        "missing": None,
    }

    usd.UserSystemDB = lambda: FakeDB(table)
    try:
        check("U2 无用户走全局兜底", _effective_timezone(None) in ("UTC", "Asia/Shanghai"))
        check("U2 按用户取时区", _effective_timezone("sh") == "Asia/Shanghai")
        check("U2 settings 为字符串也能读", _effective_timezone("json") == "Europe/Paris")
        check("U2 空值回全局", _effective_timezone("none") == _effective_timezone(None))
        check("U2 非法时区回全局", _effective_timezone("junk") == _effective_timezone(None))
        check("U2 无偏好回全局", _effective_timezone("missing") == _effective_timezone(None))

        def boom():
            raise RuntimeError("db down")

        usd.UserSystemDB = boom
        check("U2 库不可用回全局不抛", _effective_timezone("sh") == _effective_timezone(None))
    finally:
        usd.UserSystemDB = real

    # 环境上下文真的用上按用户的时区
    from coapis.app.runner.utils import build_env_context

    usd.UserSystemDB = lambda: FakeDB(table)
    try:
        ctx = build_env_context(session_id="c1", user_id="sh",
                                working_dir=Path(tmp))
        check("U2 环境上下文带用户时区", "Asia/Shanghai" in ctx)
    finally:
        usd.UserSystemDB = real


def _case_ledger_username(tmp: str, ws: str) -> None:
    """台账归属用户名：必须从**真的被绑过**的仓库取。

    用户名有三个 ContextVar 仓库，生产里只有 session_context（runner 绑）
    和 agent_context（workspace 绑）有值；config.context 没人 set，读它
    恒为 None —— 台账写下去没有归属，A1 等于没做。这条守住取法。
    """
    from coapis.agents.tools.doc_reader import _ledger_username
    from coapis.config.session_context import (
        get_current_username as svc_get,
        set_current_username as svc_set,
    )

    check("U3 未绑定时无归属", _ledger_username() in (None, ""))

    svc_set("alice")
    try:
        check("U3 从 session_context 取到用户名", _ledger_username() == "alice")
    finally:
        svc_set(None)

    # session_context 空时退到 agent_context
    import coapis.app.agent_context as ac

    real = ac.get_current_username
    ac.get_current_username = lambda: "bob"
    try:
        check("U3 session_context 空时退 agent_context", _ledger_username() == "bob")
    finally:
        ac.get_current_username = real

    check("U3 两仓库都空时无归属", _ledger_username() in (None, ""))


def main():
    print("== 一期尾巴：A1 解析入台账 / A5 附件清单 / U2 时区按用户 ==")
    for fn in (
        _case_a1_mark_parse,
        _case_a1_creates_row_when_absent,
        _case_a1_guardrails,
        _case_a1_never_raises,
        _case_doc_reader_ledger,
        _case_a5_manifest,
        _case_u2_timezone,
        _case_ledger_username,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspaces"
            ws.mkdir()
            db = Path(tmp) / "t.db"
            _init_db(f"sqlite:///{db}")
            print(f"[{fn.__name__}]")
            fn(tmp, ws)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
        return 1
    return 0


def test_parse_ledger_tails() -> None:
    """pytest 入口：跑全部用例，有失败就红。"""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
