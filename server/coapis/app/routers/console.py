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

"""Console router - Console endpoints (CoApis console compatible).

Uses CoApis-style component chain:
    Request → ConsoleChannel.stream_one() → TaskTracker → SSE events
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, Query, Body, Request
from fastapi.responses import StreamingResponse

from ..runner.models import ChatUpdate
from ..permissions import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["console"])

import re

# UUID pattern (e.g. "550e8400-e29b-41d4-a716-446655440000")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _is_default_chat_name(name: Optional[str]) -> bool:
    """Check if a chat name is a 'default' that should be auto-renamed."""
    if not name:
        return True
    if name in ("New Chat", "新聊天", ""):
        return True
    # UUID-like names (backend may use chat UUID as name when no text available)
    if _UUID_RE.match(name):
        return True
    # Very short names (likely truncated garbage)
    if len(name) <= 2:
        return True
    return False


@require_permission("chat:read")
@router.get("/console/push-messages")
async def get_push_messages(
    request: Request,
    session_id: str = Query(None),
) -> Dict[str, Any]:
    """Get push messages and pending approvals.

    Returns real pending approvals from the global ApprovalService
    so that the frontend can render interactive ApprovalCard widgets.

    Security: Strict session-level isolation. Only returns approvals
    belonging to the specified session_id. No cross-session leakage.
    """
    from ..approvals import get_approval_service
    from ...security.tool_guard.approval import format_findings_summary

    pending_approvals: list[Dict[str, Any]] = []
    try:
        svc = get_approval_service()
        # Debug: log all pending approvals
        all_pending = await svc.get_all_pending_by_session(None)
        if all_pending:
            logger.info(
                "[PUSH MESSAGES] Total pending approvals: %d. "
                "Query session_id=%s. "
                "Pending: %s",
                len(all_pending),
                session_id,
                [
                    {
                        "request_id": p.request_id[:8],
                        "session_id": p.session_id,
                        "root_session_id": p.root_session_id[:8] if p.root_session_id else None,
                        "tool": p.tool_name,
                    }
                    for p in all_pending[:5]  # Only log first 5
                ],
            )
        
        # Strict session-level isolation: must have session_id
        if not session_id:
            # No session_id = no approvals (security by default)
            pendings = []
            logger.debug("[PUSH MESSAGES] No session_id provided, returning empty")
        else:
            # Query by both session_id and root_session_id to handle
            # format differences: chat UUID vs "console:{username}".
            # list_pending_by_session filters by p.session_id (exact match),
            # get_pending_by_root_session filters by p.root_session_id.
            pendings = await svc.list_pending_by_session(session_id)
            logger.debug(
                "[PUSH MESSAGES] list_pending_by_session(%s) returned %d results",
                session_id,
                len(pendings),
            )
            if not pendings:
                pendings = await svc.get_pending_by_root_session(session_id)
                logger.debug(
                    "[PUSH MESSAGES] get_pending_by_root_session(%s) returned %d results",
                    session_id,
                    len(pendings),
                )

        for p in pendings:
            guard_result = getattr(p, "extra", {}).get("guard_result")
            findings_summary = ""
            if guard_result:
                try:
                    findings_summary = format_findings_summary(guard_result)
                except Exception:
                    findings_summary = ""
            tool_call = getattr(p, "extra", {}).get("tool_call", {})
            tool_input = tool_call.get("input", {}) if isinstance(tool_call, dict) else {}

            pending_approvals.append({
                "request_id": p.request_id,
                "session_id": p.session_id,
                "root_session_id": p.root_session_id,
                "agent_id": p.agent_id,
                "tool_name": p.tool_name,
                "severity": p.severity,
                "findings_count": p.findings_count,
                "findings_summary": findings_summary,
                "tool_params": tool_input,
                "created_at": p.created_at,
                "timeout_seconds": p.timeout_seconds,
            })
        
        if pending_approvals:
            logger.info(
                "[PUSH MESSAGES] Returning %d pending approvals for session_id=%s",
                len(pending_approvals),
                session_id,
            )
    except Exception:
        logger.debug("Failed to fetch pending approvals", exc_info=True)

    return {
        "messages": [],
        "pending_approvals": pending_approvals,
    }


@require_permission("debug:read")
@router.get("/console/debug/backend-logs")
async def get_backend_logs(
    request: Request,
    lines: int = Query(200),
) -> Dict[str, Any]:
    """Get backend debug logs."""
    from ...constant import WORKING_DIR
    log_file = WORKING_DIR / "coapis.log"
    if not log_file.exists():
        from ...constant import LOGS_DIR
        log_file = LOGS_DIR / "coapis.log"

    if not log_file.exists():
        return {
            "path": str(log_file),
            "exists": False,
            "lines": 0,
            "updated_at": None,
            "size": 0,
            "content": "",
        }

    try:
        content = log_file.read_text()
        log_lines = content.strip().split("\n")
        recent_lines = log_lines[-lines:] if len(log_lines) > lines else log_lines

        return {
            "path": str(log_file),
            "exists": True,
            "lines": len(recent_lines),
            "updated_at": log_file.stat().st_mtime,
            "size": log_file.stat().st_size,
            "content": "\n".join(recent_lines),
        }
    except Exception as e:
        logger.error(f"Failed to read logs: {e}")
        return {
            "path": str(log_file),
            "exists": True,
            "lines": 0,
            "updated_at": None,
            "size": 0,
            "content": f"Error: {e}",
        }


def _extract_native_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract native payload from CoApis frontend request format.

    CoApis frontend sends:
    {
        "input": [{"role": "user", "content": [...], "session": {...}}],
        "session_id": "...",
        "user_id": "...",
        "channel": "console",
        "stream": true,
        "biz_params": {"agent_id": "..."}
    }

    Returns native payload format expected by ConsoleChannel:
    {
        "channel_id": "console",
        "sender_id": "username",
        "content_parts": [...],
        "meta": {"session_id": "...", "user_id": "..."}
    }
    """
    input_msgs = payload.get("input", [])
    message_text = payload.get("message", "")
    session_id = payload.get("session_id", "")
    user_id = payload.get("user_id", "default")
    channel = payload.get("channel", "console")

    # Extract content parts from input messages
    content_parts: List[Any] = []
    for msg in input_msgs:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                content_parts.append({"type": "text", "text": content.strip()})
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        content_parts.append(item)

    # Fallback: if no content extracted from input, use "message" field
    if not content_parts and message_text and isinstance(message_text, str) and message_text.strip():
        content_parts.append({"type": "text", "text": message_text.strip()})

    return {
        "channel_id": channel,
        "sender_id": user_id,
        "content_parts": content_parts,
        "meta": {
            "session_id": session_id,
            "user_id": user_id,
        },
    }


@require_permission("chat:send")
@router.post("/console/chat")
async def console_chat(
    request: Request,
    payload: Optional[Dict[str, Any]] = Body(default=None),
):
    request_chat_id = None  # Initialize before any conditional use
    if payload is None:
        payload = {}
    import json as _json
    logger.warning(
        "CONSOLE_CHAT_PAYLOAD: %s",
        _json.dumps(payload, ensure_ascii=False),
    )
    """Console chat endpoint - SSE streaming response using CoApis component chain.

    Component chain:
        Request → ConsoleChannel.stream_one() → TaskTracker → SSE events

    This replaces the previous direct core.stream_chat() call with the proper
    agentscope_runtime component chain, ensuring correct event format, message
    filtering, and reconnection support.
    """
    manager = request.app.state.multi_agent_manager
    if not manager:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable, please retry later")

    # ── Extract agent_id (same logic as before) ──
    input_msgs = payload.get("input", [])
    biz_params = payload.get("biz_params", {})
    agent_id = biz_params.get("agent_id") or payload.get("agent_id")
    if not agent_id and input_msgs:
        last_msg = input_msgs[-1]
        session = last_msg.get("session", {})
        agent_id = session.get("agent_id")
    # ── Extract user identity (must come before agent_id fallback) ──
    username = getattr(request.state, "username", None)
    user_role = getattr(request.state, "role", "user")
    if not username:
        user_info = getattr(request.state, "user_info", None)
        if user_info and isinstance(user_info, dict):
            username = user_info.get("username", "anonymous")
            user_role = user_info.get("role", "user")
    if not username:
        username = "anonymous"

    if not agent_id or agent_id == "default":
        # Frontend default is "default" which no longer exists after global_
        # rename.  Fall back to the user's own default agent.
        agent_id = f"user:{username}"
        logger.info(f"agent_id not provided, falling back to {agent_id}")

    # ── Get workspace (get_agent starts workspace if needed, get_workspace is cache-only) ──
    workspace = await manager.get_agent(agent_id, username=username)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # ── Inject session context (unified contextvars, CoApis pattern) ──
    from ...config.session_context import set_session_context
    set_session_context(
        user_id=username,
        username=username,
        user_role=user_role,
        agent_id=agent_id,
        channel="console",
        workspace_dir=workspace.workspace_dir,
    )

    # ── Get console channel ──
    if workspace.channel_manager is None:
        await workspace.ensure_channel_manager()
    console_channel = workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )

    # ── Build native payload ──
    session_id = payload.get("session_id", "")
    # SECURITY: Always use authenticated username as user_id.
    # Never trust frontend-supplied user_id (it may be "default" or spoofed).
    user_id = username
    native_payload = _extract_native_payload(payload)
    native_payload["sender_id"] = user_id
    native_payload["meta"]["session_id"] = session_id
    native_payload["meta"]["user_id"] = user_id
    
    # ── Pass file references through meta (not content_parts) ──
    # File references are passed via meta to avoid polluting user message
    # They will be injected as system hint before AI processing
    selected_files = biz_params.get("selected_files", [])
    if selected_files:
        native_payload["meta"]["selected_files"] = selected_files
        logger.info(f"Passing {len(selected_files)} file references through meta")

    # ── Extract chat_id early (used in session context + chat lookup) ──
    # Check both top-level and biz_params (frontend may pass it in either place)
    request_chat_id = payload.get("chat_id") or (payload.get("biz_params") or {}).get("chat_id")

    # Pass chat_id through native_payload so background tasks can resolve it
    if request_chat_id:
        native_payload["meta"]["chat_id"] = request_chat_id
    elif payload.get("session_id"):
        # Frontend sometimes sends chat UUID as session_id
        native_payload["meta"]["chat_id"] = payload["session_id"]
        request_chat_id = payload["session_id"]

    # ── Resolve session_id via channel ──
    resolved_session_id = console_channel.resolve_session_id(
        sender_id=native_payload["sender_id"],
        channel_meta=native_payload["meta"],
    )

    # Update session context with resolved session_id (for downstream use)
    from ...config.session_context import set_current_session_id, set_current_chat_id
    set_current_session_id(resolved_session_id)
    if request_chat_id:
        set_current_chat_id(request_chat_id)

    # ── Determine chat name from content ──
    name = "New Chat"
    if native_payload["content_parts"]:
        content = native_payload["content_parts"][0]
        if content:
            if isinstance(content, str):
                name = content[:10]
            elif isinstance(content, dict) and "text" in content:
                name = content["text"][:10]
            else:
                name = str(content)[:10]

    # ── Get or create chat via per-user ChatManager (not workspace ChatManager) ──
    # This ensures chats are stored in workspaces/{username}/chat/chats.json
    # and properly isolated per user.
    user_cm = manager.get_user_chat_manager(username)
    if not user_cm:
        raise HTTPException(status_code=503, detail="Chat manager not available")
    
    # Prefer chat_id (UUID from frontend) to match the exact chat.
    # session_id is shared across all console chats (e.g. "console:admin"),
    # so using it to match causes messages to pile into the wrong chat.
    chat = None
    if request_chat_id:
        chat = await user_cm.get_chat(request_chat_id)
    if chat is None:
        chat = await user_cm.get_or_create_chat(
            session_id=resolved_session_id,
            user_id=native_payload["sender_id"],
            channel=native_payload["channel_id"],
            name=name,
            agent_id=agent_id,
        )
    elif chat.name in ("New Chat", "新聊天", "") and name != "New Chat":
        # Auto-rename: update chat name from first user message
        # ChatUpdate already imported at top of file
        try:
            await user_cm.patch_chat(chat.id, ChatUpdate(name=name))
            chat.name = name
        except Exception as e:
            logger.warning(f"Failed to auto-rename chat {chat.id}: {e}")
    elif _is_default_chat_name(chat.name) and name and name != "New Chat":
        # Auto-rename: also handle UUID-like or other default names
        # ChatUpdate already imported at top of file
        try:
            await user_cm.patch_chat(chat.id, ChatUpdate(name=name))
            chat.name = name
        except Exception as e:
            logger.warning(f"Failed to auto-rename chat {chat.id}: {e}")

    # ── Task tracker operations ──
    tracker = workspace.task_tracker
    is_reconnect = payload.get("reconnect") is True

    # ── Pre-persist user message before streaming starts ──
    # This ensures the user message is saved immediately, so it's available
    # if the user refreshes before the stream completes.
    # _persist_chat_messages has dedup logic to skip duplicate user messages.
    if not is_reconnect and native_payload.get("content_parts"):
        user_content = None
        first_part = native_payload["content_parts"][0]
        if isinstance(first_part, str):
            user_content = first_part
        elif isinstance(first_part, dict) and "text" in first_part:
            user_content = first_part["text"]
        
        if user_content and chat:
            try:
                from .chats import _get_session_for_user
                session_obj = _get_session_for_user(username, request)
                if session_obj:
                    state = await session_obj.get_session_state_dict(
                        chat.id, chat.user_id,
                        allow_not_exist=True,
                    )
                    memory_state = (state or {}).get("agent", {}).get("memory", {})
                    from agentscope.memory import InMemoryMemory
                    mem = InMemoryMemory()
                    mem.load_state_dict(memory_state, strict=False)
                    from agentscope.message import Msg, TextBlock
                    await mem.add(Msg(name="user", content=[TextBlock(text=user_content)], role="user"))
                    await session_obj.update_session_state(
                        session_id=chat.id,
                        key="agent.memory",
                        value=mem.state_dict(),
                        user_id=chat.user_id,
                    )
                    logger.info(f"Pre-persisted user message to session chat={chat.id}")
            except Exception as e:
                logger.warning(f"Failed to pre-persist user message to session: {e}")

    if is_reconnect:
        queue = await tracker.attach(chat.id)
        if queue is None:
            # No active run to reconnect to - return empty stream
            async def empty_gen():
                yield ""
            return StreamingResponse(
                empty_gen(),
                media_type="text/event-stream",
            )
    else:
        queue, started = await tracker.attach_or_start(
            chat.id,
            native_payload,
            console_channel.stream_one,
            # on_complete callback removed: workspace._process_handler now handles
            # full structured persistence (thinking, tool_use, tool_result, text blocks)
            # directly in the session, avoiding text-only overwrite.
        )
        
        # Update chat status to "running" when task starts
        if started:
            try:
                await user_cm.patch_chat(chat.id, ChatUpdate(status="running"))
                logger.info(f"Chat {chat.id} status updated to running")
            except Exception as e:
                logger.warning(f"Failed to update chat status to running: {e}")

    # ── SSE event generator ──
    # Note: All message persistence is handled by workspace._process_handler
    # (unified persist: user msg + assistant structured blocks in one atomic write)
    async def event_generator() -> AsyncGenerator[str, None]:
        stream_it = tracker.stream_from_queue(queue, chat.id)
        try:
            async for event_data in stream_it:
                yield event_data
        except Exception as e:
            logger.exception("Console chat stream error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            await stream_it.aclose()
            # Clean up session context after stream ends
            from ...config.session_context import clear_session_context
            clear_session_context()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@require_permission("chat:read")
@router.get("/console/sessions")
async def get_console_sessions(
    request: Request,
    agent_id: str = Query(""),
    channel: str = Query("", description="Filter by channel, empty=all"),
) -> Dict[str, Any]:
    """Get chat sessions for console.
    
    ENFORCES USER ISOLATION: Uses per-user ChatManager.
    channel="" returns all channels (console, wecom, dingtalk, etc).
    """
    manager = request.app.state.multi_agent_manager
    
    username = getattr(request.state, "username", None)
    if not username:
        user_info = getattr(request.state, "user_info", None)
        if user_info and isinstance(user_info, dict):
            username = user_info.get("username", "anonymous")
    if not username:
        username = "anonymous"
    
    role = getattr(request.state, "role", "user")
    is_admin = role == "admin"
    
    # Use per-user ChatManager for isolation
    user_cm = manager.get_user_chat_manager(username) if manager else None
    if not user_cm:
        return {"sessions": [], "total": 0}

    # channel="console" means "default view" — return all channels
    effective_channel = "" if channel == "console" else channel
    # Don't pass user_id — ChatManager is already per-user (file-level isolation).
    # External channels (wecom, dingtalk) use sender_id as user_id in chat records,
    # which differs from the workspace owner username. Filtering by user_id would
    # exclude all external channel chats.
    chats = await user_cm.list_chats(
        channel=effective_channel,
    )

    # Filter by agent_id if provided (frontend per-agent isolation)
    if agent_id:
        chats = [
            chat for chat in chats
            if (getattr(chat, "agent_id", None) or "default") == agent_id
        ]


    sessions = []
    for chat in chats:
        sessions.append({
            "id": chat.id,
            "name": chat.name or chat.id[:8],
            "agent_id": getattr(chat, "agent_id", "default") or "default",
            "created_at": chat.created_at,
            "updated_at": chat.updated_at,
            "message_count": 0,  # Would need message counting from repository
            "status": chat.status,
        })

    # Sort by updated_at descending
    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)

    return {
        "sessions": sessions,
        "total": len(sessions),
    }


@require_permission("chat:write")
@router.post("/console/sessions/{session_id}/rename")
async def rename_session(
    request: Request,
    session_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Rename a chat session.
    
    ENFORCES USER ISOLATION: Uses per-user ChatManager.
    """
    manager = request.app.state.multi_agent_manager
    username = getattr(request.state, "username", "anonymous")
    role = getattr(request.state, "role", "user")
    is_admin = role == "admin"
    
    cm = manager.get_user_chat_manager(username) if manager else None
    if not cm:
        raise HTTPException(status_code=503, detail="Chat manager not available")

    chat = await cm.get_chat(session_id)
    if not chat:
        # Admin aggregation: try all users
        if is_admin and manager:
            all_cms = manager.get_all_user_chat_managers()
            for _uname, ucm in all_cms.items():
                chat = await ucm.get_chat(session_id)
                if chat:
                    cm = ucm
                    break
        if not chat:
            raise HTTPException(status_code=404, detail="Session not found")
    
    # Enforce isolation: non-admin can only rename own chats
    if not is_admin and chat.user_id != username:
        raise HTTPException(status_code=403, detail="Access denied")

    new_name = payload.get("name", "")
    await cm.patch_chat(
        session_id,
        ChatUpdate(name=new_name),
    )

    return {"ok": True, "name": new_name}


@require_permission("chat:write")
@router.delete("/console/sessions/{session_id}")
async def delete_session(
    request: Request,
    session_id: str,
) -> Dict[str, Any]:
    """Delete a chat session.
    
    ENFORCES USER ISOLATION: Uses per-user ChatManager.
    """
    manager = request.app.state.multi_agent_manager
    username = getattr(request.state, "username", "anonymous")
    role = getattr(request.state, "role", "user")
    is_admin = role == "admin"
    
    cm = manager.get_user_chat_manager(username) if manager else None
    if not cm:
        raise HTTPException(status_code=503, detail="Chat manager not available")

    # First check if chat exists and belongs to user
    chat = await cm.get_chat(session_id)
    if not chat:
        # Admin aggregation: try all users
        if is_admin and manager:
            all_cms = manager.get_all_user_chat_managers()
            for _uname, ucm in all_cms.items():
                chat = await ucm.get_chat(session_id)
                if chat:
                    cm = ucm
                    break
        if not chat:
            raise HTTPException(status_code=404, detail="Session not found")
    
    # Enforce isolation: non-admin can only delete own chats
    if not is_admin and chat.user_id != username:
        raise HTTPException(status_code=403, detail="Access denied")

    success = await cm.delete_chat(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"ok": True}


@require_permission("chat:write")
@router.post("/console/chat/stop")
async def stop_chat(
    request: Request,
    chat_id: str = Query(..., description="Chat ID to stop"),
) -> Dict[str, Any]:
    """Stop an ongoing chat task.
    
    This endpoint stops the background task for the given chat_id,
    preventing further message generation and pushing.
    """
    manager = request.app.state.multi_agent_manager
    username = getattr(request.state, "username", "anonymous")
    
    if not manager:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")
    
    # Get workspace for the user's agent
    agent_id = f"user:{username}"
    workspace = manager.get_workspace(agent_id, username=username)
    
    if not workspace or not workspace.task_tracker:
        logger.warning(f"[STOP] No workspace or task_tracker for chat_id={chat_id}")
        return {"ok": True, "message": "No active task found"}
    
    # Request stop via task tracker
    stopped = await workspace.task_tracker.request_stop(chat_id)
    
    if stopped:
        logger.info(f"[STOP] Successfully stopped chat_id={chat_id}")
        return {"ok": True, "message": "Chat stopped"}
    else:
        logger.debug(f"[STOP] No active task for chat_id={chat_id}")
        return {"ok": True, "message": "No active task found"}
