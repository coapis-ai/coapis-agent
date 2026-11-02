"""判官迟到真判的回执 + 验收岗单独软阈值（v14 §3.2 闭环第二段）。

主链软超时后拿降级值先走，判官在后台跑出的**真结论**只进台账——消费方
（验收回填判档行的 outcome）拿到的永远是弃权值，闭环恒 0。这两条把断链接上：

1. ``judge(on_late_verdict=...)``：后台补判成功时，用真结论回调消费方；
2. ``judge_soft_ms_acceptance``：验收是幕后岗（整轮交付跑完才触发，没有
   任何人在等它的结论），不该吃主链那 4 秒的预算。

桩自带，不借其他测试文件的夹具——测试之间不互相绑手。
"""

from __future__ import annotations

import asyncio
import json

from coapis.decision import gateway as gw
from coapis.decision.config import DecisionHubConfig

SCOPE = {"user_id": "u1", "agent_id": "a1", "chat_id": "c1", "turn": 1}


class SlowModel:
    """固定耗时、固定回答的假判官模型。"""

    def __init__(self, text: str, sleep_s: float = 0.4):
        self.text = text
        self.sleep_s = sleep_s
        self.calls = 0

    async def __call__(self, messages, **kwargs):
        self.calls += 1
        await asyncio.sleep(self.sleep_s)
        return type(
            "R", (), {"content": [{"type": "text", "text": self.text}]},
        )()


class FakeProvider:
    def __init__(self, model: SlowModel) -> None:
        self.model = model
        self.base_url = ""
        self.models = [type("M", (), {"id": "m1", "type": "chat", "pricing": {}})()]

    def get_effective_generate_kwargs(self, model_id):
        return {"temperature": 0.7, "max_tokens": 256, "none_key": None}

    def get_chat_model_instance(self, model_id):
        return self.model


class FakeManager:
    def __init__(self, provider) -> None:
        self.provider = provider

    def get_provider(self, provider_id):
        return self.provider


def wire(monkeypatch, model: SlowModel) -> SlowModel:
    """把网关的模型解析接到替身上（v15 固定模型槽那套口子）。"""
    from coapis.providers import provider_manager as pm

    gw.reset_judge_gateway()
    monkeypatch.setattr(
        pm.ProviderManager, "get_instance",
        staticmethod(lambda: FakeManager(FakeProvider(model))),
        raising=True,
    )
    monkeypatch.setattr(
        gw, "get_judge_provider_config",
        lambda cfg=None, user_id=None, agent_id=None: {
            "provider_id": "p1", "model": "m1",
        },
        raising=True,
    )
    return model


def hub(**kw) -> DecisionHubConfig:
    base = dict(enabled=True, llm_timeout_ms=5000.0, llm_max_tokens=256)
    base.update(kw)
    return DecisionHubConfig.from_dict(base).normalized()


def parse_band(raw):
    return {"band": str(json.loads(raw).get("band"))}


def parse_verdict(raw):
    return {"verdict": str(json.loads(raw).get("verdict"))}


async def _settles(hits: list) -> None:
    for _ in range(80):
        if hits:
            return
        await asyncio.sleep(0.05)


async def test_late_verdict_hook_gets_the_real_answer(monkeypatch):
    """软超时：主链拿降级值先走，回执拿到真判结论。"""
    wire(monkeypatch, SlowModel('{"band":"high","reason":"够格"}', 0.4))
    cfg = hub(judge_soft_ms=50.0, judge_min_interval_ms=0.0)
    got: list = []

    reply = await gw.JudgeGateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=parse_band, rule_fallback="low", describe=lambda v: str(v),
        hub=cfg, scope=dict(SCOPE),
        on_late_verdict=lambda v: got.append(v),
    )
    assert reply.hit_layer == "timeout"
    assert got == []                      # 主链返回时后台还在判，回执未到

    await _settles(got)
    assert got == [{"band": "high"}], got  # 真判结论送到了消费方手里


async def test_late_verdict_hook_can_be_a_coroutine(monkeypatch):
    """异步回执（验收回填就是协程）必须被 await，不能只创建不跑。"""
    wire(monkeypatch, SlowModel('{"verdict":"hit"}', 0.4))
    cfg = hub(judge_soft_ms=50.0, judge_min_interval_ms=0.0)
    seen: list = []

    async def hook(value):
        await asyncio.sleep(0)
        seen.append(value)

    await gw.JudgeGateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=parse_verdict, rule_fallback={"verdict": "abstain"},
        describe=lambda v: str(v), hub=cfg, scope=dict(SCOPE, agent_id="a2"),
        on_late_verdict=hook,
    )
    await _settles(seen)
    assert seen == [{"verdict": "hit"}], seen


async def test_late_verdict_hook_crash_does_not_bite(monkeypatch):
    """回执是加分项：炸了也不能把后台补判本身带下水。"""
    model = wire(monkeypatch, SlowModel('{"band":"medium"}', 0.3))
    cfg = hub(judge_soft_ms=40.0, judge_min_interval_ms=0.0)

    def boom(_v):
        raise RuntimeError("消费方炸了")

    reply = await gw.JudgeGateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=parse_band, rule_fallback="low", describe=lambda v: str(v),
        hub=cfg, scope=dict(SCOPE, agent_id="a3"),
        on_late_verdict=boom,
    )
    assert reply.hit_layer == "timeout"
    await asyncio.sleep(0.6)
    assert model.calls == 1               # 后台判完了，回执炸掉被吞（不反噬）


async def test_acceptance_gets_its_own_soft_budget(monkeypatch):
    """同一个判官、同一次耗时：主链岗位弃权，验收岗判到真结论。"""
    wire(monkeypatch, SlowModel('{"verdict":"hit"}', 0.3))
    cfg = hub(judge_soft_ms=60.0, judge_soft_ms_acceptance=1200.0,
             judge_min_interval_ms=0.0)

    main = await gw.JudgeGateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=parse_band, rule_fallback="low", describe=lambda v: str(v),
        hub=cfg, scope=dict(SCOPE, agent_id="b1"),
    )
    acc = await gw.JudgeGateway().judge(
        purpose="acceptance", system="s", user="u",
        parse=parse_verdict, rule_fallback={"verdict": "abstain"},
        describe=lambda v: str(v), hub=cfg, scope=dict(SCOPE, agent_id="b2"),
    )
    assert main.hit_layer == "timeout"    # 主链等不起，降级先走
    assert acc.hit_layer == "llm"         # 验收有自己的预算，判到了
    assert acc.value["verdict"] == "hit"


def test_acceptance_soft_floor_follows_main_threshold():
    """配置手滑也不能让验收比主链还短——给验收松绑不能被一个数撤销。"""
    cfg = DecisionHubConfig.from_dict(
        {"judge_soft_ms": 4000.0, "judge_soft_ms_acceptance": 10.0},
    ).normalized()
    assert cfg.judge_soft_ms_acceptance >= cfg.judge_soft_ms

    cfg2 = DecisionHubConfig.from_dict(
        {"judge_soft_ms_acceptance": 9_999_999.0},
    ).normalized()
    assert 200.0 <= cfg2.judge_soft_ms_acceptance <= 20000.0
