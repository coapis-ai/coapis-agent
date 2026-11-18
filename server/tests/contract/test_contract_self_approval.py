# -*- coding: utf-8 -*-
"""D7 审批身份边界：自批旋钮三态 + 管理员代批留痕（方案 §13 拍板 D7）。

为什么单独一个文件：``test_contract_approvals.py`` 里的既有测试锁的是
「属主可以自批」这条常态路径，它们由 ``server/tests/conftest.py`` 的
autouse 旋钮保持在 ``allow`` 态；本文件把旋钮的三态全部钉住：

* 未设旋钮 → ``allow``（2026-11-18 拍板：个人对自己的会话自批是常态路径，
  顺畅优先；拦属主本人只造成反复打断，并不增加安全）
* ``allow`` → 放行（部署侧逃生门/回滚门）
* ``forbid`` → 拒绝并留痕（治理诉求的强约束档）
"""
from __future__ import annotations

import pytest

from coapis.app.approvals.service import ApprovalService
from coapis.security.tool_guard.approval import ApprovalDecision

pytestmark = pytest.mark.contract


def _result(severity=None):
    """造一个真实形态的 ToolGuardResult（审批入队读 max_severity/findings_count）。"""
    from coapis.security.tool_guard.models import (
        GuardFinding,
        GuardSeverity,
        GuardThreatCategory,
        ToolGuardResult,
    )

    sev = severity or GuardSeverity.HIGH
    finding = GuardFinding(
        id="f-contract",
        rule_id="R-CONTRACT",
        category=next(iter(GuardThreatCategory)),
        severity=sev,
        title="契约测试用命中",
        description="契约测试用命中",
        tool_name="Bash",
        param_name="command",
        matched_value="rm -rf /tmp/x",
    )
    return ToolGuardResult(
        tool_name="Bash",
        params={"command": "rm -rf /tmp/x"},
        findings=[finding],
    )


async def _pending(service: ApprovalService, session_id: str, **kw):
    return await service.create_pending(
        session_id=session_id,
        root_session_id=session_id,
        user_id="u-contract",
        agent_id="agent-x",
        channel="console",
        tool_name="Bash",
        result=_result(),
        **kw,
    )


async def test_self_approval_forbidden_when_switch_on(service, monkeypatch):
    # 强约束档目标锁（验收 B2「自批被拒」）：显式 forbid 时，发起这次
    # 工具调用的属主不能自己批准自己的操作。默认态已是 allow。
    monkeypatch.setenv("COAPIS_APPROVAL_SELF_APPROVAL", "forbid")
    item = await _pending(service, "s-self-approve")
    from coapis.app.approvals.service import ApprovalActor

    out = await service.resolve_request(
        item.request_id,
        ApprovalDecision.APPROVED,
        actor=ApprovalActor(user_id="u-contract", source="http"),
    )
    assert out is None, "属主自批必须被拒"
    # 卡留在队列里等别人来批（拒绝不改状态）
    assert item.status == "pending"
    rows = await service.list_intent_rows(session_id="s-self-approve")
    assert rows, "未遂自批必须留痕，不能一拒了之"
    assert rows[0]["outcome"].startswith("refused:")
    assert "self_approval_forbidden" in rows[0]["outcome"]


async def test_admin_override_is_traced(service, monkeypatch):
    # D7 目标锁（验收 B2「管理员可批 + 审计有 via_admin」）：管理员代批
    # 放行，且台账 decide_source=admin_override —— "谁替谁批的"从台账
    # 直接查得到，不靠翻日志大海捞针。
    monkeypatch.setenv("COAPIS_APPROVAL_SELF_APPROVAL", "forbid")
    item = await _pending(service, "s-admin-override")
    from coapis.app.approvals.service import ApprovalActor

    out = await service.resolve_request(
        item.request_id,
        ApprovalDecision.APPROVED,
        actor=ApprovalActor(user_id="boss", source="http", is_admin=True),
    )
    assert out is not None, "管理员代批必须放行"
    rows = await service.list_intent_rows(session_id="s-admin-override")
    assert rows and rows[0]["decide_source"] == "admin_override"
    assert rows[0]["decided_by"] == "boss"
    assert rows[0]["outcome"] == "applied"


async def test_self_approval_fallback_switch_keeps_owner_path(service, monkeypatch):
    # 回退旋钮（部署侧逃生门）：COAPIS_APPROVAL_SELF_APPROVAL=allow 时
    # 属主自批照旧放行 —— 灰度与回滚都要有据可依。
    monkeypatch.setenv("COAPIS_APPROVAL_SELF_APPROVAL", "allow")
    item = await _pending(service, "s-owner-allow")
    from coapis.app.approvals.service import ApprovalActor

    out = await service.resolve_request(
        item.request_id,
        ApprovalDecision.APPROVED,
        actor=ApprovalActor(user_id="u-contract", source="http"),
    )
    assert out is not None
    rows = await service.list_intent_rows(session_id="s-owner-allow")
    assert rows and rows[0]["decision"] == "approved"
    assert rows[0]["outcome"] == "applied"



async def test_owner_self_approval_allowed_when_switch_unset(service, monkeypatch):
    # 2026-11-18 拍板：默认态 = allow（个人对自己的会话自批是常态路径）。
    # conftest 的 autouse 旋钮把测试环境钉在 allow，所以这里必须 delenv，
    # 才能真正锁住「代码里的默认值」本身 —— 否则以后谁把默认改回 forbid
    # 都没人发现。这一锁就是那次「审批卡点不动、agent 干等 300s」的回归锁。
    monkeypatch.delenv("COAPIS_APPROVAL_SELF_APPROVAL", raising=False)
    item = await _pending(service, "s-owner-unset")
    from coapis.app.approvals.service import ApprovalActor

    out = await service.resolve_request(
        item.request_id,
        ApprovalDecision.APPROVED,
        actor=ApprovalActor(user_id="u-contract", source="http"),
    )
    assert out is not None, "未设旋钮时必须放行属主自批（默认 allow）"
    rows = await service.list_intent_rows(session_id="s-owner-unset")
    assert rows and rows[0]["decision"] == "approved"
    assert rows[0]["outcome"] == "applied"


async def test_agent_side_timeout_is_not_recorded_as_applied(service, monkeypatch):
    # 尺子回归锁：agent 等待循环超时后经 resolve_request(TIMEOUT) 落账，
    # 不得写成 outcome=applied（台账里出现过 decision=timeout /
    # outcome=applied 的自相矛盾行），decision 也要用词表值 timed_out。
    monkeypatch.delenv("COAPIS_APPROVAL_SELF_APPROVAL", raising=False)
    item = await _pending(service, "s-timeout-ruler")
    from coapis.app.approvals.service import ApprovalActor

    out = await service.resolve_request(
        item.request_id,
        ApprovalDecision.TIMEOUT,
        actor=ApprovalActor(source="agent"),
    )
    assert out is not None
    rows = await service.list_intent_rows(session_id="s-timeout-ruler")
    assert rows and rows[0]["decision"] == "timed_out"
    assert rows[0]["outcome"] == "auto:timeout"
    assert rows[0]["decide_source"] == "internal"


async def test_user_stop_is_not_recorded_as_user_denial(service, monkeypatch):
    # 尺子回归锁：用户 /stop 或断连走 CancelledError → resolve_request
    # (DENIED, source=agent)。这是系统取消，不是用户拒绝，必须落
    # system_cancelled / auto:cancel，否则「用户拒绝率」被凭空抬高。
    monkeypatch.delenv("COAPIS_APPROVAL_SELF_APPROVAL", raising=False)
    item = await _pending(service, "s-stop-ruler")
    from coapis.app.approvals.service import ApprovalActor

    out = await service.resolve_request(
        item.request_id,
        ApprovalDecision.DENIED,
        actor=ApprovalActor(source="agent"),
    )
    assert out is not None
    rows = await service.list_intent_rows(session_id="s-stop-ruler")
    assert rows and rows[0]["decision"] == "system_cancelled"
    assert rows[0]["outcome"] == "auto:cancel"


@pytest.fixture
def service():
    from coapis.app.approvals.service import ApprovalService

    return ApprovalService()
