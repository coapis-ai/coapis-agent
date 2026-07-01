# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared streaming utilities for CoApis agent message queues.

Provides ``stream_agent_messages`` — the canonical way to consume
streaming output from any ``CoApisAgent`` (or ``ReActAgent`` subclass)
via its ``msg_queue``.

Both ``runner.py`` and ``workspace.py`` should import from here instead
of duplicating the queue-drain + cancellation logic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncGenerator, Coroutine

from agentscope.message import Msg

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ResponseBlock — lightweight data class for frontend rendering
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field


@dataclass
class ResponseBlock:
    """Structured output block consumed by workspace._process_handler.

    Attributes:
        type: One of "text", "thinking", "tool_call", "tool_output", "newline"
        content: The text content of this block
        meta: Optional metadata (tool_name, tool_args, call_id, etc.)
    """

    type: str
    content: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


# Sentinel placed into the queue when the agent task finishes,
# so the consumer loop knows to stop.
_PRINT_END_SIGNAL: str = "__PRINT_END__"


async def cancel_streaming_task(task: asyncio.Task) -> None:
    """Cancel a running agent task and wait for it to settle."""
    if task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.debug(
            "Streaming agent task finished with error during cancellation",
            exc_info=True,
        )


async def stream_agent_messages(
    *,
    agents: list[Any],
    coroutine_task: Coroutine[Any, Any, Msg],
) -> AsyncGenerator[tuple[Msg, bool], None]:
    """Enable ``msg_queue`` on *agents*, run *coroutine_task* in the
    background, and yield ``(Msg, last)`` pairs as they arrive.

    Usage::

        async for msg, last in stream_agent_messages(
            agents=[agent],
            coroutine_task=agent.reply(input_msg),
        ):
            # msg  — agentscope Msg with content blocks
            # last — True if this is the final chunk for the turn
            ...

    The generator handles ``CancelledError`` gracefully: it cancels the
    background task and re-raises, making it safe to use inside
    ``async for`` loops that may be interrupted by ``/stop``.
    """

    queue: asyncio.Queue = asyncio.Queue()
    for agent in agents:
        agent.set_msg_queue_enabled(True, queue)

    task = asyncio.create_task(coroutine_task)

    # If the task already finished (e.g. instant error), signal immediately
    if task.done():
        await queue.put(_PRINT_END_SIGNAL)
    else:
        task.add_done_callback(lambda _: queue.put_nowait(_PRINT_END_SIGNAL))

    try:
        while True:
            printing_msg = await queue.get()
            if (
                isinstance(printing_msg, str)
                and printing_msg == _PRINT_END_SIGNAL
            ):
                break
            msg, last, _ = printing_msg
            yield msg, last

        # Propagate any exception raised inside the agent task
        exception = task.exception()
        if exception is not None:
            raise exception from None
    except asyncio.CancelledError:
        await cancel_streaming_task(task)
        raise
    finally:
        await cancel_streaming_task(task)
