"""边跑边补计划（auto plan backfill）的契约测试。

对应 2026-11-23 实测缺陷：模型没有按指令先立计划，直接连着调工具，
于是计划面板全程不出现、已完成的步骤也没法打勾。修法是执行过程中
每步检查一次，够两步就把干过的活回填成计划。

这里只验补建逻辑本身：用假 notebook 捕获 create_plan 入参，
并用真实 agentscope PlanNotebook 锁住属性名（plan 这个字段名不存在，
写成它会让「已有计划就别重复补」的守卫恒不生效——实测踩过）。
"""

import asyncio
import sys
import unittest
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from agentscope.plan import PlanNotebook  # noqa: E402

from coapis.agents.react_agent import CoApisAgent  # noqa: E402


class _FakeNotebook:
    def __init__(self, current_plan=None):
        self.current_plan = current_plan
        self.created = []

    async def create_plan(self, name, description, expected_outcome, subtasks):
        self.created.append({
            "name": name,
            "description": description,
            "subtasks": subtasks,
        })
        return "created"


class _FakeAgent:
    """Enough surface for CoApisAgent._maybe_backfill_plan to run."""

    def __init__(self, calls, plan=None, goal="今天有哪些热点"):
        self.plan_notebook = _FakeNotebook(current_plan=plan)
        self._turn_tool_calls = list(calls)
        self._plan_backfilled = False
        self._hub_goal = goal

    def _decision_scope(self):
        return {"session_id": "probe-session"}


def _run(agent):
    asyncio.run(CoApisAgent._maybe_backfill_plan(agent))


class TestNoteTurnToolCall(unittest.TestCase):
    def test_records_names_and_caps_at_eight(self):
        agent = _FakeAgent([])
        for i in range(20):
            CoApisAgent._note_turn_tool_call(agent, "tool_%d" % i)
        self.assertEqual(len(agent._turn_tool_calls), 8)
        self.assertEqual(agent._turn_tool_calls[0], "tool_0")

    def test_creates_list_when_missing(self):
        agent = _FakeAgent([])
        del agent._turn_tool_calls
        CoApisAgent._note_turn_tool_call(agent, "web_search")
        self.assertEqual(agent._turn_tool_calls, ["web_search"])


class TestAutoBackfill(unittest.TestCase):
    def test_backfills_once_with_done_steps_and_a_closer(self):
        agent = _FakeAgent(["web_search", "web_fetch", "read_file"])
        _run(agent)

        created = agent.plan_notebook.created
        self.assertEqual(len(created), 1, "should build exactly one plan")
        subtasks = created[0]["subtasks"]
        states = [s.state for s in subtasks]
        self.assertEqual(states.count("done"), 3, "each executed tool is done")
        self.assertEqual(states[-1], "in_progress", "closer must be in progress")
        self.assertEqual(created[0]["name"], "今天有哪些热点")

    def test_closer_is_in_progress_so_hints_do_not_ask_for_confirmation(self):
        # hints 只在全是 todo 时才走 at_the_beginning*（会叫模型等用户确认）。
        # 补建的计划必须带 in_progress，否则会反过来卡住执行。
        agent = _FakeAgent(["web_search", "web_fetch"])
        _run(agent)
        subtasks = agent.plan_notebook.created[0]["subtasks"]
        self.assertGreater(sum(1 for s in subtasks if s.state == "in_progress"), 0)
        self.assertGreater(sum(1 for s in subtasks if s.state == "done"), 0)

    def test_two_calls_is_the_threshold(self):
        one = _FakeAgent(["web_search"])
        _run(one)
        self.assertEqual(one.plan_notebook.created, [])
        self.assertFalse(one._plan_backfilled)

    def test_existing_plan_is_left_alone(self):
        agent = _FakeAgent(["web_search", "web_fetch"], plan={"id": "p1"})
        _run(agent)
        self.assertEqual(agent.plan_notebook.created, [])

    def test_no_goal_means_no_plan(self):
        agent = _FakeAgent(["web_search", "web_fetch"], goal="   ")
        _run(agent)
        self.assertEqual(agent.plan_notebook.created, [])

    def test_only_once_per_turn(self):
        agent = _FakeAgent(["web_search", "web_fetch"])
        _run(agent)
        _run(agent)
        self.assertEqual(len(agent.plan_notebook.created), 1)

    def test_missing_notebook_is_a_noop(self):
        agent = _FakeAgent(["web_search", "web_fetch"])
        agent.plan_notebook = None
        _run(agent)  # must not raise

    def test_create_plan_failure_does_not_escape(self):
        agent = _FakeAgent(["web_search", "web_fetch"])

        async def boom(**kwargs):
            raise RuntimeError("boom")

        agent.plan_notebook.create_plan = boom
        _run(agent)  # must not raise

    def test_subtask_names_are_chinese(self):
        agent = _FakeAgent(["web_search", "execute_shell_command"])
        _run(agent)
        names = [s.name for s in agent.plan_notebook.created[0]["subtasks"]]
        self.assertEqual(names[0], "联网检索")
        self.assertEqual(names[1], "执行命令")
        self.assertEqual(names[-1], "汇总结果并回答")


class TestAgainstRealPlanNotebook(unittest.TestCase):
    """The guard must use the attribute the SDK actually exposes."""

    def test_field_is_named_current_plan(self):
        nb = PlanNotebook()
        self.assertTrue(hasattr(nb, "current_plan"))
        self.assertFalse(
            hasattr(nb, "plan"),
            "PlanNotebook 没有 plan 字段；若哪天出现了，守卫要同步改",
        )

    def test_real_notebook_gets_the_backfilled_plan(self):
        nb = PlanNotebook()
        agent = _FakeAgent(["web_search", "web_fetch"])
        agent.plan_notebook = nb
        _run(agent)
        self.assertIsNotNone(nb.current_plan, "补建必须落到真实 notebook")
        names = [s.name for s in nb.current_plan.subtasks]
        self.assertEqual(names[-1], "汇总结果并回答")
        self.assertEqual(
            [s.state for s in nb.current_plan.subtasks][-1], "in_progress",
        )

    def test_real_notebook_with_a_plan_is_not_touched(self):
        nb = PlanNotebook()
        asyncio.run(nb.create_plan(
            name="模型自己立的计划",
            description="d",
            expected_outcome="o",
            subtasks=[
                {"name": "第一步", "description": "d",
                 "expected_outcome": "o", "created_at": "2026-11-23T00:00:00"},
                {"name": "第二步", "description": "d",
                 "expected_outcome": "o", "created_at": "2026-11-23T00:00:00"},
            ],
        ))
        before = nb.current_plan.name
        agent = _FakeAgent(["web_search", "web_fetch"])
        agent.plan_notebook = nb
        _run(agent)
        self.assertEqual(nb.current_plan.name, before, "不能覆盖模型自己立的计划")


if __name__ == "__main__":
    unittest.main()
