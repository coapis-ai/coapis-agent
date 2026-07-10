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

"""In-memory store for console channel push messages (e.g. cron text).

Bounded: at most _MAX_MESSAGES kept; messages older than _MAX_AGE_SECONDS
are dropped when reading. Frontend dedupes by id and caps its seen set.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List

# Single list: each item has id, text, ts, session_id and optional metadata.
# Bounded by count and age.
_list: List[Dict[str, Any]] = []
_lock = asyncio.Lock()
_MAX_AGE_SECONDS = 60
_MAX_MESSAGES = 500


async def append(session_id: str, text: str, *, sticky: bool = False) -> None:
    """Append a message (bounded: oldest dropped if over _MAX_MESSAGES)."""
    if not session_id or not text:
        return
    async with _lock:
        _list.append(
            {
                "id": str(uuid.uuid4()),
                "text": text,
                "sticky": sticky,
                "ts": time.time(),
                "session_id": session_id,
            },
        )
        if len(_list) > _MAX_MESSAGES:
            _list.sort(key=lambda m: m["ts"])
            del _list[: len(_list) - _MAX_MESSAGES]


async def take(session_id: str) -> List[Dict[str, Any]]:
    """Return and remove all messages for the session."""
    if not session_id:
        return []
    async with _lock:
        _prune_expired_locked(_MAX_AGE_SECONDS)
        out = []
        remaining = []
        for msg in _list:
            if msg.get("session_id") == session_id:
                out.append(msg)
            else:
                remaining.append(msg)
        _list[:] = remaining
        return _strip_ts(out)


async def take_all() -> List[Dict[str, Any]]:
    """Return and remove all non-expired messages from the store."""
    async with _lock:
        _prune_expired_locked(_MAX_AGE_SECONDS)
        out = list(_list)
        _list.clear()
        return _strip_ts(out)


def _strip_ts(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": m["id"],
            "text": m["text"],
            "sticky": bool(m.get("sticky", False)),
        }
        for m in msgs
    ]


def _prune_expired_locked(max_age_seconds: int) -> None:
    """Drop expired messages in-place. Caller must hold _lock."""
    cutoff = time.time() - max_age_seconds
    _list[:] = [m for m in _list if m["ts"] >= cutoff]


async def get_recent(
    max_age_seconds: int = _MAX_AGE_SECONDS,
) -> List[Dict[str, Any]]:
    """
    Return recent messages (not consumed). Drop older than max_age_seconds
    from store to bound memory.
    """
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative")

    async with _lock:
        _prune_expired_locked(max_age_seconds)
        return _strip_ts(_list)
