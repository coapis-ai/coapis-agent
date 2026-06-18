# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Chats router - Chat session management with strict user isolation.

Delegates to ChatManager for persistence, ensuring chat history survives
server restarts and stays in sync with the runner's session state.

IMPORTANT: All endpoints enforce strict user isolation. Non-admin users can
only access their own chat sessions. Admin users can access all chats.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Path, Body, Response
from fastapi.requests import Request
from pydantic import BaseModel, ConfigDict

from ..permissions.decorators import require_permission
from ..runner.utils import agentscope_msg_to_message

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chats"])


# ── Pydantic models matching CoApis frontend types ──────────────────────

class ChatSpec(BaseModel):
    """Chat specification model."""
    model_config = ConfigDict(extra="allow")
    
    id: str
    session_id: str = "default"
    user_id: str = "default"
    channel: str = "default"
    name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    status: str = "idle"
    pinned: bool = False


class Message(BaseModel):
    """Message model."""
    model_config = ConfigDict(extra="allow")
    
    role: str
    content: Any


class ChatHistory(BaseModel):
    """Chat history with messages."""
    messages: List[Message]
    status: str = "idle"


class ChatUpdateRequest(BaseModel):
    """Chat update request."""
    name: Optional[str] = None
    pinned: Optional[bool] = None


class ChatDeleteResponse(BaseModel):
    """Chat delete response."""
    success: bool
    chat_id: str


# ── Helper: get current user info ─────────────────────────────────────────

def _get_current_user(request: Request) -> tuple[str, bool]:
    """Get current username and admin status from request.
    
    Returns:
        (username, is_admin) tuple
    """
    username = getattr(request.state, "username", None)
    if not username:
        user_info = getattr(request.state, "user_info", None)
        if user_info and isinstance(user_info, dict):
            username = user_info.get("username")
    
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Check admin status
    user_role = getattr(request.state, "role", "user")
    is_admin = (user_role in ("admin", "superadmin"))
    
    return (username, is_admin)


# ── Helper: get ChatManager from request ──────────────────────────────────

def _get_chat_manager(request: Request):
    """Get the per-user ChatManager for strict user isolation.

    Returns the ChatManager for the current user's own chats directory
    (workspaces/{username}/chat/chats.json), NOT the global workspace's
    ChatManager. This ensures complete chat isolation between users.
    """
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if not manager:
        raise HTTPException(
            status_code=503,
            detail="Agent manager not initialized",
        )

    username, _ = _get_current_user(request)

    # Use per-user ChatManager (isolated storage at workspaces/{username}/chat/)
    cm = manager.get_user_chat_manager(username)
    if not cm:
        raise HTTPException(
            status_code=503,
            detail="Chat manager not available",
        )

    return cm


# ── Helper: get session for a user (aligned with CoApis pattern) ───────

def _get_session_for_user(user_id: str, request: Request = None):
    """Get SafeJSONSession for a user's workspace.

    Returns the session object that manages sessions/{user_id}*.json files.
    """
    if request is None:
        return None
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        return None
    # Look for workspace with matching user_id
    for key, ws in getattr(manager, '_workspaces', {}).items():
        if hasattr(ws, 'username') and ws.username == user_id:
            runner = getattr(ws, 'runner', None)
            return getattr(runner, 'session', None) if runner else None
    return None


def _get_session_for_chat(chat_spec, request: Request = None):
    """Get SafeJSONSession for a specific chat's agent workspace.

    Unlike _get_session_for_user which finds the user's root workspace,
    this finds the workspace matching the chat's agent_id and user_id.
    This ensures messages are loaded from the correct user-level session
    directory (e.g. workspaces/{username}/sessions/{chat_id}.json).

    Falls back to _get_session_for_user if agent_id lookup fails.
    """
    if request is None:
        return None
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        return None

    agent_id = getattr(chat_spec, "agent_id", None) or ""
    user_id = getattr(chat_spec, "user_id", None) or ""

    # Try to find workspace matching agent_id + user_id (user-level isolation).
    for key, ws in getattr(manager, '_workspaces', {}).items():
        ws_agent_id = getattr(ws, 'agent_id', None) or ""
        ws_username = getattr(ws, 'username', None) or ""
        # Match if agent_id matches AND username matches the chat owner.
        # For chats with empty agent_id, match workspaces with empty/default agent_id.
        agent_match = ws_agent_id == agent_id or (not agent_id and ws_agent_id in ("", "default"))
        user_match = not user_id or ws_username == user_id
        if agent_match and user_match:
            runner = getattr(ws, 'runner', None)
            if runner:
                logger.debug(f"_get_session_for_chat: found workspace for agent_id={agent_id or 'default'}, user_id={user_id}")
                return getattr(runner, 'session', None)

    # Fallback: find user's root workspace (default agent)
    logger.debug(f"_get_session_for_chat: falling back to user workspace for user_id={user_id}")
    return _get_session_for_user(user_id, request)


# ── Helper: normalize ChatSpec for frontend ────────────────────────────────

def _normalize_chat_spec(spec) -> Dict[str, Any]:
    """Convert ChatSpec (from runner/models.py) to frontend-compatible dict.
    
    The runner's ChatSpec uses datetime objects, but frontend expects ISO strings.
    """
    result = {
        "id": spec.id,
        "session_id": spec.session_id,
        "user_id": spec.user_id,
        "channel": spec.channel,
        "name": spec.name,
        "status": spec.status,
        "pinned": spec.pinned,
        "agent_id": getattr(spec, "agent_id", "") or "",
        "meta": spec.meta if hasattr(spec, "meta") else {},
    }
    
    # Convert datetime to ISO string
    if hasattr(spec, "created_at") and spec.created_at is not None:
        if hasattr(spec.created_at, "isoformat"):
            result["created_at"] = spec.created_at.isoformat()
        else:
            result["created_at"] = str(spec.created_at)
    else:
        result["created_at"] = None
    
    if hasattr(spec, "updated_at") and spec.updated_at is not None:
        if hasattr(spec.updated_at, "isoformat"):
            result["updated_at"] = spec.updated_at.isoformat()
        else:
            result["updated_at"] = str(spec.updated_at)
    else:
        result["updated_at"] = None
    
    return result


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("/chats")
@require_permission("chat:history")
async def list_chats(
    request: Request,
    response: Response,
    channel: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None, alias="user_id"),
    agent_id: Optional[str] = Query(None, alias="agent_id"),
) -> List[Dict[str, Any]]:
    """List chat sessions for the current user.

    ENFORCES USER ISOLATION: Non-admin users can only see their own chats.
    Admin users can see all chats across all users by aggregating
    from each user's isolated ChatManager.

    Query Parameters:
        channel: Filter by channel name (e.g., "console", "wecom")
        user_id: Filter by specific user ID (admin only, ignored for non-admin)
        agent_id: Filter by agent ID (for multi-agent isolation)
    """
    username, is_admin = _get_current_user(request)

    def _agent_filter(chats):
        """Filter chats by agent_id.

        Only returns chats whose agent_id matches the requested agent.
        Uses case-insensitive comparison to handle inconsistencies between
        frontend (e.g. "Default") and backend (e.g. "default").
        """
        if not agent_id:
            return chats
        agent_id_lower = agent_id.lower()
        # Chats with empty agent_id are treated as belonging to "default"
        return [c for c in chats if (getattr(c, "agent_id", "") or "default").lower() == agent_id_lower]

    # All users (including admin) only see their own chats for session list.
    # The admin aggregation via ?user_id=xxx is available for admin panel use
    # but the default list is always user-scoped for isolation.
    cm = _get_chat_manager(request)
    chats = await cm.list_chats(user_id=username, channel=channel)
    chats = _agent_filter(chats)
    # Ensure browsers never cache chat list responses
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return [_normalize_chat_spec(c) for c in chats]


@router.post("/chats")
@require_permission("chat:send")
async def create_chat(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Create a new chat session.
    
    ENFORCES USER ISOLATION: The user_id is set to the authenticated user's
    username, ignoring any user_id in the payload.
    """
    username, is_admin = _get_current_user(request)
    cm = _get_chat_manager(request)
    
    from ..runner.models import ChatSpec as RunnerChatSpec
    
    chat_id = payload.get("id")
    if not chat_id:
        import uuid
        chat_id = str(uuid.uuid4())
    
    # Force user_id to current user (prevent impersonation)
    # Admin can specify user_id for creating chats on behalf of others
    if is_admin:
        forced_user_id = payload.get("user_id", username)
    else:
        forced_user_id = username
    
    spec = RunnerChatSpec(
        id=chat_id,
        session_id=payload.get("session_id", f"console:{username}"),
        user_id=forced_user_id,
        channel=payload.get("channel", "console"),
        name=payload.get("name", "New Chat"),
        agent_id=payload.get("agent_id", ""),
    )
    
    result = await cm.create_chat(spec)
    return _normalize_chat_spec(result)


@router.get("/chats/{chat_id}")
@require_permission("chat:history")
async def get_chat(
    request: Request,
    response: Response,
    chat_id: str = Path(...),
    limit: int = Query(default=50, ge=1, le=1000),
    before: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Get chat history with pagination.

    Returns only the most recent `limit` messages by default (hot data).
    Older messages are archived to SQLite — use /chats/{chat_id}/archived to retrieve.

    Query Parameters:
        limit: Max messages to return (default 50, max 1000)
        before: Return messages before this message ID (for "load more")
    """
    username, is_admin = _get_current_user(request)
    cm = _get_chat_manager(request)

    # Get chat spec
    logger.info(f"get_chat: requested chat_id={chat_id}, repo_path={cm._repo.path}")
    spec = await cm.get_chat(chat_id)
    logger.info(f"get_chat: found spec={spec.id if spec else None}, requested={chat_id}, match={spec.id == chat_id if spec else False}")
    if not spec:
        logger.warning(f"get_chat: chat_id={chat_id} not found in {cm._repo.path}")
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # CRITICAL: Verify UUID matches (catch routing bugs)
    if spec.id != chat_id:
        logger.error(f"get_chat: UUID MISMATCH! requested={chat_id}, returned={spec.id} from {cm._repo.path}")
        # Try to find the correct chat by scanning all chats
        all_chats = await cm.list_chats()
        for c in all_chats:
            if c.id == chat_id:
                logger.info(f"get_chat: found correct chat in list_chats, using it")
                spec = c
                break
        else:
            logger.error(f"get_chat: requested chat_id={chat_id} not found in list_chats either")
            raise HTTPException(status_code=404, detail=f"Chat not found: {chat_id}")

    # ENFORCE USER ISOLATION: Non-admin can only access their own chats
    if not is_admin and spec.user_id != username:
        raise HTTPException(status_code=403, detail="Access denied: this chat belongs to another user")

    # Load messages from session state (aligned with CoApis pattern)
    # Use chat.id (UUID) as session key for per-chat isolation.
    # Messages are stored at workspaces/{username}/sessions/{chat_id}.json
    messages = []
    try:
        session_obj = _get_session_for_chat(spec, request)
        if session_obj:
            state = await session_obj.get_session_state_dict(
                spec.id, spec.user_id, allow_not_exist=True,
            )
            memory_state = (state or {}).get("agent", {}).get("memory", {})
            if memory_state:
                from agentscope.memory import InMemoryMemory
                from agentscope.message import Msg as ASMsg, TextBlock
                mem = InMemoryMemory()
                mem.load_state_dict(memory_state, strict=False)
                memories = await mem.get_memory(prepend_summary=False)
                messages = agentscope_msg_to_message(memories)
    except Exception as e:
        logger.warning(f"Failed to load messages from session: {e}", exc_info=True)

    total_count = len(messages)

    # Apply pagination: take last N messages
    if before:
        # Find the message with matching id and return messages before it
        before_idx = next(
            (i for i, m in enumerate(messages) if m.get("id") == before),
            None,
        )
        if before_idx is not None:
            messages = messages[max(0, before_idx - limit):before_idx]
        else:
            messages = messages[-limit:]
    else:
        messages = messages[-limit:]

    # Ensure browsers never cache chat history responses
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"

    return {
        "spec": _normalize_chat_spec(spec),
        "messages": messages,
        "status": spec.status,
        "total_count": total_count,
        "has_more": total_count > limit or (before is not None),
    }


@router.get("/chats/{chat_id}/archived")
@require_permission("chat:history")
async def get_archived_messages(
    request: Request,
    chat_id: str = Path(...),
    before: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> Dict[str, Any]:
    """Get archived (cold) messages for a chat from SQLite.

    Returns older messages that have been rotated out of the hot JSON store.
    """
    username, is_admin = _get_current_user(request)
    cm = _get_chat_manager(request)

    # Verify chat exists and user has access
    spec = await cm.get_chat(chat_id)
    if not spec:
        raise HTTPException(status_code=404, detail="Chat not found")
    if not is_admin and spec.user_id != username:
        raise HTTPException(status_code=403, detail="Access denied")

    # Query archived messages from cleanup engine
    from ..cleanup import get_cleanup_engine
    from ...constant import WORKSPACES_DIR

    ws_dir = WORKSPACES_DIR / username
    engine = get_cleanup_engine(ws_dir)
    try:
        messages = engine.get_archived_messages(
            chat_id=chat_id,
            before=before,
            limit=limit,
        )
    finally:
        engine.close()

    return {
        "messages": messages,
        "count": len(messages),
        "has_more": len(messages) >= limit,
    }


@router.put("/chats/{chat_id}")
@require_permission("chat:write")
async def update_chat(
    request: Request,
    chat_id: str = Path(...),
    payload: ChatUpdateRequest = Body(...),
) -> Dict[str, Any]:
    """Update chat metadata (name, pinned).
    
    ENFORCES USER ISOLATION: Non-admin users can only update their own chats.
    """
    username, is_admin = _get_current_user(request)
    cm = _get_chat_manager(request)
    
    # Verify ownership first
    spec = await cm.get_chat(chat_id)
    if not spec:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # ENFORCE USER ISOLATION: Non-admin can only update their own chats
    if not is_admin and spec.user_id != username:
        raise HTTPException(status_code=403, detail="Access denied: this chat belongs to another user")
    
    from ..runner.models import ChatUpdate
    
    patch = ChatUpdate(
        name=payload.name,
        pinned=payload.pinned,
    )
    
    result = await cm.patch_chat(chat_id, patch)
    if not result:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    return _normalize_chat_spec(result)


@router.delete("/chats/{chat_id}")
@require_permission("chat:manage")
async def delete_chat(
    request: Request,
    chat_id: str = Path(...),
) -> ChatDeleteResponse:
    """Delete a chat session.
    
    ENFORCES USER ISOLATION: Non-admin users can only delete their own chats.
    """
    username, is_admin = _get_current_user(request)
    cm = _get_chat_manager(request)
    
    # Verify ownership first
    spec = await cm.get_chat(chat_id)
    if not spec:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # ENFORCE USER ISOLATION: Non-admin can only delete their own chats
    if not is_admin and spec.user_id != username:
        raise HTTPException(status_code=403, detail="Access denied: this chat belongs to another user")
    
    deleted = await cm.delete_chats([chat_id])
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    return ChatDeleteResponse(success=True, chat_id=chat_id)


@router.post("/chats/batch-delete")
@require_permission("chat:manage")
async def batch_delete_chats(
    request: Request,
    chat_ids: List[str] = Body(...),
) -> Dict[str, Any]:
    """Delete multiple chat sessions.
    
    ENFORCES USER ISOLATION: Non-admin users can only delete their own chats.
    """
    username, is_admin = _get_current_user(request)
    cm = _get_chat_manager(request)
    
    # ENFORCE USER ISOLATION: Filter to only user's own chats (unless admin)
    if not is_admin:
        # Verify each chat belongs to current user
        allowed_ids = []
        for chat_id in chat_ids:
            spec = await cm.get_chat(chat_id)
            if spec and spec.user_id == username:
                allowed_ids.append(chat_id)
        chat_ids = allowed_ids
    
    deleted = await cm.delete_chats(chat_ids)
    if not deleted:
        raise HTTPException(status_code=404, detail="No chats found to delete")
    
    return {"success": True, "deleted_count": len(chat_ids)}
