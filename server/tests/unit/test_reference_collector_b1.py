# -*- coding: utf-8 -*-
"""B1 采集器 + B2 会话资源清单（台账侧）的行为契约。

盯四件事：

1. **采集口径**：写文件的工具 → producer 文件；读文件 / 搜索 → reference；
   web_search 的 JSON 结果 → 网页条目（带标题）。
2. **作用域**：只登记落在**当前用户工作区**且**真实存在**的文件；``/tmp``
   与跨用户路径、模型幻觉出来的路径一律不进清单（预览端点 B0 也拒绝它们）。
3. **去重与上限**：同一轮里同一资源只出现一次；单调用 ≤8 条、整轮 ≤20 条。
4. **台账联动**：登记后按 chat_id 能查回清单，且 ``role`` 取的是**本会话**
   的引用角色（同一文件在 A 会话是产出、在 B 会话只是引用）。
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


@pytest.fixture()
def env(tmp_path, monkeypatch):
    init_engine(f"sqlite:///{tmp_path / 'res.db'}")
    Base.metadata.create_all(get_engine())

    ws = tmp_path / "workspaces"
    (ws / "alice" / "files").mkdir(parents=True)
    (ws / "bob" / "files").mkdir(parents=True)
    (tmp_path / "media").mkdir()

    monkeypatch.setattr(rc, "_workspace_root", lambda username: (ws / username).resolve())
    import coapis.constant as const

    monkeypatch.setattr(const, "WORKSPACES_DIR", ws)
    monkeypatch.setattr(const, "DEFAULT_MEDIA_DIR", tmp_path / "media")

    ledger = ResourceLedger(workspaces_dir=str(ws))
    monkeypatch.setattr(
        "coapis.foundation.resource_ledger.get_resource_ledger",
        lambda: ledger,
    )

    with get_session() as s:
        for name in ("alice", "bob"):
            s.add(
                User(
                    id=f"u_{name}",
                    username=name,
                    password_hash="x",
                    salt="x",
                    created_at=time.time(),
                )
            )

    # 注意：ContextVar 在 fixture 生成器里 set 会在 yield 后被还原，所以
    # 采集器必须在**每个用例内** begin_turn —— 这正是它按请求隔离的方式。
    yield ws, ledger
    reset_engine()


def _tool(name: str, **inp) -> dict:
    return {"name": name, "input": inp}


def _text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


# ── 采集口径 ────────────────────────────────────────────────────────


def test_write_file_registers_producer(env):
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    (ws / "alice" / "files" / "入市方案.md").write_text("# 入市方案", encoding="utf-8")
    added = rc.collect_from_tool_call(
        _tool("write_file", file_path=str(ws / "alice" / "files" / "入市方案.md")),
        _text(f"File written: {ws}/alice/files/入市方案.md"),
    )
    assert len(added) == 1
    item = added[0]
    assert item["kind"] == "file" and item["role"] == "producer"
    assert item["ref"] == "files/入市方案.md"
    assert item["title"] == "入市方案.md"
    rows = ledger.list_resources_for_chat(
        owner_scope="user", owner_id="alice", chat_id="chat-1"
    )
    assert len(rows) == 1
    assert rows[0]["role"] == "producer"
    # 台账统一口径 = 工作区相对路径（与前端/回答正文同一口径）。
    assert rows[0]["path"] == "files/入市方案.md"


def test_read_file_registers_reference(env):
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    (ws / "alice" / "files" / "notes.md").write_text("正文", encoding="utf-8")
    added = rc.collect_from_tool_call(
        _tool("read_file", file_path=str(ws / "alice" / "files" / "notes.md")),
        _text("正文"),
    )
    assert added[0]["role"] == "reference"
    assert added[0]["ref"] == "files/notes.md"


def test_web_search_queues_candidates_not_ledgered(env):
    """闸门（D2-A）：搜索结果只是候选，采集阶段不入台账、不进清单。"""
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    payload = (
        '{"query":"深圳 规划","results":['
        '{"title":"深圳市空间规划","url":"https://www.dghx.gov.cn/gh/index.html"},'
        '{"title":"深圳2035","url":"https://fj.ta.gov.cn/zc/2035"}]}'
    )
    added = rc.collect_from_tool_call(
        _tool("web_search", search_term="深圳 规划"), _text(payload)
    )
    assert added == []
    turn = rc.get_turn_resources()
    assert len(turn.pending_web) == 2
    assert turn.pending_web[0]["title"] == "深圳市空间规划"
    rows = ledger.list_resources_for_chat(
        owner_scope="user", owner_id="alice", chat_id="chat-1"
    )
    assert rows == []


def test_finalize_keeps_only_links_cited_in_body(env):
    """闸门（D2-A）：正文引用了哪条，台账里就只有哪条，标题用正文锚文本。"""
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    payload = (
        '{"query":"深圳 规划","results":['
        '{"title":"深圳市空间规划","url":"https://www.dghx.gov.cn/gh/index.html"},'
        '{"title":"深圳2035","url":"https://fj.ta.gov.cn/zc/2035"}]}'
    )
    rc.collect_from_tool_call(
        _tool("web_search", search_term="深圳 规划"), _text(payload)
    )
    kept = rc.finalize_web_references(
        "依据 [深圳市空间规划](https://www.dghx.gov.cn/gh/index.html) 编制。"
    )
    assert kept == 1
    items = rc.take_turn_resources()
    assert len(items) == 1
    assert items[0]["ref"] == "https://www.dghx.gov.cn/gh/index.html"
    assert items[0]["title"] == "深圳市空间规划"
    rows = ledger.list_resources_for_chat(
        owner_scope="user", owner_id="alice", chat_id="chat-1"
    )
    assert [r["ref"] if "ref" in r else r.get("path") for r in rows] == [
        "https://www.dghx.gov.cn/gh/index.html"
    ]


def test_finalize_strips_tracking_params_and_entities(env):
    """正文粘贴链接常丢跟踪参数；标题里的 HTML 实体要反转义。"""
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    payload = (
        '{"query":"R&D","results":['
        '{"title":"R&amp;D 税收政策","url":"https://t.example.gov.cn/p/1?utm_source=agg"}]}'
    )
    rc.collect_from_tool_call(_tool("web_search", search_term="R&D"), _text(payload))
    assert rc.get_turn_resources().pending_web[0]["title"] == "R&D 税收政策"
    # 正文里丢了 utm 参数，仍算引用
    assert rc.finalize_web_references("见 https://t.example.gov.cn/p/1。") == 1
    items = rc.take_turn_resources()
    assert items[0]["ref"] == "https://t.example.gov.cn/p/1?utm_source=agg"


def test_finalize_without_body_drops_all_candidates(env):
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    payload = (
        '{"query":"x","results":[{"title":"A","url":"https://a.example.com/1"}]}'
    )
    rc.collect_from_tool_call(_tool("web_search", search_term="x"), _text(payload))
    assert rc.finalize_web_references("这段回答没有任何链接。") == 0
    assert rc.take_turn_resources() == []
    assert ledger.list_resources_for_chat(
        owner_scope="user", owner_id="alice", chat_id="chat-1"
    ) == []


def test_web_fetch_registers_input_url(env):
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    added = rc.collect_from_tool_call(
        _tool("web_fetch", url="https://www.dghx.gov.cn/gh/index.html"),
        _text("正文若干"),
    )
    assert added[0]["ref"] == "https://www.dghx.gov.cn/gh/index.html"


def test_glob_search_registers_listed_files(env):
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    for n in ("a.md", "b.md"):
        (ws / "alice" / "files" / n).write_text("x", encoding="utf-8")
    out = f"{ws}/alice/files/a.md:1: 内容\n{ws}/alice/files/b.md:3: 内容\n"
    added = rc.collect_from_tool_call(_tool("glob_search", pattern="*.md"), _text(out))
    assert {i["ref"] for i in added} == {"files/a.md", "files/b.md"}


# ── 作用域 ──────────────────────────────────────────────────────────


def test_tmp_paths_not_registered(env):
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    added = rc.collect_from_tool_call(
        _tool("read_file", file_path="/tmp/scratch.txt"),
        _text("内容 /tmp/scratch.txt 与 /etc/passwd"),
    )
    assert added == []


def test_cross_user_paths_not_registered(env):
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    (ws / "bob" / "files" / "private.md").write_text("私密", encoding="utf-8")
    added = rc.collect_from_tool_call(
        _tool("read_file", file_path=str(ws / "bob" / "files" / "private.md")),
        _text("私密"),
    )
    assert added == []


def test_hallucinated_path_not_registered(env):
    """模型幻觉出来的路径（文件不存在）不能进清单。"""
    ws, ledger = env
    added = rc.collect_from_tool_call(
        _tool("write_file", file_path=str(ws / "alice" / "files" / "ghost.md")),
        _text("written"),
    )
    assert added == []


def test_relative_path_resolves_into_workspace(env):
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    (ws / "alice" / "files" / "rel.md").write_text("x", encoding="utf-8")
    added = rc.collect_from_tool_call(
        _tool("write_file", file_path="files/rel.md"), _text("ok")
    )
    assert added[0]["ref"] == "files/rel.md"


# ── 去重与上限 ──────────────────────────────────────────────────────


def test_dedup_across_calls(env):
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    p = str(ws / "alice" / "files" / "same.md")
    (ws / "alice" / "files" / "same.md").write_text("x", encoding="utf-8")
    rc.collect_from_tool_call(_tool("write_file", file_path=p), _text("ok"))
    second = rc.collect_from_tool_call(_tool("read_file", file_path=p), _text("ok"))
    assert second == []
    turn = rc.get_turn_resources()
    assert len(turn.items) == 1


def test_per_call_cap(env):
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    lines = []
    for i in range(20):
        rel = f"files/g{i}.md"
        (ws / "alice" / "files" / f"g{i}.md").write_text("x", encoding="utf-8")
        lines.append(f"{ws}/alice/files/g{i}.md:1: x")
    added = rc.collect_from_tool_call(_tool("glob_search", pattern="*.md"), _text("\n".join(lines)))
    assert len(added) <= rc.MAX_PER_CALL


def test_turn_cap(env):
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    for i in range(40):
        (ws / "alice" / "files" / f"t{i}.md").write_text("x", encoding="utf-8")
        rc.collect_from_tool_call(
            _tool("write_file", file_path=str(ws / "alice" / "files" / f"t{i}.md")),
            _text("ok"),
        )
    turn = rc.get_turn_resources()
    assert len(turn.items) == rc.MAX_TURN_RESOURCES


def test_take_turn_resources_snapshot(env):
    ws, ledger = env
    rc.begin_turn(chat_id="chat-1", username="alice")
    (ws / "alice" / "files" / "snap.md").write_text("x", encoding="utf-8")
    rc.collect_from_tool_call(
        _tool("write_file", file_path=str(ws / "alice" / "files" / "snap.md")),
        _text("ok"),
    )
    snap = rc.take_turn_resources()
    assert snap and snap[0]["ref"] == "files/snap.md"
    assert snap[0]["resource_key"]


def test_no_collector_started_is_silent(env):
    """没 begin_turn（如 cron 直跑）时采集器必须完全静默，不抛。"""
    rc._turn_resources_ctx.set(None)
    assert rc.collect_from_tool_call(_tool("write_file", file_path="/x"), _text("x")) == []
    assert rc.take_turn_resources() == []


# ── 台账：按会话查清单 ──────────────────────────────────────────────


def test_chat_role_is_per_chat(env):
    ws, ledger = env
    (ws / "alice" / "files" / "plan.md").write_text("x", encoding="utf-8")
    key = ledger.register(
        owner_scope="user", owner_id="alice", kind="file", path="files/plan.md"
    )
    ledger.attach_ref(
        resource_key=key,
        referrer_kind="chat",
        referrer_id="chat-A",
        role="producer",
    )
    ledger.attach_ref(
        resource_key=key,
        referrer_kind="chat",
        referrer_id="chat-B",
        role="reference",
    )
    rows_a = ledger.list_resources_for_chat(
        owner_scope="user", owner_id="alice", chat_id="chat-A"
    )
    rows_b = ledger.list_resources_for_chat(
        owner_scope="user", owner_id="alice", chat_id="chat-B"
    )
    assert rows_a[0]["role"] == "producer"
    assert rows_b[0]["role"] == "reference"
    assert ledger.count_resources_for_chat(
        owner_scope="user", owner_id="alice", chat_id="chat-A"
    ) == 1
    # 别的会话查不到
    assert ledger.list_resources_for_chat(
        owner_scope="user", owner_id="alice", chat_id="chat-C"
    ) == []
