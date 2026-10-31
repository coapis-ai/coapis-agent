"""判断中枢台账真实性测试（v14 收尾：台账要能被查询，不能是垃圾值）。

覆盖 dev 实测的四条缺陷：
  1. complexity 列塞判断值整串（'select:low,medium'）→ 只写档位
  2. 判档行身份取构造期 request_context → 改取每请求上下文
  3. 轮号恒 0（pre_reply 钩子跑在 reply 体自增之前）→ 轮次时钟
  4. 预算键在全空作用域下退化成全平台共用 → 判官永久熔断
"""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from coapis.agents.react_agent import CoApisAgent  # noqa: E402
from coapis.config import session_context as sc  # noqa: E402
from coapis.decision.gateway import JudgeGateway, _level_of  # noqa: E402


def _fake_agent(request_context, config_id="agent-from-config"):
    return types.SimpleNamespace(
        _request_context=request_context,
        _agent_config=types.SimpleNamespace(id=config_id),
        _turn_seq=0,
    )


@pytest.fixture(autouse=True)
def _clean_session_context():
    """每条测试前后把请求上下文显式置空。

    身份取自 contextvar，前一条设的值会串进后一条。这里用
    ``set_session_context("")`` 而不是 ``clear_session_context()``：
    实测 clear 之后取值仍是上一条的值，测试会去断言残留而不是被测行为。
    """
    blank = dict(user_id="", agent_id="", session_id="", chat_id="")
    sc.set_session_context(**blank)
    yield
    sc.set_session_context(**blank)


# ------------------------------------------------------------------ 1) 档位
def test_level_of_extracts_level_only():
    """台账的复杂度列只放档位，不放判断值整串。"""
    assert _level_of("select:low,medium") == "medium"
    assert _level_of("select:minimal,simple") == "simple"
    assert _level_of("select:high,complex") == "complex"
    assert _level_of("medium") == "medium"


def test_level_of_never_invents_level():
    """解析不出来就空着——空档位比假档位好，假档位污染所有分组统计。"""
    assert _level_of("") == ""
    assert _level_of("advise:change") == ""
    assert _level_of("select:weird,x") == ""


def test_level_of_vocab_matches_plan_gate():
    """词表必须与 plan_gate.LEVELS 逐字一致，否则判档行永远解析成空。"""
    from coapis.agents.plan_gate import LEVELS
    from coapis.decision import gateway

    assert set(gateway._LEVELS) == set(LEVELS)


# ------------------------------------------------------------- 2) 作用域身份
def test_scope_prefers_per_request_context():
    """构造期 request_context 是空的（共享实例），身份必须来自请求上下文。"""
    agent = _fake_agent({})
    sc.set_session_context(
        user_id="u-real",
        agent_id="a-real",
        session_id="s-real",
        chat_id="c-real",
    )
    scope = CoApisAgent._decision_scope(agent)
    assert scope["user_id"] == "u-real"
    assert scope["agent_name"] == "a-real"
    assert scope["chat_id"] == "c-real"
    assert scope["session_id"] == "s-real"


def test_scope_falls_back_and_never_writes_fake_values():
    """请求上下文不可用时退回 request_context；取不到就空串，不写 None。"""
    agent = _fake_agent({"user_id": "u-ctx", "agent_id": "a-ctx"})
    scope = CoApisAgent._decision_scope(agent)
    assert scope["user_id"] == "u-ctx"
    assert scope["agent_name"] == "a-ctx"
    assert scope["chat_id"] == ""
    assert "None" not in {scope["user_id"], scope["agent_name"], scope["chat_id"]}


def test_scope_no_identity_at_all_is_all_empty_strings():
    """啥都取不到时：user/chat 空串，agent 退回智能体配置 id，绝不写 None/'auto'。"""
    agent = _fake_agent({})
    scope = CoApisAgent._decision_scope(agent)
    assert scope["user_id"] == ""
    assert scope["chat_id"] == ""
    assert scope["agent_name"] == "agent-from-config"
    assert "None" not in scope["agent_name"]


# ---------------------------------------------------------------- 3) 轮次时钟
def test_turn_clock_increments_per_reply():
    """每轮 +1：判档在 pre_reply 跑，拿到的必须是本轮轮号（>=1）。"""
    agent = _fake_agent({})
    CoApisAgent._hub_turn_clock_hook(agent)
    CoApisAgent._hub_turn_clock_hook(agent)
    assert agent._turn_seq == 2
    assert CoApisAgent._decision_scope(agent)["turn"] == 2


def test_turn_clock_survives_broken_counter():
    """轮号被写成坏数据也不能抛断回合。"""
    agent = _fake_agent({})
    agent._turn_seq = "不是数字"
    CoApisAgent._hub_turn_clock_hook(agent)
    assert agent._turn_seq == 1


# ----------------------------------------------------------------- 4) 预算键
def _key_of(gw, ids: dict, turn: int):
    """复刻 gateway 里的预算键构造（与实现同步：漂移由下面那条测试钉住）。"""
    key = (
        ids.get("user_id", ""),
        ids.get("agent_id", ""),
        ids.get("chat_id", "") or ids.get("session_id", ""),
        turn,
    )
    if not any(key):
        key = (id(gw), ids.get("purpose", ""), turn)
    return key


def test_budget_key_separates_chats_when_chat_missing():
    """chat 取空时用 session 分开，两个会话不再共用一个预算。"""
    gw = JudgeGateway()
    a = _key_of(gw, {"chat_id": "", "session_id": "sess-A"}, 1)
    b = _key_of(gw, {"chat_id": "", "session_id": "sess-B"}, 1)
    assert a != b


def test_budget_key_all_empty_is_not_shared_globally():
    """四项全空时键里带实例身份，绝不出现"全平台一个键"导致永久熔断。"""
    assert _key_of(JudgeGateway(), {}, 0) != _key_of(JudgeGateway(), {}, 0)


def test_gateway_budget_key_matches_replica():
    """实现与复刻必须一致：直接读源码，防两处漂移。"""
    import inspect

    src = inspect.getsource(JudgeGateway.judge)
    assert 'ids["chat_id"] or ids.get("session_id", "")' in src
    assert "if not any(tkey):" in src
    assert 'tkey = (ids["user_id"], ids["agent_id"], ids["chat_id"], turn)' not in src


def test_budget_cap_recovers_when_turn_advances():
    """预算按轮计：同一会话跑到下一轮，判官必须重新可用（不是永久熔断）。"""
    gw = JudgeGateway()
    ids = {"chat_id": "", "session_id": "s1", "purpose": "plan_gate"}

    def capped(turn):
        key = _key_of(gw, ids, turn)
        used = gw._turn_calls.get(key, 0)
        gw._turn_calls[key] = used + 1
        return used >= 2

    assert capped(1) is False
    assert capped(1) is False
    assert capped(1) is True  # 第 3 次触顶
    assert capped(2) is False  # 换轮即恢复


# -------------------------------------------------------------- 5) 落库行内容
@pytest.mark.asyncio
async def test_ledger_row_carries_level_tokens_and_scope(monkeypatch):
    """判档行落库时：complexity=档位、tokens=真实用量、作用域齐全。

    直接截获总线收到的那一行——台账的列值就是在这里定形的。
    """
    from coapis.decision import gateway as gw_mod

    caught = []
    real_bus = gw_mod.get_bus()

    class _Bus:
        def emit(self, row):
            caught.append(row)

    monkeypatch.setattr(gw_mod, "get_bus", lambda: _Bus())
    monkeypatch.setattr(
        gw_mod, "get_hub_config", lambda: types.SimpleNamespace(ledger_enabled=True)
    )

    gw = JudgeGateway()
    reply = types.SimpleNamespace(
        hub="judge",
        purpose="plan_gate",
        source="rule",
        hit_layer="rule",
        value="low,medium",
        degraded=False,
        reason="",
        model="Q3",
        input_tokens=11,
        output_tokens=7,
        cost=0.002,
        latency_ms=1234,
    )
    await gw._ledger(
        "plan_gate",
        reply,
        lambda v: "判档：%s" % v,   # describe 收判断值，签名必须匹配
        user_id="u1",
        agent_id="a1",
        chat_id="c1",
        turn=3,
    )
    assert len(caught) == 1, "台账行没有送达总线"
    row = caught[0]
    assert row.complexity == "medium"          # 档位，不是 'select:low,medium'
    assert row.source == "plan_gate"
    assert row.tokens == 18                    # 11 + 7
    assert row.turn == 3
    assert row.chat_id == "c1"
    assert row.user_id == "u1"
    assert row.agent_id == "a1"
    assert row.outcome == "pending"            # 新行一律 pending，验收再回填
    assert row.model == "Q3"
    assert real_bus is not None
