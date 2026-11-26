"""技能触发闭环账本完整性契约测试（2026-11-26）。

背景（实测证据，dev 数据卷 47 天）：
- ``TriggerTracker._active`` 只增不减，``react_agent._acting`` 每次工具调用
  都对 ``get_active_trigger_ids()`` 返回的**全部历史** trigger 各记一遍结局
  → 230 条 trigger 被写成 2165 条结局，平均 9.4 倍、单条最多 140 次。
- ``skill_tool_used`` 硬编码 True、``user_followed_up`` 硬编码 False。
- 学习层 ``ks.hits += 1`` 无条件、``satisfied`` 用 ``not user_followed_up``
  代理 → 两者恒等于 total → 满意度恒 1.0 → 权重只增不减，70 个关键词里
  68 个（97.1%）被顶到 MAX_WEIGHT 钉死，等于彻底学不动。
- ``runner.py`` 调的 ``get_session_trigger_events()`` /
  ``get_session_trigger_outcomes()`` 在 ``TriggerTracker`` 里不存在，
  AttributeError 被 ``except Exception: pass`` 吞掉，进化引擎从未拿到数据。

这些测试锁死上述四点，防止回归。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coapis.agents.utils.trigger_effectiveness import TriggerEffectivenessTracker
from coapis.agents.utils.trigger_tracker import TriggerTracker


def _outcome_rows(log_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for p in sorted(log_dir.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("event") == "trigger_outcome":
                rows.append(d)
    return rows


@pytest.fixture()
def tracker(tmp_path: Path) -> TriggerTracker:
    return TriggerTracker(log_dir=tmp_path)


def test_one_outcome_row_per_trigger_per_turn(tracker: TriggerTracker, tmp_path: Path):
    """核心反证：一轮内无论调用多少次结局接口，只落一行。

    旧实现会落 N 行（N = 工具调用次数），这是 9.4 倍重复落账的直接来源。
    """
    tid = tracker.create_event(
        skill_name="xlsx",
        trigger_method="keyword",
        matched_keywords=["表格"],
        session_id="sess-1",
        user="alice",
        agent="default",
    )
    # 模拟一轮里 5 次工具调用
    for i in range(5):
        tracker.record_trigger_outcome(
            trigger_id=tid,
            tools_used=[f"tool_{i}"],
            tool_success=True,
            duration_ms=100.0,
        )
    tracker.settle_turn()

    rows = _outcome_rows(tmp_path)
    assert len(rows) == 1, f"期望 1 行结局，实际 {len(rows)} 行（重复落账回归）"
    row = rows[0]
    # 聚合语义：工具名去重合并、耗时累加、调用次数记录
    assert sorted(row["tools_used"]) == sorted(f"tool_{i}" for i in range(5))
    assert row["tool_calls"] == 5
    assert row["duration_ms"] == pytest.approx(500.0)
    # 归因链必须非空
    assert row["session_id"] == "sess-1"
    assert row["user"] == "alice"


def test_active_scope_reset_between_turns(tracker: TriggerTracker, tmp_path: Path):
    """上一轮的 trigger 不得在下一轮被再次记结局（跨轮污染）。"""
    tid1 = tracker.create_event(
        skill_name="skill-a", trigger_method="keyword", matched_keywords=["a"],
    )
    tracker.settle_turn()

    # 第二轮：只登记 skill-b
    tracker.begin_turn()
    tid2 = tracker.create_event(
        skill_name="skill-b", trigger_method="keyword", matched_keywords=["b"],
    )
    # 即便有人误用上一轮的 trigger_id 记结局，也不应产生新行
    tracker.record_trigger_outcome(trigger_id=tid1, tools_used=["x"])
    tracker.record_trigger_outcome(trigger_id=tid2, tools_used=["y"])
    tracker.settle_turn()

    rows = _outcome_rows(tmp_path)
    assert len(rows) == 2, "两轮各一行，不应有第三条"
    assert {r["skill_name"] for r in rows} == {"skill-a", "skill-b"}
    assert rows[1]["trigger_id"] == tid2


def test_skill_tool_used_not_hardcoded(tracker: TriggerTracker, tmp_path: Path):
    """本轮没动工具时，skill_tool_used 必须是 False，不能恒真。"""
    tracker.create_event(
        skill_name="no-tool-skill", trigger_method="keyword", matched_keywords=["k"],
    )
    tracker.settle_turn()

    rows = _outcome_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["skill_tool_used"] is False, "skill_tool_used 被硬编码回 True"
    assert rows[0]["tools_used"] == []


def test_user_followed_up_unknown_is_none_not_false(tracker: TriggerTracker, tmp_path: Path):
    """未采集的字段必须写 None，不能写 False（False 在学习层等于「满意」）。"""
    tracker.create_event(
        skill_name="s", trigger_method="keyword", matched_keywords=["k"],
    )
    tracker.settle_turn()
    rows = _outcome_rows(tmp_path)
    assert rows[0]["user_followed_up"] is None


def test_settle_turn_returns_only_this_turn(tmp_path: Path):
    """轮末结算只返回本轮数据，不能把进程累计值全交出去。"""
    t1 = TriggerTracker(log_dir=tmp_path)
    t1.create_event(skill_name="a", trigger_method="keyword", matched_keywords=["a"])
    t1.record_trigger_outcome(trigger_id=list(t1._active)[0], tools_used=["t"])
    ev1, oc1 = t1.settle_turn()
    assert len(oc1) == 1

    # 同一实例再开一轮，只应拿到第二轮
    t1.begin_turn()
    t1.create_event(skill_name="b", trigger_method="keyword", matched_keywords=["b"])
    t1.record_trigger_outcome(trigger_id=list(t1._active)[0], tools_used=["t"])
    ev2, oc2 = t1.settle_turn()
    assert len(oc2) == 1, "settle_turn 泄漏了历史累计结局"
    assert oc2[0].skill_name == "b"


def test_effectiveness_counters_are_not_identity():
    """反「恒等式」：hits / satisfied 不得无条件等于 total。"""
    eff = TriggerEffectivenessTracker()
    eff._save = lambda: None  # 不落盘，只验内存语义

    # 场景一：触发了但没动工具 → total+1，hits 不涨
    eff.record_outcome(
        skill_name="s", matched_keywords=["kw"], tool_success=True,
        user_followed_up=None, skill_tool_used=False,
    )
    ks = eff._stats["s"].keywords["kw"]
    assert ks.total == 1
    assert ks.hits == 0, "hits 又变成无条件累加了"

    # 场景二：动了工具且成功 → hits / satisfied 才涨
    eff.record_outcome(
        skill_name="s", matched_keywords=["kw"], tool_success=True,
        user_followed_up=None, skill_tool_used=True,
    )
    assert ks.total == 2
    assert ks.hits == 1
    assert ks.satisfied == 1

    # 场景三：工具失败 → 不算满意
    eff.record_outcome(
        skill_name="s", matched_keywords=["kw"], tool_success=False,
        user_followed_up=None, skill_tool_used=True,
    )
    assert ks.satisfied == 1, "工具失败仍被记成满意"
    assert ks.satisfied < ks.total, "satisfied 恒等于 total 的旧病复发"


def test_max_weight_ratchet_is_bounded():
    """权重上限必须收敛在 1.2，不能钉死在 1.5。"""
    eff = TriggerEffectivenessTracker()
    assert eff.MAX_WEIGHT == pytest.approx(1.2)
    assert eff.MIN_SAMPLES_FOR_ADJUSTMENT >= 10


def test_ghost_methods_gone_and_settle_turn_exists():
    """runner 的调用目标必须真实存在，幽灵方法不得复活。"""
    from coapis.agents.utils.trigger_tracker import TriggerTracker as TT

    assert hasattr(TT, "settle_turn")
    for ghost in ("get_session_trigger_events", "get_session_trigger_outcomes"):
        assert not hasattr(TT, ghost), f"幽灵方法 {ghost} 仍存在，runner 调用会静默失败"
