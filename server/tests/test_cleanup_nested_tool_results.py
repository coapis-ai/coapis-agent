# -*- coding: utf-8 -*-
"""夜间清理必须覆盖子智能体的 tool_results 缓存 —— 防止"只扫一层"复发。

根因（2026-11-22 dev 实锤）：``_cleanup_callback`` 按用户目录构造
``CleanupEngine(workspace_dir=workspaces/<user>)``，而
``_resolve_tool_results_dir`` 只看 ``<workspace>/tool_results``。
子智能体的根却在 ``workspaces/<user>/agents/<agent_id>/``
（``workspace.py:185``），其上下文管理器按该根派生 ``tool_results_cache``，
于是每个子智能体的缓存目录都在扫描范围之外。

后果是"看起来一切正常"：夜间任务每天都报
``Scheduled cleanup completed``、每天 ``Cleaned N tool results``，
而 ``workspaces/admin/agents/user_a1af93/tool_results`` 里 13 个 8 月的
卸载文件躺了三个月无人问津。日志绿≠扫到了，所以这里锁的是覆盖面本身。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from coapis.app.cleanup import CleanupEngine

DAYS = 24 * 3600
HOT_DAYS = 3


def _make_file(path: Path, age_days: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * 128, encoding="utf-8")
    ts = time.time() - age_days * DAYS
    os.utime(path, (ts, ts))


@pytest.fixture()
def engine(tmp_path: Path) -> CleanupEngine:
    # 显式传 rules，避免 _load_rules 去连 history.db
    return CleanupEngine(
        workspace_dir=tmp_path,
        rules={"tool_results": {"hot_days": HOT_DAYS}},
    )


def test_single_ruler_lists_nested_agent_caches(
    tmp_path: Path, engine: CleanupEngine
) -> None:
    """单一实现必须把子智能体（含二级）缓存目录列进来。"""
    _make_file(tmp_path / "tool_results" / "a.txt", age_days=1)
    _make_file(tmp_path / "agents" / "sub_a" / "tool_results" / "b.txt", 1)
    _make_file(
        tmp_path / "agents" / "sub_a" / "agents" / "sub_b" / "tool_results" / "c.txt",
        1,
    )

    dirs = [Path(d).resolve() for d in engine._tool_result_dirs()]
    assert len(dirs) == len(set(dirs)), "同一目录被重复扫会重复计数"
    for rel in (
        "tool_results",
        "agents/sub_a/tool_results",
        "agents/sub_a/agents/sub_b/tool_results",
    ):
        assert (tmp_path / rel).resolve() in dirs, "清扫尺子漏掉 %s" % rel


def test_stale_files_removed_across_all_cache_dirs(
    tmp_path: Path, engine: CleanupEngine
) -> None:
    """超期文件在主目录和各级子智能体目录都要被删，未超期的必须留着。"""
    _make_file(tmp_path / "tool_results" / "primary_old.txt", age_days=10)
    _make_file(tmp_path / "tool_results" / "primary_new.txt", age_days=1)
    _make_file(
        tmp_path / "agents" / "sub_a" / "tool_results" / "nested_old.txt",
        age_days=10,
    )
    _make_file(
        tmp_path / "agents" / "sub_a" / "tool_results" / "nested_new.txt",
        age_days=1,
    )

    stats = engine.cleanup_tool_results()

    assert stats.items_deleted == 2, (
        "只清了主目录（%d）——子智能体缓存又脱离清扫了" % stats.items_deleted
    )
    assert stats.bytes_freed > 0
    assert not (tmp_path / "tool_results" / "primary_old.txt").exists()
    assert not (
        tmp_path / "agents" / "sub_a" / "tool_results" / "nested_old.txt"
    ).exists()
    assert (tmp_path / "tool_results" / "primary_new.txt").exists()
    assert (tmp_path / "agents" / "sub_a" / "tool_results" / "nested_new.txt").exists()


def test_missing_primary_dir_does_not_skip_nested(tmp_path: Path) -> None:
    """主目录不存在时（用户从未在主工作区跑过工具）也要扫子目录。"""
    _make_file(
        tmp_path / "agents" / "sub_a" / "tool_results" / "nested_old.txt",
        age_days=10,
    )
    eng = CleanupEngine(
        workspace_dir=tmp_path,
        rules={"tool_results": {"hot_days": HOT_DAYS}},
    )
    assert not (tmp_path / "tool_results").exists()

    stats = eng.cleanup_tool_results()

    assert stats.items_deleted == 1
    assert not (
        tmp_path / "agents" / "sub_a" / "tool_results" / "nested_old.txt"
    ).exists()


def test_broken_cache_dir_does_not_abort_the_sweep(
    tmp_path: Path, engine: CleanupEngine
) -> None:
    """单个文件删不掉不应中断整轮清扫，也不该把整轮统计清零。"""
    _make_file(tmp_path / "agents" / "sub_a" / "tool_results" / "old1.txt", 10)
    _make_file(tmp_path / "agents" / "sub_a" / "tool_results" / "old2.txt", 10)
    victim = tmp_path / "agents" / "sub_a" / "tool_results" / "old1.txt"

    real_unlink = Path.unlink

    def _flaky(self, *a, **kw):
        if self == victim:
            raise PermissionError("simulated")
        return real_unlink(self, *a, **kw)

    Path.unlink = _flaky  # type: ignore[method-assign]
    try:
        stats = engine.cleanup_tool_results()
    finally:
        Path.unlink = real_unlink  # type: ignore[method-assign]

    assert stats.items_deleted == 1, "一个文件失败不该吃掉整轮结果"
    assert victim.exists()
