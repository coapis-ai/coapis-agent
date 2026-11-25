# -*- coding: utf-8 -*-
"""计划执行链的三处治本锁（2026-11-23 实测缺陷）。

1. 计划簿记工具必须登记为 READ：它们只改内存里的计划状态。落到
   unknown_semantics 的 EXTERNAL_WRITE 兜底后，收尾调用会被方案授权域拦成
   待审批，模型原地重试到超时（实测 30 分钟死循环）。
2. 同一方案内连续越界达阈值要熔断（置 stalled），让模型收到"停下来汇报"
   的否决，而不是一路挂起等审批。
3. 计划簿记工具按需装备：懒注册押在 plan-change hook 的触发时序上，hook
   漏触发或模型抢跑调用时会 FunctionNotFoundError，计划收不了尾。
"""
import pytest

from coapis.agents.tool_guard_mixin import ToolGuardMixin
from coapis.plan.scope import (
    PLAN_SCOPE_STRIKE_LIMIT,
    SCOPE_STATUS_EXECUTING,
    SCOPE_STATUS_STALLED,
    get_registry,
    peek_scope,
)
from coapis.security.action_semantics import ActionSemantics, classify_action

SESSION = "sess-plan-exec-chain"

PLAN_BOOKKEEPING = (
    "create_plan",
    "revise_current_plan",
    "update_subtask_state",
    "finish_subtask",
    "view_subtasks",
    "finish_plan",
)


class _Stub(ToolGuardMixin):
    """最小宿主：只提供授权域判定需要的上下文。"""

    def __init__(self, session_id: str):
        self._request_context = {"session_id": session_id, "user_id": "tester"}


class _FakeTool:
    def __init__(self, name: str):
        self.__name__ = name


class _FakeNotebook:
    def __init__(self, names):
        self._names = names

    def list_tools(self):
        return [_FakeTool(n) for n in self._names]


class _FakeToolkit:
    def __init__(self, registered=None):
        self.tools = dict(registered or {})
        self.registered = []

    def register_tool_function(self, fn, **kwargs):
        self.registered.append(fn.__name__)
        self.tools[fn.__name__] = fn


@pytest.fixture(autouse=True)
def _clean_registry():
    get_registry().clear()
    yield
    get_registry().clear()


# ── 1. 计划簿记工具的语义档位 ──────────────────────────────────────────
@pytest.mark.parametrize("name", PLAN_BOOKKEEPING)
def test_plan_bookkeeping_is_read_semantics(name):
    """反证：漏登记会落到 EXTERNAL_WRITE，把收口动作拦成待审批。"""
    assert classify_action(name, {}) is ActionSemantics.READ


@pytest.mark.parametrize("name", PLAN_BOOKKEEPING)
def test_plan_bookkeeping_covered_in_local_write_scope(name):
    """反证：收尾工具在 local_write 授权域内必须免审批，否则执行阶段自锁。"""
    get_registry().grant(
        SESSION,
        "查热点",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    stub = _Stub(SESSION)
    assert stub._plan_scope_covers(name, {"subtask_idx": 0}) is True


def test_real_side_effect_tools_keep_their_rungs():
    """反证：登记簿记工具不能顺手放宽真正产生外部出入的工具。"""
    assert classify_action("execute_shell_command", {}) is (
        ActionSemantics.EXTERNAL_WRITE
    )
    assert classify_action("write_file", {}) is ActionSemantics.LOCAL_WRITE


# ── 2. 连续越界熔断 ────────────────────────────────────────────────────
def test_repeated_denials_open_the_circuit():
    """反证：没有熔断时，模型会一路挂起等审批、原地重试到超时。"""
    get_registry().grant(
        SESSION,
        "查热点",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    stub = _Stub(SESSION)
    for _ in range(PLAN_SCOPE_STRIKE_LIMIT):
        assert stub._plan_scope_covers("delete_file", {"file_path": "a.py"}) is False

    scope = peek_scope(SESSION)
    assert scope is not None
    assert scope.status == SCOPE_STATUS_STALLED


def test_stalled_scope_vetoes_side_effects_but_allows_reads():
    """熔断后：有副作用的动作被否决，纯读仍放行（让模型能汇报）。"""
    get_registry().grant(
        SESSION,
        "查热点",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    stub = _Stub(SESSION)
    for _ in range(PLAN_SCOPE_STRIKE_LIMIT):
        stub._plan_scope_covers("delete_file", {"file_path": "a.py"})

    veto = stub._plan_scope_veto("delete_file", {"file_path": "a.py"})
    assert veto is not None
    assert veto.kind == "auto_denied"
    finding = veto.guard_result.findings[0]
    assert finding.rule_id == "PLAN_SCOPE_STALLED"
    assert "收口" in finding.description

    assert stub._plan_scope_covers("read_file", {"file_path": "a.py"}) is True


def test_circuit_does_not_fire_below_limit():
    """反证：阈值以下不该收口，否则正常的一次越界就被误杀。"""
    get_registry().grant(
        SESSION,
        "查热点",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    stub = _Stub(SESSION)
    assert stub._plan_scope_covers("delete_file", {"file_path": "a.py"}) is False

    scope = peek_scope(SESSION)
    assert scope is not None
    assert scope.status == SCOPE_STATUS_EXECUTING


# ── 3. 计划簿记工具按需装备 ────────────────────────────────────────────
def test_missing_plan_tool_is_equipped_on_demand():
    """反证：不装备时 toolkit 查不到函数，直接 FunctionNotFoundError。"""
    stub = _Stub(SESSION)
    stub.plan_notebook = _FakeNotebook(["finish_subtask", "view_subtasks"])
    stub.toolkit = _FakeToolkit()
    stub._namesake_strategy = "override"

    stub._ensure_plan_tool_equipped("finish_subtask")

    assert "finish_subtask" in stub.toolkit.tools
    assert "view_subtasks" not in stub.toolkit.tools


def test_equipped_plan_tool_is_not_registered_twice():
    stub = _Stub(SESSION)
    stub.plan_notebook = _FakeNotebook(["finish_subtask"])
    stub.toolkit = _FakeToolkit({"finish_subtask": object()})

    stub._ensure_plan_tool_equipped("finish_subtask")

    assert stub.toolkit.registered == []


def test_non_plan_tool_is_left_alone():
    stub = _Stub(SESSION)
    stub.plan_notebook = _FakeNotebook(["finish_subtask"])
    stub.toolkit = _FakeToolkit()

    stub._ensure_plan_tool_equipped("execute_shell_command")

    assert stub.toolkit.registered == []


def test_agent_without_notebook_is_safe():
    stub = _Stub(SESSION)
    stub._ensure_plan_tool_equipped("finish_subtask")
