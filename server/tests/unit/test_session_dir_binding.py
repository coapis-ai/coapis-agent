"""会话目录绑定 + 系统目录/临时区路由（目录规划复核后的补修）。

覆盖复核认定的三个偏移：
  P0-1 跨会话共用目录 —— 目录与会话一一绑定，同一天两个会话各用各的
  P0-2 系统/治理目录混进会话目录 —— 落工作区根
  P1-2 .temp 落会话目录 —— 固定 files/.temp（清理规则只认这个路径）
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from coapis.agents.context.session_dir import (
    BINDING_FILE,
    MIN_NEW_FILES,
    bind_session_dir,
    find_loose_file,
    load_bindings,
    lookup_bound_dir,
    resolve_session_dir,
    scratch_dir_target,
    session_dir_rel,
    system_dir_target,
)

TODAY = date(2026, 10, 22)


# ── 会话目录绑定 ──────────────────────────────────────────────────


def test_two_chats_same_day_get_separate_dirs(tmp_path: Path) -> None:
    """P0 回归：同一天两个会话必须各用各的目录。

    旧实现扫"当天最新的会话目录"复用，chat-B 的产出会写进 chat-A 的目录。
    """
    files = tmp_path / "files"
    a = resolve_session_dir(files, "chat-A", "任务A", today=TODAY)
    a.mkdir(parents=True, exist_ok=True)
    (a / "a.md").write_text("A 的产出", encoding="utf-8")
    bind_session_dir(files, "chat-A", a, "任务A", TODAY)

    bound_b = lookup_bound_dir(files, "chat-B")
    b = resolve_session_dir(files, "chat-B", "任务B", today=TODAY, bound=bound_b)
    assert b.name == "2026-10-22_任务B"
    assert b != a


def test_bound_dir_wins_over_title_change(tmp_path: Path) -> None:
    """目录名是快照：会话改名后仍写进原目录，历史直链不 404。"""
    files = tmp_path / "files"
    d = resolve_session_dir(files, "chat-1", "季度报告", today=TODAY)
    d.mkdir(parents=True, exist_ok=True)
    bind_session_dir(files, "chat-1", d, "季度报告", TODAY)

    bound = lookup_bound_dir(files, "chat-1")
    assert bound == d
    again = resolve_session_dir(
        files,
        "chat-1",
        "改成了别的名字",
        today=TODAY,
        bound=bound,
    )
    assert again == d
    assert again.name == "2026-10-22_季度报告"


def test_same_title_two_chats_do_not_collide(tmp_path: Path) -> None:
    """两个会话标题相同 → 加序号，绝不共用目录。

    "新聊天" 是垃圾标题（D-3）→ 目录降级为纯日期目录，同日两个会话靠
    `-2` 后缀分开，共用目录这条老路被彻底堵死。
    """
    files = tmp_path / "files"
    a = resolve_session_dir(files, "chat-A", "新聊天", today=TODAY)
    a.mkdir(parents=True, exist_ok=True)
    bind_session_dir(files, "chat-A", a, "新聊天", TODAY)

    b = resolve_session_dir(files, "chat-B", "新聊天", today=TODAY, bound=None)
    assert b.name == "2026-10-22-2"
    assert b != a


def test_real_title_collision_gets_suffix(tmp_path: Path) -> None:
    """真标题重名（两个会话都叫"季度报告"）→ 第二个加 `-2`。"""
    files = tmp_path / "files"
    a = resolve_session_dir(files, "chat-A", "季度报告", today=TODAY)
    a.mkdir(parents=True, exist_ok=True)
    bind_session_dir(files, "chat-A", a, "季度报告", TODAY)

    b = resolve_session_dir(files, "chat-B", "季度报告", today=TODAY, bound=None)
    assert b.name == "2026-10-22_季度报告-2"
    assert b != a


def test_binding_dropped_when_dir_deleted(tmp_path: Path) -> None:
    """目录被删 → 绑定作废，下次写入重建，不会指向不存在的目录。"""
    files = tmp_path / "files"
    d = resolve_session_dir(files, "chat-1", "季度报告", today=TODAY)
    d.mkdir(parents=True, exist_ok=True)
    bind_session_dir(files, "chat-1", d, "季度报告", TODAY)
    assert lookup_bound_dir(files, "chat-1") == d

    shutil.rmtree(d)
    assert lookup_bound_dir(files, "chat-1") is None
    assert "chat-1" not in load_bindings(files)


def test_binding_survives_corrupt_file(tmp_path: Path) -> None:
    """绑定表损坏当空表：解析目录绝不能抛异常。"""
    files = tmp_path / "files"
    files.mkdir(parents=True)
    (files / BINDING_FILE).write_text("{ 这不是 json", encoding="utf-8")
    assert load_bindings(files) == {}
    assert lookup_bound_dir(files, "chat-1") is None
    out = resolve_session_dir(files, "chat-1", "季度报告", today=TODAY)
    assert out.name == "2026-10-22_季度报告"


def test_binding_file_is_not_a_session_dir(tmp_path: Path) -> None:
    """绑定表落在 files 根，不能被当成会话目录。"""
    from coapis.agents.context.session_dir import is_session_dir

    files = tmp_path / "files"
    d = resolve_session_dir(files, "chat-1", "季度报告", today=TODAY)
    d.mkdir(parents=True, exist_ok=True)
    bind_session_dir(files, "chat-1", d, "季度报告", TODAY)
    assert (files / BINDING_FILE).is_file()
    assert not is_session_dir(BINDING_FILE)


def test_day_layer_is_reused_for_same_day(tmp_path: Path) -> None:
    """日期层建好后，当天后续写入继续进当天层，不回落到会话目录根。"""
    files = tmp_path / "files"
    d = files / "2026-09" / "2026-09-30_季度报告"
    d.mkdir(parents=True)
    for i in range(MIN_NEW_FILES):
        (d / f"f{i}.md").write_text("x", encoding="utf-8")
    bind_session_dir(files, "chat-1", d, "季度报告", TODAY)

    bound = lookup_bound_dir(files, "chat-1")
    layer = resolve_session_dir(files, "chat-1", "季度报告", today=TODAY, bound=bound)
    assert layer == d / "2026-10-22_季度报告"
    layer.mkdir(parents=True, exist_ok=True)
    again = resolve_session_dir(files, "chat-1", "季度报告", today=TODAY, bound=bound)
    assert again == layer


def test_legacy_dir_adopted_when_unbound(tmp_path: Path) -> None:
    """绑定表启用前遗留的同名目录被采纳，不重复建目录。"""
    files = tmp_path / "files"
    legacy = files / "2026-10" / "2026-10-20_季度报告"
    legacy.mkdir(parents=True)
    (legacy / "old.md").write_text("x", encoding="utf-8")

    out = resolve_session_dir(files, "chat-1", "季度报告", today=TODAY)
    assert out == legacy


def test_bound_legacy_dir_is_not_stolen(tmp_path: Path) -> None:
    """已绑定给别人的目录绝不采纳 —— 那是别人的会话。"""
    files = tmp_path / "files"
    legacy = files / "2026-10" / "2026-10-20_季度报告"
    legacy.mkdir(parents=True)
    bind_session_dir(files, "chat-OWNER", legacy, "季度报告", date(2026, 10, 20))

    out = resolve_session_dir(files, "chat-NEW", "季度报告", today=TODAY)
    assert out != legacy
    assert out.name == "2026-10-22_季度报告"


# ── 系统目录 / 临时区 ─────────────────────────────────────────────


def test_system_dir_routes_to_workspace_root(tmp_path: Path) -> None:
    """P0 回归：治理/技能/会话状态等系统目录落工作区根，不进 files/。"""
    ws = tmp_path / "ws"
    for name in (
        "tool_results",
        "_tool_results_cache",
        "tool_results_cache",
        "skills",
        "sessions",
        "memory",
        "uploads",
        ".trash",
    ):
        got = system_dir_target(Path(f"{name}/a.txt"), ws)
        assert got == ws / name / "a.txt", name
    assert system_dir_target(Path("季度报告/a.md"), ws) is None
    assert system_dir_target(Path("a.md"), ws) is None


def test_scratch_dir_routes_to_files_temp(tmp_path: Path) -> None:
    """P1 回归：.temp 固定落 files/.temp —— 清理规则只认这个路径。"""
    files = tmp_path / "ws" / "files"
    assert scratch_dir_target(Path(".temp/x.py"), files) == files / ".temp" / "x.py"
    assert (
        scratch_dir_target(Path(".temp/sub/x.pdf"), files)
        == files / ".temp" / "sub" / "x.pdf"
    )
    assert scratch_dir_target(Path("x.py"), files) is None


# ── 会话目录入口 + 裸文件名读回（D-8/4d、读写口径对称）────────────────
def test_session_dir_rel_only_reads_binding(tmp_path: Path) -> None:
    """入口端点用的口径：没绑定就没有目录，且**不创建**目录。"""
    files = tmp_path / "files"
    files.mkdir()
    assert session_dir_rel(files, None) is None
    assert session_dir_rel(files, "chat-A") is None

    d = resolve_session_dir(files, "chat-A", "季度报告", today=TODAY)
    d.mkdir(parents=True)
    bind_session_dir(files, "chat-A", d, "季度报告", TODAY)
    assert session_dir_rel(files, "chat-A") == "2026-10/2026-10-22_季度报告"
    # 只读：别人的 chat_id 查不到，也不会顺手建目录
    assert session_dir_rel(files, "chat-ZZZ") is None
    assert not (files / "2026-10" / "2026-10-22_chat-ZZZ").exists()


def test_find_loose_file_prefers_bound_session_dir(tmp_path: Path) -> None:
    """写侧把裸文件名重排进会话目录，读侧按 会话目录→当月→根 兜底。"""
    files = tmp_path / "files"
    d = resolve_session_dir(files, "chat-A", "季度报告", today=TODAY)
    d.mkdir(parents=True)
    bind_session_dir(files, "chat-A", d, "季度报告", TODAY)
    (d / "报告.md").write_text("会话目录里的", encoding="utf-8")
    (files / "2026-10").mkdir(exist_ok=True)
    (files / "2026-10" / "报告.md").write_text("当月层", encoding="utf-8")
    (files / "报告.md").write_text("根", encoding="utf-8")

    assert find_loose_file(files, "报告.md", chat_id="chat-A") == d / "报告.md"
    # 没有会话身份 → 退到当月层
    assert find_loose_file(files, "报告.md") == files / "2026-10" / "报告.md"
    # 日期层里也要能找到
    day = d / "2026-10-23"
    day.mkdir()
    (day / "尾巴.md").write_text("x", encoding="utf-8")
    assert find_loose_file(files, "尾巴.md", chat_id="chat-A") == day / "尾巴.md"
    # 找不到返回 None（读侧照原路径报"文件不存在"）
    assert find_loose_file(files, "没有这个文件.md", chat_id="chat-A") is None
    # 带路径的一律不兜底：那是显式路径，语义不能改
    assert find_loose_file(files, "a/报告.md", chat_id="chat-A") is None
