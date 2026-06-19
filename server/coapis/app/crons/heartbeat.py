# -*- coding: utf-8 -*-
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

"""
Heartbeat: run agent with HEARTBEAT.md as query at interval.
Uses config functions (get_heartbeat_config, get_heartbeat_query_path,
load_config) for paths and settings.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any, Dict, Optional

from ...agents.utils.file_handling import read_text_file_with_encoding_fallback
from ...config import (
    get_heartbeat_config,
    get_heartbeat_query_path,
    load_config,
)
from ...constant import HEARTBEAT_FILE, HEARTBEAT_TARGET_LAST, TMP_DIR, WORKSPACES_DIR
from ..crons.models import _crontab_dow_to_name

logger = logging.getLogger(__name__)

# Pattern for "30m", "1h", "2h30m", "90s"
_EVERY_PATTERN = re.compile(
    r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$",
    re.IGNORECASE,
)

# 5-field cron: minute hour day month day_of_week
_CRON_FIELD_PATTERN = re.compile(
    r"^[\d\*\-/,]+$",
)


def is_cron_expression(every: str) -> bool:
    """Return True if *every* looks like a 5-field cron expression."""
    parts = (every or "").strip().split()
    if len(parts) != 5:
        return False
    return all(_CRON_FIELD_PATTERN.match(p) for p in parts)


def parse_heartbeat_cron(every: str) -> tuple:
    """Parse and normalize a 5-field cron string.

    Returns (minute, hour, day, month, dow).
    """
    parts = every.strip().split()
    if len(parts) == 5:
        parts[4] = _crontab_dow_to_name(parts[4])
    return tuple(parts)


def parse_heartbeat_every(every: str) -> int:
    """Parse interval string (e.g. '30m', '1h') to total seconds.

    Note: cron expressions should be detected via ``is_cron_expression``
    *before* calling this function.
    """
    every = (every or "").strip()
    if not every:
        return 30 * 60  # default 30 min
    m = _EVERY_PATTERN.match(every)
    if not m:
        logger.warning("heartbeat every=%r invalid, using 30m", every)
        return 30 * 60
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    seconds = int(m.group("seconds") or 0)
    total = hours * 3600 + minutes * 60 + seconds
    if total <= 0:
        return 30 * 60
    return total


def _in_active_hours(active_hours: Any) -> bool:
    """Return True if the current time in user timezone is within
    [start, end].
    """
    if (
        not active_hours
        or not hasattr(active_hours, "start")
        or not hasattr(active_hours, "end")
    ):
        return True
    try:
        start_parts = active_hours.start.strip().split(":")
        end_parts = active_hours.end.strip().split(":")
        start_t = time(
            int(start_parts[0]),
            int(start_parts[1]) if len(start_parts) > 1 else 0,
        )
        end_t = time(
            int(end_parts[0]),
            int(end_parts[1]) if len(end_parts) > 1 else 0,
        )
    except (ValueError, IndexError, AttributeError):
        return True
    user_tz = load_config().user_timezone or "UTC"
    try:
        now = datetime.now(ZoneInfo(user_tz)).time()
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning(
            "Invalid timezone %r in config, falling back to UTC"
            " for heartbeat active hours check.",
            user_tz,
        )
        now = datetime.now(timezone.utc).time()
    if start_t <= end_t:
        return start_t <= now <= end_t
    return now >= start_t or now <= end_t


async def _persist_heartbeat_result(
    *,
    runner: Any,
    agent_id: str,
    session_id: str,
    query_text: str,
    response_text: str,
    user_id: Optional[str] = None,
) -> None:
    """Persist heartbeat execution result to session state file.

    v0.5.2: Routing logic:
    - If user_id is provided → write to workspaces/{user_id}/chat/ (standard path)
    - Otherwise → write to tmp/heartbeat/{agent_id}/ (fallback)
    """
    try:
        import json
        from ...constant import WORKSPACES_DIR, TMP_DIR

        # Determine output directory based on user_id
        if user_id:
            sessions_dir = WORKSPACES_DIR / user_id / "chat"
        else:
            sessions_dir = TMP_DIR / "heartbeat" / agent_id

        sessions_dir.mkdir(parents=True, exist_ok=True)

        # session_id format: heartbeat:{agent_id}:{timestamp}
        ts = session_id.rsplit(":", 1)[-1] if ":" in session_id else str(int(time.time()))
        session_file = sessions_dir / f"{agent_id}_heartbeat--{agent_id}--{ts}.json"

        # Load existing state or create new
        if session_file.exists():
            with open(session_file) as f:
                state = json.load(f)
        else:
            state = {}

        # Build messages list
        messages = []
        if query_text:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": query_text}],
            })
        if response_text:
            messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": response_text}],
            })

        # Update state with messages
        agent_state = state.setdefault("agent", {})
        mem = agent_state.setdefault("memory", {})
        mem["content"] = messages
        mem["_compressed_summary"] = f"Heartbeat execution at {ts}"

        # Write back atomically
        tmp_file = session_file.with_suffix(".json.tmp")
        with open(tmp_file, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        tmp_file.rename(session_file)

        logger.info(
            "Persisted heartbeat result: %d messages to %s",
            len(messages),
            session_file.name,
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.warning("Failed to persist heartbeat result: %s", e)


async def run_heartbeat_once(
    *,
    runner: Any,
    channel_manager: Any,
    agent_id: Optional[str] = None,
    workspace_dir: Optional[Path] = None,
) -> None:
    """
    Run one heartbeat: read HEARTBEAT.md from workspace, run agent,
    optionally dispatch to last channel (target=last).

    Args:
        runner: Agent runner instance
        channel_manager: Channel manager instance
        agent_id: Agent ID for loading config
        workspace_dir: Workspace directory for reading HEARTBEAT.md
    """
    from ...config.config import load_agent_config

    hb = get_heartbeat_config(agent_id)
    if not _in_active_hours(hb.active_hours):
        logger.debug("heartbeat skipped: outside active hours")
        return

    # Use workspace_dir if provided, otherwise fall back to global path
    if workspace_dir:
        path = Path(workspace_dir) / HEARTBEAT_FILE
    else:
        path = get_heartbeat_query_path()

    if not path.is_file():
        logger.debug("heartbeat skipped: no file at %s", path)
        return

    query_text = read_text_file_with_encoding_fallback(path).strip()
    if not query_text:
        logger.debug("heartbeat skipped: empty query file")
        return

    # Build request: single user message with query text
    # Use isolated session per heartbeat execution to prevent context pollution
    import time
    heartbeat_session_id = f"heartbeat:{agent_id}:{int(time.time())}"
    req: Dict[str, Any] = {
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": query_text}],
            },
        ],
        "session_id": heartbeat_session_id,
        "user_id": agent_id or "heartbeat",
    }

    # Get last_dispatch from agent config if agent_id provided
    last_dispatch = None
    if agent_id:
        try:
            agent_config = load_agent_config(agent_id)
            last_dispatch = agent_config.last_dispatch
        except Exception:
            pass
    else:
        # Legacy: try root config
        config = load_config()
        last_dispatch = config.last_dispatch

    target = (hb.target or "").strip().lower()

    # Collect assistant response for persistence
    response_texts = []

    async def _collect_response(event: Any) -> None:
        """Extract text content from streaming event."""
        try:
            content = getattr(event, "content", None)
            if isinstance(content, str) and content:
                response_texts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text", "")
                        if t:
                            response_texts.append(t)
                    elif hasattr(block, "text"):
                        t = getattr(block, "text", "")
                        if t:
                            response_texts.append(t)
        except Exception:  # pylint: disable=broad-except
            pass

    if target == HEARTBEAT_TARGET_LAST and last_dispatch:
        ld = last_dispatch
        if ld.channel and (ld.user_id or ld.session_id):

            async def _run_and_dispatch() -> None:
                async for event in runner.stream_query(req):
                    await _collect_response(event)
                    await channel_manager.send_event(
                        channel=ld.channel,
                        user_id=ld.user_id,
                        session_id=ld.session_id,
                        event=event,
                        meta={},
                    )

            try:
                await asyncio.wait_for(_run_and_dispatch(), timeout=120)
            except asyncio.TimeoutError:
                logger.warning("heartbeat run timed out")
            # Persist heartbeat result to session (v0.5.2: route by user_id)
            persist_uid = req.get("user_id")
            await _persist_heartbeat_result(
                runner=runner,
                agent_id=agent_id or "default",
                session_id=heartbeat_session_id,
                query_text=query_text,
                response_text="".join(response_texts),
                user_id=persist_uid,
            )
            return

    # target main or no last_dispatch: run agent only, no dispatch
    async def _run_only() -> None:
        async for event in runner.stream_query(req):
            await _collect_response(event)

    try:
        await asyncio.wait_for(_run_only(), timeout=120)
    except asyncio.TimeoutError:
        logger.warning("heartbeat run timed out")

    # Persist heartbeat result to session (v0.5.2: route by user_id)
    persist_uid = req.get("user_id")
    await _persist_heartbeat_result(
        runner=runner,
        agent_id=agent_id or "default",
        session_id=heartbeat_session_id,
        query_text=query_text,
        response_text="".join(response_texts),
        user_id=persist_uid,
    )
