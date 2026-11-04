# -*- coding: utf-8 -*-
"""计划审查岗（判断中枢二期 · R1′）的单测。

契约三条：① 只给建议权（不改计划、不回头重规划）；② 不阻塞主链；
③ 判断不可用时静默降级，主链零影响。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from coapis.decision import hub_plan_review as pr
from coapis.decision import rubric as rb
from coapis.decision.gateway import JudgeReply


# ────────────────────────────────────────────────────── 替身
class _Hub:
    def __init__(self, **kw):
        self.enabled = kw.pop("enabled", True)
        self._off = kw.pop("off", ())
        for k, v in kw.items():
            setattr(self, k, v)

    def post_enabled(self, purpose):
        return purpose not in self._off


class _FakeGateway:
    """网关替身：payload=None 时按真实网关的次序走 rule_fast → rule_fallback。

    有 payload 时等价于「模型答对了」——走 parse，跟真实网关一样。
    """

    def __init__(self, payload=None, text="{}"):
        self.payload = payload
        self.text = text if payload is None else json.dumps(payload, ensure_ascii=False)
        self.calls = []

    async def judge(self, **kw):
        self.calls.append(kw)
        parse = kw.get("parse")
        value = None
        layer = "rule"
        if self.payload is not None:
            value = parse(self.text) if callable(parse) else dict(self.payload)
            layer = "llm"
        if value is None:
            fast = kw.get("rule_fast")
            value = fast() if callable(fast) else None
            if value is None:
                fb = kw.get("rule_fallback")
                value = fb() if callable(fb) else None
        return JudgeReply(
            ok=value is not None,
            value=value,
            text=self.text,
            source=kw.get("purpose", ""),
            hit_layer=layer if value is not None else "abstain",
            reason="fake",
            model="fake-model" if layer == "llm" else "",
            latency_ms=12.0,
            input_tokens=100 if layer == "llm" else 0,
            output_tokens=20 if layer == "llm" else 0,
            cost=0.001 if layer == "llm" else 0.0,
        )


def _install(monkeypatch, gateway: _FakeGateway) -> _FakeGateway:
    from coapis.decision import gateway as gw

    monkeypatch.setattr(gw, "get_judge_gateway", lambda: gateway)
    return gateway


def _plan(goal, steps, state="todo"):
    sub = [_Sub(name, outcome, state) for name, outcome in steps]
    return _Plan(goal, sub)


class _Sub:
    def __init__(self, name, outcome, state="todo"):
        self.name = name
        self.outcome = outcome
        self.state = state


class _Plan:
    def __init__(self, goal, subtasks):
        self.description = goal
        self.subtasks = subtasks


class _NB:
    def __init__(self, plan):
        self.current_plan = plan


# ────────────────────────────────────────────────────── 岗位在配置与台账里
def test_post_is_registered_everywhere():
    from coapis.decision.config import POSTS
    from coapis.decision.ledger_contract import SOURCES

    assert "plan_review" in POSTS
    assert "plan_review" in SOURCES
    assert pr.POST == "plan_review"


def test_hub_config_can_switch_post_off():
    from coapis.decision.config import merge_hub_config

    hub = merge_hub_config({"plan_review_enabled": False})
    assert hub.post_enabled("plan_review") is False
    assert pr.should_review(hub) is False


# ────────────────────────────────────────────────────── 判则
def test_rubric_builtin_for_plan_review():
    text = rb.rubric_for("plan_review")
    assert "计划审查岗" in text
    assert "一期只有建议权" in text
    assert "pass / revise / replan" in text


# ────────────────────────────────────────────────────── 取计划
def test_collect_from_notebook():
    snap = pr.collect(_NB(_plan("调研 A 并输出报告", [("查资料", "一份清单")])))
    assert snap and snap["goal"] == "调研 A 并输出报告"
    assert snap["step_count"] == 1
    assert snap["steps"][0]["idx"] == 1


def test_collect_empty_plan_returns_none():
    assert pr.collect(None) is None
    assert pr.collect(_NB(None)) is None
    assert pr.collect(_NB(_plan("有目标", []))) is None


# ────────────────────────────────────────────────────── 规则（确定性那一半）
def test_rule_single_step_multi_goal():
    snap = pr.collect(_NB(_plan("先调研 A，再实现 B，最后写总结", [("一口气干完", "结果")])))
    action, why, _ = pr.review_rules(snap)
    assert action == "replan"
    assert "只有 1 步" in why


def test_rule_no_execution_step():
    snap = pr.collect(_NB(_plan("把分析结果保存到文件", [("想清楚方向", "方向")])))
    action, why, _ = pr.review_rules(snap)
    assert action == "replan"
    assert "产出落不到" in why


def test_rule_chitchat_plan():
    snap = pr.collect(_NB(_plan("你好", [("打招呼", "问候")])))
    action, why, _ = pr.review_rules(snap)
    assert action == "replan"
    assert "寒暄" in why


def test_rule_vague_step():
    snap = pr.collect(_NB(_plan("输出报告", [
        ("查资料", "若干"), ("写报告", "报告"), ("finish", "答案"),
    ])))
    action, why, _ = pr.review_rules(snap)
    assert action == "revise"
    assert "产出描述" in why


def test_rule_silent_on_healthy_plan():
    snap = pr.collect(_NB(_plan("调研 A 并输出报告", [
        ("搜集资料", "一份带来源的清单"),
        ("汇总分析", "分析结论"),
        ("finish", "最终报告"),
    ])))
    assert pr.review_rules(snap) is None


def test_forced_rule_abstains_on_healthy_plan():
    snap = pr.collect(_NB(_plan("调研 A 并输出报告", [
        ("搜集资料", "一份带来源的清单"), ("finish", "最终报告"),
    ])))
    assert pr.forced_rule(snap) is None


# ────────────────────────────────────────────────────── 提示只给建议权
def test_hint_wording_is_advice_only():
    hint = pr.review_hint({"action": "revise", "why": "步骤 1 模糊", "hint": "写成可检查的结果"})
    assert hint.startswith("<coapis-plan-review>")
    assert "</coapis-plan-review>" in hint
    assert "只改计划，别改用户的要求" in hint
    assert pr.review_hint({"action": "pass", "why": "可以"}) == ""
    assert pr.review_hint({}) == ""


# ────────────────────────────────────────────────────── 判断流程
def test_review_rules_hit_skips_model(monkeypatch):
    g = _install(monkeypatch, _FakeGateway(payload=None))
    got = []
    out = asyncio.run(pr.review_plan(
        _NB(_plan("先调研 A，再实现 B", [("全干了", "结果")])),
        hub=_Hub(), scope={"chat_id": "c1", "turn": 1},
        on_verdict=lambda r: got.append(r),
    ))
    assert out["action"] == "replan"
    assert out["decided_by"] == "rule"
    assert len(got) == 1
    assert got[0]["decided_by"] == "rule"
    # 规则命中走的是 rule_fast：不查模型
    assert g.calls[0]["purpose"] == "plan_review"


def test_review_model_pass_is_quiet(monkeypatch):
    _install(monkeypatch, _FakeGateway(payload={"action": "pass", "why": "计划可执行"}))
    got = []
    out = asyncio.run(pr.review_plan(
        _NB(_plan("调研 A 并输出报告", [
            ("搜集资料", "带来源的清单"), ("汇总", "结论"), ("finish", "报告"),
        ])),
        hub=_Hub(), scope={"chat_id": "c2", "turn": 1},
        on_verdict=lambda r: got.append(r),
    ))
    assert out is None
    assert got == []


def test_review_model_revise_calls_back(monkeypatch):
    g = _install(monkeypatch, _FakeGateway(payload={
        "action": "replan", "why": "第 2 步做不了", "hint": "拆开做",
    }))
    got = []
    out = asyncio.run(pr.review_plan(
        _NB(_plan("调研 A 并输出报告", [
            ("搜集资料", "带来源的清单"),
            ("全部完成", "答案"),
            ("finish", "报告"),
        ])),
        hub=_Hub(), scope={"chat_id": "c3", "turn": 1},
        on_verdict=lambda r: got.append(r),
    ))
    assert out["action"] == "replan"
    assert out["decided_by"] == "model"
    assert got and "拆开做" in pr.review_hint(got[0])
    assert g.calls[0]["on_late_verdict"] is not None  # 迟到真判必须有回执


def test_review_prompt_carries_rubric(monkeypatch):
    g = _install(monkeypatch, _FakeGateway(payload={"action": "pass"}))
    asyncio.run(pr.review_plan(
        _NB(_plan("调研 A", [("搜集资料", "清单"), ("finish", "报告")])),
        hub=_Hub(), scope={"chat_id": "c4", "turn": 1},
    ))
    call = g.calls[0]
    assert "计划审查岗" in call["system"]
    assert "目标：调研 A" in call["user"]
    assert "1. 搜集资料" in call["user"]


def test_review_post_off_never_calls_model(monkeypatch):
    g = _install(monkeypatch, _FakeGateway(payload={"action": "replan"}))
    out = asyncio.run(pr.review_plan(
        _NB(_plan("先 A 再 B", [("全干了", "结果")])),
        hub=_Hub(off=("plan_review",)), scope={"chat_id": "c5", "turn": 1},
    ))
    assert out is None
    assert g.calls == []


def test_review_never_raises(monkeypatch):
    from coapis.decision import gateway as gw

    def _boom():
        raise RuntimeError("网关坏了")

    monkeypatch.setattr(gw, "get_judge_gateway", _boom)
    got = []
    out = asyncio.run(pr.review_plan(
        _NB(_plan("先 A 再 B", [("全干了", "结果")])),
        hub=_Hub(), scope={"chat_id": "c6", "turn": 1},
        on_verdict=lambda r: got.append(r),
    ))
    assert out is None
    assert got == []


def test_review_bad_model_text_falls_back_to_rules(monkeypatch):
    _install(monkeypatch, _FakeGateway(payload=None, text="我不确定"))
    out = asyncio.run(pr.review_plan(
        _NB(_plan("先 A 再 B", [("全干了", "结果")])),
        hub=_Hub(), scope={"chat_id": "c7", "turn": 1},
    ))
    assert out["action"] == "replan"
    assert out["decided_by"] == "rule"  # 模型话多不影响：规则结论已经给了


# ────────────────────────────────────────────────────── 发射即忘
def test_fire_returns_none_without_running_loop():
    assert pr.fire_plan_review(
        _NB(_plan("先 A 再 B", [("全干了", "结果")])),
        hub=_Hub(), scope={"chat_id": "c8"},
    ) is None


def test_fire_respects_post_switch(monkeypatch):
    _install(monkeypatch, _FakeGateway(payload={"action": "replan"}))
    assert pr.fire_plan_review(
        _NB(_plan("先 A 再 B", [("全干了", "结果")])),
        hub=_Hub(off=("plan_review",)), scope={"chat_id": "c9"},
    ) is None


def test_fire_launches_task(monkeypatch):
    g = _install(monkeypatch, _FakeGateway(payload={"action": "revise", "why": "模糊"}))
    got = []

    async def _go():
        task = pr.fire_plan_review(
            _NB(_plan("输出报告", [("想一下", "若干"), ("finish", "报告")])),
            hub=_Hub(), scope={"chat_id": "c10", "turn": 1},
            on_verdict=lambda r: got.append(r),
        )
        assert task is not None
        await task

    asyncio.run(_go())
    assert len(g.calls) == 1
    assert got and got[0]["action"] == "revise"
