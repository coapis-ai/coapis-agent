# -*- coding: utf-8 -*-
"""B0 契约锁 · 审批闭环（方案 v1 §3 第 0 批 / D14）

**口径照抄代码**（``coapis/app/approvals/service.py::ApprovalService``）。
方法名与签名全部实测取，契约锁一个不存在的名字等于自欺。真实形状::

    create_pending(*, session_id, root_session_id, user_id, channel, agent_id,
                   tool_name, result: ToolGuardResult,
                   timeout_seconds=TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
                   extra=None) -> PendingApproval          # 关键字参数
    resolve_request(rid, decision: ApprovalDecision) -> PendingApproval | None
    get_request(rid) / get_pending_by_session(sid) / get_pending_by_root_session(root)
    live_remaining_seconds(rid) / resolve_live(rid)
    cancel_all_pending_by_root_session(root)

服务方法都是协程（仓库 pytest 配了 ``asyncio_mode=auto``，直接 async def 即可）。
现状锁 = B2 收尾时不许改松的行为；B2 目标锁 = ``xfail(strict=True)``
（今天必须失败，做完自动变红，逼着摘标记）。
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from coapis.app.approvals.service import (
    TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
    ApprovalService,
    PendingApproval,
)
from coapis.security.tool_guard.approval import ApprovalDecision
from coapis.security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)

B2 = pytest.mark.xfail(
    strict=True,
    reason="B2 目标契约：审批意图台账与超时默认拒绝语义（未实现）",
)


def _result(
    tool_name: str = "Bash",
    severity: GuardSeverity = GuardSeverity.HIGH,
) -> ToolGuardResult:
    return ToolGuardResult(
        tool_name=tool_name,
        params={"command": "echo hi"},
        findings=[
            GuardFinding(
                id="f-1",
                rule_id="r-1",
                category=GuardThreatCategory.COMMAND_INJECTION,
                severity=severity,
                title="危险命令",
                description="命中注入规则",
                tool_name=tool_name,
                remediation="改命令",
            ),
        ],
    )


@pytest.fixture()
def service() -> ApprovalService:
    # 每个用例一个干净服务实例（队列是内存态，共用会互相污染）
    return ApprovalService()


async def _pending(
    service: ApprovalService,
    session_id: str = "s-contract",
    **kw,
) -> PendingApproval:
    return await service.create_pending(
        session_id=session_id,
        root_session_id=session_id,
        user_id="u-contract",
        channel="console",
        agent_id="a-contract",
        tool_name="Bash",
        result=_result(),
        **kw,
    )


# ── 1. 入队：台账行的必备字段 ───────────────────────────────────────────


async def test_create_pending_returns_a_pending_row(service):
    item = await _pending(service)
    assert isinstance(item, PendingApproval)
    assert item.request_id
    assert item.tool_name == "Bash"
    # 台账字段：严重度与命中数必须随行走，否则看板无法分级
    assert item.severity == GuardSeverity.HIGH
    assert item.findings_count == 1


def test_create_pending_is_keyword_only():
    # 会话/用户/通道/岗位是身份归因的必需项。用位置参数调用必须直接报错，
    # 不许静默接受后写出归因不全的行。
    with pytest.raises(TypeError):
        ApprovalService.create_pending(
            ApprovalService(),
            "s1",
            "s1",
            "u",
            "console",
            "a",
            "Bash",
            _result(),
        )


async def test_pending_row_carries_attribution_fields(service):
    item = await _pending(service, "s-attr")
    for field in ("session_id", "root_session_id", "user_id", "agent_id"):
        assert getattr(item, field, None), f"审批行缺归因字段 {field}"


async def test_pending_lookup_is_session_scoped(service):
    a_item = await _pending(service, "s-A")
    await _pending(service, "s-B")
    # 单数版返回"该会话的第一个待裁决项"，复数版返回全部（前端轮询用）
    a = await service.get_pending_by_session("s-A")
    b = await service.get_pending_by_session("s-B")
    assert a is not None and b is not None
    assert a.request_id == a_item.request_id
    assert a.request_id != b.request_id


async def test_pending_list_per_session_excludes_others(service):
    await _pending(service, "s-L1")
    await _pending(service, "s-L2")
    await _pending(service, "s-L2")
    one = await service.list_pending_by_session("s-L1")
    two = await service.list_pending_by_session("s-L2")
    assert len(one) == 1 and len(two) == 2
    assert {i.request_id for i in one}.isdisjoint({i.request_id for i in two})


async def test_lookup_by_unknown_session_is_empty_not_error(service):
    assert await service.get_pending_by_session("no-such-session") is None
    assert not await service.list_pending_by_session("no-such-session")


# ── 2. 裁决：一次性、可查、未知 id 不崩 ─────────────────────────────────


async def test_resolve_request_returns_the_resolved_row(service):
    item = await _pending(service)
    resolved = await service.resolve_request(item.request_id, ApprovalDecision.APPROVED)
    assert resolved is not None
    assert resolved.request_id == item.request_id


async def test_resolve_request_is_single_use(service):
    # 二次裁决必须取不到：审批一旦被复用就是"一次同意、永久放行"。
    item = await _pending(service)
    first = await service.resolve_request(item.request_id, ApprovalDecision.APPROVED)
    second = await service.resolve_request(item.request_id, ApprovalDecision.DENIED)
    assert first is not None
    assert second is None


async def test_resolve_request_survives_unknown_id(service):
    assert await service.resolve_request("no-such-request", ApprovalDecision.APPROVED) is None


async def test_resolve_request_survives_empty_id(service):
    assert await service.resolve_request("", ApprovalDecision.APPROVED) is None


async def test_get_request_reads_without_consuming(service):
    # 读操作（看板/前端轮询）不能把待审批项读走——读走就等于没批。
    item = await _pending(service)
    assert await service.get_request(item.request_id) is not None
    assert await service.get_pending_by_session("s-contract") is not None


async def test_denied_path_is_first_class(service):
    # 拒绝必须与批准同样可查（红线：拒绝是一等公民，不是异常路径）。
    item = await _pending(service)
    resolved = await service.resolve_request(item.request_id, ApprovalDecision.DENIED)
    assert resolved is not None


def test_decision_vocabulary_is_stable():
    # 前端/台账/超时处理共用这套字面量，改名等于历史对不上。
    values = {d.value for d in ApprovalDecision}
    assert {"approved", "denied"} <= values


async def test_cancel_by_root_session_clears_the_whole_family(service):
    # 一次会话派生的多子会话审批必须能整族取消，否则会话结束后
    # 残留的 pending 会永久占位（216 条堆积的成因之一）。
    await service.create_pending(
        session_id="child-1",
        root_session_id="root-1",
        user_id="u",
        channel="console",
        agent_id="a",
        tool_name="Bash",
        result=_result(),
    )
    await service.cancel_all_pending_by_root_session("root-1")
    assert not await service.get_pending_by_session("child-1")


# ── 3. 超时尺子：一把，不许两份 ─────────────────────────────────────────


def test_timeout_ruler_is_a_single_module_constant():
    assert isinstance(TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS, (int, float))
    assert TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS > 0
    # create_pending 的默认超时就是这把尺子（调用点不许各写一份）
    sig = inspect.signature(ApprovalService.create_pending)
    assert sig.parameters["timeout_seconds"].default == TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS


async def test_timeout_is_per_request_overridable(service):
    item = await _pending(service, "s-short", timeout_seconds=1.0)
    assert item.timeout_seconds == 1.0


async def test_live_remaining_seconds_is_a_countdown(service):
    item = await _pending(service, "s-live", timeout_seconds=60.0)
    first = await service.live_remaining_seconds(item.request_id)
    assert first is not None and 0 < first <= 60.0


async def test_expired_row_leaves_the_queue_not_the_ledger(service):
    # 现状锁（B0 实锤）：超时由服务侧兜底——日志记 "auto-timed out"，
    # 行从队列消失。但 ``PendingApproval`` **没有 decision 字段**，
    # 所以超时在看板上等于"没发生"（统计隐形）。台账化是 B2 目标锁。
    item = await _pending(service, "s-expired", timeout_seconds=0.0)
    await asyncio.sleep(0.05)
    assert not hasattr(item, "decision")
    assert await service.get_pending_by_session("s-expired") is None


# ── 4. 结果模型：严重度取最高，不取第一个 ───────────────────────────────


def test_max_severity_takes_the_highest_finding():
    res = ToolGuardResult(
        tool_name="Bash",
        params={},
        findings=[
            GuardFinding(
                id="f-low",
                rule_id="r1",
                category=GuardThreatCategory.COMMAND_INJECTION,
                severity=GuardSeverity.LOW,
                title="t",
                description="d",
                tool_name="Bash",
                remediation="r",
            ),
            GuardFinding(
                id="f-crit",
                rule_id="r2",
                category=GuardThreatCategory.COMMAND_INJECTION,
                severity=GuardSeverity.CRITICAL,
                title="t",
                description="d",
                tool_name="Bash",
                remediation="r",
            ),
        ],
    )
    assert res.findings_count == 2
    assert res.max_severity is GuardSeverity.CRITICAL


def test_clean_result_is_safe_and_never_crashes():
    res = ToolGuardResult(tool_name="Read", params={}, findings=[])
    assert res.findings_count == 0
    # 无命中也要有一个可显示的最低严重度（前端渲染不许因缺字段而崩）
    assert res.max_severity is GuardSeverity.SAFE


# ── 5. B2 目标：意图台账与超时默认语义 ──────────────────────────────────


@B2
async def test_user_choice_leaves_an_intent_ledger_row(service):
    # 终态判据（方案 §4 验收 5）：用户选择要能回答"选了哪种、为什么"。
    # 今天只有内存里的 decision 值，队列取走即消失，台账里没有任何一行。
    item = await _pending(service, "s-intent")
    await service.resolve_request(item.request_id, ApprovalDecision.APPROVED)
    rows = await service.list_intent_rows(session_id="s-intent")
    assert rows and rows[0]["decision"] == "approved"


@B2
async def test_timeout_leaves_a_ledger_row_not_a_vanish(service):
    # 终态判据（方案 §4 验收 5）：超时也要进台账，可统计、可追溯。
    # 今天超时只在内存里留下一条 decision，队列取走即消失，台账 0 行。
    item = await _pending(service, "s-timeout", timeout_seconds=0.0)
    await asyncio.sleep(0.05)
    rows = await service.list_timeout_rows(session_id="s-timeout")
    assert rows and rows[0]["decision"] == ApprovalDecision.TIMED_OUT.value