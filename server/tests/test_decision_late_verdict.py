"""判官迟到真判的回执 + 验收岗单独软阈值（v14 §3.2 闭环第二段）。

主链软超时后拿降级值先走，判官在后台跑出的**真结论**只进台账——消费方
（验收回填判档行 outcome）拿到的永远是弃权值，闭环恒 0。这两条把断链接上：

1. ``judge(on_late_verdict=...)``：后台补判成功时用真结论回调消费方；
2. ``judge_soft_ms_acceptance``：验收是幕后岗，不该吃主链那 4 秒预算。
"""

from __future__ import annotations

import asyncio
import time

from coapis.decision import gateway as gw
from coapis.decision.config import DecisionHubConfig

from .test_decision_gateway import SCOPE, FakeModel, wire


def hub(**kw) -> DecisionHubConfig:
    base = dict(enabled=True, llm_timeout_ms=5000.0, llm_max_tokens=256)
    base.update(kw)
    return DecisionHubConfig.from_dict(base).normalized()


async def test_late_verdict_hook_gets_the_real_answer(monkeypatch):
    """软超时：主链拿降级值，回执拿真判结论。"""
    wire(monkeypatch, FakeModel('{"band":"high","reason":"够格"}'))
    cfg = hub(judge_soft_ms=50.0, judge_min_interval_ms=0.0)
    got: list = []

    reply = await gw.JudgeGateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda raw: {"band": str((__import__("json").loads(raw) or {}).get("band"))},
        rule_fallback="low", describe=lambda v: str(v),
        hub=cfg, scope=dict(SCOPE),
        on_late_verdict=lambda v: got.append(v),
    )
    assert reply.hit_layer == "timeout"
    assert got == []                      # 回执在后台任务里，主链返回时还没到

    for _ in range(60):
        if got:
            break
        await asyncio.sleep(0.05)
    assert got == [{"band": "high"}], got  # 真判结论送到了消费方


async def test_late_verdict_hook_can_be_a_coroutine(monkeypatch):
    """异步回执（验收回填就是协程）必须被 await，不能只创建不跑。"""
    import json

    wire(monkeypatch, FakeModel('{"verdict":"hit"}'))
    cfg = hub(judge_soft_ms=50.0, judge_min_interval_ms=0.0)
    seen: list = []

    async def hook(value):
        await asyncio.sleep(0)
        seen.append(value)

    await gw.JudgeGateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda raw: {"verdict": str(json.loads(raw).get("verdict"))},
        rule_fallback={"verdict": "abstain"}, describe=lambda v: str(v),
        hub=cfg, scope=dict(SCOPE, agent_id="a2"),
        on_late_verdict=hook,
    )
    for _ in range(60):
        if seen:
            break
        await asyncio.sleep(0.05)
    assert seen == [{"verdict": "hit"}], seen


async def test_late_verdict_hook_crash_does_not_bite(monkeypatch):
    """回执是加分项：炸了也不能把后台补判的台账写入带下水。"""
    wire(monkeypatch, FakeModel('{"band":"medium"}'))
    cfg = hub(judge_soft_ms=40.0, judge_min_interval_ms=0.0)

    def boom(_v):
        raise RuntimeError("消费方炸了")

    reply = await gw.JudgeGateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda raw: {"band": "medium"},
        rule_fallback="low", describe=lambda v: str(v),
        hub=cfg, scope=dict(SCOPE, agent_id="a3"),
        on_late_verdict=boom,
    )
    assert reply.hit_layer == "timeout"
    for _ in range(40):
        if gw.get_judge_gateway().stats() is not None:
            break
        await asyncio.sleep(0.05)


async def test_acceptance_gets_its_own_soft_budget(monkeypatch):
    """同一个判官：主链岗位 4 秒弃权，验收岗拿到真判。"""
    import json

    class SlowModel:
        def __init__(self, sleep_s: float):
            self.sleep_s = sleep_s
            self.calls = 0

        async def __call__(self, messages, **kwargs):
            self.calls += 1
            await asyncio.sleep(self.sleep_s)
            return type("R", (), {"content": [{'type': 'text', 'text': '{"verdict":"hit"}'}]})()

    slow = SlowModel(0.30)
    wire(monkeypatch, slow)
    cfg = hub(
        judge_soft_ms=60.0,
        judge_soft_ms_acceptance=1200.0,
        judge_min_interval_ms=0.0,
    )

    main = await gw.JudgeGateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda raw: {"band": "low"},
        rule_fallback="low", describe=lambda v: str(v),
        hub=cfg, scope=dict(SCOPE, agent_id="b1"),
    )
    acc = await gw.JudgeGateway().judge(
        purpose="acceptance", system="s", user="u",
        parse=lambda raw: {"verdict": str(json.loads(raw).get("verdict"))},
        rule_fallback={"verdict": "abstain"}, describe=lambda v: str(v),
        hub=cfg, scope=dict(SCOPE, agent_id="b2"),
    )
    assert main.hit_layer == "timeout"          # 主链等不起，降级先走
    assert acc.hit_layer == "llm"               # 验收判到了真结论
    assert acc.value["verdict"] == "hit"


def test_acceptance_soft_floor_follows_main_threshold():
    """配置手滑也不能让验收比主链还短——松绑这件事不能被一个数撤销。"""
    cfg = DecisionHubConfig.from_dict(
        {"judge_soft_ms": 4000.0, "judge_soft_ms_acceptance": 10.0},
    ).normalized()
    assert cfg.judge_soft_ms_acceptance >= cfg.judge_soft_ms

    cfg2 = DecisionHubConfig.from_dict(
        {"judge_soft_ms_acceptance": 9_999_999.0},
    ).normalized()
    assert cfg2.judge_soft_ms_acceptance <= 20000.0
