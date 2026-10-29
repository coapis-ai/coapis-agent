#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一期尾巴测试：A1 解析入台账 / A5 附件清单 / U2 时区按用户。

跑法：
    .venv-test/bin/python -m pytest tests/test_phase1_tails.py -q
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("COAPIS_IS_DOCKER", "1")
os.environ["COAPIS_SQLITE_DB_PATH"] = str(
    Path(tempfile.mkdtemp(prefix="coapis-tails-")) / "t.db"
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

FAILURES: list[str] = []


def check(name: str, cond: bool) -> None:
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"  FAIL {name}")
        FAILURES.append(name)


def _stub_agentscope_runtime() -> None:
    """测试环境没有 agentscope_runtime，按需打桩（与既有台账测试同法）。"""
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


def _init_db() -> None:
    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.engine import get_engine, init_engine

    # 先导入模型，表才会挂上 metadata（create_all 只认已注册的表）
    from coapis.foundation.db.models import files  # noqa: F401
    import coapis.foundation.db.models  # noqa: F401

    init_engine(f"sqlite:///{os.environ['COAPIS_SQLITE_DB_PATH']}")
    BaseRow.metadata.create_all(get_engine())


_init_db()  # 导入期先建一次，保证模块可独立导入

from coapis.foundation.file_ledger import (  # noqa: E402
    PARSE_STATUSES,
    FileLedgerService,
)


def _ledger(tmp: Path) -> FileLedgerService:
    return FileLedgerService(workspaces_dir=tmp / "workspaces")


def _row_count(led: FileLedgerService, username: str, suffix: str) -> int:
    """直接数台账原始行数（list_records 会按路径去重，数不出重复）。"""
    from coapis.foundation.db.engine import get_session
    from coapis.foundation.db.models.files import FileRecord

    with get_session() as s:
        rows = (
            s.query(FileRecord)
            .filter(FileRecord.user_id == username)
            .all()
        )
    return len([r for r in rows if str(r.file_path or "").endswith(suffix)])


# ---------------------------------------------------------------- A1 ----


def _case_mark_parse_updates_existing_row(tmp: Path) -> None:
    led = _ledger(tmp)
    f = tmp / "workspaces" / "alice" / "files" / "a.docx"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x")
    check("A1 先登记上传行", led.record("alice", str(f), source="upload"))
    check(
        "A1 解析结果写在该行",
        led.mark_parse(
            "alice", str(f), status="ok", chars=1234, method="full/docx"
        ),
    )
    info = led.parse_status_of("alice", str(f))
    check("A1 状态可读回", bool(info) and info["status"] == "ok")
    check("A1 字符数可读回", bool(info) and info["chars"] == 1234)
    check("A1 方式可读回", bool(info) and info["method"] == "full/docx")
    check("A1 时间戳可读回", bool(info) and float(info["at"]) > 0)
    # 只写解析列，不新增事件行
    check("A1 不产生重复台账行", _row_count(led, "alice", "a.docx") == 1)


def _case_mark_parse_creates_row_when_absent(tmp: Path) -> None:
    led = _ledger(tmp)
    f = tmp / "workspaces" / "bob" / "files" / "b.pdf"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x")
    check(
        "A1 未登记过的文件补登一行",
        led.mark_parse("bob", str(f), status="degraded", chars=10, method="pages/pdf"),
    )
    info = led.parse_status_of("bob", str(f))
    check("A1 补登行状态正确", bool(info) and info["status"] == "degraded")


def _case_mark_parse_scope_and_status(tmp: Path) -> None:
    led = _ledger(tmp)
    outside = tmp / "outside" / "x.docx"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("x")
    check("A1 工作区外的路径不记", not led.mark_parse("alice", str(outside), status="ok"))
    f = tmp / "workspaces" / "carl" / "files" / "c.docx"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x")
    led.mark_parse("carl", str(f), status="weird", chars=1)
    info = led.parse_status_of("carl", str(f))
    check("A1 非法状态归入 fail", bool(info) and info["status"] == "fail")
    check("A1 合法状态集合", {"ok", "timeout", "fail", "degraded"} <= set(PARSE_STATUSES))


def _case_mark_parse_never_raises(tmp: Path) -> None:
    led = _ledger(tmp)
    for bad in (None, "", "   ", "/nonexistent/deep/path.docx"):
        try:
            led.mark_parse("alice", bad, status="ok")
            led.parse_status_of("alice", bad)
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        check(f"A1 坏输入不抛异常({bad!r})", ok)


def _case_parse_status_of_newest(tmp: Path) -> None:
    led = _ledger(tmp)
    f = tmp / "workspaces" / "dora" / "files" / "d.docx"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x")
    led.mark_parse("dora", str(f), status="timeout", chars=0, method="full/docx")
    led.mark_parse("dora", str(f), status="ok", chars=99, method="full/docx")
    info = led.parse_status_of("dora", str(f))
    check("A1 取最近一次解析结果", bool(info) and info["status"] == "ok" and info["chars"] == 99)


# ------------------------------------------------------- A1 (doc_reader) ----


def test_record_parse_ledger_classification() -> None:
    from coapis.agents.tools import doc_reader as dr
    import coapis.foundation.file_ledger as fl

    calls: list[dict] = []
    orig = fl.record_parse_event
    fl.record_parse_event = lambda user, path, **kw: calls.append(
        {"user": user, "path": path, **kw}
    )
    try:
        # 全文成功
        dr._record_parse_ledger(
            ("read", "/w/a.docx"), {}, {"file": "/w/a.docx", "mode": "full",
                                         "format": "docx", "content": "x" * 10}
        )
        check("A1 全文解析记 ok", calls[-1]["status"] == "ok")
        check("A1 方式带模式与格式", calls[-1]["method"] == "full/docx")
        # 截断 → degraded
        dr._record_parse_ledger(
            ("read", "/w/b.pdf"), {}, {"file": "/w/b.pdf", "mode": "pages",
                                       "format": "pdf", "truncated": True,
                                       "returned_chars": 500}
        )
        check("A1 截断/分页记 degraded", calls[-1]["status"] == "degraded")
        # 超时
        dr._record_parse_ledger(
            ("read", "/w/c.docx"), {}, {"file": "/w/c.docx",
                                        "error": "解析超时（120s）"}
        )
        check("A1 超时记 timeout", calls[-1]["status"] == "timeout")
        # 其它失败
        dr._record_parse_ledger(
            ("read", "/w/d.docx"), {}, {"file": "/w/d.docx", "error": "文件损坏"}
        )
        check("A1 其它错误记 fail", calls[-1]["status"] == "fail")
        # 非 read 动作不记
        n = len(calls)
        dr._record_parse_ledger(("formats",), {}, {"formats": []})
        dr._record_parse_ledger(("detect", "/w/e.pdf"), {}, {"file": "/w/e.pdf"})
        check("A1 formats/detect 不产生解析事实", len(calls) == n)
        # 直接喂内容不记
        dr._record_parse_ledger(
            (), {"action": "read", "content": "abc"}, {"content": "abc"}
        )
        check("A1 直接喂内容不记台账", len(calls) == n)
        # 坏结果不抛
        for junk in (None, "str", {}, {"file": None}):
            dr._record_parse_ledger(("read",), {}, junk)
        check("A1 坏结果不抛异常", True)
    finally:
        fl.record_parse_event = orig


def test_doc_reader_wrapper_keeps_schema() -> None:
    import inspect

    from coapis.agents.tools.doc_reader import doc_reader

    sig = inspect.signature(doc_reader)
    params = list(sig.parameters)
    check("A1 包装后签名仍可解析", "action" in params)
    check("A1 包装后 docstring 保留", bool((doc_reader.__doc__ or "").strip()))
    check("A1 包装后仍是协程", inspect.iscoroutinefunction(doc_reader))


# ---------------------------------------------------------------- A5 ----


def test_attachment_manifest() -> None:
    from coapis.agents.utils import message_processing as mp
    import coapis.foundation.file_ledger as fl
    import coapis.config.session_context as sc

    table = {
        "ok.docx": {"status": "ok", "chars": 5000, "method": "full/docx"},
        "part.pdf": {"status": "degraded", "chars": 800, "method": "pages/pdf"},
        "to.docx": {"status": "timeout", "chars": 0, "method": "full/docx"},
        "bad.docx": {"status": "fail", "chars": 0, "method": "full/docx"},
        "new.docx": None,
    }

    class FakeLedger:
        def parse_status_of(self, user, path):
            return table.get(Path(path).name)

    orig_ledger = fl.get_file_ledger
    orig_user = sc.get_current_username
    fl.get_file_ledger = lambda: FakeLedger()
    sc.get_current_username = lambda: "alice"
    try:
        files = [(n, f"/w/{n}") for n in table]
        text = mp._attachment_manifest(files, "zh")
        check("A5 清单包含每个附件", all(n in text for n in table))
        check("A5 已解析带字符数", "已解析（5000 字符）" in text)
        check("A5 部分解析标方式", "只解析了部分" in text and "pages/pdf" in text)
        check("A5 超时/失败明说", "解析超时" in text and "解析失败" in text)
        check("A5 未解析标明", "未解析" in text)
        check("A5 带判据话术", "doc_reader" in text and "臆测" in text)
        check("A5 空清单返回空", mp._attachment_manifest([], "zh") == "")
        en = mp._attachment_manifest(files, "en")
        check("A5 英文环境可用", "Attachment manifest" in en and "not parsed" in en)
    finally:
        fl.get_file_ledger = orig_ledger
        sc.get_current_username = orig_user


def test_attachment_manifest_survives_infra_failure() -> None:
    from coapis.agents.utils import message_processing as mp
    import coapis.foundation.file_ledger as fl

    orig = fl.get_file_ledger
    fl.get_file_ledger = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        check("A5 台账不可用时不抛、返回空",
              mp._attachment_manifest([("a.docx", "/w/a.docx")], "zh") == "")
    finally:
        fl.get_file_ledger = orig


# ---------------------------------------------------------------- U2 ----


def test_effective_timezone() -> None:
    from coapis.app.runner import utils as u
    import coapis.user_system.database as usdb

    cases = {
        "alice": {"settings": {"timezone": "Asia/Kolkata"}},
        "bob": {"settings": {"timezone": "Not/AZone"}},
        "carl": {"settings": {}},
        "dora": {"settings": '{"timezone":"Europe/Paris"}'},
        "eve": None,
    }

    class FakeDB:
        def get_user_preferences(self, username):
            if username == "boom":
                raise RuntimeError("db down")
            return cases.get(username)

    orig = usdb.UserSystemDB
    usdb.UserSystemDB = lambda: FakeDB()
    try:
        check("U2 用户时区生效", u._effective_timezone("alice") == "Asia/Kolkata")
        check("U2 非法时区回兜底", u._effective_timezone("bob") not in ("Not/AZone", ""))
        check("U2 未设置回兜底", u._effective_timezone("carl") not in (None, ""))
        check("U2 settings 为字符串也能解析",
              u._effective_timezone("dora") == "Europe/Paris")
        check("U2 无偏好行回兜底", u._effective_timezone("eve") not in (None, ""))
        check("U2 无用户名回兜底", u._effective_timezone(None) not in (None, ""))
        check("U2 库不可用回兜底", u._effective_timezone("boom") not in (None, ""))
    finally:
        usdb.UserSystemDB = orig


def test_env_context_uses_user_timezone() -> None:
    from coapis.app.runner import utils as u
    import coapis.user_system.database as usdb

    class FakeDB:
        def get_user_preferences(self, username):
            return {"settings": {"timezone": "Pacific/Auckland"}}

    orig = usdb.UserSystemDB
    usdb.UserSystemDB = lambda: FakeDB()
    try:
        ctx = u.build_env_context(
            session_id="s1", user_id="alice",
            user_name="爱丽丝", user_role="user", working_dir="/tmp",
        )
        check("U2 环境上下文带用户时区", "Pacific/Auckland" in ctx)
        check("U1 环境上下文带用户名", "爱丽丝" in ctx)
    finally:
        usdb.UserSystemDB = orig


# ---------------------------------------------------------------- run ----


def main() -> int:
    # 全量套件里别的模块会重绑全局 engine，执行时重新绑定并建表
    _init_db()
    print("A1 解析入台账")
    for fn in (
        _case_mark_parse_updates_existing_row,
        _case_mark_parse_creates_row_when_absent,
        _case_mark_parse_scope_and_status,
        _case_mark_parse_never_raises,
        _case_parse_status_of_newest,
    ):
        with tempfile.TemporaryDirectory() as td:
            fn(Path(td))
    print("A1 doc_reader 包装")
    test_record_parse_ledger_classification()
    test_doc_reader_wrapper_keeps_schema()
    print("A5 附件清单")
    test_attachment_manifest()
    test_attachment_manifest_survives_infra_failure()
    print("U2 时区按用户")
    test_effective_timezone()
    test_env_context_uses_user_timezone()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ALL OK")
    return 0


def test_phase1_tails() -> None:
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
