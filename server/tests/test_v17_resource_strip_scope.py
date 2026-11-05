"""v17 资源条口径自检（右侧栏两块 + 排序尺子 + 台账时刻对账）。

对应小蜜蜂 2026-11-05 的要求：
 ① 右侧栏 200px：上半区=当前会话（跨聊天）、下半区=当前聊天 —— 台账必须
    提供 session 作用域，且与 chat 作用域同一份合并/排序口径；
 ② 排序尺子 = 显示口径（更新时间倒序），分页发生在排序之后；
 ③ 文件被聊天之外重写时，台账时刻/大小/版本要与磁盘对账（update_activity）。
"""
from __future__ import annotations

import time

import pytest

from coapis.foundation.db import get_session, init_engine, reset_engine
from coapis.foundation.db.base import Base
from coapis.foundation.resource_ledger import ResourceLedger

OWNER = "alice"
CHAT_ID = "v17-chat-1"
SESSION_ID = "v17-session-1"


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    """独立临时库 + 临时工作区（与 B2 端点测试同一套隔离口径）。"""
    init_engine(f"sqlite:///{tmp_path / 'ledger.db'}")
    Base.metadata.create_all(_engine())
    ws = tmp_path / "workspaces"
    (ws / OWNER / "files").mkdir(parents=True)
    (ws / OWNER / "files" / "a.md").write_text("# A", encoding="utf-8")
    (ws / OWNER / "files" / "b.xlsx").write_bytes(b"xlsx-b")
    import coapis.constant as const

    monkeypatch.setattr(const, "WORKSPACES_DIR", ws)
    led = ResourceLedger(workspaces_dir=str(ws))
    monkeypatch.setattr(
        "coapis.foundation.resource_ledger.get_resource_ledger",
        lambda: led,
    )
    yield led
    reset_engine()


def _engine():
    from coapis.foundation.db import get_engine

    return get_engine()


def _seed(led: ResourceLedger) -> None:
    """两个文件都挂在聊天上；a.md 另挂会话引用。"""
    for name in ("files/a.md", "files/b.xlsx"):
        key = led.register(kind="file", owner_scope="user", owner_id=OWNER, path=name)
        led.attach_ref(resource_key=key, referrer_kind="chat", referrer_id=CHAT_ID)
    key_a = led.register(kind="file", owner_scope="user", owner_id=OWNER, path="files/a.md")
    led.attach_ref(resource_key=key_a, referrer_kind="session", referrer_id=SESSION_ID)


def _chat(led, **kw):
    return led.list_resources_for_chat(
        owner_scope="user", owner_id=OWNER, chat_id=CHAT_ID, **kw
    )


def _sess(led, chat_ids, **kw):
    return led.list_session_resources(
        owner_scope="user", owner_id=OWNER, session_id=SESSION_ID, chat_ids=chat_ids, **kw
    )


def test_session_scope_covers_chat_refs(ledger):
    """上半区（session）= 会话引用 + 会话内聊天引用，绝不比下半区少。"""
    _seed(ledger)
    chat_rows = _chat(ledger, limit=50)
    sess_rows = _sess(ledger, [CHAT_ID], limit=50)
    assert len(chat_rows) == 2
    assert {r["path"] for r in sess_rows} == {r["path"] for r in chat_rows}
    assert (
        ledger.count_session_resources(
            owner_scope="user", owner_id=OWNER, session_id=SESSION_ID, chat_ids=[CHAT_ID]
        )
        == len(sess_rows)
    )


def test_session_scope_without_chat_ids(ledger):
    """只给 session_id（拿不到同伴聊天时）：仍出 session 引用，不整块空掉。"""
    _seed(ledger)
    rows = _sess(ledger, [], limit=50)
    assert {r["path"] for r in rows} == {"files/a.md"}


def test_sort_ruler_equals_display_ruler(ledger):
    """显示列是更新时间 → 排序就按更新时间倒序；分页在排序之后切。"""
    _seed(ledger)
    # 给两个文件制造可区分的更新时间
    rows = _chat(ledger, limit=50, sort_by="updated_at")
    ts = [float(r.get("updated_at") or 0) for r in rows]
    assert ts == sorted(ts, reverse=True)
    page = _chat(ledger, limit=1, offset=1, sort_by="updated_at")
    assert rows[1]["resource_key"] == page[0]["resource_key"]
    srows = _sess(ledger, [CHAT_ID], limit=50, sort_by="updated_at")
    sts = [float(r.get("updated_at") or 0) for r in srows]
    assert sts == sorted(sts, reverse=True)


def test_illegal_sort_falls_back(ledger):
    """非法排序值不抛错、不自创尺子：回落默认「最近引用在前」。"""
    _seed(ledger)
    assert _chat(ledger, limit=5, sort_by="drop table") is not None
    assert _sess(ledger, [CHAT_ID], limit=5, sort_by="🙃") is not None


def test_update_activity_reconciles_disk_mtime(ledger):
    """聊天外重写文件后，台账时刻/大小/版本必须与磁盘对账。"""
    _seed(ledger)
    rows = _chat(ledger, limit=50)
    key = rows[0]["resource_key"]
    newer = time.time() + 5
    assert ledger.update_activity(key, updated_at=newer, size=4321) is True
    hit = [r for r in _chat(ledger, limit=50) if r["resource_key"] == key][0]
    assert float(hit["updated_at"]) >= newer
    assert int(hit["size_bytes"]) == 4321
    assert int(hit["version"]) >= 2  # 内容换了 → 版本递增

    # 幂等：旧时刻不得把台账改回过去
    assert ledger.update_activity(key, updated_at=time.time() - 10**6) is True
    hit2 = [r for r in _chat(ledger, limit=50) if r["resource_key"] == key][0]
    assert float(hit2["updated_at"]) >= newer


def test_update_activity_never_creates_rows(ledger):
    """未登记的 key 只返回 False —— 登记归采集器，对账不越权建行。"""
    _seed(ledger)
    assert ledger.update_activity("file:__no_such__.md") is False
    assert ledger.update_activity("") is False
    assert len(_chat(ledger, limit=50)) == 2
