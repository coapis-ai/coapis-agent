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

"""Estimated token counter implementation."""

from typing import Any

from agentscope.token import TokenCounterBase


class EstimatedTokenCounter(TokenCounterBase):
    """Token counter that estimates tokens using character-based calculation.

    This is a lightweight approximation suitable for cases where exact token
    counting is not critical. For accurate counts, use tiktoken or the
    model's tokenizer directly.
    """

    def __init__(self, estimate_divisor: float = 4):
        """Initialize the estimated token counter.

        Args:
            estimate_divisor: The divisor for character-to-token estimation.
                Default 4 assumes roughly 4 characters per token.
                Use 2-3 for Chinese/Japanese text, 4-5 for English.
        """
        if estimate_divisor <= 0:
            raise ValueError("estimate_divisor cannot be zero")
        self.estimate_divisor: float = estimate_divisor

    async def count(self, text: str, **_kwargs) -> int:
        """Count tokens in the given messages.

        Args:
            text: The text to count tokens.
            **kwargs: Additional arguments.

        Returns:
            Estimated number of tokens in all messages.
        """
        if not text:
            return 0
        return int(len(text.encode("utf-8")) / self.estimate_divisor + 0.5)


class TokenCounterAdapter(TokenCounterBase):
    """Adapter to make EstimatedTokenCounter compatible with agentscope's
    TokenCounterBase interface.

    agentscope's TokenCounterBase.count() expects messages: list[dict],
    but CoApis's EstimatedTokenCounter.count() expects text: str.
    This adapter bridges the gap by converting messages to string.
    """

    def __init__(self, counter: EstimatedTokenCounter):
        """Initialize with an EstimatedTokenCounter instance.

        Args:
            counter: The CoApis EstimatedTokenCounter to wrap.
        """
        self._counter = counter

    async def count(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> int:
        """Count tokens by converting messages to string.

        Args:
            messages: List of message dicts (agentscope format).
            tools: Optional list of tool dicts.

        Returns:
            Estimated token count.
        """
        # Convert messages to string representation
        parts = []
        for msg in messages:
            parts.append(str(msg))
        if tools:
            parts.append(str(tools))
        text = "\n".join(parts)
        return await self._counter.count(text=text)
