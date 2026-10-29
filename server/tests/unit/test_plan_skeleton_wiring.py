# -*- coding: utf-8 -*-
"""Plan-skeleton wiring tests.

Why: ``ComplexityClassifier`` shipped calibrated (20 cases, 80% agreement)
with **zero consumers** - a ghost module.  A multi-step request therefore
ran as ad-hoc tool calls with no written plan, and after compaction rolled
the early turns away the agent could not say which subtasks were done.

Contract:
- a multi-step request arms the skeleton (hint injected) when the plan tools
  exist and no plan is active;
- a simple request does not;
- an active plan is never re-armed;
- no plan tools -> nothing happens;
- the gate is rule-based: no model call, and a gate failure never breaks
  the reply.
"""

import asyncio
from types import SimpleNamespace

from agentscope.agent._react_agent import _MemoryMark
from agentscope.message import Msg

from coapis.agents.react_agent import CoApisAgent as CoPawAgent
from coapis.agents.plan_gate import COMPLEX, SIMPLE, ComplexityClassifier

MULTI_STEP = (
    "请全面分析这个模块的实现，找出所有问题，然后给出方案，"
    "逐条修复并测试验证，最后部署到开发环境并检查运行状态，"
    "把结果整理成文档，包含每一步的证据和数据，"
    "并对比修复前后的指标变化，列出剩余的决策点等待拍板。"
)

SIMPLE_ASK = "今天几号？"


class _FakeMemory:
    def __init__(self):
        self.added = []

    async def add(self, msg, marks=None):
        self.added.append((msg, marks))


def _stub(notebook, memory):
    """A bare object exercising the agent's plan-skeleton method."""
    stub = SimpleNamespace(
        plan_notebook=notebook,
        memory=memory,
        _complexity_classifier=None,
    )
    stub._gate_text = CoPawAgent._gate_text
    stub._PLAN_SKELETON_HINT = CoPawAgent._PLAN_SKELETON_HINT
    # 真实实现从 request_context 取台账作用域；桩里返回空 scope 即可
    # （只影响判级入账，不影响判档与骨架注入本身）。
    stub._decision_scope = lambda: {}
    stub._maybe_arm_plan = lambda msg: CoPawAgent._maybe_arm_plan(stub, msg)
    return stub


class TestGateText:
    def test_string_content(self):
        assert CoPawAgent._gate_text(Msg("user", "hello", "user")) == "hello"

    def test_block_content(self):
        msg = Msg(
            "user",
            [{"type": "text", "text": "a"}, {"type": "image", "source": {}}],
            "user",
        )
        assert CoPawAgent._gate_text(msg) == "a"

    def test_list_and_none(self):
        assert CoPawAgent._gate_text(None) == ""
        msgs = [Msg("user", "a", "user"), Msg("user", "b", "user")]
        assert CoPawAgent._gate_text(msgs) == "a\nb"


class TestSkeletonArming:
    def test_multi_step_request_arms_the_skeleton(self):
        memory = _FakeMemory()
        stub = _stub(SimpleNamespace(plan=None), memory)
        asyncio.run(stub._maybe_arm_plan(Msg("user", MULTI_STEP, "user")))
        assert len(memory.added) == 1
        msg, marks = memory.added[0]
        assert marks == _MemoryMark.HINT
        assert "<plan-skeleton>" in msg.content
        assert "plan tool" in msg.content

    def test_simple_request_is_left_alone(self):
        memory = _FakeMemory()
        stub = _stub(SimpleNamespace(plan=None), memory)
        asyncio.run(stub._maybe_arm_plan(Msg("user", SIMPLE_ASK, "user")))
        assert memory.added == []

    def test_active_plan_is_not_rearmed(self):
        memory = _FakeMemory()
        stub = _stub(SimpleNamespace(plan=SimpleNamespace(id="p1")), memory)
        asyncio.run(stub._maybe_arm_plan(Msg("user", MULTI_STEP, "user")))
        assert memory.added == []

    def test_no_plan_tools_means_no_injection(self):
        memory = _FakeMemory()
        stub = _stub(None, memory)
        asyncio.run(stub._maybe_arm_plan(Msg("user", MULTI_STEP, "user")))
        assert memory.added == []

    def test_empty_message_is_ignored(self):
        memory = _FakeMemory()
        stub = _stub(SimpleNamespace(plan=None), memory)
        asyncio.run(stub._maybe_arm_plan(None))
        assert memory.added == []

    def test_classifier_is_cached_and_rule_only(self):
        memory = _FakeMemory()
        stub = _stub(SimpleNamespace(plan=None), memory)
        asyncio.run(stub._maybe_arm_plan(Msg("user", MULTI_STEP, "user")))
        classifier = stub._complexity_classifier
        assert isinstance(classifier, ComplexityClassifier)
        assert classifier.judge_enabled is False, (
            "the gate must not spend a model call"
        )
        # Second call reuses the same classifier instance.
        asyncio.run(stub._maybe_arm_plan(Msg("user", MULTI_STEP, "user")))
        assert stub._complexity_classifier is classifier

    def test_gate_failure_never_breaks_the_reply(self):
        memory = _FakeMemory()
        stub = _stub(SimpleNamespace(plan=None), memory)
        stub._complexity_classifier = SimpleNamespace(
            classify=lambda text: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        asyncio.run(stub._maybe_arm_plan(Msg("user", MULTI_STEP, "user")))
        assert memory.added == []

    def test_classifier_rules_are_calibrated_on_the_two_poses(self):
        clf = ComplexityClassifier(judge_enabled=False)
        assert clf.classify(MULTI_STEP) == COMPLEX
        assert clf.classify(SIMPLE_ASK) == SIMPLE
