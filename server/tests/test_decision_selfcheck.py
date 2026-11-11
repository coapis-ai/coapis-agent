# -*- coding: utf-8 -*-
"""自检验收单测（v27 · 拍板 D3）。

锁四件事：① 自评只在判官不在岗时由调用方发射（本模块自己只管熄火条件）；
② 判不出就不写台账（垃圾自评比不写更坏——它会回填出假档位）；
③ 写台账必带 source=selfcheck 且 outcome 与 verdict 同值（看板要靠这一列把
「自己给自己打分」与「判官外部验收」分开统计）；④ 任何异常都不许逃出模块。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from coapis.decision import hub_acceptance as acc
from coapis.decision import selfcheck as sc
from coapis.decision.config import DecisionHubConfig
from coapis.decision.ledger_contract import SOURCES


def _resp(text: str):
    """会话模型返回的替身形状（agentscope ChatResponse 的正文块形状）。"""
    return SimpleNamespace(
        content=[{"type": "text", "text": text}],
        usage={"input_tokens": 120, "output_tokens": 30},
    )


class _Hub:
    """最小配置替身。"""

    def __init__(self, **kw):
        self.enabled = kw.pop("enabled", True)
        self.selfcheck_enabled = kw.pop("selfcheck_enabled", True)
        self.selfcheck_timeout_ms = kw.pop("selfcheck_timeout_ms", 20000)
        self.selfcheck_min_answer_chars = kw.pop("selfcheck_min_answer_chars", 80)
        self._off = kw.pop("off", ())
        for k, v in kw.items():
            setattr(self, k, v)

    def post_enabled(self, purpose):
        return purpose not in self._off


class _Model:
    """会话模型替身：async 调用返回一条文本；model_name 用来验标签。"""

    def __init__(self, text="{}", model_name="main-chat", sleep=0.0, boom=None):
        self.text = text
        self.model_name = model_name
        self.sleep = sleep
        self.boom = boom
        self.calls = []

    async def __call__(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.boom is not None:
            raise self.boom
        return _resp(self.text)


class _StreamModel(_Model):
    """流式返回的替身：自评必须把流收完再判（会话模型常是流式的）。"""

    async def __call__(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})

        async def _gen():
            yield SimpleNamespace(content=[], usage=None)
            yield _resp(self.text)

        return _gen()


@pytest.fixture
def sink(monkeypatch):
    """拦下台账写入与档位回填，返回 (台账行, 回填记录)。"""
    rows, fills = [], []
    monkeypatch.setattr(
        sc,
        "write_ledger",
        lambda **kw: rows.append(kw),
    )

    async def _fill(*, scope=None, verdict=""):
        fills.append((scope, verdict))

    monkeypatch.setattr(acc, "_backfill_plan_gate", _fill)
    return rows, fills


# ─── 解析口径 ────────────────────────────────────────────────────────────────


def test_parse_accepts_plain_and_fenced_json():
    ok = json.dumps({"verdict": "partial", "reason": "第二条红线没满足"})
    assert sc.parse_selfcheck(ok)["verdict"] == "partial"
    assert sc.parse_selfcheck(f"```json\n{ok}\n```")["verdict"] == "partial"


@pytest.mark.parametrize(
    "raw",
    ["", "没有 JSON", '{"reason":"只有理由"}', '{"verdict":"ok"}', "[]"],
)
def test_parse_rejects_bad_shape(raw):
    with pytest.raises(ValueError):
        sc.parse_selfcheck(raw)


def test_verdicts_stay_inside_the_acceptance_vocabulary():
    """自评不许造第四种说法，也不许用 abstain 装死。

    验收口径里有 abstain（判官没判就留空）；自评不存在「不判」——要么给出
    结论，要么整条不写台账。把 abstain 写进自评，等于给台账灌一行假档位。
    """
    assert set(sc.VERDICTS) <= set(acc.VERDICTS)
    assert "abstain" not in sc.VERDICTS
    assert set(sc.VERDICTS) == {"satisfied", "partial", "failed"}


def test_build_prompt_carries_goal_answer_and_schema():
    txt = sc.build_prompt(query="修好左栏", answer="已完成并部署", skills=[])
    assert "修好左栏" in txt and "已完成并部署" in txt
    assert "satisfied" in txt and "partial" in txt and "failed" in txt


# ─── 熄火条件 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_config_stays_quiet(sink):
    rows, fills = sink
    out = await sc.judge_selfcheck(
        query="目标",
        answer="x" * 200,
        model=_Model('{"verdict":"satisfied","reason":"ok"}'),
        scope={"chat_id": "c1", "turn": 1},
        hub=_Hub(selfcheck_enabled=False),
    )
    assert out is None and rows == [] and fills == []


@pytest.mark.asyncio
async def test_acceptance_post_off_stays_quiet(sink):
    rows, _, = sink
    out = await sc.judge_selfcheck(
        query="目标",
        answer="x" * 200,
        model=_Model('{"verdict":"satisfied","reason":"ok"}'),
        scope={"chat_id": "c1", "turn": 1},
        hub=_Hub(off=("acceptance",)),
    )
    assert out is None


@pytest.mark.asyncio
async def test_short_answer_skips_selfcheck(sink):
    """寒暄类交付不自评：判了只产垃圾行，还白烧 token。"""
    rows, fills = sink
    out = await sc.judge_selfcheck(
        query="在吗",
        answer="在的",
        model=_Model('{"verdict":"satisfied","reason":"ok"}'),
        scope={"chat_id": "c1", "turn": 1},
        hub=_Hub(),
    )
    assert out is None and rows == [] and fills == []


@pytest.mark.asyncio
async def test_missing_model_stays_quiet(sink):
    rows, _ = sink
    out = await sc.judge_selfcheck(
        query="目标",
        answer="x" * 200,
        model=None,
        scope={"chat_id": "c1", "turn": 1},
        hub=_Hub(),
    )
    assert out is None and rows == []


# ─── 判得出：台账 + 回填 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verdict_writes_ledger_and_backfills(sink):
    rows, fills = sink
    out = await sc.judge_selfcheck(
        query="把左栏排序修好",
        answer="已修复排序并按 updated_at 排序，测试全绿。" * 6,
        model=_Model(
            '{"verdict":"partial","reason":"改了排序，没验证浏览器实测"}',
            model_name="qwen-chat",
        ),
        scope={"chat_id": "chat-9", "turn": 3},
        hub=_Hub(),
    )
    assert out is not None and out["verdict"] == "partial"
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "selfcheck"
    assert row["purpose"] == "selfcheck"
    assert row["action"] == "selfcheck:partial"
    assert row["outcome"] == "partial"
    assert row["model"] == "qwen-chat"
    assert row["hit_layer"] == "llm"
    assert row["latency_ms"] >= 0
    assert "没验证浏览器实测" in row["value"]
    assert fills == [({"chat_id": "chat-9", "turn": 3}, "partial")]


@pytest.mark.asyncio
async def test_stream_reply_is_collected(sink):
    """会话模型多是流式返回：自评必须把流收完再判，不能拿首块空内容当结论。"""
    rows, fills = sink
    out = await sc.judge_selfcheck(
        query="目标",
        answer="x" * 200,
        model=_StreamModel('{"verdict":"satisfied","reason":"三条红线都满足"}'),
        scope={"chat_id": "c1", "turn": 1},
        hub=_Hub(),
    )
    assert out is not None and out["verdict"] == "satisfied"
    assert rows[0]["tokens"] == 150


@pytest.mark.asyncio
async def test_all_three_verdicts_are_accepted(sink):
    rows, fills = sink
    for verdict in sc.VERDICTS:
        out = await sc.judge_selfcheck(
            query="目标",
            answer="x" * 200,
            model=_Model(json.dumps({"verdict": verdict, "reason": "r"})),
            scope={"chat_id": "c", "turn": 1},
            hub=_Hub(),
        )
        assert out is not None and out["verdict"] == verdict
    assert [r["outcome"] for r in rows] == list(sc.VERDICTS)
    assert [f[1] for f in fills] == list(sc.VERDICTS)


# ─── 判不出：一行都不许写 ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_junk_reply_writes_nothing(sink):
    """解析失败必须留空：垃圾自评会回填出假档位，比空白更坏。"""
    rows, fills = sink
    out = await sc.judge_selfcheck(
        query="目标",
        answer="x" * 200,
        model=_Model("我觉得做得挺好的，应该算完成吧。"),
        scope={"chat_id": "c1", "turn": 1},
        hub=_Hub(),
    )
    assert out is None and rows == [] and fills == []


@pytest.mark.asyncio
async def test_bad_verdict_writes_nothing(sink):
    rows, fills = sink
    out = await sc.judge_selfcheck(
        query="目标",
        answer="x" * 200,
        model=_Model('{"verdict":"great","reason":"好"}'),
        scope={"chat_id": "c1", "turn": 1},
        hub=_Hub(),
    )
    assert out is None and rows == [] and fills == []


@pytest.mark.asyncio
async def test_timeout_is_silence(sink):
    """超时即弃：自评在轮尾后台跑，绝不允许拖成一条长链。"""
    rows, fills = sink
    out = await sc.judge_selfcheck(
        query="目标",
        answer="x" * 200,
        model=_Model('{"verdict":"satisfied","reason":"ok"}', sleep=2.4),
        scope={"chat_id": "c1", "turn": 1},
        hub=_Hub(selfcheck_timeout_ms=2000),
    )
    assert out is None and rows == [] and fills == []


@pytest.mark.asyncio
async def test_model_exception_is_silence(sink):
    rows, fills = sink
    out = await sc.judge_selfcheck(
        query="目标",
        answer="x" * 200,
        model=_Model(boom=RuntimeError("provider down")),
        scope={"chat_id": "c1", "turn": 1},
        hub=_Hub(),
    )
    assert out is None and rows == [] and fills == []


@pytest.mark.asyncio
async def test_backfill_failure_does_not_break_ledger(sink, monkeypatch):
    """回填失败不影响台账：两处记账彼此独立。"""
    rows, _ = sink

    async def _boom(*, scope=None, verdict=""):
        raise RuntimeError("db locked")

    monkeypatch.setattr(acc, "_backfill_plan_gate", _boom)
    out = await sc.judge_selfcheck(
        query="目标",
        answer="x" * 200,
        model=_Model('{"verdict":"satisfied","reason":"ok"}'),
        scope={"chat_id": "c1", "turn": 1},
        hub=_Hub(),
    )
    assert out is not None and len(rows) == 1


@pytest.mark.asyncio
async def test_backfill_is_awaited_not_just_called(sink):
    """回填必须真的被 await：取协程不 await，档位会一直卡 pending（台账实测
    outcome 100% pending 的一半成因）。
    """
    rows, fills = sink
    seen = []

    async def _spy(*, scope=None, verdict=""):
        await asyncio.sleep(0)
        seen.append((scope, verdict))

    import coapis.decision.hub_acceptance as _acc

    old = _acc._backfill_plan_gate
    _acc._backfill_plan_gate = _spy
    try:
        out = await sc.judge_selfcheck(
            query="目标",
            answer="x" * 200,
            model=_Model('{"verdict":"failed","reason":"没动手"}'),
            scope={"chat_id": "c7", "turn": 4},
            hub=_Hub(),
        )
    finally:
        _acc._backfill_plan_gate = old
    assert out is not None
    assert seen == [({"chat_id": "c7", "turn": 4}, "failed")]


# ─── 发射（fire-and-forget）────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fire_selfcheck_delivers_result(sink):
    rows, fills = sink
    got = []
    task = sc.fire_selfcheck(
        query="目标",
        answer="x" * 200,
        model=_Model('{"verdict":"failed","reason":"没动手改"}'),
        scope={"chat_id": "c1", "turn": 2},
        hub=_Hub(),
        on_done=got.append,
    )
    assert task is not None
    await task
    await asyncio.sleep(0)
    assert got and got[0]["verdict"] == "failed"
    assert rows[0]["source"] == "selfcheck"


@pytest.mark.asyncio
async def test_fire_selfcheck_swallows_model_crash(sink):
    rows, _ = sink
    task = sc.fire_selfcheck(
        query="目标",
        answer="x" * 200,
        model=_Model(boom=RuntimeError("boom")),
        scope={"chat_id": "c1", "turn": 2},
        hub=_Hub(),
        on_done=lambda r: pytest.fail("不该回调"),
    )
    await task
    assert rows == []


# ─── 配置与台账口径 ─────────────────────────────────────────────────────────


def test_selfcheck_is_a_ledger_source():
    assert "selfcheck" in SOURCES


def test_config_defaults_and_clamps():
    cfg = DecisionHubConfig.from_dict({})
    assert cfg.selfcheck_enabled is True
    assert cfg.selfcheck_timeout_ms == 20000
    assert cfg.selfcheck_min_answer_chars == 80
    # 夹取：过短的自评尺子判不出东西，过长的会在轮尾拖成尾巴
    tight = DecisionHubConfig.from_dict({"selfcheck_timeout_ms": 10})
    assert tight.selfcheck_timeout_ms == 2000
    loose = DecisionHubConfig.from_dict({"selfcheck_timeout_ms": 999999})
    assert loose.selfcheck_timeout_ms == 60000
    off = DecisionHubConfig.from_dict({"selfcheck_enabled": False})
    assert off.selfcheck_enabled is False
    # 必须能从 as_dict 复原（热加载链路靠这一对）
    assert cfg.as_dict()["selfcheck_enabled"] is True
    assert DecisionHubConfig.from_dict(
        cfg.as_dict(),
    ).selfcheck_timeout_ms == 20000


def test_model_label_falls_back_to_inner_model():
    class _Inner:
        model_name = "inner-model"

    class _Wrapper:
        _model = _Inner()

    assert sc._label_of(_Model(model_name="outer")) == "outer"
    assert sc._label_of(_Wrapper()) == "inner-model"
    assert sc._label_of(object()).startswith("unknown:")
