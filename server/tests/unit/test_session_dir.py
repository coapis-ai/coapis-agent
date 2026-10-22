# -*- coding: utf-8 -*-
"""会话目录解析测试（files/{月}/{日期}_{任务} 规则）。

方案：tech_docs/我的空间目录规划_方案与实施计划_20261022.md
核心断言：**目录由系统决定**，模型只给文件名。
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from coapis.agents.context.session_dir import (
    MIN_NEW_FILES,
    SESSION_DIR_WINDOW_DAYS,
    flatten_rel_path,
    is_session_dir,
    resolve_session_dir,
    sanitize_task_name,
    session_write_dir,
    sweep_empty_session_dirs,
    sweep_report,
)

TODAY = date(2026, 10, 22)
MONTH = "2026-10"


@pytest.fixture()
def root(tmp_path):
    d = tmp_path / "files"
    d.mkdir()
    return d


def _mk(root: Path, name: str, files: int = 0) -> Path:
    p = root / MONTH / name
    p.mkdir(parents=True, exist_ok=True)
    for i in range(files):
        (p / f"f{i}.md").write_text("x", encoding="utf-8")
    return p


# ── 清洗与识别 ──────────────────────────────────────────────────────


def test_sanitize_strips_path_separators():
    assert sanitize_task_name("a/b\\c:d?e") == "a b c d e"
    assert sanitize_task_name("季度报告 v2") == "季度报告 v2"


def test_sanitize_rejects_empty_and_hidden():
    assert sanitize_task_name("") == ""
    assert sanitize_task_name(None) == ""
    assert sanitize_task_name("///") == ""
    assert sanitize_task_name("...") == ""
    assert sanitize_task_name(".git") == "git"


def test_sanitize_caps_length():
    from coapis.agents.context.session_dir import MAX_SLUG_LEN

    assert len(sanitize_task_name("长" * 200)) <= MAX_SLUG_LEN


def test_sanitize_shortens_sentence_titles():
    """会话标题经常就是用户第一句话，整句当目录名没法看。"""
    assert sanitize_task_name(
        "请直接写一个文件 e2e目录验证.md，内容写一句话即可。不要问我",
    ) == "直接写一个文件 e2e目录验证"
    assert sanitize_task_name("2026年Q3营收分析，含图表") == "2026年Q3营收分析"
    assert sanitize_task_name("写个报告。") == "写个报告"
    # 子句太短不切，避免"好，写个报告"切成"好"
    assert sanitize_task_name("好，写个报告") == "好，写个报告"
    # 纯指令前缀切完没东西 → 用原文兜底
    assert sanitize_task_name("请") == "请"


def test_is_session_dir():
    assert is_session_dir("2026-10-22_季度报告")
    assert is_session_dir("2026-10-22")
    assert not is_session_dir("季度报告")
    assert not is_session_dir("2026-13-40_x")  # 非法日期
    assert not is_session_dir("20261022_x")


# ── 落点计算 ────────────────────────────────────────────────────────


def test_no_chat_id_lands_flat_in_month(root):
    got = resolve_session_dir(root, None, None, today=TODAY)
    assert got == root / MONTH


def test_new_session_creates_dated_task_dir(root):
    got = resolve_session_dir(root, "chat-1", "季度报告", today=TODAY)
    assert got == root / MONTH / "2026-10-22_季度报告"


def test_titleless_session_falls_back_to_pure_date(root):
    got = resolve_session_dir(root, "chat-1", None, today=TODAY)
    assert got == root / MONTH / "2026-10-22"


def test_same_day_reuses_existing_dir(root):
    d = _mk(root, "2026-10-22_季度报告", files=3)
    got = resolve_session_dir(root, "chat-1", "季度报告", today=TODAY)
    assert got == d  # 绝不新建第二个当天目录


def test_under_threshold_appends_flat(root):
    d = _mk(root, "2026-10-20_季度报告", files=MIN_NEW_FILES - 1)
    got = resolve_session_dir(root, "chat-1", "季度报告", today=TODAY)
    assert got == d  # 未达门槛 → 平铺进同一会话目录


def test_at_threshold_adds_day_layer(root):
    d = _mk(root, "2026-10-20_季度报告", files=MIN_NEW_FILES)
    got = resolve_session_dir(root, "chat-1", "季度报告", today=TODAY)
    assert got == d / "2026-10-22_季度报告"


def test_window_ignores_older_session_dirs(root):
    old = date(2026, 10, 1)
    _mk(root, f"{old:%Y-%m-%d}_旧会话", files=2)
    got = resolve_session_dir(root, "chat-1", "季度报告", today=TODAY)
    assert got == root / MONTH / "2026-10-22_季度报告"
    assert SESSION_DIR_WINDOW_DAYS == 7


def test_other_month_is_isolated(root):
    _mk(root, "2026-09-30_旧会话", files=2)
    got = resolve_session_dir(root, "chat-1", "季度报告", today=TODAY)
    assert got.parent == root / MONTH


def test_new_dir_is_not_created_eagerly(root):
    """纯计算：解析本身不建目录（建目录由写文件时 mkdir 负责）。"""
    got = resolve_session_dir(root, "chat-1", "季度报告", today=TODAY)
    assert got == root / MONTH / "2026-10-22_季度报告"
    assert not got.exists()
    assert not (root / MONTH).exists()


# ── 深度保护 ────────────────────────────────────────────────────────


def test_flatten_keeps_reasonable_depth():
    assert flatten_rel_path(Path("a/b/x.md")) == Path("a/b/x.md")


def test_flatten_collapses_deep_paths():
    assert flatten_rel_path(Path("a/b/c/d/e/x.md")) == Path("x.md")
    assert flatten_rel_path(Path("./x.md")) == Path("x.md")


# ── 标题解析（走 ChatManager，失败必须降级） ───────────────────────


async def test_session_write_dir_uses_chat_title(root, monkeypatch):
    class _Chat:
        name = "OA 报销流程"

    class _CM:
        async def get_chat(self, chat_id):
            return _Chat()

    class _Mgr:
        def get_user_chat_manager(self, username):
            return _CM()

    import coapis.app.multi_agent_manager as mam

    monkeypatch.setattr(mam, "get_multi_agent_manager", lambda: _Mgr())
    from coapis.agents.context import session_dir as sd

    sd._TITLE_CACHE.clear()
    got = await session_write_dir(root, "chat-9", "alice", today=TODAY)
    assert got == root / MONTH / "2026-10-22_OA 报销流程"
    sd._TITLE_CACHE.clear()


async def test_session_write_dir_degrades_on_manager_failure(root, monkeypatch):
    import coapis.app.multi_agent_manager as mam

    def _boom():
        raise RuntimeError("manager 未就绪")

    monkeypatch.setattr(mam, "get_multi_agent_manager", _boom)
    from coapis.agents.context import session_dir as sd

    sd._TITLE_CACHE.clear()
    got = await session_write_dir(root, "chat-9", "alice", today=TODAY)
    # 标题解析失败 → 纯日期目录，写文件不能被阻断
    assert got == root / MONTH / "2026-10-22"
    sd._TITLE_CACHE.clear()


async def test_session_write_dir_without_chat_is_flat(root):
    got = await session_write_dir(root, None, "alice", today=TODAY)
    assert got == root / MONTH


# ── 空目录巡检（只报告不删） ───────────────────────────────────────


def test_sweep_reports_empty_session_dirs(root):
    _mk(root, "2026-10-20_有内容", files=1)
    empty = _mk(root, "2026-10-20_空壳")
    # 制造"昨天建的"（mtime 在今天之前）
    from datetime import datetime as _dt

    stamp = _dt(TODAY.year, TODAY.month, TODAY.day).timestamp() - 3600
    import os as _os
    _os.utime(empty, (stamp, stamp))
    _os.utime(root / MONTH / "2026-10-20_有内容", (stamp, stamp))
    got = sweep_empty_session_dirs(root, today=TODAY)
    assert got == [empty]
    # 只报告：目录仍在
    assert empty.is_dir()


def test_sweep_ignores_today_and_plain_dirs(root):
    _mk(root, "2026-10-22_刚建")          # 今天建的 → 不报
    _mk(root, "手工目录")                  # 用户自建目录 → 不碰
    assert sweep_empty_session_dirs(root, today=TODAY) == []


def test_sweep_report_survives_missing_root(tmp_path, monkeypatch):
    import coapis.constant as const

    monkeypatch.setattr(const, "WORKSPACES_DIR", tmp_path / "nope")
    out = sweep_report()
    assert out["total"] == 0
