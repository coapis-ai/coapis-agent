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

"""SipBackend Protocol -- abstraction for Dev / Production.

* **PyVoIPBackend** (``sip_mode="dev"``)
* **LiveKitBackend** (``sip_mode="livekit"``)
"""
from __future__ import annotations

import asyncio
from typing import (
    Any,
    Callable,
    Coroutine,
    Optional,
    Protocol,
    runtime_checkable,
)

IncomingCallCallback = Callable[
    [
        str,
        str,
        str,
        asyncio.Queue,
        Callable[[bytes], Coroutine[Any, Any, None]],
    ],
    Coroutine[Any, Any, None],
]

CallEndedCallback = Callable[
    [str],
    Coroutine[Any, Any, None],
]


@runtime_checkable
class SipBackend(Protocol):
    """Pluggable SIP/RTP backend."""

    on_incoming_call: Optional[IncomingCallCallback]
    on_call_ended: Optional[CallEndedCallback]

    async def start(self) -> None:
        """Start the backend."""

    async def stop(self) -> None:
        """Stop the backend."""

    async def play_audio(
        self,
        call_id: str,
        audio: bytes,
    ) -> None:
        """Send raw PCM audio to the caller."""
