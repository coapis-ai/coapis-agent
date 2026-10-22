# -*- coding: utf-8 -*-
"""台账会跟着文件走：标题兜底、移动跟随、失效软删。

实测 dev 台账 347 行的两个遗留缺陷：

* **94 行标题为空** —— 文件台账钩子登记资源时不传标题，前端资源条只能退化成
  显示整条路径（``files/2026-10/2026-10-22_任务/报告.docx``）。
* **26 行文件已消失却永远挂在台账里** —— 巡检只把 ``fs_present`` 置 0，行本身
  永不失效，资源条长期显示"已删除"的死链；文件被改名/挪目录后台账还指旧路径。

这里补齐三件事（巡检每天 03:00 跑一次，全部只写库、**永不删 FS 文件**）：
① 登记时标题兜底成文件名，存量空标题由巡检补齐；
② 文件在工作区里换了位置 → 台账改指新位置，``resource_refs`` 一起迁；
③ 连续两轮巡检都看不见 → 软删台账行（``deleted_at`` 置位），清单不再返回。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from coapis.foundation import resource_ledger as rl
    from coapis.foundation.db.base import Base
    from coapis.foundation.db.engine import get_engine, get_session, init_engine, reset_engine
    from coapis.foundation.db.models.user import User

    ws = tmp_path / "workspaces"
    (ws / "alice" / "files" / "a").mkdir(parents=True)
    (ws / "alice" / "files" / "b").mkdir(parents=True)
    (ws / "alice" / "files" / ".trash").mkdir(parents=True)

    init_engine(f"sqlite:///{tmp_path / 'follow.db'}")
    Base.metadata.create_all(get_engine())
    with get_session() as s:
        s.add(
            User(
                id="u_alice",
                username="alice",
                password_hash="x",
                salt="x",
                created_at=time.time(),
            )
        )
    monkeypatch.setattr(rl, "WORKSPACES_DIR", ws)
    yield rl.ResourceLedger(workspaces_dir=str(ws)), ws
    reset_engine()


def _mk(ws: Path, user: str, rel: str, text: str = "x") -> Path:
    p = ws / user / "files" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _set_updated_at(led, path: str, ts: float) -> None:
    """把某行的"第一次发现缺失"时刻挪到过去（模拟上一轮巡检）。"""
    from coapis.foundation.db.engine import get_session
    from coapis.foundation.db.models.resources import Resource
    from sqlalchemy import select

    with get_session() as s:
        row = s.execute(
            select(Resource).where(Resource.path == path)
        ).scalar_one_or_none()
        assert row is not None
        row.updated_at = ts


# ── ① 标题兜底 ────────────────────────────────────────────────────


def test_register_fills_title_from_filename(env):
    led, ws = env
    _mk(ws, "alice", "report.md")
    led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="report.md",
        path_form="files_root",
    )
    rows = led.list_resources(owner_scope="user", owner_id="alice")
    assert rows[0]["title"] == "report.md"


def test_register_keeps_richer_title(env):
    """显式标题优先；兜底只补空，不把采集器给过的网页标题降级成文件名。"""
    led, ws = env
    _mk(ws, "alice", "report.md")
    led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="report.md",
        path_form="files_root",
        title="季度报告",
    )
    led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="report.md",
        path_form="files_root",
    )
    rows = led.list_resources(owner_scope="user", owner_id="alice")
    assert rows[0]["title"] == "季度报告"


def test_sweep_backfills_existing_empty_titles(env):
    led, ws = env
    _mk(ws, "alice", "old.md")
    led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="old.md",
        path_form="files_root",
    )
    # 造出存量空标题
    from coapis.foundation.db.engine import get_session
    from coapis.foundation.db.models.resources import Resource
    from sqlalchemy import select

    with get_session() as s:
        s.execute(select(Resource)).scalar_one_or_none()
        for r in s.execute(select(Resource)).scalars().all():
            r.title = None
    assert led.list_resources(owner_scope="user", owner_id="alice")[0]["title"] is None

    rep = led.sweep()
    assert rep["titled"] == 1
    assert led.list_resources(owner_scope="user", owner_id="alice")[0]["title"] == "old.md"


# ── ② 台账跟随移动 ────────────────────────────────────────────────


def test_sweep_follows_moved_file_and_migrates_refs(env):
    led, ws = env
    _mk(ws, "alice", "a/report.md", "报告")
    key = led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="a/report.md",
        path_form="files_root",
    )
    led.attach_ref(
        resource_key=key, referrer_kind="chat", referrer_id="chat-1", role="producer"
    )
    # 用户把文件挪到 b/
    (ws / "alice" / "files" / "a" / "report.md").rename(
        ws / "alice" / "files" / "b" / "report.md"
    )

    rep = led.sweep()
    assert rep["relocated"] == 1
    assert rep["relocated_list"][0]["to"] == "files/b/report.md"

    rows = led.list_resources(owner_scope="user", owner_id="alice")
    assert len(rows) == 1
    assert rows[0]["path"] == "files/b/report.md"
    assert rows[0]["fs_present"] == 1
    assert rows[0]["ref_count"] == 1  # refs 迁过去了，会话引用没丢
    # 会话资源条仍然看得见
    chat = led.list_resources_for_chat(
        owner_scope="user", owner_id="alice", chat_id="chat-1"
    )
    assert [c["path"] for c in chat] == ["files/b/report.md"]


def test_sweep_merges_when_target_row_already_exists(env):
    """移动目标已有台账行 → 合并成一行，refs 去重迁移，旧行消失。"""
    led, ws = env
    _mk(ws, "alice", "a/report.md", "报告")
    _mk(ws, "alice", "b/report.md", "报告")
    old_key = led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="a/report.md",
        path_form="files_root",
    )
    new_key = led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="b/report.md",
        path_form="files_root",
    )
    led.attach_ref(
        resource_key=old_key, referrer_kind="chat", referrer_id="chat-1", role="producer"
    )
    led.attach_ref(
        resource_key=new_key, referrer_kind="chat", referrer_id="chat-1", role="producer"
    )
    # 旧位置的文件没了
    (ws / "alice" / "files" / "a" / "report.md").unlink()

    rep = led.sweep()
    assert rep["relocated"] == 1
    assert rep["relocated_list"][0]["merged"] is True

    rows = led.list_resources(owner_scope="user", owner_id="alice")
    assert len(rows) == 1  # 同一文件只剩一行
    assert rows[0]["path"] == "files/b/report.md"
    assert rows[0]["ref_count"] == 1  # 重复引用去重，没有翻倍
    assert new_key in {r["resource_key"] for r in rows}
    assert old_key not in {r["resource_key"] for r in rows}


def test_sweep_skips_ambiguous_move(env):
    """同名、同大小、同 mtime → 判不准是哪一个，宁留旧行也不猜。"""
    led, ws = env
    _mk(ws, "alice", "a/report.md", "same")
    _mk(ws, "alice", "b/report.md", "same")
    _mk(ws, "alice", "c/report.md", "same")
    stamp = time.time() - 10
    for sub in ("a", "b", "c"):
        p = ws / "alice" / "files" / sub / "report.md"
        import os

        os.utime(p, (stamp, stamp))
    led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="a/report.md",
        path_form="files_root",
    )
    (ws / "alice" / "files" / "a" / "report.md").unlink()

    rep = led.sweep()
    assert rep["relocated"] == 0
    rows = led.list_resources(owner_scope="user", owner_id="alice")
    missing = [r for r in rows if r["path"] == "files/a/report.md"]
    assert missing and missing[0]["fs_present"] == 0


def test_sweep_does_not_follow_into_trash(env):
    """移进回收站是删除，不是换位置：台账不该把资源条指向 ``.trash``。"""
    led, ws = env
    _mk(ws, "alice", "report.md", "报告")
    led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="report.md",
        path_form="files_root",
    )
    (ws / "alice" / "files" / "report.md").rename(
        ws / "alice" / "files" / ".trash" / "report.md"
    )

    rep = led.sweep()
    assert rep["relocated"] == 0
    rows = led.list_resources(owner_scope="user", owner_id="alice")
    assert all(not r["path"].startswith(".trash") for r in rows)
    assert (ws / "alice" / "files" / ".trash" / "report.md").exists()  # FS 不动


# ── ③ 失效软删 ────────────────────────────────────────────────────


def test_sweep_keeps_fresh_missing_rows(env):
    """首轮发现缺失只起表，不软删（可能只是移动中途）。"""
    led, ws = env
    _mk(ws, "alice", "report.md")
    led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="report.md",
        path_form="files_root",
    )
    (ws / "alice" / "files" / "report.md").unlink()

    rep = led.sweep()
    assert rep["fs_missing"] == 1
    assert rep["expired"] == 0
    assert len(led.list_resources(owner_scope="user", owner_id="alice")) == 1


def test_sweep_soft_deletes_stale_missing_rows(env):
    led, ws = env
    _mk(ws, "alice", "report.md")
    led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="report.md",
        path_form="files_root",
    )
    (ws / "alice" / "files" / "report.md").unlink()
    led.sweep()  # 第一轮：标记缺失
    _set_updated_at(led, "files/report.md", time.time() - 40 * 3600)

    rep = led.sweep()
    assert rep["expired"] == 1
    assert rep["expired_list"][0]["path"] == "files/report.md"
    # 清单不再返回（资源条上的死链消失）
    assert led.list_resources(owner_scope="user", owner_id="alice") == []
    assert led.count_resources(owner_scope="user", owner_id="alice") == 0
    # 软删只写 deleted_at：FS 与台账行都还在，可恢复
    from coapis.foundation.db.engine import get_session
    from coapis.foundation.db.models.resources import Resource
    from sqlalchemy import select

    with get_session() as s:
        row = s.execute(select(Resource)).scalar_one_or_none()
        assert row is not None and row.deleted_at is not None
        assert row.status == "deleted"


def test_expired_rows_vanish_from_chat_panel(env):
    led, ws = env
    _mk(ws, "alice", "report.md")
    key = led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="report.md",
        path_form="files_root",
    )
    led.attach_ref(
        resource_key=key, referrer_kind="chat", referrer_id="chat-1", role="producer"
    )
    (ws / "alice" / "files" / "report.md").unlink()
    led.sweep()
    _set_updated_at(led, "files/report.md", time.time() - 40 * 3600)
    led.sweep()

    assert (
        led.count_resources_for_chat(owner_scope="user", owner_id="alice", chat_id="chat-1")
        == 0
    )
    assert (
        led.list_resources_for_chat(owner_scope="user", owner_id="alice", chat_id="chat-1")
        == []
    )


def test_relocate_can_be_disabled(env):
    led, ws = env
    _mk(ws, "alice", "a/report.md")
    led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="a/report.md",
        path_form="files_root",
    )
    (ws / "alice" / "files" / "a" / "report.md").rename(
        ws / "alice" / "files" / "b" / "report.md"
    )
    rep = led.sweep(relocate=False)
    assert rep["relocated"] == 0
    assert rep["fs_missing"] == 1


def test_sweep_never_deletes_files(env):
    """铁律：巡检任何一条路径都不许动 FS。"""
    led, ws = env
    keep = _mk(ws, "alice", "keep.md", "内容")
    gone = _mk(ws, "alice", "gone.md", "内容")
    gone.unlink()
    led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="keep.md",
        path_form="files_root",
    )
    led.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="gone.md",
        path_form="files_root",
    )
    _set_updated_at(led, "files/gone.md", time.time() - 40 * 3600)
    led.sweep()
    assert keep.exists()
    assert not (ws / "alice" / "files" / "gone.md").exists()
