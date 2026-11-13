# -*- coding: utf-8 -*-
"""B0 契约锁 · 判断台账写入面（方案 v1 §3 第 0 批 / D14）

**口径照抄代码，不照抄方案。** 判断台账是真表 ``decision_events``；统一写入
入口是 ``coapis/decision/ledger_contract.py::write_ledger``，它经
``bus.get_bus().emit(DecisionResult)`` 落行，再由 ``_write_governance``
补治理列（origin/zero_reason/dirty_band）。

这一节绝大多数是**现状锁**——B3 动判官时不许把它们改松。只有弃权原因码
是 B3 目标锁（``xfail(strict=True)``）。
"""
from __future__ import annotations

import pytest

from coapis.decision import ledger_contract as lc
from coapis.decision.rubric import LEVELS

B3 = pytest.mark.xfail(
    strict=True,
    reason="B3 目标契约：弃权行带原因码入账（未实现）",
)


class FakeBus:
    """只抓 emit 的事件，不碰数据库。"""

    def __init__(self) -> None:
        self.events: list = []

    def emit(self, event) -> None:
        self.events.append(event)


@pytest.fixture()
def fake_bus(monkeypatch):
    bus = FakeBus()
    import coapis.decision.bus as bus_mod

    monkeypatch.setattr(bus_mod, "get_bus", lambda: bus)
    # 治理列补写走真库，契约测试里不需要
    monkeypatch.setattr(lc, "_write_governance", lambda *a, **k: None)
    return bus


# ── 1. 档位尺子：只认判则词表，绝不发明档位 ─────────────────────────────


def test_band_vocabulary_comes_from_the_rubric():
    # 台账档位与判则同源；岗位自带小词表 = 档位对不上判则。
    assert set(LEVELS) >= {"simple", "medium", "complex"}


def test_normalize_band_accepts_whitelist():
    for band in LEVELS:
        got, dirty = lc.normalize_band(band)
        assert got == band
        assert dirty == ""


def test_normalize_band_never_invents_a_band():
    # 岗位想写 "plan_gate"/"select:low,medium"：清洗成默认档，原值留痕。
    for bad in ("plan_gate", "select:low,medium", "none-ish", "L3", "复杂"):
        got, dirty = lc.normalize_band(bad)
        assert got not in {"plan_gate", "select:low,medium"}, bad
        assert dirty == bad, f"{bad} 的原值必须留痕：清洗不销毁证据"


def test_normalize_band_is_case_insensitive():
    assert lc.normalize_band("CoMpLeX")[0] == "complex"


def test_normalize_band_empty_falls_back_to_default():
    # 现状口径：空/空白 → 默认档（空串）且不判脏。台账列因此可以为空，
    # 看板按档位分桶时必须把空档单列一档，不许与 "none" 混算。
    for value in (None, "", "   "):
        got, dirty = lc.normalize_band(value)
        assert got == ""
        assert dirty == ""


# ── 2. 零值标记：把"设计上为 0"和"记账坏了"分开 ─────────────────────────


def test_zero_marks_are_named_values():
    assert lc.ZERO_NO_LLM == "no_llm_cost"
    assert lc.ZERO_USAGE_MISSING == "usage_missing"
    assert lc.ZERO_WRITE_FAILURE == "write_failure"


def test_llm_layer_with_zero_cost_is_marked_usage_missing(fake_bus):
    lc.write_ledger(
        source="acceptance",
        purpose="验收",
        hit_layer="llm",
        cost=0.0,
        chat_id="chat-1",
        session_id="s-1",
    )
    assert len(fake_bus.events) == 1
    ev = fake_bus.events[0]
    assert ev.payload["zero_reason"] == lc.ZERO_USAGE_MISSING


def test_rule_layer_with_zero_cost_is_marked_no_llm_cost(fake_bus):
    lc.write_ledger(
        source="tool_gate",
        purpose="工具闸",
        hit_layer="rule",
        cost=0.0,
        chat_id="chat-1",
        session_id="s-1",
    )
    assert fake_bus.events[0].payload["zero_reason"] == lc.ZERO_NO_LLM


def test_paid_row_carries_no_zero_mark(fake_bus):
    lc.write_ledger(
        source="acceptance",
        purpose="验收",
        hit_layer="llm",
        cost=0.0012,
        model="Judge",
        chat_id="chat-1",
        session_id="s-1",
    )
    ev = fake_bus.events[0]
    assert ev.payload["zero_reason"] == ""
    assert ev.cost == pytest.approx(0.0012)
    # 模型名归一（大小写/空格）：台账按模型聚合，两份写法=两张表
    assert ev.model == "judge"


# ── 3. 身份归因：scope 优先 → ContextVar → session 兜底 ─────────────────


def test_resolve_ids_prefers_explicit_scope():
    uid, aid, sid, cid, tn = lc.resolve_ids(
        {"user_id": "u", "agent_id": "a", "session_id": "s", "chat_id": "c", "turn": 3},
    )
    assert (uid, aid, sid, cid, tn) == ("u", "a", "s", "c", 3)


def test_resolve_ids_falls_back_to_context_vars(monkeypatch):
    # 岗位不传身份时必须从 ContextVar 兜底 —— 这正是"台账行归不了因"
    # 的根治点（PRD C1 的归因半边）。
    from coapis.config import session_context as sc

    sc.set_current_chat_id("ctx-chat")
    sc.set_current_session_id("ctx-session")
    sc.set_current_user_id("ctx-user")
    try:
        uid, _aid, sid, cid, _tn = lc.resolve_ids({})
        assert cid == "ctx-chat"
        assert sid == "ctx-session"
        assert uid == "ctx-user"
    finally:
        # 显式清空：clear_session_context 不清 _CHAT_ID（见 usage 契约里的
        # B1 目标锁），这里手工收口，不让身份泄漏到后续用例。
        sc.set_current_chat_id("")
        sc.set_current_session_id("")
        sc.set_current_user_id("")


def test_resolve_ids_uses_session_id_as_chat_fallback():
    # 只有 session 键时，chat_id 退化为 session 键：同一对话至少可聚合。
    _uid, _aid, sid, cid, _tn = lc.resolve_ids({"session_id": "only-session"})
    assert cid == sid == "only-session"


def test_resolve_ids_coerces_turn_to_int():
    assert lc.resolve_ids({"turn": "7"})[4] == 7
    assert lc.resolve_ids({"turn": "abc"})[4] == 0


def test_resolve_ids_auto_numbers_turn_per_chat():
    chat = "contract-auto-turn"
    _u, _a, _s, _c, first = lc.resolve_ids({"chat_id": chat})
    _u, _a, _s, _c, second = lc.resolve_ids({"chat_id": chat})
    assert first >= 1 and second > first


def test_detect_origin_separates_test_traffic():
    # 测试/控制台流量必须与真实用户分开统计，否则效果指标被探针污染
    # （本仓反复踩过的坑：探针造数冒充真实效果）。签名 = (chat_id, user_id)。
    assert lc.detect_origin("e2e-chat", "e2e-user") == "test"
    assert lc.detect_origin("console:admin", "console") == "test"
    assert lc.detect_origin("", "") == "no_identity"
    assert lc.detect_origin("chat-real", "user-real") == "web"


def test_next_turn_is_monotonic_and_empty_chat_is_zero():
    chat = "contract-monotonic"
    assert lc.next_turn(chat) >= 1
    assert lc.next_turn(chat) > lc.next_turn("contract-other") - 1
    first = lc.next_turn(chat)
    assert lc.next_turn(chat) > first
    assert lc.next_turn("") == 0


# ── 4. 岗位白名单与写侧红线 ─────────────────────────────────────────────


def test_source_whitelist_is_closed_set():
    # 岗位名漂移会让看板分桶失真：新增岗位必须显式进白名单。
    assert isinstance(lc.SOURCES, frozenset)
    assert {
        "plan_gate",
        "plan_review",
        "skill_trigger",
        "tool_gate",
        "acceptance",
        "advisor",
        "selfcheck",
    } == set(lc.SOURCES)


def test_write_ledger_never_raises_on_bus_failure(monkeypatch):
    # 红线：台账坏了可以修，主链停了是事故。
    import coapis.decision.bus as bus_mod

    class BrokenBus:
        def emit(self, *_a, **_k):
            raise RuntimeError("db down")

    monkeypatch.setattr(bus_mod, "get_bus", lambda: BrokenBus())
    monkeypatch.setattr(lc, "_write_governance", lambda *a, **k: None)
    assert lc.write_ledger(source="tool_gate", purpose="工具闸") is False


def test_write_ledger_writes_unknown_source_row_for_audit(fake_bus):
    # 现状语义：未知岗位**照写**（行留着给治理对账），返回值仍是 True。
    # 这条锁住"不静默丢行"。要改成拒绝写入必须走拍板，不许顺手改。
    assert lc.write_ledger(source="not_a_post", purpose="x") is True
    assert len(fake_bus.events) == 1


def test_write_ledger_carries_attribution_in_payload(fake_bus):
    lc.write_ledger(
        source="advisor",
        purpose="改道",
        chat_id="chat-payload",
        session_id="s-payload",
        turn=5,
    )
    ev = fake_bus.events[0]
    assert ev.chat_id == "chat-payload"
    assert ev.turn == 5
    assert ev.payload["session_id"] == "s-payload"


def test_write_ledger_never_leaves_band_dirty_in_column(fake_bus):
    # 岗位传了非档位字面量：列里必须是干净档位（现状是清洗成默认空档），
    # 脏值只能在治理列 dirty_band 留痕，绝不允许原样进列。
    lc.write_ledger(
        source="plan_gate",
        purpose="定档",
        band="select:low,medium",
        chat_id="chat-band",
    )
    assert fake_bus.events[0].complexity in set(LEVELS) | {""}


def test_ledger_target_table_is_the_decision_ledger():
    # 表名是看板/迁移/对账共用的地址，改名必须同步迁移脚本。
    from coapis.foundation.db.models.decision import DecisionEvent

    assert DecisionEvent.__tablename__ == "decision_events"


# ── 5. B3 目标：弃权必须带原因码 ────────────────────────────────────────


@B3
def test_abstention_row_carries_a_reason_code(fake_bus):
    # 验收口径（方案 §5）：弃权行 100% 带原因码。今天弃权=空判定，
    # 看板只看到"判官没意见"，看不出为什么没意见。
    lc.write_ledger(
        source="acceptance",
        purpose="验收",
        hit_layer="llm",
        cost=0.0,
        band="none",
        model="judge",
        chat_id="chat-abstain",
        session_id="s-abstain",
    )
    ev = fake_bus.events[0]
    assert ev.payload.get("abstain_reason"), "弃权行必须带原因码"