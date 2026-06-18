# -*- coding: utf-8 -*-
"""Chat models for runner with UUID management."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ChatSpec(BaseModel):
    """Chat specification with UUID identifier.

    Stored in Redis and can be persisted in JSON file.
    """

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Chat UUID identifier",
    )
    name: str = Field(default="New Chat", description="Chat name")
    session_id: str = Field(
        ...,
        description="Session identifier (channel:user_id format)",
    )
    user_id: str = Field(..., description="User identifier")
    channel: str = Field(default="console", description="Channel name")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Chat creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Chat last update timestamp",
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )
    agent_id: str = Field(
        default="",
        description="Agent ID that owns this chat (for multi-agent isolation)",
    )
    status: str = Field(
        default="idle",
        description="Conversation status: idle or running",
    )
    pinned: bool = Field(
        default=False,
        description="Whether the chat is pinned to the top",
    )
    # NOTE: messages removed — history now stored in sessions/{session_id}.json
    # via AgentScope memory state, matching CoApis's architecture.
    # Use GET /chats/{chat_id} to load messages on-demand.


class ChatUpdate(BaseModel):
    """Mutable chat fields accepted from external clients."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, description="Chat name")
    pinned: bool | None = Field(
        default=False,
        description="Whether the chat is pinned to the top",
    )


class ChatHistory(BaseModel):
    """Complete chat view with spec and state."""

    messages: list = Field(default_factory=list)
    status: str = Field(
        default="idle",
        description="Conversation status: idle or running",
    )


class ChatsFile(BaseModel):
    """Chat registry file for JSON repository.

    Stores chat_id (UUID) -> session_id mappings for persistence.
    """

    version: int = 1
    chats: list[ChatSpec] = Field(default_factory=list)
