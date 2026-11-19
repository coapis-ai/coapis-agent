# -*- coding: utf-8 -*-
"""登记侧闸门：工具"扫到"的文件，必须被正文引用才进资源台账。

盯的缺陷：一次 glob_search / grep_search 会把工作区里的文件整片登记成
本会话引用，会话资源面板于是出现"跟这次对话无关的文件"（实测会话
690f6f88 混进了另一个项目的 pptx）。

立场与 ``finalize_web_references`` 对搜索 URL 的处理一致：捞到过只是候选，
模型回复里没提就不算这轮的引用。差别只在尺子 —— 文件看文件名/相对路径
有没有出现在正文里。
"""
from __future__ import annotations

import time

import pytest

from coapis.agents.context import reference_collector as rc
from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import (
    get_engine,
    get_session,
    init_engine,
    reset_engine,
)
from coapis.foundation.db.models.user import User
from coapis.foundation.resource_ledger import ResourceLedger

CHAT = "chat-1"
USER = "alice"


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    """真实 sqlite + 真实台账 + 真实工作区：断言打在库里的行上。"""
    init_engine(f"sqlite:///{tmp_path / 'gate.db'}")
    Base.metadata.create_all(get_engine())

    root = tmp_path / "workspaces"
    alice = root / USER
    (alice / "files" / "notes").mkdir(parents=True)
    (alice / "files" / "notes" / "report.md").write_text("正文里提到的文件", encoding="utf-8")
    (alice / "files" / "notes" / "无关汇报.pptx").write_text("与本会话无关", encoding="utf-8")
    (alice / "files" / "notes" / "out.md").write_text("产出", encoding="utf-8")

    monkeypatch.setattr(rc, "_workspace_root", lambda username: (root / username).resolve())
    import coapis.constant as const

    monkeypatch.setattr(const, "WORKSPACES_DIR", root)
    monkeypatch.setattr(const, "DEFAULT_MEDIA_DIR", tmp_path / "media")

    ledger = ResourceLedger(workspaces_dir=str(root))
    monkeypatch.setattr(
        "coapis.foundation.resource_ledger.get_resource_ledger",
        lambda: ledger,
    )

    with get_session() as s:
        s.add(
            User(
                id="u_alice",
                username=USER,
                password_hash="x",
                salt="x",
                created_at=time.time(),
            ),
        )

    yield alice.resolve()

    reset_engine()


def _tool(name, **inp):
    return {"id": "tc-1", "name": name, "input": inp}


def _rows():
    return ResourceLedger().list_resources_for_chat(
        owner_scope="user",
        owner_id=USER,
        chat_id=CHAT,
    )


def test_glob_hits_are_not_registered_until_cited(ws):
    """glob 列出的文件只是候选：没裁决前台账必须一条都没有。"""
    rc.begin_turn(chat_id=CHAT, username=USER, turn_id="t-glob")

    added = rc.collect_from_tool_call(
        _tool("glob_search", pattern="**/*"),
        str(ws / "files" / "notes" / "report.md") + "\n" + str(ws / "files" / "notes" / "无关汇报.pptx") + "\n",
        chat_id=CHAT,
        username=USER,
    )
    assert added, "候选仍要进本轮池（界面提示用），只是不入账"
    assert _rows() == [], "扫到的文件不得绕过正文闸门"

    turn = rc._turn_resources_ctx.get()
    assert {it["ref"] for it in turn.pending_files} == {
        "files/notes/report.md",
        "files/notes/无关汇报.pptx",
    }


def test_only_body_cited_file_lands_in_ledger(ws):
    """正文只提到 report.md，那也只有它能入账。"""
    rc.begin_turn(chat_id=CHAT, username=USER, turn_id="t-grep")
    rc.collect_from_tool_call(
        _tool("grep_search", pattern="hello"),
        str(ws / "files" / "notes" / "report.md") + ":1:hello\n"
        + str(ws / "files" / "notes" / "无关汇报.pptx") + "\n",
        chat_id=CHAT,
        username=USER,
    )

    assert rc.finalize_file_references("我把 report.md 的内容整理了一下") == 1
    rows = _rows()
    assert [r["path"] for r in rows] == ["files/notes/report.md"]
    assert rows[0]["role"] == "reference"


def test_uncited_scan_drops_everything(ws):
    """正文没提任何文件 → 扫描候选整批丢弃，会话资源池保持干净。"""
    rc.begin_turn(chat_id=CHAT, username=USER, turn_id="t-empty")
    rc.collect_from_tool_call(
        _tool("glob_search", pattern="**/*"),
        str(ws / "files" / "notes" / "无关汇报.pptx") + "\n",
        chat_id=CHAT,
        username=USER,
    )

    assert rc.finalize_file_references("这轮只是聊了聊，没动任何文件") == 0
    assert _rows() == []


def test_explicit_read_target_registers_at_once(ws):
    """read_file 参数里写死的文件是"明确操作目标"，无需等正文，立即入账。"""
    rc.begin_turn(chat_id=CHAT, username=USER, turn_id="t-read")
    rc.collect_from_tool_call(
        _tool("read_file", file_path=str(ws / "files" / "notes" / "report.md")),
        "正文里提到的文件",
        chat_id=CHAT,
        username=USER,
    )

    assert [r["path"] for r in _rows()] == ["files/notes/report.md"]


def test_declared_producer_is_not_gated(ws):
    """本轮声明的产出不能被正文闸门卡住 —— 产出清单得看得见。"""
    rc.begin_turn(chat_id=CHAT, username=USER, turn_id="t-write")
    rc.collect_from_tool_call(
        _tool("write_file", file_path=str(ws / "files" / "notes" / "out.md")),
        "ok",
        chat_id=CHAT,
        username=USER,
    )

    rows = _rows()
    assert [r["path"] for r in rows] == ["files/notes/out.md"]
    assert rows[0]["role"] == "producer"
