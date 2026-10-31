# -*- coding: utf-8 -*-
"""C4 事中改道 / C5 验收回灌 / 判则 的单测（v14 §3.4/§3.5/§3.1）。"""
from __future__ import annotations

import asyncio

import pytest

from coapis.decision import hub_acceptance as acc
from coapis.decision import hub_advisor as adv
from coapis.decision import rubric as rb
from coapis.decision.gateway import JudgeReply


class _Hub:
    """最小配置替身（只带这两个岗位要用到的字段）。"""

    def __init__(self, **kw):
        self.enabled = kw.pop("enabled", True)
        self.advisor_every_iters = kw.pop("advisor_every_iters", 3)
        self.advisor_min_iters = kw.pop("advisor_min_iters", 3)
        self.acceptance_max_chars = kw.pop("acceptance_max_chars", 4000)
        self._off = kw.pop("off", ())
        for k, v in kw.items():
            setattr(self, k, v)

    def post_enabled(self, purpose):
        return purpose not in self._off


class _FakeGateway:
    """网关替身：按脚本吐结论，并记录调用。"""

    def __init__(self, payload=None, text="{}"):
        self.payload = payload
        self.text = text
        self.calls = []

    async def judge(self, **kw):
        self.calls.append(kw)
        value = self.payload
        if value is None and kw.get("rule_fallback") is not None:
            value = kw["rule_fallback"]()
        describe = kw.get("describe")
        return JudgeReply(
            ok=value is not None,
            value=value,
            text=self.text,
            source=kw.get("purpose", ""),
            hit_layer="llm" if self.payload is not None else "rule",
            reason="fake",
            model="fake-model",
            latency_ms=12.0,
            input_tokens=100,
            output_tokens=20,
            cost=0.001,
        )


def _install(monkeypatch, gateway: _FakeGateway) -> _FakeGateway:
    from coapis.decision import gateway as gw

    monkeypatch.setattr(gw, "get_judge_gateway", lambda: gateway)
    return gateway


# ---------------------------------------------------------------- 判则
def test_rubric_builtins_present():
    for name in ("level", "acceptance", "advisor"):
        text = rb.rubric_for(name)
        assert len(text) > 80, name
    assert "simple" in rb.rubric_for("level")
    assert "overreach" in rb.rubric_for("acceptance")
    assert "continue" in rb.rubric_for("advisor")
    assert rb.rubric_for("nope") == ""


def test_rubric_overlay_only_from_rubric_skills():
    skills = [
        {"name": "判则-需求满足度", "description": "只认交付物形态"},
        {"name": "普通技能", "description": "不该进来"},
    ]
    text = rb.rubric_for("acceptance", skills)
    assert "只认交付物形态" in text
    assert "不该进来" not in text
    long = rb.rubric_for("level", [("判则-超长", "字" * 5000)])
    assert len(long) <= len(rb.RUBRIC_LEVEL) + rb._OVERLAY_CAP + 40


# ---------------------------------------------------------------- C4 闸门
def test_should_advise_rhythm_and_gates():
    hub = _Hub(advisor_every_iters=3, advisor_min_iters=3)
    assert [adv.should_advise(hub, i) for i in range(1, 10)] == [
        False, False, True, False, False, True, False, False, True,
    ]
    assert not adv.should_advise(None, 5)
    assert not adv.should_advise(_Hub(enabled=False), 5)
    assert not adv.should_advise(_Hub(_off=("advisor",)), 5)
    assert not adv.should_advise(_Hub(advisor_every_iters=0), 5)


def test_fire_advisor_respects_gate(monkeypatch):
    g = _install(monkeypatch, _FakeGateway(payload={"verdict": "continue"}))

    async def go():
        assert adv.fire_advisor(
            goal="写个报告", tool_msgs=[], scope={"iters": 1, "turn": 1},
            hub=_Hub(),
        ) is None
        scope = {"iters": 3, "turn": 1, "chat_id": "c", "agent_id": "a"}
        task = adv.fire_advisor(goal="写个报告", tool_msgs=[], scope=scope,
                                hub=_Hub())
        assert task is not None
        await task
        assert len(g.calls) == 1
        assert g.calls[0]["purpose"] == "advisor"

    asyncio.run(go())


def test_advise_parses_verdict(monkeypatch):
    g = _install(monkeypatch, _FakeGateway(payload={
        "verdict": "change", "evidence": "第2号动作", "next": "先读文件",
    }))

    async def go():
        res = await adv.advise(
            goal="改配置", tool_msgs=[], scope={"turn": 2, "chat_id": "c"},
            hub=_Hub(),
        )
        assert res["verdict"] == "change"
        assert res["next"] == "先读文件"
        assert res["evidence"] == "第2号动作"
        assert "改配置" in g.calls[0]["user"]

    asyncio.run(go())


def test_advise_prompt_carries_rubric(monkeypatch):
    g = _install(monkeypatch, _FakeGateway(payload={"verdict": "continue"}))

    async def go():
        await adv.advise(goal="目标", tool_msgs=[], scope={"turn": 1},
                         hub=_Hub())
        assert "改道判则" in g.calls[0]["user"]
        assert "只输出一个 JSON 对象" in g.calls[0]["system"]

    asyncio.run(go())


def test_fire_advisor_on_verdict_callback(monkeypatch):
    seen = []
    _install(monkeypatch, _FakeGateway(payload={
        "verdict": "stop", "evidence": "第3号", "next": "停",
    }))

    async def go():
        task = adv.fire_advisor(
            goal="目标", tool_msgs=[], scope={"iters": 3, "turn": 1},
            hub=_Hub(), on_verdict=lambda r: seen.append(r["verdict"]),
        )
        await task
        assert seen == ["stop"]

    asyncio.run(go())


def test_build_digest_numbers_actions():
    class M:
        name = "read_file"

        def get_text_content(self):
            return "文件内容"

    d = adv.build_digest([M(), M()])
    assert d.startswith("1. read_file")
    assert "2. read_file" in d
    assert adv.build_digest([]) == "（还没有动作记录）"


# ---------------------------------------------------------------- C5
_LONG_ANSWER = (
    "已完成：季度报告在 /tmp/quarter.md，含营收、成本、人力三张表，"
    "并附了同比对比与结论段。"
)


def test_fire_acceptance_gates(monkeypatch):
    _install(monkeypatch, _FakeGateway(payload={"verdict": "satisfied"}))
    hub = _Hub()
    scope = {"chat_id": "c", "agent_id": "a", "turn": 1}

    async def go():
        # 需求太短：不判
        assert acc.fire_acceptance(query="好", answer=_LONG_ANSWER,
                                   scope=scope, hub=hub) is None
        # 交付太短：不判
        assert acc.fire_acceptance(query="请写一份季度报告并给出数据表",
                                   answer="完成了",
                                   scope=scope, hub=hub) is None
        # 无配置：不判
        assert acc.fire_acceptance(query="请写一份季度报告并给出数据表",
                                   answer=_LONG_ANSWER,
                                   scope=scope, hub=None) is None
        task = acc.fire_acceptance(
            query="请写一份季度报告并给出数据表",
            answer=_LONG_ANSWER,
            scope=scope, hub=hub,
        )
        assert task is not None
        await task

    asyncio.run(go())


def test_acceptance_abstain_when_no_value(monkeypatch):
    _install(monkeypatch, _FakeGateway(payload=None))

    async def go():
        res = await acc.judge_acceptance(
            query="请写一份季度报告", answer="完成了，含三张表。",
            scope={"chat_id": "c", "agent_id": "a", "turn": 1}, hub=_Hub(),
        )
        assert res["verdict"] == "abstain"
        assert res["hit_layer"] == "rule"

    asyncio.run(go())


def test_acceptance_prompt_carries_rubric_and_delivery(monkeypatch):
    g = _install(monkeypatch, _FakeGateway(payload={"verdict": "partial"}))

    async def go():
        res = await acc.judge_acceptance(
            query="要三张表", answer="给了一张表",
            scope={"chat_id": "c", "agent_id": "a", "turn": 1}, hub=_Hub(),
        )
        assert res["verdict"] == "partial"
        user = g.calls[0]["user"]
        assert "验收判则" in user and "给了一张表" in user

    asyncio.run(go())


def test_acceptance_backfills_plan_gate(monkeypatch):
    calls = []
    monkeypatch.setattr(
        acc, "_backfill_sync",
        lambda chat_id, turn, verdict: calls.append((chat_id, turn, verdict)),
    )

    async def go():
        _install(monkeypatch, _FakeGateway(payload={"verdict": "satisfied"}))
        await acc.judge_acceptance(
            query="把配置改掉", answer="已改完并验证。",
            scope={"chat_id": "chat-1", "agent_id": "a", "turn": 4}, hub=_Hub(),
        )
        assert calls == [("chat-1", 4, "satisfied")]
        # 没有 chat/turn 就不回填
        calls.clear()
        await acc.judge_acceptance(
            query="把配置改掉", answer="已改完并验证。",
            scope={"chat_id": "", "agent_id": "a", "turn": 0}, hub=_Hub(),
        )
        assert calls == []

    asyncio.run(go())


def test_acceptance_abstain_never_backfills(monkeypatch):
    """弃权不能回填成 miss——判官没判就没有对错。"""
    calls = []
    monkeypatch.setattr(
        acc, "_backfill_sync",
        lambda chat_id, turn, verdict: calls.append(verdict),
    )
    _install(monkeypatch, _FakeGateway(payload=None))

    async def go():
        res = await acc.judge_acceptance(
            query="把配置改掉", answer="已改完并验证。",
            scope={"chat_id": "c", "agent_id": "a", "turn": 3}, hub=_Hub(),
        )
        assert res["verdict"] == "abstain"
        assert calls == []

    asyncio.run(go())


def test_backfill_sync_updates_only_pending_plan_gate_rows(tmp_path):
    """真库跑一遍回填 SQL：命中口径 + 只动 pending 的判档行。"""
    from sqlalchemy import text

    from coapis.foundation.db import BaseRow, init_engine, reset_engine
    from coapis.foundation.db.engine import get_session
    from coapis.foundation.db.models import decision as _decision  # noqa: F401
    # ↑ 导入即注册表；create_all 只建已注册的表

    db = tmp_path / "sessions.db"
    engine = init_engine(f"sqlite:///{db}")
    BaseRow.metadata.create_all(engine)
    with get_session() as s:
        s.execute(text(
            "INSERT INTO decision_events (event_id, source, chat_id, turn, "
            "judgment, outcome, action, created_at) VALUES "
            "('e1','plan_gate','c1',2,'complex','pending','approve',1), "
            "('e2','plan_gate','c1',2,'complex','hit','approve',1), "
            "('e3','acceptance','c1',2,'','pending','satisfied',1)"
        ))

    acc._backfill_sync("c1", 2, "satisfied")

    with get_session() as s:
        rows = s.execute(text(
            "SELECT source, outcome, rating FROM decision_events "
            "ORDER BY source, action")).fetchall()
    reset_engine()
    # rating 列默认 3（未评）；回填只动 outcome=pending 的判档行
    assert [tuple(r) for r in rows] == [
        ("acceptance", "pending", 3),
        ("plan_gate", "hit", 1),
        ("plan_gate", "hit", 3),
    ]


def test_acceptance_never_raises(monkeypatch):
    """网关炸了也不能把收尾带炸（验收是加分项）。"""
    from coapis.decision import gateway as gw

    class Boom:
        async def judge(self, **kw):
            raise RuntimeError("网关炸了")

    monkeypatch.setattr(gw, "get_judge_gateway", lambda: Boom())

    async def go():
        task = acc.fire_acceptance(
            query="请写一份季度报告并给出数据表", answer=_LONG_ANSWER,
            scope={"chat_id": "c", "agent_id": "a", "turn": 1}, hub=_Hub(),
        )
        assert task is not None
        await task  # 不抛

    asyncio.run(go())
