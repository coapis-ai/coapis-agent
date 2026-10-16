# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
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

"""Custom memory implementation with bugfixes and extensions."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os
from agentscope.agent._react_agent import _MemoryMark  # noqa
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg

from .as_msg_handler import AsMsgHandler
from .compactor_prompts import SUMMARY_PROMPT_EN
from ..utils.estimate_token_counter import EstimatedTokenCounter

logger = logging.getLogger(__name__)


class AgentContext(InMemoryMemory):
    """Extended InMemoryMemory with bugfixes and summary support."""

    def __init__(
        self,
        token_counter: EstimatedTokenCounter,
        dialog_path: str | Path | None = None,
    ):
        """Initialize the AgentContext.

        Args:
            token_counter: Token counter for measuring content length.
            dialog_path: Path to the dialog storage directory.
                If provided, messages will be persisted to jsonl
                files when cleared or compressed.
        """
        super().__init__()
        self._token_counter: EstimatedTokenCounter = token_counter
        self._msg_handler: AsMsgHandler = AsMsgHandler(token_counter)
        self._dialog_path: Path | None = (
            Path(dialog_path) if dialog_path else None
        )
        # Initialize compressed summary
        self._compressed_summary: str = ""

    async def _append_messages_to_dialog(self, messages: list[Msg]) -> int:
        """Append messages to dialog storage file.

        Saves messages to jsonl files named by message date (YYYY-mm-dd.jsonl).
        Each line is a JSON representation of a message.
        Messages are grouped by their timestamp date.

        Args:
            messages: List of messages to append to the dialog file.

        Returns:
            Number of messages successfully appended.
        """
        if not messages:
            return 0

        if self._dialog_path is None:
            logger.warning(
                "dialog_path is not set, skipping dialog persistence",
            )
            return 0

        # Ensure dialog directory exists
        try:
            await aiofiles.os.makedirs(self._dialog_path, exist_ok=True)
        except Exception as e:
            logger.exception(
                f"Failed to create dialog directory {self._dialog_path}: {e}",
            )
            return 0

        # Group messages by date (extracted from timestamp)
        # timestamp format: "YYYY-mm-dd HH:MM:SS.fff"
        messages_by_date: dict[str, list[Msg]] = {}
        for msg in messages:
            try:
                if msg.timestamp:
                    # Extract date part from timestamp
                    date_str = msg.timestamp.split()[0]  # "YYYY-mm-dd"
                else:
                    date_str = datetime.now().strftime("%Y-%m-%d")

                if date_str not in messages_by_date:
                    messages_by_date[date_str] = []
                messages_by_date[date_str].append(msg)
            except Exception as e:
                logger.warning(
                    f"Failed to process message timestamp: {e}, "
                    f"using today's date",
                )
                date_str = datetime.now().strftime("%Y-%m-%d")
                if date_str not in messages_by_date:
                    messages_by_date[date_str] = []
                messages_by_date[date_str].append(msg)

        # Append messages to corresponding date files
        # (sorted by timestamp within each date)
        total_count = 0
        for date_str, msgs in messages_by_date.items():
            # Sort messages by timestamp within the same date
            try:
                msgs_sorted = sorted(msgs, key=lambda m: m.timestamp or "")
            except Exception as e:
                logger.warning(f"Failed to sort messages by timestamp: {e}")
                msgs_sorted = msgs

            filename = f"{date_str}.jsonl"
            filepath = self._dialog_path / filename

            try:
                async with aiofiles.open(
                    filepath,
                    mode="a",
                    encoding="utf-8",
                ) as f:
                    for msg in msgs_sorted:
                        msg_dict = msg.to_dict()
                        await f.write(
                            json.dumps(msg_dict, ensure_ascii=False) + "\n",
                        )
                        total_count += 1
                logger.info(
                    f"Appended {len(msgs_sorted)} messages to {filepath}",
                )
            except Exception as e:
                logger.exception(
                    f"Failed to append messages to dialog "
                    f"file {filepath}: {e}",
                )

        return total_count

    async def get_memory(
        self,
        prepend_summary: bool = True,
        **_kwargs,
    ) -> list[Msg]:
        """Get the messages from the memory by mark (if provided).

        Args:
            prepend_summary: Whether to prepend compressed summary
            **_kwargs: Additional keyword arguments (ignored)

        Returns:
            List of filtered messages
        """
        filtered_content = [
            (msg, marks)
            for msg, marks in self.content
            if _MemoryMark.COMPRESSED not in marks
        ]

        if prepend_summary and self._compressed_summary:
            return [
                Msg(
                    "user",
                    SUMMARY_PROMPT_EN.format(summary=self._compressed_summary),
                    "user",
                ),
                *[msg for msg, _ in filtered_content],
            ]

        return [msg for msg, _ in filtered_content]

    def get_compressed_summary(self) -> str:
        """Get the compressed summary of the memory."""
        return self._compressed_summary

    async def update_compressed_summary(self, summary: str) -> None:
        """Update the compressed summary of the memory.

        The signature must stay ``async``.  Upstream
        ``ReActAgent._compress_memory_if_needed`` calls it as

            await self.memory.update_compressed_summary(...)

        and this class overrides the async base method.  A sync override
        makes that statement ``await None``, which raises ``TypeError`` the
        first time compression actually fires — i.e. the compaction path
        breaks exactly when it starts working.

        Args:
            summary: The compressed summary text to store.
        """
        self._compressed_summary = summary

    def state_dict(self) -> dict:
        """Get the state dictionary for serialization."""
        return {
            "content": [[msg.to_dict(), marks] for msg, marks in self.content],
            "_compressed_summary": self._compressed_summary,
        }

    # pylint: disable=attribute-defined-outside-init
    def load_state_dict(self, state_dict: dict, strict: bool = True) -> None:
        """Load the state dictionary for deserialization."""
        if strict and "content" not in state_dict:
            raise KeyError(
                "The state_dict does not contain 'content' key "
                "required for InMemoryMemory.",
            )

        self.content = []  # pylint: disable=attribute-defined-outside-init
        for item in state_dict.get("content", []):
            if isinstance(item, (tuple, list)) and len(item) == 2:
                msg_dict, marks = item
                msg = Msg.from_dict(msg_dict)
                self.content.append((msg, marks))

            elif isinstance(item, dict):
                # For compatibility with older versions
                msg = Msg.from_dict(item)
                self.content.append((msg, []))

            else:
                raise ValueError(
                    "Invalid item format in state_dict for InMemoryMemory.",
                )

        self._compressed_summary = state_dict.get("_compressed_summary", "")

    async def archive_compressed_and_purge(self) -> list[Msg]:
        """Archive upstream-compressed messages to dialog storage, then
        physically delete them from working memory.

        Upstream ``ReActAgent._compress_memory_if_needed`` summarizes the old
        prefix and flags those messages with ``MemoryMark.COMPRESSED``.  They
        stay in ``self.content`` forever unless someone removes them, which
        means every later prompt re-formats dead weight and the persisted
        session state keeps growing.  This closes the loop in one place:

        1. Persist the marked messages to ``dialog/*.jsonl`` (nothing is lost
           — the full transcript stays on disk).
        2. Drop them from ``self.content``.

        Returns:
            The archived messages in original order, so callers can feed them
            to long-term memory summarization.
        """
        marked = [
            msg
            for msg, marks in self.content
            if _MemoryMark.COMPRESSED in marks
        ]
        if not marked:
            return []

        try:
            archived = await self._append_messages_to_dialog(marked)
        except Exception:
            # If the archive write fails, keep live memory intact: losing the
            # transcript is worse than carrying dead weight.
            logger.exception("Failed to archive compressed messages to dialog.")
            return []

        if archived < len(marked):
            # ``_append_messages_to_dialog`` swallows its own errors and
            # reports how many messages it actually wrote.  A short count
            # means part of the transcript is not on disk, so the purge is
            # cancelled and the next compaction attempt retries it.
            logger.warning(
                "Archived only %d/%d compressed message(s); keeping them in "
                "working memory and retrying on the next compaction.",
                archived,
                len(marked),
            )
            return []

        msg_ids = {msg.id for msg in marked}

        initial_size = len(self.content)
        self.content = [
            (msg, marks)
            for msg, marks in self.content
            if msg.id not in msg_ids
        ]
        removed_count = initial_size - len(self.content)

        logger.info(
            "Archived + purged %d compressed message(s); %d remain in "
            "working memory.",
            removed_count,
            len(self.content),
        )
        return marked

    def clear_compressed_summary(self):
        """Clear the compressed summary."""
        self._compressed_summary = (
            ""  # pylint: disable=attribute-defined-outside-init
        )

    async def clear_content(self):
        """Persist all messages to dialog storage and clear the content.

        This method:
        1. Persists all messages in memory to the dialog storage
        2. Clears the in-memory content
        """
        # Persist all messages to dialog storage
        if self.content:
            messages = [msg for msg, _ in self.content]
            await self._append_messages_to_dialog(messages)

        # Clear in-memory content
        self.content.clear()
        logger.info("Cleared all messages from memory")

    async def estimate_tokens(
        self,
        max_input_length: int,
        window: Any = None,
    ) -> dict:
        """Estimate token usage for current memory.

        Args:
            max_input_length: Max input length for context usage calculation.
                Ignored when *window* is given — the window is the truth.
            window: ``WindowInfo`` of the model that will consume this
                history.  When passed, tokens are converted from measured
                characters with the **same calibration the compaction gate
                uses**, and the percentage is taken against the *effective*
                window, so what the user reads and what triggers compaction
                cannot diverge.  ``None`` keeps the legacy char/4 estimate.

        Returns:
            Dict containing detailed token statistics:
            - total_messages: Number of messages
            - compressed_summary_tokens: Tokens in compressed summary
            - messages_tokens: Tokens in messages
            - estimated_tokens: Total estimated tokens
            - max_input_length: Window the percentage was measured against
            - context_usage_ratio: Usage percentage
            - measured_chars: Raw character measurement (calibrated basis)
            - messages_detail: List of per-message AsMsgStat objects
        """
        messages = await self.get_memory(prepend_summary=False)

        compressed_summary = self.get_compressed_summary()
        compressed_summary_tokens = await self._msg_handler.count_str_token(
            compressed_summary,
        )

        # Build per-message token details using AsMsgHandler
        messages_detail = [
            await self._msg_handler.stat_message(msg) for msg in messages
        ]

        # Calculate total message tokens from stats
        messages_tokens = sum(stat.total_tokens for stat in messages_detail)
        estimated_tokens = messages_tokens + compressed_summary_tokens
        denominator = max_input_length

        # Same-source path: measure characters exactly like the budget gate
        # does (``len(str(msg.content))``) and convert with the calibrated
        # chars/token.  The char/4 counter below under-reports by ~3.6x at
        # the 1.1 calibration, which is why sessions read as "room left"
        # and then overflowed.
        measured_chars = sum(len(str(msg.content)) for msg in messages) + len(
            compressed_summary,
        )
        if window is not None:
            effective = int(getattr(window, "effective_tokens", 0) or 0)
            if effective > 0:
                estimated_tokens = window.to_tokens(measured_chars)
                messages_tokens = window.to_tokens(
                    measured_chars - len(compressed_summary),
                )
                compressed_summary_tokens = window.to_tokens(
                    len(compressed_summary),
                )
                denominator = effective

        # Calculate context usage ratio
        context_usage_ratio = (
            (estimated_tokens / denominator * 100) if denominator > 0 else 0
        )

        return {
            "total_messages": len(messages),
            "compressed_summary_tokens": compressed_summary_tokens,
            "messages_tokens": messages_tokens,
            "estimated_tokens": estimated_tokens,
            "max_input_length": denominator,
            "context_usage_ratio": context_usage_ratio,
            "measured_chars": measured_chars,
            "messages_detail": messages_detail,
        }

    async def get_history_str(
        self,
        max_input_length: int,
        window: Any = None,
    ) -> str:
        """Get formatted history string similar to /history command output.

        Args:
            max_input_length: Max input length for context usage calculation.
            window: ``WindowInfo`` forwarded to :meth:`estimate_tokens`.

        Returns:
            Formatted string containing conversation history details
        """
        stats = await self.estimate_tokens(max_input_length, window=window)

        lines = []
        for i, msg_stat in enumerate(stats["messages_detail"], 1):
            blocks_info = ""
            if msg_stat.content:
                block_strs = [
                    f"{b.block_type}(tokens={b.token_count})"
                    for b in msg_stat.content
                ]
                blocks_info = f"\n    content: [{', '.join(block_strs)}]"

            lines.append(
                f"[{i}] **{msg_stat.role}** "
                f"(total_tokens={msg_stat.total_tokens})"
                f"{blocks_info}\n    preview: {msg_stat.preview}",
            )

        calibration = getattr(window, "chars_per_token", None)
        basis = (
            f"- Measured: {stats['measured_chars']} chars "
            f"at {calibration} chars/token\n"
            if window is not None and calibration
            else ""
        )
        return (
            f"**Conversation History**\n\n"
            f"- Total messages: {stats['total_messages']}\n"
            f"- Estimated tokens: {stats['estimated_tokens']}\n"
            f"- Max input length: {stats['max_input_length']}\n"
            f"- Context usage: "
            f"{stats['context_usage_ratio']:.1f}%\n"
            f"{basis}"
            f"- Compressed summary tokens: "
            f"{stats['compressed_summary_tokens']}\n\n" + "\n\n".join(lines)
        )
