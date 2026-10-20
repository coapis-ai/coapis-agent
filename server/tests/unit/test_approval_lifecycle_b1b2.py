# -*- coding: utf-8 -*-
"""批1+批2 lock: an approval is only offered/accepted while it is *live*.

Defect being locked (企业生产 2026-10-19, 三现象):
  1. "提示要审批，但没有审批窗口" — ``/console/push-messages`` handed out
     records whose timeout had elapsed 34x ago; the card mounted, computed
     ``remaining = 0`` and removed itself within the same frame.
  2. "/approve 不在下拉里" — frontend-only symptom (批4), not covered here.
  3. "已批准但对话直接断开" — ``/approve`` resolved the FIFO *oldest*
     record, whose Future was already closed; the reply promised
     "正在执行" with no agent coroutine waiting on it.

Contract:
  * every reader expires stale records first and returns only live ones;
  * ``resolve_live`` refuses to resolve a record nobody waits on;
  * ``/approve`` / ``/deny`` never promise execution for a dead record;
  * expiry is time-driven (maintenance loop), not creation-driven.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from coapis.app.approvals.service import ApprovalService
from coapis.app.runner.control_commands.approval_handler import (
    ApprovalCommandHandler,
)
from coapis.app.runner.control_commands.base import ControlContext
from coapis.security.tool_guard.approval import ApprovalDecision
from coapis.security.tool_guard.models import ToolGuardResult

SESSION = "console:approval-lifecycle"
AGENT = "agent:default"


def _result(tool: str = "execute_shell_command") -> ToolGuardResult:
    return ToolGuardResult(tool_name=tool, params={"command": "echo x"})


async def _make(
    svc: ApprovalService,
    *,
    tool: str = "execute_shell_command",
    timeout: float = 300.0,
    age: float = 0.0,
    session_id: str = SESSION,
) -> str:
    """Create a pending approval, optionally backdated by *age* seconds."""
    pending = await svc.create_pending(
        session_id=session_id,
        root_session_id=session_id,
        user_id="admin",
        channel="console",
        agent_id=AGENT,
        tool_name=tool,
        result=_result(tool),
        timeout_seconds=timeout,
    )
    if age:
        pending.created_at -= age
    return pending.request_id


def _ctx(svc: ApprovalService, args: dict) -> ControlContext:
    return ControlContext(
        workspace=None,
        payload={},
        channel=None,
        session_id=SESSION,
        user_id="admin",
        agent_id=AGENT,
        role="admin",
        args=args,
    )


@pytest.fixture(autouse=True)
def _patch_service(monkeypatch, request):
    """The handler resolves the singleton via the module-level import."""
    import coapis.app.runner.control_commands.approval_handler as ah

    svc = ApprovalService()
    monkeypatch.setattr(ah, "get_approval_service", lambda: svc)
    request.node.svc = svc
    return svc


async def _run(svc: ApprovalService, args: dict) -> str:
    return await ApprovalCommandHandler().handle(_ctx(svc, args))


# ---------------------------------------------------------------------------
# 批1 — readers must not hand out dead approvals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_reader_expires_stale():
    svc = ApprovalService()
    await _make(svc, age=3600.0)
    live = await _make(svc)

    assert await svc.list_pending_by_session(SESSION) == [
        p for p in svc._pending.values() if p.request_id == live  # noqa: SLF001
    ]
    record = svc._pending[live]  # noqa: SLF001
    assert record.status == "pending"


@pytest.mark.asyncio
async def test_global_poll_drops_stale():
    """ConsolePollService path: session_id=None must not return dead cards."""
    svc = ApprovalService()
    dead = await _make(svc, age=10190.0)  # the production elapsed value
    live = await _make(svc)

    items = await svc.get_all_pending_by_session(None)
    ids = {p.request_id for p in items}
    assert ids == {live}
    assert dead not in ids
    # Expired records are marked timeout, then GC'd by the same reader call.
    record = svc._pending.get(dead)  # noqa: SLF001
    assert record is None or (
        record.status == "timeout" and record.future.done()
    ), record


@pytest.mark.asyncio
async def test_fifo_head_skips_stale():
    svc = ApprovalService()
    dead = await _make(svc, age=3600.0)
    live = await _make(svc)

    head = await svc.get_pending_by_session(SESSION)
    assert head is not None and head.request_id == live
    assert dead != head.request_id


@pytest.mark.asyncio
async def test_root_session_reader_drops_stale():
    svc = ApprovalService()
    await _make(svc, age=3600.0)
    live = await _make(svc)
    items = await svc.get_pending_by_root_session(SESSION)
    assert [p.request_id for p in items] == [live]


@pytest.mark.asyncio
async def test_countdown_is_server_authoritative():
    svc = ApprovalService()
    rid = await _make(svc, timeout=300.0, age=40.0)
    left = await svc.live_remaining_seconds(rid)
    assert left is not None and 255.0 < left <= 300.0
    assert await svc.live_remaining_seconds("no-such-id") is None


@pytest.mark.asyncio
async def test_maintenance_loop_expires_without_new_creates():
    """Production symptom: a quiet session kept its dead record for 2.8h."""
    svc = ApprovalService()
    dead = await _make(svc, timeout=0.05)
    svc.start_maintenance(interval_seconds=0.02)
    try:
        for _ in range(50):
            if svc._pending[dead].status != "pending":  # noqa: SLF001
                break
            await asyncio.sleep(0.02)
    finally:
        svc.stop_maintenance()
    assert svc._pending[dead].status == "timeout"  # noqa: SLF001


# ---------------------------------------------------------------------------
# 批2 — resolve_live / handler must refuse dead approvals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_live_ok_for_live_record():
    svc = ApprovalService()
    rid = await _make(svc)
    pending, state = await svc.resolve_live(rid, ApprovalDecision.APPROVED)
    assert state == "ok"
    assert pending is not None and pending.status == "approved"
    assert pending.future.result() == ApprovalDecision.APPROVED


@pytest.mark.asyncio
async def test_resolve_live_refuses_closed_future():
    """The waiting agent gave up → approving must not claim execution."""
    svc = ApprovalService()
    rid = await _make(svc)
    svc._pending[rid].future.cancel()  # noqa: SLF001 - agent gave up
    pending, state = await svc.resolve_live(rid, ApprovalDecision.APPROVED)
    assert state == "stale"
    assert pending is not None
    assert pending.status == "pending"  # untouched: nothing to resolve


@pytest.mark.asyncio
async def test_resolve_live_not_found():
    svc = ApprovalService()
    pending, state = await svc.resolve_live("missing", ApprovalDecision.APPROVED)
    assert pending is None and state == "not_found"


@pytest.mark.asyncio
async def test_prefix_lookup_only_live_and_ambiguous():
    svc = ApprovalService()
    dead = await _make(svc, age=3600.0)
    cand, matches = await svc.find_live_by_prefix(dead[:8])
    assert (cand, matches) == (None, 0)

    live = await _make(svc)
    cand, matches = await svc.find_live_by_prefix(live[:8])
    assert matches == 1 and cand is not None
    assert cand.request_id == live

    await _make(svc)
    cand, matches = await svc.find_live_by_prefix("")
    assert (cand, matches) == (None, 0)


@pytest.mark.asyncio
async def test_approve_command_never_promises_execution_for_dead_record(request):
    svc = request.node.svc
    dead = await _make(svc, age=3600.0)
    text = await _run(svc, {"action": "approve", "request_id": dead})
    # Either "no pending approval" (record GC'd) or the explicit
    # "approval is dead, nothing will run" guidance — never a promise.
    assert "正在执行" not in text
    assert "工具已批准" not in text
    assert ("无待审批工具" in text) or ("审批已失效" in text), text


@pytest.mark.asyncio
async def test_approve_dead_id_by_prefix_explains_invalidation(request):
    """Full id of a record that is past timeout → guidance, not '已批准'."""
    svc = request.node.svc
    dead = await _make(svc, age=3600.0)
    # Force the record to stay visible as a *closed* approval (not popped):
    svc._pending[dead].future.cancel()  # noqa: SLF001
    text = await _run(svc, {"action": "approve", "request_id": dead})
    assert "已批准" not in text
    assert "正在执行" not in text


@pytest.mark.asyncio
async def test_approve_live_record_reports_executing(request):
    svc = request.node.svc
    rid = await _make(svc)
    text = await _run(svc, {"action": "approve", "request_id": rid[:8]})
    assert "工具已批准" in text
    assert "正在执行" in text


@pytest.mark.asyncio
async def test_approve_ambiguous_prefix_lists_count(request):
    svc = request.node.svc
    r1 = await _make(svc, tool="execute_shell_command")
    r2 = await _make(svc, tool="write_file")
    # Re-key both records so they share an id prefix (UUIDs rarely do).
    for rid, new in ((r1, "feedface-0001"), (r2, "feedface-0002")):
        rec = svc._pending.pop(rid)  # noqa: SLF001
        rec.request_id = new
        svc._pending[new] = rec  # noqa: SLF001

    text = await _run(svc, {"action": "approve", "request_id": "feedface"})
    assert "不唯一" in text
    assert "2" in text
    assert svc._pending["feedface-0001"].status == "pending"  # noqa: SLF001
    assert svc._pending["feedface-0002"].status == "pending"  # noqa: SLF001


@pytest.mark.asyncio
async def test_deny_dead_record_says_nothing_to_deny(request):
    svc = request.node.svc
    dead = await _make(svc, age=3600.0)
    svc._pending[dead].future.cancel()  # noqa: SLF001
    text = await _run(svc, {"action": "deny", "request_id": dead})
    assert "已失效" in text or "无待审批工具" in text


@pytest.mark.asyncio
async def test_agent_id_guard_still_applies(request):
    svc = request.node.svc
    rid = await _make(svc)
    svc._pending[rid].agent_id = "agent:other"  # noqa: SLF001
    text = await _run(svc, {"action": "approve", "request_id": rid})
    assert "权限不足" in text
