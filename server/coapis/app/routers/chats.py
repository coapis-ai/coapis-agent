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

def _find_workspace_for_agent(request: Request, agent_id: str, username: str):
    """Find the workspace matching agent_id and username."""
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if not manager:
        return None
    
    # Try composite key first
    for key_format in [f"{username}:{agent_id}", f"global:{agent_id}"]:
        ws = getattr(manager, '_workspaces', {}).get(key_format)
        if ws:
            return ws
    
    # Fallback: search all workspaces
    for key, ws in getattr(manager, '_workspaces', {}).items():
        ws_agent_id = getattr(ws, 'agent_id', None) or ""
        ws_username = getattr(ws, 'username', None) or ""
        if ws_agent_id == agent_id and ws_username == username:
            return ws
    
    return None


async def _get_chat_manager(request: Request, agent_id: str = None):
    """Get the ChatManager for the appropriate agent workspace.

    Uses get_agent() to trigger lazy-start for unstarted workspaces.
    When agent_id is None, falls back to user's default.
    """
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if not manager:
        raise HTTPException(
            status_code=503,
            detail="Agent manager not initialized",
        )

    username, _ = _get_current_user(request)

    # Strict mode: use get_agent() which triggers lazy-start
    if agent_id:
        try:
            ws = await manager.get_agent(agent_id, username=username)
        except Exception as exc:
            logger.warning("_get_chat_manager: get_agent(%s) failed: %s", agent_id, exc)
            ws = None
        if ws and hasattr(ws, 'chat_manager') and ws.chat_manager:
            return ws.chat_manager
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found for user '{username}'",
        )

    # No agent_id — find user's default workspace (prefer user:xxx agent)
    # Try to find and lazy-start a workspace for this user
    fallback_agent = None
    for key, ws in getattr(manager, '_workspaces', {}).items():
        ws_username = getattr(ws, 'username', None) or ""
        if ws_username != username:
            continue
        ws_agent_id = getattr(ws, 'agent_id', None) or ""
        if ws_agent_id.startswith("user:"):
            fallback_agent = ws_agent_id
            break
        if fallback_agent is None:
            fallback_agent = ws_agent_id

    if fallback_agent:
        try:
            ws = await manager.get_agent(fallback_agent, username=username)
            if ws and hasattr(ws, 'chat_manager') and ws.chat_manager:
                return ws.chat_manager
        except Exception as exc:
            logger.warning("_get_chat_manager: fallback get_agent(%s) failed: %s", fallback_agent, exc)

    raise HTTPException(
        status_code=503,
        detail="Chat manager not available",
    )


async def _find_chat_across_managers(request: Request, chat_id: str, username: str):
    """Search for a chat across ALL of the user's ChatManagers.

    Searches in order:
    1. User-level ChatManager (workspaces/{user}/chat/)
    2. All agent-level ChatManagers (workspaces/{user}/agents/{id}/chat/)

    Returns:
        (ChatSpec, ChatManager) tuple, or (None, None) if not found.
    """
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if not manager:
        return None, None

    # 1. User-level ChatManager
    user_cm = manager.get_user_chat_manager(username)
    if user_cm:
        spec = await user_cm.get_chat(chat_id)
        if spec:
            return spec, user_cm

    # 2. All agent-level ChatManagers for this user
    for key, ws in getattr(manager, '_workspaces', {}).items():
        ws_username = getattr(ws, 'username', None) or ""
        if ws_username != username:
            continue
        ws_cm = getattr(ws, 'chat_manager', None)
        if not ws_cm or ws_cm is user_cm:
            continue
        spec = await ws_cm.get_chat(chat_id)
        if spec:
            return spec, ws_cm

    return None, None


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

    Finds the workspace matching the chat's agent_id.
    Uses the authenticated username (not chat.user_id) for workspace lookup,
    because external channels (wecom, dingtalk) store sender_id as user_id
    in ChatSpec, which differs from the workspace owner username.
    """
    if request is None:
        return None
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        return None

    agent_id = getattr(chat_spec, "agent_id", None) or ""
    # Use authenticated username for workspace lookup, not chat.user_id
    # (chat.user_id may be an external sender ID like wecom open ID)
    username, _ = _get_current_user(request)

    # Try to find workspace matching agent_id + authenticated username
    for key, ws in getattr(manager, '_workspaces', {}).items():
        ws_agent_id = getattr(ws, 'agent_id', None) or ""
        ws_username = getattr(ws, 'username', None) or ""
        agent_match = ws_agent_id == agent_id or (not agent_id and ws_agent_id in ("", "default"))
        if agent_match and ws_username == username:
            runner = getattr(ws, 'runner', None)
            if runner:
                logger.debug(f"_get_session_for_chat: found workspace for agent_id={agent_id or 'default'}, username={username}")
                return getattr(runner, 'session', None)

    # Fallback: find user's root workspace (default agent)
    logger.debug(f"_get_session_for_chat: falling back to user workspace for username={username}")
    return _get_session_for_user(username, request)


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
    """List chat sessions for a specific agent, strictly isolated.

    Query Parameters:
        channel: Filter by channel name (e.g., "console", "wecom")
        user_id: Filter by specific user ID (admin only, ignored for non-admin)
        agent_id: Filter by agent ID (required for multi-agent isolation).
                  Falls back to X-Agent-Id header if not in query param.
    """
    username, is_admin = _get_current_user(request)

    # channel="console" means "default view" — return all channels
    effective_channel = "" if (channel == "console" or not channel) else channel

    # Resolve agent_id: query param > header
    resolved_agent_id = agent_id or request.headers.get("X-Agent-Id", "")

    if not resolved_agent_id:
        raise HTTPException(
            status_code=400,
            detail="agent_id is required (query param or X-Agent-Id header)",
        )

    try:
        cm = await _get_chat_manager(request, agent_id=resolved_agent_id)
    except HTTPException:
        logger.warning(
            "list_chats: agent_id=%s not found for user=%s",
            resolved_agent_id, username,
        )
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{resolved_agent_id}' not found or access denied",
        )

    chats = await cm.list_chats(channel=effective_channel)

    # Check TaskTracker for generating status of each chat
    generating_chat_ids: set = set()
    try:
        ws = _find_workspace_for_agent(request, resolved_agent_id, username)
        tracker = getattr(ws, "task_tracker", None) if ws else None
        if tracker:
            active_tasks = await tracker.list_active_tasks()
            generating_chat_ids = set(active_tasks)
    except Exception:
        pass  # Non-critical: generating status is best-effort

    # Ensure browsers never cache chat list responses
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    result = []
    for c in chats:
        entry = _normalize_chat_spec(c)
        entry["generating"] = entry["id"] in generating_chat_ids
        result.append(entry)
    return result


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
    cm = await _get_chat_manager(request, agent_id=request.headers.get("X-Agent-Id", ""))
    
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
        session_id=payload.get("session_id", chat_id),
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
    resolved_agent_id = request.headers.get("X-Agent-Id", "") or ""

    # Try to get the agent's ChatManager; fall back to cross-manager search
    cm = None
    try:
        cm = await _get_chat_manager(request, agent_id=resolved_agent_id or None)
    except HTTPException:
        pass

    # Get chat spec
    spec = None
    if cm:
        logger.info(f"get_chat: requested chat_id={chat_id}, repo_path={cm._repo.path}")
        spec = await cm.get_chat(chat_id)
    if not spec:
        # Fallback: search across all user's ChatManagers
        spec, cm = await _find_chat_across_managers(request, chat_id, username)
    logger.info(f"get_chat: found spec={spec.id if spec else None}, requested={chat_id}, match={spec.id == chat_id if spec else False}")
    if not spec:
        logger.warning(f"get_chat: chat_id={chat_id} not found in any ChatManager")
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
        # Use workspace owner username for session lookup, not spec.user_id
        # (spec.user_id may be an external sender ID like wecom open ID)
        session_user_id = username  # from _get_current_user() above
        session_obj = _get_session_for_chat(spec, request)
        state = None
        if session_obj:
            state = await session_obj.get_session_state_dict(
                spec.id, session_user_id, allow_not_exist=True,
            )
        # Fallback: when session_obj is None (workspace not registered in
        # multi_agent_manager), load session file directly from disk.
        if not state:
            import json as _json
            from ...constant import WORKSPACES_DIR as _WS_DIR
            _session_file = _WS_DIR / session_user_id / "sessions" / f"{session_user_id}_{spec.id}.json"
            if _session_file.exists():
                state = _json.loads(_session_file.read_text(encoding="utf-8"))
                logger.info(f"get_chat: loaded session from disk fallback: {_session_file}")
            # Legacy fallback: messages may still be in the old session_id format
            # (e.g. "admin_console--admin.json") because _persist_chat_messages
            # only migrates when a NEW message is sent.  If the new-format file
            # is empty or missing, try the legacy key so refresh always works.
            if not state and spec.session_id:
                _legacy_key = f"{session_user_id}--{spec.session_id}".replace(":", "--")
                _legacy_file = _WS_DIR / session_user_id / "sessions" / f"{_legacy_key}.json"
                if _legacy_file.exists():
                    state = _json.loads(_legacy_file.read_text(encoding="utf-8"))
                    logger.info(f"get_chat: loaded legacy session fallback: {_legacy_file}")
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
    cm = await _get_chat_manager(request, agent_id=request.headers.get("X-Agent-Id", ""))

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
    cm = await _get_chat_manager(request, agent_id=request.headers.get("X-Agent-Id", ""))
    
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
@require_permission("chat:delete")
async def delete_chat(
    request: Request,
    chat_id: str = Path(...),
) -> ChatDeleteResponse:
    """Delete a chat session.
    
    ENFORCES USER ISOLATION: Non-admin users can only delete their own chats.
    Searches across all of the user's ChatManagers (user-level + agent-level).
    """
    username, is_admin = _get_current_user(request)
    cm = await _get_chat_manager(request, agent_id=request.headers.get("X-Agent-Id", ""))
    
    # Try primary ChatManager first
    spec = await cm.get_chat(chat_id)
    if not spec:
        # Fallback: search across all user's ChatManagers
        spec, cm = await _find_chat_across_managers(request, chat_id, username)
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
@require_permission("chat:delete")
async def batch_delete_chats(
    request: Request,
    chat_ids: List[str] = Body(...),
) -> Dict[str, Any]:
    """Delete multiple chat sessions.
    
    ENFORCES USER ISOLATION: Non-admin users can only delete their own chats.
    Searches across all of the user's ChatManagers (user-level + agent-level).
    """
    username, is_admin = _get_current_user(request)
    cm = await _get_chat_manager(request, agent_id=request.headers.get("X-Agent-Id", ""))

    # For each chat_id, find the ChatManager that owns it
    # Group by ChatManager for efficient batch deletion
    cm_to_ids: Dict[Any, List[str]] = {}  # ChatManager -> [chat_ids]

    for chat_id in chat_ids:
        # Try primary ChatManager first
        spec = await cm.get_chat(chat_id)
        target_cm = cm
        if not spec:
            # Fallback: search across all user's ChatManagers
            spec, target_cm = await _find_chat_across_managers(request, chat_id, username)
        if not spec:
            continue
        # ENFORCE USER ISOLATION
        if not is_admin and spec.user_id != username:
            continue
        cm_to_ids.setdefault(target_cm, []).append(chat_id)

    total_deleted = 0
    for target_cm, ids in cm_to_ids.items():
        deleted = await target_cm.delete_chats(ids)
        if deleted:
            total_deleted += len(ids)

    if total_deleted == 0:
        raise HTTPException(status_code=404, detail="No chats found to delete")

    return {"success": True, "deleted_count": total_deleted}
