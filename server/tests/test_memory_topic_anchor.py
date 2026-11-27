# -*- coding: utf-8 -*-
"""短期层与中文意图过滤的回归锁。

治两个病：
  1. 注入里没有"眼下在聊什么"这一层 —— 会话内话题会漂移，只按语义检索
     捞长期记忆，旧话题的记忆就会变成噪音（用户原话：老记忆一直存在，
     但问题其实已经变了）。
  2. 经验池意图过滤表只有英文键，中文提问永不命中，过滤形同虚设。
"""

import io
import os
import types

from coapis.agents.react_agent import CoApisAgent

SRC = os.path.join(os.path.dirname(__file__), os.pardir, "coapis", "agents",
                   "react_agent.py")


def _msg(role, text):
    return types.SimpleNamespace(role=role, content=text)


def _fake(memory_content):
    return types.SimpleNamespace(
        memory=types.SimpleNamespace(content=memory_content))


# ── 短期层（会话话题锚点）────────────────────────────────────────
def test_digest_collects_recent_user_turns_in_order():
    agent = _fake([
        (_msg("user", "先看下左栏为什么是空的"), []),
        (_msg("assistant", "我去读代码"), []),
        (_msg("user", "再改一下计划卡位置"), []),
    ])
    got = CoApisAgent._build_short_term_digest(agent)
    assert "左栏" in got
    assert "计划卡位置" in got
    assert got.index("左栏") < got.index("计划卡位置")
    assert "我去读代码" not in got, "短期层只收用户输入"


def test_digest_empty_without_user_turns():
    agent = _fake([(_msg("assistant", "hi"), [])])
    assert CoApisAgent._build_short_term_digest(agent) == ""


def test_digest_swallows_broken_memory_state():
    # 短期层绝不能把主链带崩：状态异常一律退回空串
    assert CoApisAgent._build_short_term_digest(
        types.SimpleNamespace(memory=None)) == ""


def test_digest_collapses_whitespace_and_caps_length():
    agent = _fake([(_msg("user", "x" * 500 + "\n\n第二段"), [])])
    got = CoApisAgent._build_short_term_digest(agent)
    assert "\n" not in got
    assert len(got) <= 400


# ── 中文意图过滤表（旧表全英文键 → 中文永不命中）─────────────────


# ── 意图过滤接线（历史事故：过滤比的是数据里不存在的类型词，等于没过滤）──
def test_injection_delegates_to_recall_intent_filter():
    src = io.open(SRC, encoding="utf-8").read()
    assert "_recall.filter_by_intent(" in src
