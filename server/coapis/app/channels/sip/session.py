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

"""Call session management for the SIP channel."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class SIPCallSession:
    """One active or ended SIP call."""

    call_id: str
    from_uri: str
    to_uri: str
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    sip_call: Any = None
    stt_engine: Any = None
    status: str = "ringing"
    hangup_cause: str = ""
    tts_abort: asyncio.Event = field(
        default_factory=asyncio.Event,
    )

    @property
    def session_id(self) -> str:
        return f"sip:{self.call_id}"


class SIPCallSessionManager:
    """Registry of active SIP call sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, SIPCallSession] = {}

    def create_session(
        self,
        call_id: str,
        from_uri: str,
        to_uri: str,
        sip_call: Any = None,
    ) -> SIPCallSession:
        session = SIPCallSession(
            call_id=call_id,
            from_uri=from_uri,
            to_uri=to_uri,
            sip_call=sip_call,
        )
        self._sessions[call_id] = session
        logger.info(
            "SIP session created: %s from=%s",
            call_id,
            from_uri,
        )
        return session

    def get_session(
        self,
        call_id: str,
    ) -> Optional[SIPCallSession]:
        return self._sessions.get(call_id)

    def end_session(self, call_id: str) -> None:
        session = self._sessions.pop(call_id, None)
        if session:
            session.status = "ended"
            logger.info(
                "SIP session ended: %s",
                call_id,
            )

    def active_sessions(self) -> list[SIPCallSession]:
        return [
            s
            for s in self._sessions.values()
            if s.status in ("ringing", "active")
        ]

    def active_count(self) -> int:
        return sum(
            1
            for s in self._sessions.values()
            if s.status in ("ringing", "active")
        )
