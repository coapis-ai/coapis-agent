# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Approval API endpoints for tool guard approvals."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..approvals import get_approval_service
from ...security.tool_guard.approval import ApprovalDecision

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approval", tags=["approval"])


class ApprovalActionRequest(BaseModel):
    """Request body for approval actions."""

    request_id: str = Field(..., description="Approval request ID (UUID)")
    session_id: str = Field(..., description="Session ID")
    user_id: Optional[str] = Field(
        None,
        description="User ID (optional, for validation)",
    )
    reason: Optional[str] = Field(
        None,
        description="Optional reason for denial",
    )


class ApprovalActionResponse(BaseModel):
    """Response for approval actions."""

    success: bool
    message: str
    tool_name: Optional[str] = None
    request_id: str


class ApprovalListResponse(BaseModel):
    """Response for listing pending approvals."""

    pending_approvals: list[dict]
    count: int


@router.post(
    "/approve",
    response_model=ApprovalActionResponse,
    summary="Approve a pending tool execution",
)
async def post_approval_approve(
    request: Request,  # pylint: disable=unused-argument
    body: ApprovalActionRequest,
) -> ApprovalActionResponse:
    """Approve a pending tool execution.

    Resolves the Future associated with the approval request,
    allowing the agent to continue executing the tool.
    """
    svc = get_approval_service()

    logger.info(
        "Approval approve request: request_id=%s session_id=%s",
        body.request_id[:16],
        body.session_id,
    )

    # Verify the request belongs to the root session (support cross-session)
    pending = await svc.get_request(body.request_id)
    if pending is None:
        logger.warning(
            "Approval request not found: %s",
            body.request_id[:16],
        )
        raise HTTPException(
            status_code=404,
            detail=f"Approval request not found: {body.request_id[:16]}",
        )

    # Accept either the root session or the agent-side session id: the
    # frontend resolves the chat identity from several sources (URL chatId →
    # per-approval rootSessionId → global window fallback) and used to be
    # rejected with 403 whenever it landed on the agent session id.
    if body.session_id and body.session_id not in (
        pending.root_session_id,
        pending.session_id,
    ):
        logger.warning(
            "Root session mismatch: request %s (root: %s, session: %s) "
            "not in session %s",
            body.request_id[:16],
            pending.root_session_id,
            pending.session_id,
            body.session_id,
        )
        raise HTTPException(
            status_code=403,
            detail="Root session mismatch: cannot approve other session trees",
        )

    # Resolve the Future — only when an agent is still waiting on it.
    resolved, state = await svc.resolve_live(
        body.request_id,
        ApprovalDecision.APPROVED,
    )

    if state == "stale":
        # The waiting agent already gave up (timeout / cancelled). Promising
        # "approved, executing..." here is the symptom-3 lie: the card says
        # 批准 and nothing runs.
        logger.warning(
            "Approval approve on stale record: request_id=%s status=%s",
            body.request_id[:16],
            pending.status,
        )
        raise HTTPException(
            status_code=410,
            detail=(
                "该审批已超时失效，批准不会执行工具。"
                "请重新发起该操作，出现新审批卡后立即批准。"
            ),
        )

    assert resolved is not None
    logger.info(
        "Approval approved: request_id=%s session=%s tool=%s",
        body.request_id[:16],
        body.session_id,
        resolved.tool_name,
    )

    return ApprovalActionResponse(
        success=True,
        message=f"Tool '{resolved.tool_name}' approved, executing...",
        tool_name=resolved.tool_name,
        request_id=body.request_id,
    )


@router.post(
    "/deny",
    response_model=ApprovalActionResponse,
    summary="Deny a pending tool execution",
)
async def post_approval_deny(
    request: Request,  # pylint: disable=unused-argument
    body: ApprovalActionRequest,
) -> ApprovalActionResponse:
    """Deny a pending tool execution.

    Resolves the Future with DENIED decision, preventing
    the agent from executing the tool.
    """
    svc = get_approval_service()

    reason = body.reason or "User denied"

    logger.info(
        "Approval deny request: request_id=%s session_id=%s reason=%s",
        body.request_id[:16],
        body.session_id,
        reason,
    )

    # Verify the request belongs to the root session (support cross-session)
    pending = await svc.get_request(body.request_id)
    if pending is None:
        logger.warning(
            "Approval request not found: %s",
            body.request_id[:16],
        )
        raise HTTPException(
            status_code=404,
            detail=f"Approval request not found: {body.request_id[:16]}",
        )

    if body.session_id and body.session_id not in (
        pending.root_session_id,
        pending.session_id,
    ):
        logger.warning(
            "Root session mismatch: request %s (root: %s, session: %s) "
            "not in session %s",
            body.request_id[:16],
            pending.root_session_id,
            pending.session_id,
            body.session_id,
        )
        raise HTTPException(
            status_code=403,
            detail="Root session mismatch: cannot approve other session trees",
        )

    # Resolve the Future — only when an agent is still waiting on it.
    resolved, state = await svc.resolve_live(
        body.request_id,
        ApprovalDecision.DENIED,
    )

    if state == "stale":
        # Denying a record nobody waits on is harmless; report it honestly.
        logger.info(
            "Approval deny on stale record: request_id=%s status=%s",
            body.request_id[:16],
            pending.status,
        )
        return ApprovalActionResponse(
            success=True,
            message=(
                f"Tool '{pending.tool_name}' 已超时失效，"
                "该操作不会执行（无需拒绝）。"
            ),
            tool_name=pending.tool_name,
            request_id=body.request_id,
        )

    assert resolved is not None
    logger.info(
        "Approval denied: request_id=%s session=%s tool=%s",
        body.request_id[:16],
        body.session_id,
        resolved.tool_name,
    )

    return ApprovalActionResponse(
        success=True,
        message=f"Tool '{resolved.tool_name}' denied: {reason}",
        tool_name=resolved.tool_name,
        request_id=body.request_id,
    )


@router.get(
    "/list",
    response_model=ApprovalListResponse,
    summary="List pending approval requests",
)
async def get_approval_list(
    request: Request,  # pylint: disable=unused-argument
    session_id: Optional[str] = None,
) -> ApprovalListResponse:
    """List all pending approval requests.

    Optionally filter by session_id.
    """
    svc = get_approval_service()

    if session_id:
        logger.debug(
            "Listing approvals for root session (includes children): %s",
            session_id,
        )
        # Use get_pending_by_root_session for cross-session support
        pending_list = await svc.get_pending_by_root_session(session_id)
    else:
        logger.debug("Listing all pending approvals")
        # pylint: disable=protected-access
        async with svc._lock:
            pending_list = list(svc._pending.values())

    # Serialize pending approvals
    result = []
    for pending in pending_list:
        result.append(
            {
                "request_id": pending.request_id,
                "session_id": pending.session_id,
                "root_session_id": pending.root_session_id,
                "agent_id": pending.agent_id,
                "tool_name": pending.tool_name,
                "severity": pending.severity,
                "findings_count": pending.findings_count,
                "created_at": pending.created_at,
                "timeout_seconds": pending.timeout_seconds,
                "result_summary": pending.result_summary,
            },
        )

    logger.info("Listed %d pending approvals", len(result))

    return ApprovalListResponse(
        pending_approvals=result,
        count=len(result),
    )
