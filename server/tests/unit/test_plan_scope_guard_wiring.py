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


# ═══════════════════════════════════════════════════════════════════════
# F1 真拦：pending 授权域必须能否决动作，而不只是"免审批"
# （E2E 实测：scope 一直显示待确认，模型照样删掉了 3 个文件）
# ═══════════════════════════════════════════════════════════════════════


def test_pending_scope_vetoes_confirmation_level_action():
    """待确认的域内，出入/破坏性动作必须被否决（不是放行去审批）。"""
    _Stub(SESSION)
    get_registry().grant(
        SESSION,
        "删除文件并生成汇总",
        status=SCOPE_STATUS_PENDING,
        max_semantics=ActionSemantics.DESTRUCTIVE,
    )
    action = _Stub(SESSION)._plan_scope_veto(
        "execute_shell_command",
        {"command": "ssh ops@prod 'systemctl restart app'"},
    )
    assert action is not None
    assert action.kind == "auto_denied"
    assert action.guard_result is not None
    finding = action.guard_result.findings[0]
    assert finding.rule_id == "PLAN_SCOPE_PENDING"
    assert finding.guardian == "plan_scope"
    # 否决文案要能教模型停下来问用户，而不是让它换个说法再来
    assert "确认" in finding.description
    assert "不要靠改写方案标题" in finding.description


def test_pending_scope_vetoes_destructive_action():
    _Stub(SESSION)
    get_registry().grant(
        SESSION,
        "清理临时文件",
        status=SCOPE_STATUS_PENDING,
        max_semantics=ActionSemantics.DESTRUCTIVE,
    )
    action = _Stub(SESSION)._plan_scope_veto(
        "execute_shell_command",
        {"command": "rm -rf ./build"},
    )
    assert action is not None and action.kind == "auto_denied"


def test_pending_scope_lets_reads_through_but_still_blocks_writes():
    """读类照常放行（会话不会被冻死）；从本地写入起一律拦下。

    这就是 F1 的边界：未确认的方案不放行任何有副作用的动作，
    但查看文件、读配置这类只读动作照常走，模型仍能把方案讲清楚。
    """
    _Stub(SESSION)
    get_registry().grant(
        SESSION,
        "删除文件并生成汇总",
        status=SCOPE_STATUS_PENDING,
        max_semantics=ActionSemantics.DESTRUCTIVE,
    )
    stub = _Stub(SESSION)
    assert stub._plan_scope_veto("read_file", {"path": "notes/a.txt"}) is None
    assert (
        stub._plan_scope_veto(
            "write_file",
            {"file_path": "notes/a.txt", "content": "x"},
        )
        is not None
    )


def test_veto_without_session_id_is_silent():
    get_registry().grant(
        SESSION,
        "删除文件并生成汇总",
        status=SCOPE_STATUS_PENDING,
        max_semantics=ActionSemantics.DESTRUCTIVE,
    )
    assert _Stub("")._plan_scope_veto(
        "execute_shell_command",
        {"command": "rm -rf ./build"},
    ) is None
