# -*- coding: utf-8 -*-
"""Background job: weekly eval report (Friday 18:00 Asia/Shanghai).

A single asyncio task sleeps until the next Friday 18:00, writes the report
via :func:`coapis.agent_eval.miner.write_weekly_report`, then re-arms. Kept
deliberately simple (no APScheduler dependency) and fully fault-tolerant:
any exception is logged and the loop re-arms on the following week.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - exotic runtimes
    _TZ = timezone(timedelta(hours=8))

logger = logging.getLogger(__name__)

_TASK: asyncio.Task | None = None


def _next_friday_18(now: datetime) -> datetime:
    days_ahead = (4 - now.weekday()) % 7  # Monday=0 ... Friday=4
    target = (now + timedelta(days=days_ahead)).replace(
        hour=18, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=7)
    return target


async def _loop() -> None:
    while True:
        now = datetime.now(_TZ)
        target = _next_friday_18(now)
        try:
            await asyncio.sleep((target - now).total_seconds())
        except asyncio.CancelledError:
            return
        try:
            from .miner import write_weekly_report
            path = write_weekly_report()
            logger.info("[eval-sched] weekly report ready: %s", path)
        except Exception:  # noqa: BLE001 - never kill the loop
            logger.exception("[eval-sched] weekly report generation failed")


async def start_weekly_report_job() -> None:
    """Idempotent; safe to call on every app start."""
    global _TASK
    if _TASK is None or _TASK.done():
        _TASK = asyncio.create_task(_loop(), name="eval-weekly-report")
        logger.info("[eval-sched] weekly report job armed (Fri 18:00 Asia/Shanghai)")


async def stop_weekly_report_job() -> None:
    global _TASK
    if _TASK is not None and not _TASK.done():
        _TASK.cancel()
        try:
            await _TASK
        except asyncio.CancelledError:
            pass
    _TASK = None
