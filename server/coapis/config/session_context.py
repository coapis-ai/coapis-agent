# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
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

"""Per-request session context variables for concurrent safety.

Inspired by CoApis (coapis) ``gateway/session_context.py``:
uses ``contextvars.ContextVar`` so each async task gets its own copy of
session metadata.  This prevents concurrent requests from overwriting
each other's user identity, session ID, channel, etc.

**Why contextvars?**

The gateway processes messages concurrently via ``asyncio``.  Without
task-local storage, Request A's ``set_current_username("alice")`` could
be silently overwritten by Request B's ``set_current_username("bob")``
before A finishes — causing B's identity to leak into A's context.

``contextvars.ContextVar`` values are task-local: each ``asyncio`` task
(and any ``run_in_executor`` thread it spawns via ``copy_context()``)
gets its own copy, so concurrent requests never interfere.

**Usage**

    from coapis.config.session_context import (
        set_session_context,
        get_current_user_id,
        get_current_session_id,
        clear_session_context,
    )

    # At the start of a request handler:
    set_session_context(
        user_id="alice",
        session_id="console:alice",
        channel="console",
        agent_id="default",
    )

    # Deep in the call stack:
    uid = get_current_user_id()  # "alice"

    # At the end (optional — contextvars auto-clean on task exit):
    clear_session_context()
"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, Optional


# ── Sentinel to distinguish "never set" from "explicitly None" ────────

_UNSET: Any = object()


# ── Core session variables ────────────────────────────────────────────

_SESSION_ID: ContextVar[Optional[str]] = ContextVar(
    "eater_session_id", default=None,
)
_USER_ID: ContextVar[Optional[str]] = ContextVar(
    "eater_user_id", default=None,
)
_CHANNEL: ContextVar[Optional[str]] = ContextVar(
    "eater_channel", default=None,
)
_AGENT_ID: ContextVar[Optional[str]] = ContextVar(
    "eater_agent_id", default=None,
)
_USER_ROLE: ContextVar[Optional[str]] = ContextVar(
    "eater_user_role", default=None,
)
_ROOT_SESSION_ID: ContextVar[Optional[str]] = ContextVar(
    "eater_root_session_id", default=None,
)
_WORKSPACE_DIR: ContextVar[Optional[Path]] = ContextVar(
    "eater_workspace_dir", default=None,
)
_USERNAME: ContextVar[Optional[str]] = ContextVar(
    "eater_username", default=None,
)
_CHAT_ID: ContextVar[Optional[str]] = ContextVar(
    "eater_chat_id", default=None,
)


# ── Bulk set / clear ─────────────────────────────────────────────────

def set_session_context(
    *,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    channel: Optional[str] = None,
    agent_id: Optional[str] = None,
    user_role: Optional[str] = None,
    username: Optional[str] = None,
    root_session_id: Optional[str] = None,
    workspace_dir: Optional[Path] = None,
) -> None:
    """Set all session context variables at once.

    Call this at the start of each request handler to bind the
    current async task to a specific user + session + channel.

    Args:
        user_id: Authenticated user identifier.
        session_id: Chat session identifier (e.g. ``console:alice``).
        channel: Channel name (console / dingtalk / wecom / ...).
        agent_id: Agent identifier for this request.
        user_role: User role (user/advanced/admin/superadmin).
        username: Human-readable username (same as user_id in most cases).
        root_session_id: Root session ID for agent-to-agent chains.
        workspace_dir: Workspace directory path for this agent+user.
    """
    if user_id is not None:
        _USER_ID.set(user_id)
    if session_id is not None:
        _SESSION_ID.set(session_id)
    if channel is not None:
        _CHANNEL.set(channel)
    if agent_id is not None:
        _AGENT_ID.set(agent_id)
    if user_role is not None:
        _USER_ROLE.set(user_role)
    if username is not None:
        _USERNAME.set(username)
    if root_session_id is not None:
        _ROOT_SESSION_ID.set(root_session_id)
    if workspace_dir is not None:
        _WORKSPACE_DIR.set(workspace_dir)

    # ── Backward compatibility: sync old config.context vars ──
    # Many tool files (shell.py, file_io.py, browser_control.py, etc.)
    # still read from config.context.get_current_workspace_dir() and
    # config.context.get_current_user_role(). We must keep those in sync.
    try:
        from .context import (
            set_current_username as _old_set_username,
            set_current_user_role as _old_set_role,
            set_current_workspace_dir as _old_set_wd,
        )
        if username is not None:
            _old_set_username(username)
        if user_role is not None:
            _old_set_role(user_role)
        if workspace_dir is not None:
            _old_set_wd(workspace_dir)
    except ImportError:
        pass  # config.context may not exist in all environments


def clear_session_context() -> None:
    """Reset all session context variables to None.

    Optionally call at the end of a request handler for hygiene.
    Contextvars auto-clean when the async task exits, but explicit
    cleanup is good practice for long-lived connection handlers.
    """
    _SESSION_ID.set(None)
    _USER_ID.set(None)
    _CHANNEL.set(None)
    _AGENT_ID.set(None)
    _USER_ROLE.set(None)
    _ROOT_SESSION_ID.set(None)
    _WORKSPACE_DIR.set(None)
    _USERNAME.set(None)

    # Backward compatibility: clear old config.context vars too
    try:
        from .context import (
            set_current_username as _old_set_username,
            set_current_user_role as _old_set_role,
            set_current_workspace_dir as _old_set_wd,
        )
        _old_set_username(None)
        _old_set_role(None)
        _old_set_wd(None)
    except ImportError:
        pass


# ── Individual getters ────────────────────────────────────────────────

def get_current_session_id() -> Optional[str]:
    """Get the current request's session ID."""
    return _SESSION_ID.get()


def get_current_user_id() -> Optional[str]:
    """Get the current request's user ID."""
    return _USER_ID.get()


def get_current_channel() -> Optional[str]:
    """Get the current request's channel name."""
    return _CHANNEL.get()


def get_current_agent_id() -> Optional[str]:
    """Get the current request's agent ID."""
    return _AGENT_ID.get()


def get_current_user_role() -> Optional[str]:
    """Get the current request's user role."""
    return _USER_ROLE.get()


def get_current_root_session_id() -> Optional[str]:
    """Get the current request's root session ID (agent chain)."""
    return _ROOT_SESSION_ID.get()


def get_current_workspace_dir() -> Optional[Path]:
    """Get the current request's workspace directory."""
    return _WORKSPACE_DIR.get()


def get_current_username() -> Optional[str]:
    """Get the current request's username."""
    return _USERNAME.get()


# ── Individual setters (for targeted updates mid-request) ─────────────

def set_current_user_id(user_id: Optional[str]) -> None:
    """Update the current user ID."""
    _USER_ID.set(user_id)


def set_current_session_id(session_id: Optional[str]) -> None:
    """Update the current session ID."""
    _SESSION_ID.set(session_id)


def set_current_channel(channel: Optional[str]) -> None:
    """Update the current channel."""
    _CHANNEL.set(channel)


def set_current_agent_id(agent_id: Optional[str]) -> None:
    """Update the current agent ID."""
    _AGENT_ID.set(agent_id)


def set_current_user_role(role: Optional[str]) -> None:
    """Update the current user role."""
    _USER_ROLE.set(role)


def set_current_username(username: Optional[str]) -> None:
    """Update the current username."""
    _USERNAME.set(username)


def get_current_chat_id() -> Optional[str]:
    """Get the current request's chat ID (UUID from frontend)."""
    return _CHAT_ID.get()


def set_current_chat_id(chat_id: Optional[str]) -> None:
    """Update the current chat ID."""
    _CHAT_ID.set(chat_id)


def set_current_root_session_id(root_session_id: Optional[str]) -> None:
    """Update the current root session ID."""
    _ROOT_SESSION_ID.set(root_session_id)


def set_current_workspace_dir(workspace_dir: Optional[Path]) -> None:
    """Update the current workspace directory."""
    _WORKSPACE_DIR.set(workspace_dir)


# ── Snapshot for logging / debugging ──────────────────────────────────

def get_session_snapshot() -> Dict[str, Any]:
    """Return a dict of all current session context values.

    Useful for structured logging to trace which user/session
    is active in the current async task.
    """
    return {
        "user_id": _USER_ID.get(),
        "username": _USERNAME.get(),
        "session_id": _SESSION_ID.get(),
        "channel": _CHANNEL.get(),
        "agent_id": _AGENT_ID.get(),
        "user_role": _USER_ROLE.get(),
        "root_session_id": _ROOT_SESSION_ID.get(),
        "workspace_dir": str(_WORKSPACE_DIR.get()) if _WORKSPACE_DIR.get() else None,
    }
