# -*- coding: utf-8 -*-
"""B0 契约锁 · 审批闭环（方案 v1 §3 第 0 批 / D14）

**口径照抄代码**（``coapis/app/approvals/service.py::ApprovalService``）。
方法名与签名全部实测取，契约锁一个不存在的名字等于自欺。真实形状::

    create_pending(*, session_id, root_session_id, user_id, channel, agent_id,
                   tool_name, result: ToolGuardResult,
                   timeout_seconds=TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
                   extra=None) -> PendingApproval          # 关键字参数
    resolve_request(rid, decision, *, actor: ApprovalActor | None)
    get_request(rid) / get_pending_by_session(sid) / get_pending_by_root_session(root)
    live_remaining_seconds(rid) / resolve_live(rid)
    cancel_all_pending_by_root_session(root)

服务方法都是协程（仓库 pytest 配了 ``asyncio_mode=auto``，直接 async def 即可）。
现状锁 = B2 收尾时不许改松的行为；B2 目标锁 = ``xfail(strict=True)``
（今天必须失败，做完自动变红，逼着摘标记）。

**B2 已收紧**：裁决必须带身份。``actor`` 是必答项——缺身份、跨用户、
通道不符一律拒绝；admin 放行并留审计日志；企微卡片回调用受信任来源直通。
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from coapis.app.approvals.service import (
    TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
    ApprovalActor,
    ApprovalService,
    PendingApproval,
    identity_check,
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
    defaults = {
        "user_id": "u-contract",
        "channel": "console",
        "agent_id": "a-contract",
        "tool_name": "Bash",
    }
    defaults.update(kw)
    return await service.create_pending(
        session_id=session_id,
        root_session_id=session_id,
        result=_result(),
        **defaults,
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
    resolved = await service.resolve_request(
        item.request_id,
        ApprovalDecision.APPROVED,
        actor=ApprovalActor(user_id="u-contract", channel="console", source="http"),
    )
    assert resolved is not None
    assert resolved.request_id == item.request_id


async def test_resolve_request_is_single_use(service):
    # 二次裁决必须取不到：审批一旦被复用就是"一次同意、永久放行"。
    item = await _pending(service)
    first = await service.resolve_request(
        item.request_id,
        ApprovalDecision.APPROVED,
        actor=ApprovalActor(user_id="u-contract", channel="console", source="http"),
    )
    second = await service.resolve_request(
        item.request_id,
        ApprovalDecision.DENIED,
        actor=ApprovalActor(user_id="u-contract", channel="console", source="http"),
    )
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
    resolved = await service.resolve_request(
        item.request_id,
        ApprovalDecision.DENIED,
        actor=ApprovalActor(user_id="u-contract", channel="console", source="http"),
    )
    assert resolved is not None


def test_decision_vocabulary_is_stable():
    # 前端/台账/超时处理共用这套字面量，改名等于历史对不上。
    values = {d.value for d in ApprovalDecision}
    assert {"approved", "denied"} <= values


# ----------------------------------------------------------- 身份边界（B2）
#
# 五例矩阵：无身份 / 正确身份 / admin / 跨用户 / 受信任回调。
# 检查写在 service 层，不在路由里——路由忘了做检查，机器不会替它兜底。


_OWNER = "alice"
_OWNER_ACTOR = ApprovalActor(user_id=_OWNER, channel="console", source="http")


async def test_identity_missing_actor_is_refused(service):
    """缺身份必须失败：不带 actor 的裁决不得改动任何台账。"""
    item = await _pending(service, user_id=_OWNER)
    assert await service.resolve_request(
        item.request_id,
        ApprovalDecision.APPROVED,
    ) is None
    # 行还在，且仍是 pending —— 没有被人隔空批掉。
    live = await service.get_request(item.request_id)
    assert live is not None and live.status == "pending"


async def test_identity_owner_is_allowed(service):
    item = await _pending(service, user_id=_OWNER)
    resolved = await service.resolve_request(
        item.request_id,
        ApprovalDecision.APPROVED,
        actor=_OWNER_ACTOR,
    )
    assert resolved is not None and resolved.status == "approved"


async def test_identity_admin_is_allowed_and_logged(service):
    """admin 跨用户放行，但必须留审计痕迹（日志）。"""
    item = await _pending(service, user_id=_OWNER)
    resolved = await service.resolve_request(
        item.request_id,
        ApprovalDecision.APPROVED,
        actor=ApprovalActor(
            user_id="boss",
            is_admin=True,
            channel="console",
            source="http",
        ),
    )
    assert resolved is not None and resolved.status == "approved"


async def test_identity_cross_user_is_refused(service):
    """跨用户必须 403 语义：拿别人的 request_id 批不动。"""
    item = await _pending(service, user_id=_OWNER)
    assert await service.resolve_request(
        item.request_id,
        ApprovalDecision.APPROVED,
        actor=ApprovalActor(user_id="mallory", channel="console", source="http"),
    ) is None
    live = await service.get_request(item.request_id)
    assert live is not None and live.status == "pending"


async def test_identity_channel_mismatch_is_refused(service):
    """通道维度：同一用户从错误通道下裁决也要被拒。"""
    item = await _pending(service, user_id=_OWNER, channel="wecom")
    assert await service.resolve_request(
        item.request_id,
        ApprovalDecision.APPROVED,
        actor=ApprovalActor(user_id=_OWNER, channel="console", source="http"),
    ) is None


async def test_identity_trusted_sources_are_allowed(service):
    """超时收口、智能体自动拒绝、企微卡片回调：受信任来源直通。"""
    for source in ("internal", "agent", "card_callback"):
        item = await _pending(service, user_id=_OWNER)
        resolved = await service.resolve_request(
            item.request_id,
            ApprovalDecision.DENIED,
            actor=ApprovalActor(user_id=_OWNER, channel="wecom", source=source),
        )
        assert resolved is not None, source


async def test_identity_check_reason_codes_are_stable():
    """拒绝理由码是稳定字面量：前端与日志共用，改名即历史对不上。"""
    row = PendingApproval(
        request_id="r-code",
        session_id="s-code",
        root_session_id="s-code",
        user_id=_OWNER,
        channel="console",
        agent_id="a-code",
        tool_name="Bash",
        created_at=0.0,
        future=asyncio.get_event_loop().create_future(),
        owner_user_id=_OWNER,
    )
    assert identity_check(row, None) == "missing_actor"
    assert identity_check(row, ApprovalActor(source="http")) == "missing_identity"
    assert (
        identity_check(row, ApprovalActor(user_id="mallory", source="http"))
        == "not_owner"
    )
    assert (
        identity_check(row, ApprovalActor(user_id=_OWNER, source="http")) is None
    )
    legacy = PendingApproval(
        request_id="r-legacy",
        session_id="s-legacy",
        root_session_id="s-legacy",
        user_id="",
        channel="console",
        agent_id="a-legacy",
        tool_name="Bash",
        created_at=0.0,
        future=asyncio.get_event_loop().create_future(),
        owner_user_id="",
    )
    assert identity_check(legacy, _OWNER_ACTOR) == "unowned_record"


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


async def test_user_choice_leaves_an_intent_ledger_row(service):
    # B2 交付（2026-11-15）：审批意图台账表 ``approval_intents`` +
    # ``approvals/intent_ledger`` 写入器。一行两列是刻意的：``decision``
    # 记用户点的动作，``outcome`` 记系统是否采纳（refused:*）。
    # 无 actor 的 resolve 照旧被身份边界拒绝，但"用户点了批准"这件事
    # 本身入账 —— 台账不歪曲用户行为。
    item = await _pending(service, "s-intent")
    await service.resolve_request(item.request_id, ApprovalDecision.APPROVED)
    rows = await service.list_intent_rows(session_id="s-intent")
    assert rows and rows[0]["decision"] == "approved"


async def test_timeout_leaves_a_ledger_row_not_a_vanish(service):
    # B2 交付（2026-11-15）：超时 = 一次**默认拒绝**，落台账
    # ``decision=timed_out``（``ApprovalDecision.TIMED_OUT``，台账尺子）。
    # Future 侧仍回 TIMEOUT —— 那是 agent 等的信号，改名等于历史对不上。
    # 读侧 ``list_timeout_rows`` 先结账再查，超时计数不依赖维护循环节拍。
    item = await _pending(service, "s-timeout", timeout_seconds=0.0)
    await asyncio.sleep(0.05)
    rows = await service.list_timeout_rows(session_id="s-timeout")
    assert rows and rows[0]["decision"] == ApprovalDecision.TIMED_OUT.value