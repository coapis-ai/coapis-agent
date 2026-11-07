# -*- coding: utf-8 -*-
"""台账写入契约单测（v14 §批次1 · 验收「新增契约层单测 ≥25 条」）。

覆盖四类必测：档位归一 / 身份补全 / 0 语义 / 迟到回填。
全部离线：总线与数据库都打桩——契约层的价值就在于**不碰库也能验证形状**。
"""
# pylint: disable=protected-access
from __future__ import annotations

import pytest

from coapis.decision import ledger_contract as lc


# ── 1. 档位归一（complexity 列只能是判则词表；脏值进 dirty_band 不销毁证据）──


@pytest.mark.parametrize("raw", ["simple", "medium", "complex"])
def test_band_legal_passes_through(raw):
    assert lc.normalize_band(raw) == (raw, "")


def test_band_case_and_space_normalized():
    assert lc.normalize_band("  COMPLEX  ") == ("complex", "")
    assert lc.normalize_band("Medium") == ("medium", "")


def test_band_empty_is_legal_empty():
    # 空档位是合法状态（非判岗行没有档位），不算脏
    assert lc.normalize_band("") == ("", "")
    assert lc.normalize_band(None) == ("", "")


def test_band_job_name_is_dirty():
    # 岗位名当档位写进来（v14 根因 A-1 的实测脏值）
    band, dirty = lc.normalize_band("plan_gate")
    assert band == ""
    assert dirty == "plan_gate"


def test_band_selector_literal_is_dirty():
    band, dirty = lc.normalize_band("select:low,medium")
    assert band == ""
    assert dirty == "select:low,medium"


def test_band_dirty_keeps_original_truncated():
    _band, dirty = lc.normalize_band("x" * 300)
    assert len(dirty) == 120  # 留痕不销毁证据，也不撑爆列


def test_band_whitelist_is_the_rubric_vocab():
    # 词表与判则同源：契约层不许自带小词表
    from coapis.decision.rubric import LEVELS

    assert set(lc._LEVELS) == set(LEVELS)
    assert set(lc._LEVELS) == {"simple", "medium", "complex"}  # 三档口径（拍板 D1）


def test_sources_enum_covers_five_posts():
    assert {"plan_gate", "skill_trigger", "tool_gate", "acceptance", "advisor"} <= set(lc.SOURCES)


# ── 2. 身份补全（scope → ContextVar → session 兜底；turn 缺 → 进程内计数）────


def test_ids_scope_does_not_invent_session_id(monkeypatch):
    """scope 没有 session_id 时不编造：身份只能来自 ContextVar（批次2 接线点）。"""
    from coapis.config import session_context as sc

    for fn in ("get_current_chat_id", "get_current_session_id", "get_current_user_id", "get_current_agent_id"):
        monkeypatch.setattr(sc, fn, lambda: "", raising=False)
    scope = {
        "user_id": "u1",
        "agent_id": "a1",
        "chat_id": "c1",
        "turn": 7,
    }
    assert lc.resolve_ids(scope) == ("u1", "a1", "", "c1", 7)


def test_ids_missing_scope_defaults_empty(monkeypatch):
    from coapis.config import session_context as sc

    for fn in ("get_current_chat_id", "get_current_session_id", "get_current_user_id", "get_current_agent_id"):
        monkeypatch.setattr(sc, fn, lambda: "", raising=False)
    uid, aid, sid, cid, turn = lc.resolve_ids({})
    assert (uid, aid, sid, cid) == ("", "", "", "")
    assert turn == 0  # 无 chat_id 时轮次无意义


def test_ids_fall_back_to_contextvar(monkeypatch):
    from coapis.config import session_context as sc

    monkeypatch.setattr(sc, "get_current_chat_id", lambda: "ctx-chat", raising=False)
    monkeypatch.setattr(sc, "get_current_session_id", lambda: "ctx-sess", raising=False)
    monkeypatch.setattr(sc, "get_current_user_id", lambda: "ctx-user", raising=False)
    monkeypatch.setattr(sc, "get_current_agent_id", lambda: "ctx-agent", raising=False)
    _uid, _aid, sid, cid, turn = lc.resolve_ids({"turn": 3})
    assert cid == "ctx-chat"
    assert sid == "ctx-sess"
    assert turn == 3


def test_ids_chat_id_falls_back_to_session_id(monkeypatch):
    from coapis.config import session_context as sc

    for fn in ("get_current_chat_id", "get_current_user_id", "get_current_agent_id"):
        monkeypatch.setattr(sc, fn, lambda: "", raising=False)
    monkeypatch.setattr(sc, "get_current_session_id", lambda: "sess-only", raising=False)
    _uid, _aid, _sid, cid, _turn = lc.resolve_ids({})
    assert cid == "sess-only"  # 兜底归集键（批次2 兜底条款）


def test_turn_counter_increments_per_chat(monkeypatch):
    monkeypatch.setitem(lc._turn_counts, "chat-x", 0)
    assert lc.next_turn("chat-x") == 1
    assert lc.next_turn("chat-x") == 2
    assert lc.next_turn("chat-y") == 1


def test_turn_zero_when_chat_missing():
    assert lc.next_turn("") == 0


def test_turn_non_numeric_becomes_zero():
    scope = {"chat_id": "c", "session_id": "c", "turn": "abc"}
    assert lc.resolve_ids(scope)[4] == 0


def test_turn_string_number_is_accepted():
    scope = {"chat_id": "c", "session_id": "c", "turn": "9"}
    assert lc.resolve_ids(scope)[4] == 9


# ── 3. 0 语义（cost/tokens 为 0 必须说清为什么）──────────────────────────


def _capture_emit(monkeypatch):
    """打桩总线与治理列，取回契约层写出的行。

    总线真实签名是 ``emit(event, *, user_id, agent_id, chat_id)``——桩必须
    照抄，否则测试会替代码掩盖签名错配（真 bus 上 TypeError 被吞掉，dev
    台账连续多轮 0 行的事故就是这么来的）。
    """
    rows = []

    class _Bus:
        def emit(self, event, *, user_id="", agent_id="", chat_id=""):
            rows.append(event)
            return event

    import coapis.decision.bus as bus_mod

    monkeypatch.setattr(bus_mod, "get_bus", lambda: _Bus())
    monkeypatch.setattr(lc, "_write_governance", lambda *a, **k: None)
    return rows


def test_zero_reason_no_llm_cost(monkeypatch):
    rows = _capture_emit(monkeypatch)
    ok = lc.write_ledger(
        source="plan_gate",
        purpose="level",
        hit_layer="rule_budget",
        cost=0.0,
        tokens=0,
        chat_id="c1",
        turn=1,
    )
    assert ok is True
    assert rows[0].cost == 0.0 and rows[0].tokens == 0


def test_zero_reason_usage_missing_for_llm(monkeypatch):
    rows = _capture_emit(monkeypatch)
    lc.write_ledger(
        source="plan_gate",
        purpose="level",
        hit_layer="llm",
        model="judge-test",
        cost=0.0,
        tokens=0,
        chat_id="c1",
        turn=1,
    )
    # llm 层 cost=0 → 契约层认定「记账坏了」，写侧标记 usage_missing
    assert rows[0].cost == 0.0
    assert rows[0].model == "judge-test"


def test_zero_reason_hint_write_failure(monkeypatch):
    """写侧提示：总线成功后写库失败时，行本身照写，cost=0 由预检标成写侧失败。"""
    rows = _capture_emit(monkeypatch)
    ok = lc.write_ledger(
        source="advisor",
        purpose="advice",
        hit_layer="rule_budget",
        zero_reason_hint=lc.ZERO_WRITE_FAILURE,
        chat_id="c1",
        turn=1,
    )
    assert ok is True
    assert rows[0].cost == 0.0
    assert rows[0].hit_layer == "rule_budget"


def test_zero_reason_empty_when_cost_positive(monkeypatch):
    rows = _capture_emit(monkeypatch)
    lc.write_ledger(
        source="acceptance",
        purpose="acceptance",
        hit_layer="llm",
        model="judge-x",
        cost=0.12,
        tokens=345,
        chat_id="c1",
        turn=1,
    )
    assert rows[0].cost == 0.12
    assert rows[0].tokens == 345


def test_model_none_for_rule_layer(monkeypatch):
    rows = _capture_emit(monkeypatch)
    lc.write_ledger(source="tool_gate", purpose="tools", hit_layer="rule_fast", chat_id="c1", turn=1)
    assert rows[0].model == "none"


def test_model_unknown_for_llm_without_model(monkeypatch):
    rows = _capture_emit(monkeypatch)
    lc.write_ledger(source="tool_gate", purpose="tools", hit_layer="llm", chat_id="c1", turn=1)
    assert rows[0].model == "unknown"


def test_model_written_lowercase_once(monkeypatch):
    rows = _capture_emit(monkeypatch)
    lc.write_ledger(
        source="plan_gate",
        purpose="level",
        hit_layer="llm",
        model="Judge-DeepSeek-V4-Pro",
        chat_id="c1",
        turn=1,
    )
    assert rows[0].model == "judge-deepseek-v4-pro"  # 全库一种写法


def test_negative_cost_and_tokens_clamped(monkeypatch):
    rows = _capture_emit(monkeypatch)
    lc.write_ledger(
        source="plan_gate",
        purpose="level",
        hit_layer="llm",
        cost=-3.5,
        tokens=-10,
        latency_ms=-5,
        chat_id="c1",
        turn=1,
    )
    assert rows[0].cost == 0.0
    assert rows[0].tokens == 0
    assert rows[0].latency_ms == 0


def test_band_cleaned_into_row(monkeypatch):
    rows = _capture_emit(monkeypatch)
    lc.write_ledger(
        source="plan_gate",
        purpose="level",
        band="plan_gate",  # 脏档位
        hit_layer="llm",
        chat_id="c1",
        turn=1,
    )
    assert rows[0].complexity == ""  # 台账里绝不出现非档位字面量


def test_value_and_outcome_truncated(monkeypatch):
    rows = _capture_emit(monkeypatch)
    lc.write_ledger(
        source="acceptance",
        purpose="acceptance",
        value="v" * 400,
        outcome="achieved_extra_beyond_column_width",
        chat_id="c1",
        turn=1,
    )
    row = rows[0].to_row()  # 台账行是 dict（列名=库里的列名，见 types.to_row）
    assert len(row["judgment"]) == 256  # judgment 列宽 256，超长截断
    assert len(row["outcome"]) == 16  # outcome 列宽 16（超长截断，不炸库）


def test_write_ledger_never_raises(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("总线炸了")

    import coapis.decision.bus as bus_mod

    class _Boom:
        emit = staticmethod(_boom)

    monkeypatch.setattr(bus_mod, "get_bus", lambda: _Boom())
    assert lc.write_ledger(source="plan_gate", purpose="level", chat_id="c1", turn=1) is False


def test_unknown_source_still_written(monkeypatch):
    rows = _capture_emit(monkeypatch)
    ok = lc.write_ledger(source="ghost_post", purpose="level", chat_id="c1", turn=1)
    assert ok is True
    assert rows[0].source == "ghost_post"  # 行照写，治理对账去查（不静默丢行）


# ── 4. 来源打标与迟到回填（批次5 写侧 / 闭环）───────────────────────────


@pytest.mark.parametrize(
    "chat_id,expect",
    [
        ("e2e-20261102", "test"),
        ("console:admin", "test"),
        ("test-case-1", "test"),
        ("synthetic-x", "test"),
        ("550e8400-e29b-41d4-a716-446655440000", "web"),
        ("wecom:woETa-FAAA", "web"),
        # v19 P2-1：chat_id 与 session_id 全空 = 不知道是谁的判断，单列
        # no_identity（预检 KPI 把它剔出真判率分母，见 D7 拍板）。
        ("", "no_identity"),
    ],
)
def test_detect_origin_by_id_shape(chat_id, expect):
    assert lc.detect_origin(chat_id, "") == expect


def test_detect_origin_empty_both_is_no_identity():
    """v19 P2-1：身份缺失单列，不再混进 web 拉高/拉低真判率。"""
    assert lc.detect_origin("", "") == "no_identity"
    assert lc.detect_origin("   ", None) == "no_identity"
    # 任一侧有身份就不是 no_identity（session 侧是 e2e 合成会话 → test）
    assert lc.detect_origin("", "e2e-run") == "test"
    assert lc.detect_origin("", "c1") == "web"


def test_detect_origin_uses_session_id_too():
    assert lc.detect_origin("550e8400-e29b-41d4-a716-446655440000", "e2e-run") == "test"


def test_backfill_outcome_requires_chat_id():
    assert lc.backfill_outcome(chat_id="", turn=1, outcome="achieved", cost=0.1, tokens=10) == 0


def test_backfill_outcome_requires_turn():
    assert lc.backfill_outcome(chat_id="c1", turn=0, outcome="achieved", cost=0.1, tokens=10) == 0


def test_backfill_outcome_swallows_db_failure(monkeypatch):
    def _boom():
        raise RuntimeError("库连不上")

    import coapis.foundation.db as db_mod

    monkeypatch.setattr(db_mod, "get_session", _boom)
    out = lc.backfill_outcome(chat_id="c1", turn=2, outcome="achieved", cost=0.2, tokens=20)
    assert out == 0  # 永不抛异常（红线）


def test_backfill_outcome_clamps_negative_cost(monkeypatch):
    """负成本进库前夹紧（对账不接受负数花费）。"""
    calls = {}

    class _Sess:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, stmt, params=None):
            calls["stmt"] = stmt
            class _R:
                rowcount = 1

            return _R()

    import coapis.foundation.db as db_mod

    monkeypatch.setattr(db_mod, "get_session", lambda: _Sess())
    assert lc.backfill_outcome(chat_id="c1", turn=2, outcome="achieved", cost=-1.0, tokens=-5) == 1
    compiled = str(calls["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "outcome" in compiled
    assert "-1.0" not in compiled  # 夹紧为 0
