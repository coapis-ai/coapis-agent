# -*- coding: utf-8 -*-
"""片0 · 方案授权域接入工具守卫链路的接线测试。

只验证"接线"本身：授权域覆盖 → 免审；破坏性/越界 → 回落审批。
"""
import pytest

from coapis.agents.tool_guard_mixin import ToolGuardMixin
from coapis.plan.scope import (
    SCOPE_STATUS_EXECUTING,
    SCOPE_STATUS_PENDING,
    get_registry,
)
from coapis.security.action_semantics import ActionSemantics

SESSION = "sess-guard-wire"


class _Stub(ToolGuardMixin):
    """最小宿主：只提供授权域判定需要的上下文。"""

    def __init__(self, session_id: str):
        self._request_context = {"session_id": session_id, "user_id": "tester"}


@pytest.fixture(autouse=True)
def _clean_registry():
    get_registry().clear()
    yield
    get_registry().clear()


def test_covered_tool_skips_approval():
    get_registry().grant(
        SESSION,
        "改代码",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    stub = _Stub(SESSION)
    assert stub._plan_scope_covers("read_file", {"file_path": "a.py"}) is True
    assert stub._plan_scope_covers("write_file", {"file_path": "a.py"}) is True


def test_out_of_scope_tool_falls_back_to_approval():
    get_registry().grant(
        SESSION,
        "改代码",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    stub = _Stub(SESSION)
    assert stub._plan_scope_covers("delete_file", {"file_path": "a.py"}) is False


def test_destructive_never_covered_in_guard():
    get_registry().grant(
        SESSION,
        "全量清理",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.DESTRUCTIVE,
    )
    stub = _Stub(SESSION)
    command = "rm" + " -rf ./build"
    assert stub._plan_scope_covers("execute_shell_command", {"command": command}) is (
        False
    )


def test_pending_plan_covers_nothing():
    get_registry().grant(
        SESSION,
        "待确认方案",
        status=SCOPE_STATUS_PENDING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    stub = _Stub(SESSION)
    assert stub._plan_scope_covers("write_file", {"file_path": "a.py"}) is False


def test_without_scope_covers_nothing():
    stub = _Stub(SESSION)
    assert stub._plan_scope_covers("write_file", {"file_path": "a.py"}) is False


def test_missing_session_id_is_safe():
    stub = _Stub("")
    assert stub._plan_scope_covers("write_file", {}) is False
