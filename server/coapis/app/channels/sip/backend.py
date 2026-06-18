# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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
