# -*- coding: utf-8 -*-
"""file_io 路径解析语义测试（基础能力回归护栏）。

对应 2026-10-15 故障定位（tech_docs/文档解析基础能力故障定位-2026-10-15.md）：
智能体拿到的是虚拟/裸文件名路径，解析根必须是「当前会话工作区」（目录引用
优先），绝不能落到进程 CWD —— 否则文件写到了没人看得见的地方，读也读不到。

2026-10-22 起目录由系统规划（tech_docs/我的空间目录规划_方案与实施计划_20261022.md）：
相对路径落在 ``<workspace>/files/{YYYY-MM}/``（无会话身份时月层平铺），
会话身份存在时落 ``files/{YYYY-MM}/{YYYY-MM-DD}_{任务}/``。

覆盖：
- 相对路径 → ``<workspace>/files/{月}/``（读写一致）
- 目录引用激活 → 读写都落在被引用目录内（系统不重排用户选的目录）
- 绝对路径 → 原样使用
- 进程 CWD 不参与解析（核心护栏）
- append_file / edit_file 与 write_file 同根
- memory/ 前缀不重排（系统目录）
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from coapis.agents.tools import file_io as fi
from coapis.config.context import (
    set_current_folder_ref,
    set_current_workspace_dir,
)

MONTH = date.today().strftime("%Y-%m")


def _text(resp) -> str:
    """ToolResponse -> plain text."""
    blocks = getattr(resp, "content", None) or []
    out = []
    for b in blocks:
        if isinstance(b, dict):
            out.append(b.get("text", ""))
        else:
            out.append(getattr(b, "text", ""))
    return "\n".join(out)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    """会话工作区（含 files/ 目录），并保证进程 CWD 在工作区之外。"""
    (tmp_path / "files").mkdir()
    cwd = tmp_path.parent / "proc-cwd"
    cwd.mkdir(exist_ok=True)
    monkeypatch.chdir(cwd)
    set_current_workspace_dir(tmp_path)
    set_current_folder_ref(None)
    yield tmp_path
    set_current_workspace_dir(None)
    set_current_folder_ref(None)


# ── 解析函数层 ──────────────────────────────────────────────────────


def test_relative_read_resolves_under_workspace_files(ws):
    got = fi._resolve_file_path("report.txt")
    assert got == str(ws / "files" / "report.txt")


async def test_relative_write_resolves_under_month_dir(ws):
    got = await fi._resolve_write_path("report.txt")
    assert got == str(ws / "files" / MONTH / "report.txt")
    assert (ws / "files" / MONTH).is_dir()


async def test_nested_relative_keeps_subpath(ws):
    got = await fi._resolve_write_path(os.path.join("sub", "a.md"))
    assert got == str(ws / "files" / MONTH / "sub" / "a.md")


async def test_files_prefix_is_not_doubled(ws):
    """模型爱把读取用的 files/ 前缀抄回来，不能变成 files/files/。"""
    got = await fi._resolve_write_path(os.path.join("files", "notes.md"))
    assert got == str(ws / "files" / MONTH / "notes.md")
    assert "files/files" not in got


async def test_memory_prefix_is_not_relocated(ws):
    """memory/ 是系统目录（每日笔记），不套会话目录。"""
    got = await fi._resolve_write_path(os.path.join("memory", "2026-10-22.md"))
    assert got == str(ws / "memory" / "2026-10-22.md")


async def test_absolute_path_used_as_is(ws):
    abs_path = str(ws / "files" / "abs.txt")
    assert fi._resolve_file_path(abs_path) == abs_path
    assert await fi._resolve_write_path(abs_path) == abs_path


async def test_folder_ref_takes_priority_for_read_and_write(ws):
    ref = ws / "files" / "project"
    ref.mkdir(parents=True)
    set_current_folder_ref(ref)
    try:
        assert fi._resolve_file_path("x.md") == str(ref / "x.md")
        assert await fi._resolve_write_path("x.md") == str(ref / "x.md")
    finally:
        set_current_folder_ref(None)


async def test_resolution_never_uses_process_cwd(ws):
    """核心护栏：CWD 在工作区之外，解析结果不得包含 CWD。"""
    cwd = Path(os.getcwd())
    assert not str(ws).startswith(str(cwd))
    for resolved in (
        fi._resolve_file_path("a.txt"),
        await fi._resolve_write_path("a.txt"),
    ):
        assert not str(resolved).startswith(str(cwd)), f"落到 CWD: {resolved}"
        assert str(resolved).startswith(str(ws))


# ── 工具层（端到端，含 CWD 干扰） ──────────────────────────────────


async def test_write_then_read_roundtrip_with_bare_name(ws):
    w = await fi.write_file(file_path="季度报告.md", content="# 营收 1250 万")
    assert "Wrote" in _text(w)
    target = ws / "files" / MONTH / "季度报告.md"
    assert target.is_file(), "写入未落在 <workspace>/files/{月}/"
    assert not (Path(os.getcwd()) / "季度报告.md").exists(), "文件泄漏到 CWD"

    r = await fi.read_file(file_path=target.relative_to(ws).as_posix())
    assert "1250" in _text(r)


async def test_append_uses_same_root_as_write(ws):
    await fi.write_file(file_path="log.txt", content="第一行\n")
    a = await fi.append_file(file_path="log.txt", content="第二行\n")
    assert "Appended" in _text(a)
    lines = (
        (ws / "files" / MONTH / "log.txt")
        .read_text(encoding="utf-8-sig")
        .splitlines()
    )
    assert lines == ["第一行", "第二行"]


async def test_edit_uses_same_root_as_write(ws):
    await fi.write_file(file_path="cfg.txt", content="debug=false")
    e = await fi.edit_file(
        file_path="cfg.txt",
        old_text="debug=false",
        new_text="debug=true",
    )
    assert "replaced" in _text(e)
    assert (
        (ws / "files" / MONTH / "cfg.txt").read_text(encoding="utf-8-sig")
        == "debug=true"
    )


async def test_missing_file_reports_resolved_workspace_path(ws):
    r = await fi.read_file(file_path="不存在.txt")
    text = _text(r)
    assert "does not exist" in text
    # 报错里给出的是解析后的绝对路径，智能体才能据此纠正路径
    assert str(ws / "files" / "不存在.txt") in text


async def test_folder_ref_write_is_readable_by_bare_name(ws):
    """目录引用激活时，写了必须能读回来（读写同根）。"""
    ref = ws / "files" / "docs"
    set_current_folder_ref(ref)
    try:
        w = await fi.write_file(file_path="说明.md", content="内容 A")
        assert "Wrote" in _text(w)
        assert (ref / "说明.md").is_file()
        r = await fi.read_file(file_path="说明.md")
        assert "内容 A" in _text(r)
    finally:
        set_current_folder_ref(None)
