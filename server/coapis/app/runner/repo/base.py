# -*- coding: utf-8 -*-
"""Chat repository for storing chat/session specs."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models import ChatSpec, ChatsFile


class BaseChatRepository(ABC):
    """Abstract repository for chat specs persistence."""

    @abstractmethod
    async def load(self) -> ChatsFile:
        """Load all chat specs from storage."""
        raise NotImplementedError

    @abstractmethod
    async def save(self, chats_file: ChatsFile) -> None:
        """Persist all chat specs to storage (should be atomic if possible)."""
        raise NotImplementedError

    # ---- Convenience operations ----

    async def list_chats(self) -> list[ChatSpec]:
        """List all chat specifications."""
        cf = await self.load()
        return cf.chats

    async def get_chat(self, chat_id: str) -> Optional[ChatSpec]:
        """Get chat spec by chat_id (UUID)."""
        cf = await self.load()
        for chat in cf.chats:
            if chat.id == chat_id:
                return chat
        return None

    async def get_chat_by_id(
        self,
        session_id: str,
        user_id: str,
        channel: str = "console",
    ) -> Optional[ChatSpec]:
        """Get chat spec by session_id and user_id."""
        import logging

        logger = logging.getLogger(__name__)

        cf = await self.load()

        logger.debug(
            f"get_chat_by_id: Searching in {len(cf.chats)} chats for "
            f"session_id={session_id}, user_id={user_id}, "
            f"channel={channel}",
        )

        for chat in cf.chats:
            if (
                chat.session_id == session_id
                and chat.user_id == user_id
                and chat.channel == channel
            ):
                logger.debug(f"get_chat_by_id: Found match: {chat.id}")
                return chat

        logger.debug("get_chat_by_id: No match found")
        return None

    async def upsert_chat(self, spec: ChatSpec) -> None:
        """Insert or update a chat spec."""
        cf = await self.load()
        for i, c in enumerate(cf.chats):
            if c.id == spec.id:
                cf.chats[i] = spec
                break
        else:
            cf.chats.append(spec)
        await self.save(cf)

    async def delete_chats(self, chat_ids: list[str]) -> bool:
        """Delete chat specs by chat_id (UUID)."""
        cf = await self.load()
        original_len = len(cf.chats)
        cf.chats = [c for c in cf.chats if c.id not in chat_ids]
        if len(cf.chats) < original_len:
            await self.save(cf)
            return True
        return False

    async def filter_chats(
        self,
        user_id: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> list[ChatSpec]:
        """List chat specs with optional filters.

        Empty string ("") is treated as "no filter" (return all).
        """
        cf = await self.load()
        result = cf.chats
        if user_id:
            result = [c for c in result if c.user_id == user_id]
        if channel:
            result = [c for c in result if c.channel == channel]
        return result
