# -*- coding: utf-8 -*-
"""D7 审批身份边界：禁止自批 + 管理员代批留痕（方案 §13 拍板 D7）。

为什么单独一个文件：``test_contract_approvals.py`` 里的既有测试锁的是
"D7 之前属主可以自批"这条现状，它们由 ``server/tests/conftest.py`` 的
autouse 旋钮保持在 ``allow`` 态；本文件测 ``forbid`` 态（默认）。
两态都是产品承诺，所以两边都要有锁。
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


async def test_self_approval_is_forbidden_by_default(service, monkeypatch):
    # D7 目标锁（验收 B2「自批被拒」）：发起这次工具调用的属主，
    # 不能自己批准自己的操作。默认态 = forbid。
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


@pytest.fixture
def service():
    from coapis.app.approvals.service import ApprovalService

    return ApprovalService()
