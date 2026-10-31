# -*- coding: utf-8 -*-
"""智能判断中枢 第0批（F1/F2/F3）测试。

对应 tech_docs/智能判断中枢设计方案-定稿v13.md 第 1 章：

- F1 技能选择器异步死分支：``_llm_classify_sync`` 在事件循环内不再静默
  ``return []``，改为明确 WARNING 留痕；新增异步入口 ``select_async`` /
  ``_llm_classify``，兜底判在异步链里真正执行。
- F2 线程池兜底：``react_agent._llm_classify_skills`` 改为异步原生
  （await 直连 + ``asyncio.wait_for`` 超时硬限），删除线程池/嵌套事件循环。
- F3 兜底路径异步补判：``_load_on_demand_skills`` 异步化，Phase 2 真 await。

Run: python3 -m pytest server/tests/test_decision_hub_batch0.py -q
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import types
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from coapis.agents.react_agent import CoApisAgent
from coapis.agents.utils import intent_classifier
from coapis.agents.utils.skill_selector import SkillSelector


def meta(name, desc, triggers=(), hints=""):
    return {
        name: {
            "description": desc,
            "trigger_keywords": list(triggers),
            "keyword_weights": {k: 2.0 for k in triggers},
            "intent_hints": hints,
        }
    }


def make_selector(skill_meta, config=None, scene_skills=None):
    s = SkillSelector(config=config, scene_skills=scene_skills)
    s.build_index(skill_meta, scene_skills=scene_skills)
    return s


# --------------------------------------------------------------------------
# F2 / F3 — react_agent 兜底判异步化
# --------------------------------------------------------------------------
class _AgentStub:
    """借用 CoApisAgent 的兜底判方法，避免构造完整 agent。"""

    _skill_judge_model_name = CoApisAgent._skill_judge_model_name
    _decision_hub = CoApisAgent._decision_hub
    _decision_scope = CoApisAgent._decision_scope
    _llm_classify_skills = CoApisAgent._llm_classify_skills
    _decision_hub = CoApisAgent._decision_hub
    _decision_scope = CoApisAgent._decision_scope
    _skill_llm_timeout_s = CoApisAgent._skill_llm_timeout_s
    _agent_id = ""
    _agent_config = None
    _user_id = ""
    _current_chat_id = ""
    _reasoning_turn = 0
    # 生产 __init__ 里的留痕字段，桩必须齐（降级留痕靠它断言）
    _skill_trigger_reason = ""

    def __init__(self, skill_names, config=None):
        self._on_demand_skills = {
            n: (f"/tmp/skills/{n}", []) for n in skill_names
        }
        self._skill_selector = types.SimpleNamespace(config=config or {})

    def _get_skill_summary(self, skill_dir, max_len=500):
        return f"summary of {Path(skill_dir).name}"

    def _get_skill_intent_hints(self, skill_dir):
        return []


def test_llm_classify_skills_is_coroutine():
    """F2：兜底判必须是协程函数（不再同步阻塞/线程池）。"""
    assert inspect.iscoroutinefunction(CoApisAgent._llm_classify_skills)


def test_load_on_demand_skills_is_coroutine():
    """F3：Phase1/Phase2 入口必须可 await。"""
    assert inspect.iscoroutinefunction(CoApisAgent._load_on_demand_skills)


def test_no_threadpool_or_nested_loop_in_fallback():
    """F2：源码里不得再出现线程池 / asyncio.run 嵌套事件循环（看代码不看注释）。"""
    src = inspect.getsource(CoApisAgent._llm_classify_skills)
    body = src.split('"""')[2] if src.count('"""') >= 2 else src
    assert "ThreadPoolExecutor" not in body
    assert "asyncio.run" not in body
    assert "concurrent.futures" not in body


@pytest.mark.asyncio
async def test_llm_classify_skills_returns_matches(monkeypatch):
    async def fake_llm(message, summaries, timeout=3.0, **_kw):
        assert "pdf" in summaries
        return ["pdf"]

    monkeypatch.setattr(intent_classifier, "classify_intent_llm", fake_llm)
    stub = _AgentStub(["pdf", "mail"])
    got = await stub._llm_classify_skills("帮我把这份 pdf 转成图片")
    assert got == ["pdf"]


# --------------------------------------------------------------------------
# 判官不可用时消费方契约（v14 §4.4②③）——走真实判断网关
# --------------------------------------------------------------------------
@contextlib.contextmanager
def _hub_chain(monkeypatch, tmp_path, invoke, rows=None):
    """把兜底判接在真实判断网关上，判官层用注入的假模型调用。

    batch0 时代是整层替换 classify_intent_llm，超时/异常由消费方自己兜；
    v14 起超时与降级归网关管，测试必须走真实链路，别把网关跳过。
    ``rows`` 传入列表时收集台账行，便于断言入账内容。
    """
    from coapis.decision import config as cfg
    from coapis.decision import gateway as gw

    provider = types.SimpleNamespace(
        provider_id="p1",
        provider_type="openai",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=[{"id": "m1", "name": "m1", "type": "chat"}],
        get_effective_generate_kwargs=lambda model_id=None: {"top_k": None},
    )

    async def _fake_ledger(_self, purpose, reply, _describe, **_ids):
        if rows is not None:
            rows.append((purpose, reply.hit_layer, reply.reason))

    monkeypatch.setattr(
        gw,
        "get_judgment_provider_config",
        lambda **_kw: {"provider_id": "p1", "model": "m1"},
    )
    with ExitStack() as stack:
        for _name, replacement in (
            ("_get_provider", lambda _self, _pid: provider),
            ("_model_type", lambda _self, _p, _m: "chat"),
            ("_invoke", invoke),
            ("_ledger", _fake_ledger),
        ):
            stack.enter_context(patch.object(gw.JudgeGateway, _name, replacement))
        monkeypatch.setenv("COAPIS_DECISION_ENABLED", "1")
        monkeypatch.setenv("COAPIS_DECISION_LLM_TIMEOUT_MS", "200")
        monkeypatch.setenv("COAPIS_DECISION_LLM_BUDGET_PER_TURN", "1")
        monkeypatch.setenv("COAPIS_DECISION_CACHE_ENABLED", "0")
        cfg.reset_hub_config()
        gw.reset_judge_gateway()
        try:
            yield
        finally:
            gw.reset_judge_gateway()
            cfg.reset_hub_config()


@pytest.mark.asyncio
async def test_llm_classify_skills_timeout_returns_empty(monkeypatch, tmp_path, caplog):
    """超时硬限（走真实判断网关）：判官卡住 → 空结果 + 降级留痕，不阻塞主流程。"""

    async def slow_invoke(_self, _provider, _model_id, _system, _user, _kwargs):
        await asyncio.sleep(5)
        return ("pdf", 10, 2)

    stub = _AgentStub(["pdf", "mail"])
    rows: list[tuple] = []
    with caplog.at_level(logging.WARNING):
        with _hub_chain(monkeypatch, tmp_path, slow_invoke, rows):
            got = await stub._llm_classify_skills("帮我把这份 pdf 转成图片")
    assert got == []
    # 消费方留痕写明判官兜底判空；台账记下真正的降级层与原因
    assert stub._skill_trigger_reason.startswith("judge_empty")
    assert rows and rows[0][0] == "skill_trigger"
    assert rows[0][1] == "timeout"
    assert "判断超时" in rows[0][2]


@pytest.mark.asyncio
async def test_llm_classify_skills_exception_returns_empty(monkeypatch, tmp_path, caplog):
    """异常降级（走真实判断网关）：提供商炸了 → 空结果 + 台账记 transport 层。"""

    async def boom_invoke(_self, _provider, _model_id, _system, _user, _kwargs):
        raise RuntimeError("provider down")

    stub = _AgentStub(["pdf", "mail"])
    rows: list[tuple] = []
    with caplog.at_level(logging.WARNING):
        with _hub_chain(monkeypatch, tmp_path, boom_invoke, rows):
            got = await stub._llm_classify_skills("帮我把这份 pdf 转成图片")
    assert got == []
    assert stub._skill_trigger_reason.startswith("judge_empty")
    assert rows and rows[0][1] == "transport"
    assert "判断调用失败" in rows[0][2]



@pytest.mark.asyncio
async def test_llm_classify_skills_no_candidates_skips_llm(monkeypatch):
    called = False

    async def fake_llm(message, summaries, timeout=3.0, **_kw):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(intent_classifier, "classify_intent_llm", fake_llm)
    stub = _AgentStub([])
    assert await stub._llm_classify_skills("hello") == []
    assert called is False


def test_skill_llm_timeout_s_reads_config():
    assert _AgentStub([], config={"llm_timeout_ms": 1500})._skill_llm_timeout_s() == 1.5
    assert _AgentStub([], config={"llm_timeout_ms": 0})._skill_llm_timeout_s() == 0.5
    assert _AgentStub([], config={})._skill_llm_timeout_s() == 3.0
    assert _AgentStub([], config={"llm_timeout_ms": "abc"})._skill_llm_timeout_s() == 3.0


# --------------------------------------------------------------------------
# F1 — 技能选择器：异步入口 + 死分支去静默
# --------------------------------------------------------------------------
def test_selector_has_async_entry():
    assert inspect.iscoroutinefunction(SkillSelector.select_async)
    assert inspect.iscoroutinefunction(SkillSelector._llm_classify)


@pytest.mark.asyncio
async def test_selector_llm_classify_async_match(monkeypatch):
    async def fake_llm(message, summaries, timeout=3.0, **_kw):
        assert "mail" in summaries
        assert "发邮件" in summaries["mail"]  # intent_hints 进 prompt
        return ["mail"]

    monkeypatch.setattr(intent_classifier, "classify_intent_llm", fake_llm)
    sm = meta("mail", "邮件收发", hints="发邮件")
    sel = make_selector(sm)
    assert await sel._llm_classify("帮我发封邮件给张三", None) == ["mail"]


@pytest.mark.asyncio
async def test_selector_llm_classify_async_timeout(monkeypatch, caplog):
    async def slow_llm(message, summaries, timeout=3.0, **_kw):
        await asyncio.sleep(5)
        return ["mail"]

    monkeypatch.setattr(intent_classifier, "classify_intent_llm", slow_llm)
    sel = make_selector(meta("mail", "邮件收发"), config={"llm_timeout_ms": 200})
    with caplog.at_level(logging.WARNING):
        got = await sel._llm_classify("发邮件", None)
    assert got == []
    assert any("timed out" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_selector_llm_classify_async_failure_returns_empty(monkeypatch, caplog):
    async def boom(message, summaries, timeout=3.0, **_kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(intent_classifier, "classify_intent_llm", boom)
    sel = make_selector(meta("mail", "邮件收发"))
    with caplog.at_level(logging.WARNING):
        assert await sel._llm_classify("发邮件", None) == []
    assert any("provider down" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_sync_entry_warns_instead_of_silently_skipping(caplog):
    """F1：同步入口落在事件循环内必须 WARNING 留痕（旧代码是 debug 级静默）。"""
    sel = make_selector(meta("mail", "邮件收发"))
    with caplog.at_level(logging.WARNING):
        got = sel._llm_classify_sync("发邮件", None)
    assert got == []
    msgs = " ".join(r.message for r in caplog.records)
    assert "select_async" in msgs


@pytest.mark.asyncio
async def test_select_async_uses_llm_when_keywords_miss(monkeypatch):
    async def fake_llm(message, summaries, timeout=3.0, **_kw):
        return ["mail"]

    monkeypatch.setattr(intent_classifier, "classify_intent_llm", fake_llm)
    sel = make_selector(meta("mail", "邮件收发", triggers=["邮件"]))
    got = await sel.select_async("帮我给张三发封通知")  # 无关键词命中 → 兜底判
    assert "mail" in got


@pytest.mark.asyncio
async def test_select_async_skips_llm_when_keywords_hit(monkeypatch):
    calls = []

    async def fake_llm(message, summaries, timeout=3.0, **_kw):
        calls.append(message)
        return []

    monkeypatch.setattr(intent_classifier, "classify_intent_llm", fake_llm)
    sel = make_selector(meta("mail", "邮件收发", triggers=["邮件"]))
    got = await sel.select_async("帮我发一封邮件")
    assert got == ["mail"]
    assert calls == [], "关键词命中不应触发兜底判（零 LLM 开销）"


def test_select_sync_keyword_path_unchanged():
    """关键词命中路径不受本次改造影响（回归保护）。"""
    sm = meta("pdf", "处理 PDF 文件", triggers=["pdf"])
    sm["xlsx"] = {"description": "表格处理", "trigger_keywords": [], "keyword_weights": {}}
    sel = make_selector(sm)
    assert sel.select("把这个 pdf 转成表格")[0] == "pdf"


def test_llm_summaries_excludes_always_load():
    sm = meta("mail", "邮件收发")
    sm["memory"] = {
        "description": "记忆检索",
        "trigger_keywords": [],
        "keyword_weights": {},
        "always_load": True,
    }
    sel = SkillSelector()
    sel.build_index(sm)
    summaries = sel._llm_summaries(None)
    assert "mail" in summaries
    assert "memory" not in summaries


def test_prepare_selection_and_finalize():
    sm = meta("pdf", "处理 PDF 文件", triggers=["pdf"])
    sel = make_selector(sm)
    # 空消息 → 无可选项（select 回落 always_load）
    assert sel._prepare_selection("", None) is None
    assert sel.select("") == list(sel.always_load_skills)
    # 场景候选限制
    assert sel._llm_candidates(["pdf"]) == ["pdf"]
    assert sel._llm_candidates(["nope"]) == []
    assert sel._llm_candidates([]) is None
    # 去重 + 上限
    assert sel._finalize_selection(["pdf", "pdf", "mail"], top_k=1) == ["pdf"]
    # Stage 0/1 命中
    scene_names, selected = sel._prepare_selection("处理 pdf", None)
    assert "pdf" in selected
