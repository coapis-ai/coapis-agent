# -*- coding: utf-8 -*-
"""B0 契约锁 · 用量口径（方案 v1 §3 第 0 批 / D1-D3）

分两段，口径不同，不许混：

* **现状锁**（普通断言）—— 锁今天已经成立的语义。B1 动刀时如果把这几条
  改松了，全量测试立刻变红。
* **目标锁**（``xfail(strict=True)``）—— 锁 B1 要交付的契约。今天必须是
  **失败**，所以标成 xfail：全量测试因此仍然全绿，而 B1 完成后它们会
  变 XPASS→在 strict 下判红，逼着实现方把标记摘掉。**标记不会自己消失，
  这是刻意的**：目标兑现必须以"摘掉 xfail"为凭据，不留哑目标。

取证口径（写在这里，免得下一个人猜）：
  - 主模型用量在 ``TokenRecordingModelWrapper._record_usage`` 取得，
    入参是 agentscope 的 ``ChatUsage(input_tokens, output_tokens, time, ...)``。
  - **``ChatUsage.time`` 现成就有**（秒），今天的实现读都不读就丢了 ——
    B1 的"每轮耗时"不需要新增埋点，只需要别扔。
  - token 取不到（流式不回 usage）时 pt/ct 双 0 → 直接 return，
    表里那一行**从来没有过**，这就是 PRD C1 的"tokens 恒 0"的一半。
"""
from __future__ import annotations

import asyncio

import pytest
from agentscope.model._model_usage import ChatUsage

# 尺子口径（B1）：生产写入侧是 ``coapis.config.session_context``
# （runner.py / console.py 实测都写它）；``app.agent_context`` 是另一套
# ContextVar，两边各写一份就是"两把尺子"——契约只认 session_context。
from coapis.config.session_context import (
    set_current_agent_id,
    set_current_session_id,
)
from coapis.providers.retry_chat_model import RETRYABLE_STATUS_CODES
from coapis.token_usage.buffer import _UsageEvent
from coapis.token_usage.model_wrapper import TokenRecordingModelWrapper

# 目标锁：B1 交付后这些必须变 XPASS（strict 下即判红 → 摘标记）。
# 2026-11-14 B1-A 交付时摘掉 5 条（逐轮 usage 已落库 + clear 补 chat/turn）；
# 仍挂着的 @B1 都是未交付项，不许提前摘。
# 2026-11-14 B1-B 又摘 1 条（冻结尺子：集合元素一个没动，只换成 frozenset）。
B1 = pytest.mark.xfail(
    strict=True,
    reason="B1 目标契约：逐轮用量带 chat_id/turn/latency 并落库（未实现）",
)


def _wrapper(provider_id: str = "p-contract") -> TokenRecordingModelWrapper:
    """绕开 __init__ 的模型依赖，只装用量记账需要的字段。"""
    wrapper = TokenRecordingModelWrapper.__new__(TokenRecordingModelWrapper)
    wrapper._provider_id = provider_id
    wrapper.model_name = "m-contract"
    wrapper.stream = False
    return wrapper


@pytest.fixture(autouse=True)
def _clean_session_state():
    TokenRecordingModelWrapper._usage_by_session.clear()
    yield
    TokenRecordingModelWrapper._usage_by_session.clear()


# ── 1. 可重试状态码：一把尺子，不许两份 ──────────────────────────────────


def test_retryable_status_codes_cover_rate_limit_and_upstream():
    # 429/529=限流，500/502/503/504=上游坏了：这几类**必须**可重试。
    # 少一类，就会把"临时失败"变成"这轮没有用量记录"。
    assert {429, 529, 500, 502, 503, 504} <= set(RETRYABLE_STATUS_CODES)


def test_retryable_status_codes_are_frozen_set():
    # 它是"用量/重试/熔断"共用的尺子，运行时必须只读。
    # 现状是可变 set：B1 冻结它（frozenset），防止任何模块就地 .add()。
    assert isinstance(RETRYABLE_STATUS_CODES, frozenset)


def test_retryable_status_codes_are_single_source():
    # 全仓只允许一处定义这把尺子（PRD C2 的"两份实现"病灶）：
    # 别的模块要用必须 import 这个常量，不许自己抄一份字面量。
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    hits = []
    for py in repo.glob("server/coapis/**/*.py"):
        if py.name == "retry_chat_model.py":
            continue  # 唯一定义点
        text = py.read_text(encoding="utf-8", errors="ignore")
        # 判据：同时出现 429 与 529 的状态码集合字面量 = 另一把尺子
        if "429" in text and "529" in text and "status" in text.lower():
            hits.append(str(py.relative_to(repo)))
    assert hits == [], f"可重试状态码在多处各写一份：{hits}"


# ── 2. 用量事件的形状（现状：五个必填字段） ─────────────────────────────


def test_usage_event_shape_is_the_disk_contract():
    # 落盘/聚合都以这些字段为键，改名等于历史清零。
    # B1 交付：追加逐轮面五字段（与迁移 0026 同名列）；旧六字段一个没动，
    # 历史聚合读面因此不受影响。
    fields = set(_UsageEvent._fields)
    assert fields == {
        "provider_id",
        "model_name",
        "prompt_tokens",
        "completion_tokens",
        "date_str",
        "now_iso",
        "chat_id",
        "session_id",
        "turn_index",
        "latency_ms",
        "api_call_id",
    }


def test_usage_event_carries_call_identity_and_turn():
    # 逐轮落库要求每条事件说清"属于哪一次调用、哪一轮、谁发起"。
    ev = _UsageEvent(
        provider_id="p",
        model_name="m",
        prompt_tokens=1,
        completion_tokens=1,
        date_str="2026-11-13",
        now_iso="2026-11-13T00:00:00+00:00",
        chat_id="chat-1",
        api_call_id="call-1",
        session_id="s-1",
        turn_index=3,
        latency_ms=812,
    )
    assert ev.chat_id == "chat-1"
    assert ev.api_call_id == "call-1"
    assert ev.turn_index == 3
    assert ev.latency_ms == 812


def test_usage_event_token_fields_default_to_zero():
    # 归因字段必须保持可选（新增字段不许让既有调用点构造失败），
    # token 缺省为 0 —— 0 进账由 _record_usage 的闸门负责拦（见 §3）。
    ev = _UsageEvent(
        provider_id="p",
        model_name="m",
        prompt_tokens=0,
        completion_tokens=0,
        date_str="2026-11-13",
        now_iso="2026-11-13T00:00:00+00:00",
    )
    assert (ev.prompt_tokens, ev.completion_tokens) == (0, 0)
    assert getattr(ev, "chat_id", None) in ("", None)


# ── 3. 取用规则：0 用量不进账、pop 一次性、会话互相隔离 ─────────────────


def test_zero_token_usage_is_not_recorded():
    # 0/0 的"用量"进表就是污染：统计会把空轮算成成功轮。
    wrapper = _wrapper()
    set_current_session_id("contract-zero")
    wrapper._record_usage(ChatUsage(input_tokens=0, output_tokens=0, time=0.0))
    assert not TokenRecordingModelWrapper._usage_by_session.get("contract-zero")


def test_usage_none_is_tolerated():
    # 上游没给 usage 不能炸主链（PRD C1 的失败面：宁可不记，不可崩）。
    wrapper = _wrapper()
    set_current_session_id("contract-none")
    wrapper._record_usage(None)
    assert not TokenRecordingModelWrapper._usage_by_session.get("contract-none")


def test_record_usage_stores_session_totals():
    wrapper = _wrapper()
    set_current_session_id("contract-agg")
    wrapper._record_usage(
        ChatUsage(input_tokens=10, output_tokens=5, time=1.2),
    )
    got = TokenRecordingModelWrapper.pop_usage_for_session("contract-agg")
    assert got is not None
    assert got["prompt_tokens"] == 10
    assert got["completion_tokens"] == 5
    assert got["total_tokens"] == 15


def test_pop_usage_for_session_is_single_use():
    # pop 语义锁死：取一次就没了。B1 若改成"读取"，同一轮会被计两次。
    wrapper = _wrapper()
    sid = "contract-pop"
    set_current_session_id(sid)
    wrapper._record_usage(
        ChatUsage(input_tokens=40, output_tokens=2, time=0.5),
    )
    first = TokenRecordingModelWrapper.pop_usage_for_session(sid)
    second = TokenRecordingModelWrapper.pop_usage_for_session(sid)
    assert first is not None and first["total_tokens"] == 42
    assert second is None


def test_pop_usage_is_per_session_isolated():
    TokenRecordingModelWrapper._usage_by_session["A"] = {"total_tokens": 1}
    TokenRecordingModelWrapper._usage_by_session["B"] = {"total_tokens": 2}
    got = TokenRecordingModelWrapper.pop_usage_for_session("A")
    assert got is not None and got["total_tokens"] == 1
    # A 被取走不许影响 B（会话串数据是最难查的 bug）
    assert "B" in TokenRecordingModelWrapper._usage_by_session


# ── 4. B1 目标：每轮一行、带归因与耗时、写进 token_usage ────────────────


def test_record_usage_keeps_latency_from_chatusage():
    # ChatUsage.time 现成就有（秒）。现状实现直接丢掉 → 台账 latency 恒 0。
    wrapper = _wrapper()
    sid = "contract-latency"
    set_current_session_id(sid)
    wrapper._record_usage(
        ChatUsage(input_tokens=3, output_tokens=4, time=0.812),
    )
    got = TokenRecordingModelWrapper.pop_usage_for_session(sid)
    assert got is not None
    assert int(got["latency_ms"]) == 812


def test_record_usage_carries_chat_identity(tmp_path, monkeypatch):
    # 归因三件套（chat_id / session_id / turn_index）必须在事件里，
    # 否则 token_usage 永远无法按轮对账 —— PRD C1 的病根。
    wrapper = _wrapper()
    sid = "contract-identity"
    set_current_session_id(sid)
    set_current_agent_id("user:contract")
    wrapper._record_usage(
        ChatUsage(input_tokens=2, output_tokens=3, time=0.1),
    )
    got = TokenRecordingModelWrapper.pop_usage_for_session(sid)
    assert got is not None
    assert got["chat_id"] == sid
    assert got["turn_index"] >= 1


def test_record_usage_writes_one_db_row_per_call(tmp_path, monkeypatch):
    # 终态判据（方案 §4 验收 1）：一次调用 → token_usage 一行且 tokens>0。
    from coapis.token_usage import db_writer

    captured: list[dict] = []
    monkeypatch.setattr(
        db_writer,
        "save_token_usage",
        lambda **kw: captured.append(kw),
    )
    wrapper = _wrapper()
    set_current_session_id("contract-dbrow")
    set_current_agent_id("user:contract")
    wrapper._record_usage(
        ChatUsage(input_tokens=7, output_tokens=8, time=0.3),
    )
    assert len(captured) == 1
    row = captured[0]
    assert row["input_tokens"] == 7 and row["output_tokens"] == 8
    assert row.get("chat_id") == "contract-dbrow"
    assert row.get("latency_ms", 0) > 0


def test_record_usage_never_raises_on_db_failure(monkeypatch):
    # 台账坏了不能停主链（与 ledger_contract 同一条红线）。
    from coapis.token_usage import db_writer

    def _boom(**_kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(db_writer, "save_token_usage", _boom)
    wrapper = _wrapper()
    set_current_session_id("contract-dbfail")
    set_current_agent_id("user:contract")
    wrapper._record_usage(
        ChatUsage(input_tokens=1, output_tokens=1, time=0.1),
    )
    # 不抛异常即为通过；用量仍应留在会话侧供兜底
    assert TokenRecordingModelWrapper.pop_usage_for_session("contract-dbfail")


def test_session_context_exposes_identity_pair_and_reset():
    # B1 靠 ContextVar 把 chat_id/turn 送到 provider 层；
    # 三个接口缺一个，归因就会跨请求泄漏（跨用户串数据）。
    from coapis.config import session_context as sc

    for name in (
        "get_current_chat_id",
        "set_current_chat_id",
        "get_current_turn_id",
        "set_current_turn_id",
        "clear_session_context",
    ):
        assert hasattr(sc, name), f"session_context 缺 {name}"

    sc.set_current_chat_id("contract-chat")
    sc.set_current_turn_id("contract-turn")
    assert sc.get_current_chat_id() == "contract-chat"
    assert sc.get_current_turn_id() == "contract-turn"


def test_clear_session_context_resets_chat_and_turn():
    # 实测缺陷（B0 取证）：clear_session_context 清了 9 个变量，
    # **漏了 _CHAT_ID 与 _TURN_ID** —— 长连接处理器"清完上下文"后，
    # 下一轮仍带着上一轮的 chat_id 写台账，归因从此串轮。
    from coapis.config import session_context as sc

    sc.set_current_chat_id("contract-leak")
    sc.set_current_turn_id("turn-leak")
    sc.clear_session_context()
    assert sc.get_current_chat_id() in (None, "")
    assert sc.get_current_turn_id() in (None, "")
