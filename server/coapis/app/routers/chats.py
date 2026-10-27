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
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Path, Body, Response
from fastapi.requests import Request
from pydantic import BaseModel, ConfigDict

from ..permissions.decorators import require_permission
from ..runner.utils import agentscope_msg_to_message
from ..runner.models import ChatUpdate

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
    # Scene-related fields
    scene_id: Optional[str] = None
    composed_agent_id: Optional[str] = None


class Message(BaseModel):
    """Message model."""
    model_config = ConfigDict(extra="allow")
    
    role: str
    content: Any


class ChatHistory(BaseModel):
    """Chat history with messages."""
    messages: List[Message]
    status: str = "idle"
    session_missing: bool = False


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


# ── Helper: openability of a chat (index/session drift guard) ──────────────

# A chat index entry is written when the chat is created; the session
# snapshot is written when the turn finishes.  So a freshly created chat is
# legitimately file-less for a few minutes.  Anything older than this grace
# window without a snapshot is an orphan: clicking it can only ever return
# an empty shell, so it must not be listed.
_CHAT_FILE_GRACE = timedelta(minutes=30)


def _session_file_exists(
    session_obj,
    session_id: str,
    user_id: str,
) -> Optional[bool]:
    """True/False = 判定结果；None = 无从判定。

    Uses the exact path the session writer uses
    (``SafeJSONSession._get_save_path``), so the guard can never disagree
    with the writer about where a session lives.

    ``None`` is the load-bearing case: when the session store is
    unavailable (no session object, no id, path resolution blows up) we
    have no evidence the snapshot is gone.  Treating that as "gone" would
    blank the whole sidebar the moment the session path is misconfigured —
    a far worse failure than listing a chat that opens empty.  Callers
    must drop an entry only on an explicit ``False``.
    """
    if session_obj is None or not session_id:
        return None
    try:
        path = session_obj._get_save_path(session_id, user_id=user_id)
    except Exception:  # pragma: no cover - defensive
        return None
    return os.path.exists(path)


def _entry_age_too_old(entry: Dict[str, Any]) -> bool:
    """True when an entry's last activity is past the file grace window."""
    stamp = entry.get("updated_at") or entry.get("created_at")
    if not stamp:
        return True
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - when > _CHAT_FILE_GRACE


def _agent_scope_match(entry_agent: str, agent_id: str) -> bool:
    """Exact agent scoping for the sidebar list.

    ``GET /chats?agent_id=X`` used to return *every* chat in the user's
    workspace, so a user's list mixed in chats owned by scene agents, the
    legacy ``default`` agent and empty agent ids.  Those chats open against
    a different agent than the one the UI is talking to, which is how the
    "session does not exist" shells show up.  Only the requested agent's own
    chats (or, for a legacy chat with no agent id, the default agent) are
    listed.
    """
    if not agent_id:
        return True
    if entry_agent == agent_id:
        return True
    if not entry_agent and agent_id in ("", "default"):
        return True
    return False


# ── Helper: normalize ChatSpec for frontend ────────────────────────────────

def _short_title(name: Optional[str]) -> str:
    """One-line, length-capped title for the sidebar.

    ``ChatSpec.name`` is the whole first prompt, which for real usage is a
    multi-paragraph instruction; the sidebar row is 20px tall so the row
    reads as noise.  The title keeps the first non-empty line and caps it,
    with an ellipsis when it was cut.
    """
    text = (name or "").strip()
    if not text:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line:
            text = line
            break
    if len(text) <= 40:
        return text
    return text[:40].rstrip() + "…"


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
        "title": _short_title(spec.name),
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


def _release_chat_refs(chat_id: str, session_id: str = "") -> None:
    """R2 hook: release every resource ref owned by a deleted chat.

    Fire-and-forget by design — a ledger failure must never break the delete
    path (same rule as the file ledger hooks). Resources left with zero refs
    move to ``orphan`` inside the ledger, not here.

    Both identifiers are released: refs are keyed by the chat **UUID** when the
    frontend created the chat, and by the **session_id** when the chat came
    from a channel session (console/wecom) with no UUID at write time.
    Releasing only the UUID would leave channel-session refs dangling.
    """
    try:
        from ...foundation.resource_ledger import get_resource_ledger

        rl = get_resource_ledger()
        n = 0
        for kind_id in (chat_id, session_id):
            if kind_id:
                n += rl.detach_refs_by_referrer("chat", kind_id)
        if n:
            logger.info("chat %s deleted: released %d resource refs", chat_id[:16], n)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("resource ref release skipped for chat %s: %s", chat_id[:16], exc)


# ── Endpoints ────────────────────────────────────────────────────────────

async def _build_chat_entries(
    request: Request,
    agent_id: str,
    channel: str,
) -> List[Dict[str, Any]]:
    """Build the frontend chat list for one agent+channel scope.

    Shared by ``GET /chats`` (full list) and ``GET /chats/page`` (B5 paged)
    so the two can never drift in shape, in the ``generating`` flag, or in the
    stale-status self-healing.

    Returns normalized dicts — the exact shape the frontend consumes.
    """
    cm = await _get_chat_manager(request, agent_id=agent_id)
    chats = await cm.list_chats(channel=channel)

    # Get generating chat IDs from stream tracking
    generating_chat_ids = set()
    try:
        mgr = getattr(request.app.state, "multi_agent_manager", None)
        if mgr:
            for ws in mgr.get_workspaces():
                generating_chat_ids.update(ws.get_generating_chat_ids())
    except Exception:
        pass

    username, _ = _get_current_user(request)
    result: List[Dict[str, Any]] = []
    dropped = 0
    for c in chats:
        if not _agent_scope_match(getattr(c, "agent_id", "") or "", agent_id):
            dropped += 1
            continue
        entry = _normalize_chat_spec(c)
        is_generating = c.id in generating_chat_ids
        entry["generating"] = is_generating

        # Openability: an index entry whose session snapshot is gone can
        # only ever open as an empty shell.  Keep it out of the list once
        # the grace window has passed (a chat created seconds ago has no
        # snapshot yet and must stay visible).  An unknown verdict (None)
        # keeps the entry — see _session_file_exists.
        session_obj = _get_session_for_chat(c, request)
        session_exists = _session_file_exists(
            session_obj,
            c.session_id or c.id,
            getattr(session_obj, "user_id", "") or username,
        )
        entry["session_exists"] = session_exists is not False
        if (
            session_exists is False
            and not is_generating
            and _entry_age_too_old(entry)
        ):
            dropped += 1
            continue

        # Self-healing: clear stale "running" status when not generating
        if not is_generating and c.status == "running":
            entry["status"] = "idle"
            try:
                await cm.update_chat(c.id, ChatUpdate(status="idle"))
            except Exception as exc:
                logger.debug(
                    "Self-healing failed for chat %s: %s",
                    c.id[:8],
                    exc,
                )

        result.append(entry)
    if dropped:
        logger.info(
            "Chat list for agent=%s: %d openable entries, %d dropped "
            "(agent scope / missing session snapshot).",
            agent_id or "-",
            len(result),
            dropped,
        )
    return result


def _chat_entry_time(entry: Dict[str, Any]) -> str:
    """Sort key: ISO string of last activity (missing timestamps sort last)."""
    return entry.get("updated_at") or entry.get("created_at") or ""


def _sort_chat_entries(
    entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Pinned first, then most-recently-active first.

    The sidebar paginates server-side (B5), so the order has to be decided
    *before* the slice — sorting only what the browser already holds would
    let a pinned chat sit on page 5 forever.
    """
    pinned = [e for e in entries if e.get("pinned")]
    rest = [e for e in entries if not e.get("pinned")]
    pinned.sort(key=_chat_entry_time, reverse=True)
    rest.sort(key=_chat_entry_time, reverse=True)
    return pinned + rest


@router.get("/chats")
@require_permission("chat:history")
async def list_chats(
    request: Request,
    response: Response,
    channel: Optional[str] = Query(None, description="Filter by channel"),
    agent_id: Optional[str] = Query(
        None,
        description="Filter by agent ID for multi-agent isolation",
    ),
) -> List[Dict[str, Any]]:
    """List chats for the current user, scoped to a specific agent.

    Query Parameters:
        channel: "console"/omitted → all channels (default view); any other
            value filters by that channel.
        agent_id: required (query param, else the X-Agent-Id header).

    Full list. The sidebar switched to ``GET /chats/page`` (B5); this endpoint
    stays for the admin pages and every caller that needs everything at once.
    """
    username, is_admin = _get_current_user(request)

    # channel="console" means "default view" → return all channels.
    # (HEAD semantics — the sidebar depends on it; do not force a single
    # channel, that is what hides every wecom/discord session.)
    effective_channel = "" if (channel == "console" or not channel) else channel

    # Resolve agent_id: query param > X-Agent-Id header.
    # (HEAD semantics. There is no ``resolve_user_default_agent`` in this
    # tree — inventing it here crashed both /chats and /chats/page.)
    resolved_agent_id = agent_id or request.headers.get("X-Agent-Id", "")
    if not resolved_agent_id:
        raise HTTPException(
            status_code=400,
            detail="agent_id is required (query param or X-Agent-Id header)",
        )

    try:
        result = await _build_chat_entries(
            request,
            agent_id=resolved_agent_id,
            channel=effective_channel,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to list chats for agent=%s user=%s",
            resolved_agent_id,
            username,
        )
        raise HTTPException(
            status_code=404,
            detail=f"Chat manager not found for agent '{resolved_agent_id}'",
        ) from exc

    # Prevent browser from caching the chat list
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"

    return result


@router.get("/chats/page")
@require_permission("chat:history")
async def list_chats_page(
    request: Request,
    response: Response,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    channel: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Paged chat list for the sidebar (B5) — first paint loads 20, not 100.

    ``total`` is the size of the whole filtered list, so the caller knows when
    to stop asking for pages. Order is pinned-first then updated_at desc,
    applied before slicing.

    Registered **before** ``GET /chats/{chat_id}``: FastAPI matches routes in
    registration order, so this literal path placed after the parameterised
    route would be swallowed by it (``page`` → chat_id → 404).
    """
    username, is_admin = _get_current_user(request)

    # Same channel/agent semantics as ``GET /chats`` (see notes there):
    # channel="console"/omitted → all channels; agent from param or header.
    effective_channel = "" if (channel == "console" or not channel) else channel
    resolved_agent_id = agent_id or request.headers.get("X-Agent-Id", "")
    if not resolved_agent_id:
        raise HTTPException(
            status_code=400,
            detail="agent_id is required (query param or X-Agent-Id header)",
        )

    try:
        entries = await _build_chat_entries(
            request,
            agent_id=resolved_agent_id,
            channel=effective_channel,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to list chats (page) for agent=%s user=%s",
            resolved_agent_id,
            username,
        )
        raise HTTPException(
            status_code=404,
            detail=f"Chat manager not found for agent '{resolved_agent_id}'",
        ) from exc

    ordered = _sort_chat_entries(entries)
    total = len(ordered)
    items = ordered[offset : offset + limit]

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(items) < total,
    }


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
    session_found = False
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
            session_found = bool(state)
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

    # ── Self-healing: verify status against TaskTracker ──────────────────
    # If ChatSpec.status says "running" but TaskTracker has no active task,
    # the task was lost (backend restart / crash / OOM). Fix the persisted
    # status so the frontend doesn't get stuck on a phantom "generating"
    # spinner (same logic as list_chats, applied to single-chat reads).
    effective_status = spec.status
    if effective_status == "running" and resolved_agent_id:
        try:
            ws = _find_workspace_for_agent(request, resolved_agent_id, username)
            tracker = getattr(ws, "task_tracker", None) if ws else None
            if tracker:
                tracker_status = await tracker.get_status(chat_id)
                if tracker_status == "idle":
                    effective_status = "idle"
                    from ..runner.models import ChatUpdate
                    await cm.patch_chat(chat_id, ChatUpdate(status="idle"))
                    logger.info(
                        "get_chat: self-healed stale 'running' status for chat %s",
                        chat_id[:16],
                    )
        except Exception as e:
            logger.debug(
                "get_chat: TaskTracker status check skipped for chat %s: %s",
                chat_id[:16], e,
            )

    # Explicit empty state: the UI used to render a chat with no messages as
    # a blank page, which reads as "the product is broken".  Tell the caller
    # the snapshot is gone so it can say so.
    session_missing = not session_found
    if session_missing and not messages:
        logger.info(
            "get_chat: chat %s has an index entry but no session snapshot "
            "under any known name (session_id=%s).",
            chat_id[:8], spec.session_id,
        )

    return {
        "spec": _normalize_chat_spec(spec),
        "messages": messages,
        "status": effective_status,
        "session_missing": session_missing,
        "total_count": total_count,
        "has_more": total_count > limit or (before is not None),
    }


@router.get("/chats/{chat_id}/resources")
@require_permission("chat:history")
async def list_chat_resources(
    request: Request,
    chat_id: str,
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """会话资源清单（B2）：本会话引用/产出的文件与网页。

    权威源是资源台账（``resource_refs`` 按 chat 过滤），所以刷新页面、
    会话压缩、台账清扫之后清单都能还原——这正是「资源条」刷新后不丢的
    依据。实时那一轮走 completed 事件上的 ``resources``，历史轮走这里。

    返回：``{items, total, offset, limit}``；``items`` 里
      - ``kind``  file | web | kb | mcp | db
      - ``path``  file → 工作区相对路径；web → URL
      - ``title`` 显示标题（文件名 / 网页标题）
      - ``role``  producer（本会话产出）| reference（本会话引用）
      - ``ref_count`` / ``updated_at`` / ``size``（file 侧现 stat）
    """
    username, is_admin = _get_current_user(request)

    # 归属校验：非管理员只能读自己会话的资源。
    cm = await _get_chat_manager(request, agent_id=request.headers.get("X-Agent-Id", ""))
    spec = await cm.get_chat(chat_id) if cm is not None else None
    owner = str(getattr(spec, "user_id", "") or "") if spec is not None else ""
    if spec is not None and not is_admin and owner and owner != username:
        raise HTTPException(status_code=404, detail="Chat not found")

    try:
        from ...foundation.resource_ledger import get_resource_ledger

        rl = get_resource_ledger()
        rows = rl.list_resources_for_chat(
            owner_scope="user",
            owner_id=owner or username,
            chat_id=chat_id,
            limit=limit,
            offset=offset,
            include_deleted=True,
        )
        total = rl.count_resources_for_chat(
            owner_scope="user",
            owner_id=owner or username,
            chat_id=chat_id,
            include_deleted=True,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("chat %s resources skipped: %s", chat_id[:16], exc)
        rows, total = [], 0

    # 角色按 ref 归属：本会话是 producer 就是产出，否则是引用。
    items: List[Dict[str, Any]] = []
    for row in rows:
        kind = str(row.get("kind") or "")
        path = str(row.get("path") or "")
        role = str(row.get("role") or "reference")
        item = {
            "resource_key": row.get("resource_key"),
            "kind": kind,
            "path": path,
            "title": row.get("title") or (path.rsplit("/", 1)[-1] if kind == "file" else path),
            "role": role,
            "ref_count": row.get("ref_count", 0),
            "status": row.get("status"),
            "version": int(row.get("version") or 1),
            "deleted": bool(row.get("deleted_at")),
            "updated_at": row.get("last_seen_at") or row.get("updated_at"),
            "size": None,
            "exists": True,
        }
        if kind == "file":
            try:
                from ...constant import WORKSPACES_DIR
                from ...foundation.resource_ledger import workspace_relative_path
                from pathlib import Path

                # 台账存工作区相对路径；存量裸路径（files 根相对的历史行）在这里
                # 兜底补 ``files/`` 前缀——前端按首段分桶，裸路径会被当成 media。
                owner_dir = Path(WORKSPACES_DIR) / (owner or username)
                item["path"] = workspace_relative_path(path, owner_dir)
                # 存在性/大小与台账同一口径解析，避免真实文件显示成「已删除」。
                abs_p = rl.resolve_file_path(owner or username, path)
                st = abs_p.stat() if abs_p is not None else None
                if st is not None:
                    item["size"] = int(st.st_size)
                    item["updated_at"] = st.st_mtime
                item["exists"] = st is not None
            except Exception:  # pragma: no cover - defensive
                pass
        items.append(item)

    return {"items": items, "total": total, "offset": offset, "limit": limit}


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

    # R2: 会话删除 → 解除该会话的全部资源引用；refs 清空的资源流转为 orphan。
    _release_chat_refs(chat_id, getattr(spec, "session_id", "") or "")

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
    cm_to_ids: Dict[Any, List[tuple]] = {}  # ChatManager -> [(chat_id, session_id)]

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
        cm_to_ids.setdefault(target_cm, []).append(
            (chat_id, getattr(spec, "session_id", "") or "")
        )

    total_deleted = 0
    for target_cm, pairs in cm_to_ids.items():
        deleted = await target_cm.delete_chats([cid for cid, _ in pairs])
        if deleted:
            total_deleted += len(pairs)
            # R2: 会话删除 → 解除该会话的全部资源引用（refs 清空 → orphan）
            for cid, sid in pairs:
                _release_chat_refs(cid, sid)

    if total_deleted == 0:
        raise HTTPException(status_code=404, detail="No chats found to delete")

    return {"success": True, "deleted_count": total_deleted}


@router.post("/chats/admin/gc-orphans")
async def gc_orphan_chats(
    request: Request,
    agent_id: Optional[str] = Query(None),
    dry_run: bool = Query(True),
):
    """批次 A1「索引 GC」：把「索引里有、会话文件不在」的条目归档。

    实测（dev 数据根 /apps/ai/coapis-dev，2026-10-27）：25 个 chats.json
    共 447 条索引，393 条（88%）的会话文件不存在；admin 一个索引 283 条
    里 257 条是空壳。列表把它们全列出来，用户点开是空白页。

    归档不是删除：条目原样写进
    ``<workspace>/.trash/chat_archive/<时间戳>.json``，一份文件即可整份
    还原。默认 dry_run，必须显式 dry_run=false 才落盘。

    判定只用 ``_session_file_exists`` 的显式 False —— 它返回 None 代表
    「无法判定」（没有 session 对象），这种情况一律保留，绝不因为探测
    不到就删用户的会话。
    """
    from pathlib import Path as FsPath

    # _get_current_user 返回 (username, is_admin) 元组，不是对象。
    current = _get_current_user(request)
    if not current or not current[1]:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="多智能体管理器未就绪")
    reports = []
    for key, ws in list(manager.agents.items()):
        if agent_id:
            ws_agent = getattr(ws, "agent_id", None)
            if ws_agent and ws_agent != agent_id:
                continue
        chat_manager = getattr(ws, "chat_manager", None)
        if chat_manager is None:
            continue

        session = getattr(getattr(ws, "runner", None), "session", None)
        ws_username = getattr(ws, "username", "") or ""

        def keep(spec, _session=session, _username=ws_username):
            verdict = _session_file_exists(
                _session,
                spec.session_id,
                spec.user_id or _username,
            )
            # None = 判不了 -> 保留。只有明确 False 才归档。
            return verdict is not False

        archive_dir = FsPath(ws.workspace_dir) / ".trash" / "chat_archive"
        report = await chat_manager.archive_chats_where(
            keep,
            archive_dir,
            dry_run=dry_run,
        )
        report["workspace_key"] = key
        reports.append(report)

    total = sum(r["total"] for r in reports)
    archived = sum(r["archived"] for r in reports)
    logger.info(
        "Chat index GC (dry_run=%s): %d entries scanned, %d orphan across %d indexes",
        dry_run,
        total,
        archived,
        len(reports),
    )
    return {
        "dry_run": dry_run,
        "indexes": len(reports),
        "total_entries": total,
        "orphan_entries": archived,
        "reports": reports,
    }
