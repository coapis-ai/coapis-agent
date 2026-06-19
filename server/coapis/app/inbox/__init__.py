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

"""Inbox module - async message queue and notification system.

Provides:
- Async message queue per user
- Message types: notification, task_result, approval, system
- Unread count tracking
- WebSocket push support
- REST API for inbox operations
"""

import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

from ..auth import get_current_user

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """Message types for inbox notifications."""
    NOTIFICATION = "notification"
    TASK_RESULT = "task_result"
    APPROVAL = "approval"
    SYSTEM = "system"
    SECURITY = "security"


class MessageStatus(str, Enum):
    """Message read status."""
    UNREAD = "unread"
    READ = "read"
    ARCHIVED = "archived"


class InboxMessage:
    """Single inbox message."""

    def __init__(
        self,
        user_id: str,
        message_type: MessageType,
        title: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        priority: int = 0,
    ):
        self.id = str(uuid.uuid4())
        self.user_id = user_id
        self.message_type = message_type
        self.title = title
        self.content = content
        self.metadata = metadata or {}
        self.priority = priority
        self.status = MessageStatus.UNREAD
        self.created_at = datetime.utcnow()
        self.read_at: Optional[datetime] = None
        self.expires_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "type": self.message_type.value,
            "title": self.title,
            "content": self.content,
            "metadata": self.metadata,
            "priority": self.priority,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


class InboxManager:
    """Manages inbox messages for all users.

    In-memory implementation. For production, replace with Redis/DB backend.
    """

    def __init__(self, max_messages_per_user: int = 100, default_ttl_hours: int = 72):
        self._messages: Dict[str, List[InboxMessage]] = {}
        self._ws_connections: Dict[str, WebSocket] = {}
        self._max_messages = max_messages_per_user
        self._default_ttl = timedelta(hours=default_ttl_hours)

    async def send(
        self,
        user_id: str,
        message_type: MessageType,
        title: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        priority: int = 0,
        ttl_hours: Optional[float] = None,
    ) -> InboxMessage:
        """Send a message to user's inbox."""
        msg = InboxMessage(
            user_id=user_id,
            message_type=message_type,
            title=title,
            content=content,
            metadata=metadata,
            priority=priority,
        )

        if ttl_hours is not None:
            msg.expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)

        if user_id not in self._messages:
            self._messages[user_id] = []

        # Add message
        self._messages[user_id].append(msg)

        # Enforce max messages (remove oldest archived/read)
        if len(self._messages[user_id]) > self._max_messages:
            removable = [
                m for m in self._messages[user_id]
                if m.status != MessageStatus.UNREAD
            ]
            removable.sort(key=lambda m: m.created_at)
            for old_msg in removable[:len(self._messages[user_id]) - self._max_messages]:
                self._messages[user_id].remove(old_msg)

        # Push to WebSocket if connected
        await self._push_to_ws(user_id, msg)

        logger.info(
            "Inbox message sent: user=%s type=%s title=%s",
            user_id, message_type.value, title,
        )

        return msg

    async def get_messages(
        self,
        user_id: str,
        status: Optional[MessageStatus] = None,
        message_type: Optional[MessageType] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[InboxMessage]:
        """Get user's inbox messages with filters."""
        if user_id not in self._messages:
            return []

        messages = self._messages[user_id]

        # Apply filters
        if status is not None:
            messages = [m for m in messages if m.status == status]
        if message_type is not None:
            messages = [m for m in messages if m.message_type == message_type]

        # Sort by priority (desc) then created_at (desc)
        messages.sort(key=lambda m: (m.priority, m.created_at), reverse=True)

        # Clean expired
        now = datetime.utcnow()
        messages = [m for m in messages if m.expires_at is None or m.expires_at > now]

        # Pagination
        return messages[offset: offset + limit]

    async def mark_read(self, user_id: str, message_id: str) -> bool:
        """Mark a message as read."""
        if user_id not in self._messages:
            return False

        for msg in self._messages[user_id]:
            if msg.id == message_id and msg.status == MessageStatus.UNREAD:
                msg.status = MessageStatus.READ
                msg.read_at = datetime.utcnow()
                return True

        return False

    async def mark_all_read(self, user_id: str) -> int:
        """Mark all messages as read. Returns count of marked messages."""
        if user_id not in self._messages:
            return 0

        count = 0
        for msg in self._messages[user_id]:
            if msg.status == MessageStatus.UNREAD:
                msg.status = MessageStatus.READ
                msg.read_at = datetime.utcnow()
                count += 1

        return count

    async def archive(self, user_id: str, message_id: str) -> bool:
        """Archive a message."""
        if user_id not in self._messages:
            return False

        for msg in self._messages[user_id]:
            if msg.id == message_id:
                msg.status = MessageStatus.ARCHIVED
                return True

        return False

    async def unread_count(self, user_id: str) -> int:
        """Get unread message count."""
        if user_id not in self._messages:
            return 0

        now = datetime.utcnow()
        return sum(
            1 for m in self._messages[user_id]
            if m.status == MessageStatus.UNREAD
            and (m.expires_at is None or m.expires_at > now)
        )

    async def connect_ws(self, user_id: str, ws: WebSocket):
        """Register WebSocket connection for user."""
        await ws.accept()
        self._ws_connections[user_id] = ws
        logger.info("WebSocket connected: user=%s", user_id)

    async def disconnect_ws(self, user_id: str):
        """Remove WebSocket connection."""
        self._ws_connections.pop(user_id, None)
        logger.info("WebSocket disconnected: user=%s", user_id)

    async def _push_to_ws(self, user_id: str, msg: InboxMessage):
        """Push message to user's WebSocket if connected."""
        ws = self._ws_connections.get(user_id)
        if ws:
            try:
                await ws.send_json({
                    "type": "inbox_message",
                    "message": msg.to_dict(),
                })
            except Exception as e:
                logger.warning("Failed to push to WS: user=%s error=%s", user_id, e)
                self._ws_connections.pop(user_id, None)

    def cleanup_expired(self):
        """Remove expired messages (call periodically)."""
        now = datetime.utcnow()
        for user_id in list(self._messages.keys()):
            self._messages[user_id] = [
                m for m in self._messages[user_id]
                if m.expires_at is None or m.expires_at > now
            ]
            if not self._messages[user_id]:
                self._messages.pop(user_id, None)


# Global inbox manager instance
inbox_manager = InboxManager()


# ---- API Router ----

router = APIRouter(prefix="/api/inbox", tags=["Inbox"])


def _get_user_id(user_info: dict) -> str:
    """Extract user ID from auth user_info."""
    return user_info.get("username") or user_info.get("sub", "anonymous")


@router.get("/messages")
async def get_messages(
    request: Request,
    status: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """Get inbox messages."""
    user_info = get_current_user(request)
    user_id = _get_user_id(user_info)

    status_enum = MessageStatus(status) if status else None
    type_enum = MessageType(type) if type else None

    messages = await inbox_manager.get_messages(
        user_id=user_id,
        status=status_enum,
        message_type=type_enum,
        limit=limit,
        offset=offset,
    )

    return {
        "messages": [m.to_dict() for m in messages],
        "unread_count": await inbox_manager.unread_count(user_id),
    }


@router.post("/messages/{message_id}/read")
async def mark_message_read(
    request: Request,
    message_id: str,
):
    """Mark a message as read."""
    user_info = get_current_user(request)
    user_id = _get_user_id(user_info)

    ok = await inbox_manager.mark_read(user_id, message_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Message not found")

    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(
    request: Request,
):
    """Mark all messages as read."""
    user_info = get_current_user(request)
    user_id = _get_user_id(user_info)

    count = await inbox_manager.mark_all_read(user_id)
    return {"ok": True, "marked": count}


@router.post("/messages/{message_id}/archive")
async def archive_message(
    request: Request,
    message_id: str,
):
    """Archive a message."""
    user_info = get_current_user(request)
    user_id = _get_user_id(user_info)

    ok = await inbox_manager.archive(user_id, message_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Message not found")

    return {"ok": True}


@router.get("/unread-count")
async def get_unread_count(
    request: Request,
):
    """Get unread message count."""
    user_info = get_current_user(request)
    user_id = _get_user_id(user_info)

    count = await inbox_manager.unread_count(user_id)
    return {"unread_count": count}


@router.websocket("/ws")
async def inbox_websocket(ws: WebSocket):
    """WebSocket endpoint for real-time inbox updates."""
    # TODO: Authenticate WebSocket connection
    await inbox_manager.connect_ws("anonymous", ws)
    try:
        while True:
            data = await ws.receive_text()
            # Handle client messages if needed
            pass
    except WebSocketDisconnect:
        await inbox_manager.disconnect_ws("anonymous")


# ---- Convenience Functions ----

async def send_notification(
    user_id: str,
    title: str,
    content: str,
    **kwargs,
):
    """Send a notification message."""
    return await inbox_manager.send(
        user_id=user_id,
        message_type=MessageType.NOTIFICATION,
        title=title,
        content=content,
        **kwargs,
    )


async def send_task_result(
    user_id: str,
    task_id: str,
    success: bool,
    result: Any = None,
    **kwargs,
):
    """Send a task result message."""
    return await inbox_manager.send(
        user_id=user_id,
        message_type=MessageType.TASK_RESULT,
        title="Task Completed" if success else "Task Failed",
        content=str(result) if result else ("Success" if success else "Failed"),
        metadata={"task_id": task_id, "success": success},
        **kwargs,
    )


async def send_approval_request(
    user_id: str,
    requester: str,
    action: str,
    details: str = "",
    **kwargs,
):
    """Send an approval request message."""
    return await inbox_manager.send(
        user_id=user_id,
        message_type=MessageType.APPROVAL,
        title=f"Approval Required: {action}",
        content=f"Request from {requester}: {details}",
        metadata={"requester": requester, "action": action},
        priority=10,
        **kwargs,
    )


async def send_security_alert(
    user_id: str,
    alert_type: str,
    details: str,
    **kwargs,
):
    """Send a security alert message."""
    return await inbox_manager.send(
        user_id=user_id,
        message_type=MessageType.SECURITY,
        title=f"Security Alert: {alert_type}",
        content=details,
        priority=20,
        **kwargs,
    )
