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

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from agentscope_runtime.engine.schemas.exception import ConfigurationException

from ...config import get_heartbeat_config, get_dream_cron

from ..console_push_store import append as push_store_append
from .executor import CronExecutor
from .heartbeat import (
    is_cron_expression,
    parse_heartbeat_cron,
    parse_heartbeat_every,
    run_heartbeat_once,
)
from .models import CronExecutionRecord, CronJobSpec, CronJobState
from .repo.base import BaseJobRepository

HEARTBEAT_JOB_ID = "_heartbeat"
DREAM_JOB_ID = "_dream"
CLEANUP_JOB_ID = "_cleanup"

logger = logging.getLogger(__name__)


@dataclass
class _Runtime:
    sem: asyncio.Semaphore


class CronManager:
    def __init__(
        self,
        *,
        repo: BaseJobRepository,
        runner: Any,
        channel_manager: Any,
        timezone: str = "UTC",  # pylint: disable=redefined-outer-name
        agent_id: Optional[str] = None,
        owner_user_id: Optional[str] = None,
    ):
        self._repo = repo
        self._runner = runner
        self._channel_manager = channel_manager
        self._agent_id = agent_id
        self._owner_user_id = owner_user_id
        self._scheduler = AsyncIOScheduler(timezone=timezone)
        self._executor = CronExecutor(
            runner=runner,
            channel_manager=channel_manager,
            owner_user_id=owner_user_id,
        )

        self._lock = asyncio.Lock()
        self._states: Dict[str, CronJobState] = {}
        self._rt: Dict[str, _Runtime] = {}
        self._started = False
        # Per-job execution history (bounded deque, max 50 per job)
        self._history: Dict[str, deque] = {}
        self._history_max = 50

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            jobs_file = await self._repo.load()

            self._scheduler.start()
            for job in jobs_file.jobs:
                try:
                    await self._register_or_update(job)
                except Exception as e:  # pylint: disable=broad-except
                    logger.warning(
                        "Skipping invalid cron job during startup: "
                        "job_id=%s name=%s cron=%s error=%s",
                        job.id,
                        job.name,
                        job.schedule.cron,
                        repr(e),
                    )
                    if job.enabled:
                        disabled_job = job.model_copy(
                            update={"enabled": False},
                        )
                        await self._repo.upsert_job(disabled_job)
                        logger.warning(
                            "Auto-disabled invalid cron job: "
                            "job_id=%s name=%s",
                            job.id,
                            job.name,
                        )

            # Heartbeat: scheduled job when enabled in config
            hb = get_heartbeat_config(self._agent_id)
            if getattr(hb, "enabled", False):
                trigger = self._build_heartbeat_trigger(hb.every)
                self._scheduler.add_job(
                    self._heartbeat_callback,
                    trigger=trigger,
                    id=HEARTBEAT_JOB_ID,
                    replace_existing=True,
                )
                logger.info(
                    "Heartbeat job scheduled for agent %s: every=%s",
                    self._agent_id,
                    hb.every,
                )

            # Dream-based memory optimization: cron job from config
            dream_cron = get_dream_cron(self._agent_id)
            if dream_cron:
                try:
                    trigger = CronTrigger.from_crontab(
                        dream_cron,
                        timezone=self._scheduler.timezone,
                    )
                    self._scheduler.add_job(
                        self._dream_callback,
                        trigger=trigger,
                        id=DREAM_JOB_ID,
                        replace_existing=True,
                    )
                    logger.info(
                        f"Dream-based memory optimization job scheduled for "
                        f"agent {self._agent_id}: cron={dream_cron}",
                    )
                except Exception as e:  # pylint: disable=broad-except
                    logger.error(
                        f"Failed to schedule dream-based memory optimization"
                        f"for  agent {self._agent_id}: error={repr(e)}",
                    )

            # Scheduled data cleanup: runs daily at 2:00 AM (system-level only)
            if self._agent_id and "default" in self._agent_id.lower():
                try:
                    cleanup_cron = "0 2 * * *"  # 2:00 AM daily
                    trigger = CronTrigger.from_crontab(
                        cleanup_cron,
                        timezone=self._scheduler.timezone,
                    )
                    self._scheduler.add_job(
                        self._cleanup_callback,
                        trigger=trigger,
                        id=CLEANUP_JOB_ID,
                        replace_existing=True,
                    )
                    logger.info(
                        "Scheduled data cleanup job: agent=%s cron=%s",
                        self._agent_id,
                        cleanup_cron,
                    )
                except Exception as e:  # pylint: disable=broad-except
                    logger.error(
                        "Failed to schedule cleanup job for agent %s: %s",
                        self._agent_id,
                        repr(e),
                    )

            self._started = True

    async def stop(self) -> None:
        async with self._lock:
            if not self._started:
                return
            self._scheduler.shutdown(wait=False)
            self._started = False

    # ----- read/state -----

    async def list_jobs(self) -> list[CronJobSpec]:
        return await self._repo.list_jobs()

    async def get_job(self, job_id: str) -> Optional[CronJobSpec]:
        return await self._repo.get_job(job_id)

    def get_state(self, job_id: str) -> CronJobState:
        return self._states.get(job_id, CronJobState())

    # ----- write/control -----

    async def create_or_replace_job(self, spec: CronJobSpec) -> None:
        async with self._lock:
            await self._repo.upsert_job(spec)
            if self._started:
                await self._register_or_update(spec)

    async def delete_job(self, job_id: str) -> bool:
        async with self._lock:
            if self._started and self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
            self._states.pop(job_id, None)
            self._rt.pop(job_id, None)
            return await self._repo.delete_job(job_id)

    async def pause_job(self, job_id: str) -> None:
        async with self._lock:
            self._scheduler.pause_job(job_id)

    async def resume_job(self, job_id: str) -> None:
        async with self._lock:
            self._scheduler.resume_job(job_id)

    async def reschedule_heartbeat(self) -> None:
        """Reload heartbeat config and update or remove the heartbeat job.

        Note: CronManager should always be started during workspace
        initialization, so this method assumes self._started is True.
        """
        async with self._lock:
            if not self._started:
                logger.warning(
                    f"CronManager not started for agent {self._agent_id}, "
                    f"cannot reschedule heartbeat. This should not happen.",
                )
                return

            hb = get_heartbeat_config(self._agent_id)

            # Remove existing heartbeat job if present
            if self._scheduler.get_job(HEARTBEAT_JOB_ID):
                self._scheduler.remove_job(HEARTBEAT_JOB_ID)

            # Add heartbeat job if enabled
            if getattr(hb, "enabled", False):
                trigger = self._build_heartbeat_trigger(hb.every)
                self._scheduler.add_job(
                    self._heartbeat_callback,
                    trigger=trigger,
                    id=HEARTBEAT_JOB_ID,
                    replace_existing=True,
                )
                logger.info(
                    "heartbeat rescheduled: every=%s",
                    hb.every,
                )
            else:
                logger.info("heartbeat disabled, job removed")

    async def reschedule_dream(self) -> None:
        """Reschedule the dream-based memory optimization job based on
        configuration.

        Note: CronManager should always be started during workspace
        initialization, so this method assumes self._started is True.
        """
        async with self._lock:
            if not self._started:
                logger.warning(
                    f"CronManager not started for agent {self._agent_id}, "
                    "cannot reschedule dream-based memory optimization."
                    "This should not happen.",
                )
                return

            # Check if dream-based memory optimization is enabled in config
            dream_cron = get_dream_cron(self._agent_id)

            # Remove existing job if any
            if self._scheduler.get_job(DREAM_JOB_ID):
                self._scheduler.remove_job(DREAM_JOB_ID)
                logger.info(
                    "Dream-based memory optimization job removed for "
                    f"agent {self._agent_id}",
                )

            # Add new job if cron expression is valid
            if dream_cron:
                try:
                    trigger = CronTrigger.from_crontab(
                        dream_cron,
                        timezone=self._scheduler.timezone,
                    )
                    self._scheduler.add_job(
                        self._dream_callback,
                        trigger=trigger,
                        id=DREAM_JOB_ID,
                        replace_existing=True,
                    )
                    logger.info(
                        "Dream-based memory optimization job rescheduled"
                        f"for agent {self._agent_id}: cron={dream_cron}",
                    )
                except Exception as e:  # pylint: disable=broad-except
                    logger.error(
                        "Failed to reschedule dream-based memory  "
                        f"optimization for agent {self._agent_id}: "
                        f"error={repr(e)}",
                    )
            else:
                logger.info(
                    "dream-based memory optimization disabled, job removed",
                )

    async def run_job(self, job_id: str) -> None:
        """Trigger a job to run in the background (fire-and-forget).

        Raises KeyError if the job does not exist.
        The actual execution happens asynchronously; errors are logged
        and reflected in the job state but NOT propagated to the caller.
        """
        job = await self._repo.get_job(job_id)
        if not job:
            raise KeyError(f"Job not found: {job_id}")
        logger.info(
            "cron run_job (async): job_id=%s channel=%s task_type=%s "
            "target_user_id=%s target_session_id=%s",
            job_id,
            job.dispatch.channel,
            job.task_type,
            (job.dispatch.target.user_id or "")[:40],
            (job.dispatch.target.session_id or "")[:40],
        )
        task = asyncio.create_task(
            self._execute_once(job, trigger_type="manual"),
            name=f"cron-run-{job_id}",
        )
        task.add_done_callback(lambda t: self._task_done_cb(t, job))

    async def run_job_once(self, job_id: str) -> dict:
        """Trigger immediate execution and return result.

        Used by the /run API endpoint for immediate (non-scheduled) execution.
        Returns a dict with execution status.
        """
        job = await self._repo.get_job(job_id)
        if not job:
            raise KeyError(f"Job not found: {job_id}")
        logger.info(
            "cron run_job_once (immediate): job_id=%s channel=%s task_type=%s",
            job_id,
            job.dispatch.channel,
            job.task_type,
        )
        try:
            await self._execute_once(job, trigger_type="manual")
            return {"status": "success", "job_id": job_id, "message": "Job executed successfully"}
        except Exception as e:
            logger.warning("cron run_job_once failed: job_id=%s error=%s", job_id, repr(e))
            return {"status": "error", "job_id": job_id, "error": repr(e)}

    # ----- callbacks -----

    def _task_done_cb(self, task: asyncio.Task, job: CronJobSpec) -> None:
        """Suppress and log exceptions from fire-and-forget tasks.

        On failure, push an error message to the console push store so
        the frontend can display it.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "cron background task %s failed: %s",
                task.get_name(),
                repr(exc),
            )
            # Push error to isolated cron session (not main chat)
            target_session_id = job.dispatch.target.session_id
            if target_session_id:
                import time
                cron_session_id = f"cron:{job.id}:{int(time.time())}"
                error_text = f"❌ Cron job [{job.name}] failed: {exc}"
                asyncio.ensure_future(
                    push_store_append(cron_session_id, error_text),
                )

    # ----- internal -----

    async def _register_or_update(self, spec: CronJobSpec) -> None:
        # Enforce owner_user_id: all jobs must target the owning user
        if (
            self._owner_user_id
            and spec.dispatch
            and spec.dispatch.target
            and spec.dispatch.target.user_id
            and spec.dispatch.target.user_id != self._owner_user_id
        ):
            logger.warning(
                "Cron job user_id mismatch: job_id=%s name=%s "
                "expected_owner=%s got=%s, auto-correcting",
                spec.id,
                spec.name,
                self._owner_user_id,
                spec.dispatch.target.user_id,
            )
            spec.dispatch.target.user_id = self._owner_user_id

        # Validate and build trigger first. If cron is invalid, fail fast
        # without mutating scheduler/runtime state.
        assert spec.id is not None, "Job must have an id"
        trigger = self._build_trigger(spec)

        # per-job concurrency semaphore
        self._rt[spec.id] = _Runtime(
            sem=asyncio.Semaphore(spec.runtime.max_concurrency),
        )

        # replace existing
        if self._scheduler.get_job(spec.id):
            self._scheduler.remove_job(spec.id)

        self._scheduler.add_job(
            self._scheduled_callback,
            trigger=trigger,
            id=spec.id,
            args=[spec.id],
            misfire_grace_time=spec.runtime.misfire_grace_seconds,
            replace_existing=True,
        )

        if not spec.enabled:
            self._scheduler.pause_job(spec.id)

        # update next_run
        aps_job = self._scheduler.get_job(spec.id)
        st = self._states.get(spec.id, CronJobState())
        st.next_run_at = aps_job.next_run_time if aps_job else None
        self._states[spec.id] = st

    def _build_trigger(self, spec: CronJobSpec) -> CronTrigger:
        # enforce 5 fields (no seconds)
        parts = [p for p in spec.schedule.cron.split() if p]
        if len(parts) != 5:
            raise ConfigurationException(
                message=(
                    f"cron must have 5 fields, "
                    f"got {len(parts)}: {spec.schedule.cron}"
                ),
            )

        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=spec.schedule.timezone,
        )

    def _build_heartbeat_trigger(
        self,
        every: str,
    ) -> Union[CronTrigger, IntervalTrigger]:
        """Build a trigger from the heartbeat *every* value.

        Returns CronTrigger for cron expressions,
        IntervalTrigger for interval strings.
        """
        if is_cron_expression(every):
            minute, hour, day, month, day_of_week = parse_heartbeat_cron(every)
            return CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
            )
        interval_seconds = parse_heartbeat_every(every)
        return IntervalTrigger(seconds=interval_seconds)

    async def _scheduled_callback(self, job_id: str) -> None:
        job = await self._repo.get_job(job_id)
        if not job:
            return

        await self._execute_once(job)

        # refresh next_run
        aps_job = self._scheduler.get_job(job_id)
        st = self._states.get(job_id, CronJobState())
        st.next_run_at = aps_job.next_run_time if aps_job else None
        self._states[job_id] = st

    async def _heartbeat_callback(self) -> None:
        """Run one heartbeat (HEARTBEAT.md as query, optional dispatch)."""
        try:
            # Get workspace_dir from runner if available
            workspace_dir = None
            if hasattr(self._runner, "workspace_dir"):
                workspace_dir = self._runner.workspace_dir

            await run_heartbeat_once(
                runner=self._runner,
                channel_manager=self._channel_manager,
                agent_id=self._agent_id,
                workspace_dir=workspace_dir,
            )
        except asyncio.CancelledError:
            logger.info("heartbeat cancelled")
            raise
        except Exception:  # pylint: disable=broad-except
            logger.exception("heartbeat run failed")

    async def _dream_callback(self) -> None:
        """Run one dream-based memory optimization task."""
        try:
            # Run dream task
            await self._runner.memory_manager.dream()
            logger.debug("Dream task executed successfully")
        except asyncio.CancelledError:
            logger.info("Dream task was cancelled")
            raise
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Failed to execute dream task: {e}", exc_info=True)

    async def _cleanup_callback(self) -> None:
        """Run scheduled data cleanup — hot→warm→cold lifecycle for all users."""
        try:
            from ..cleanup import CleanupEngine
            from ...constant import WORKSPACES_DIR

            workspaces_root = WORKSPACES_DIR

            total_archived = 0
            total_deleted = 0

            if workspaces_root.exists():
                for user_dir in sorted(workspaces_root.iterdir()):
                    if not user_dir.is_dir():
                        continue
                    try:
                        engine = CleanupEngine(workspace_dir=user_dir)
                        results = engine.run_full_cleanup(user_id=user_dir.name)
                        for stat in results:
                            total_archived += stat.items_archived
                            total_deleted += stat.items_deleted
                    except Exception as e:  # pylint: disable=broad-except
                        logger.warning(
                            "Cleanup failed for user %s: %s",
                            user_dir.name,
                            repr(e),
                        )

            logger.info(
                "Scheduled cleanup completed: users_archived=%d users_deleted=%d",
                total_archived,
                total_deleted,
            )

            # --- Heartbeat session cleanup ---
            # Keep only the most recent 10 heartbeat sessions per agent,
            # and delete any older than 7 days.
            self._cleanup_heartbeat_sessions(data_root)

        except asyncio.CancelledError:
            logger.info("Cleanup task was cancelled")
            raise
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Scheduled cleanup failed: {e}", exc_info=True)

    def _cleanup_heartbeat_sessions(self, data_root: Path) -> None:
        """Clean up old heartbeat session files from tmp/heartbeat/.

        v0.5.2: Heartbeat sessions are now stored under tmp/heartbeat/{agent_id}/
        (or workspaces/{user}/chat/ for user-scoped heartbeats, which are
        cleaned by ChatManager). This method only cleans the tmp/ fallback path.

        Strategy:
        - Scan tmp/heartbeat/{agent_id}/ directories
        - Sort by timestamp (extracted from filename)
        - Keep the 10 most recent files per agent
        - Delete files older than 7 days
        """
        import time

        KEEP_RECENT = 10
        MAX_AGE_DAYS = 7
        max_age_ts = time.time() - (MAX_AGE_DAYS * 86400)

        tmp_heartbeat_dir = data_root / "tmp" / "heartbeat"
        if not tmp_heartbeat_dir.exists():
            return

        total_deleted = 0
        for agent_dir in tmp_heartbeat_dir.iterdir():
            if not agent_dir.is_dir():
                continue

            hb_files = list(agent_dir.glob("*_heartbeat--*.json"))
            if not hb_files:
                continue

            def _extract_ts(path: Path) -> float:
                name = path.stem
                try:
                    return float(name.rsplit("--", 1)[-1])
                except (ValueError, IndexError):
                    return path.stat().st_mtime

            hb_files.sort(key=_extract_ts, reverse=True)

            deleted = 0
            for i, f in enumerate(hb_files):
                ts = _extract_ts(f)
                if i < KEEP_RECENT:
                    continue
                if ts < max_age_ts:
                    try:
                        f.unlink()
                        deleted += 1
                    except OSError as e:
                        logger.warning("Failed to delete heartbeat session %s: %s", f, e)

            if deleted > 0:
                logger.info(
                    "Cleaned %d heartbeat sessions in %s",
                    deleted,
                    agent_dir,
                )
                total_deleted += deleted

        # Remove empty agent directories
        for agent_dir in tmp_heartbeat_dir.iterdir():
            if agent_dir.is_dir() and not any(agent_dir.iterdir()):
                agent_dir.rmdir()

        if total_deleted > 0:
            logger.info("Total heartbeat sessions cleaned: %d", total_deleted)

    # ----- execution history -----

    def _record_execution(
        self,
        job_id: str,
        status: str,
        duration_seconds: float,
        error: Optional[str] = None,
        trigger_type: str = "cron",
        task_type: str = "agent",
        dispatch_channel: Optional[str] = None,
    ) -> None:
        """Record one execution into the bounded per-job history deque."""
        record = CronExecutionRecord(
            job_id=job_id,
            run_at=datetime.now(timezone.utc),
            status=status,
            duration_seconds=round(duration_seconds, 3),
            error=error,
            trigger_type=trigger_type,
            task_type=task_type,
            dispatch_channel=dispatch_channel,
        )
        dq = self._history.get(job_id)
        if dq is None:
            dq = deque(maxlen=self._history_max)
            self._history[job_id] = dq
        dq.append(record)

    def get_history(
        self,
        job_id: str,
        limit: int = 20,
    ) -> List[CronExecutionRecord]:
        """Return the most recent execution records for a job."""
        dq = self._history.get(job_id)
        if not dq:
            return []
        items = list(dq)
        return items[-limit:]

    # ----- internal -----

    async def _execute_once(
        self,
        job: CronJobSpec,
        trigger_type: str = "cron",
    ) -> None:
        assert job.id is not None, "Job must have an id"
        rt = self._rt.get(job.id)
        if not rt:
            rt = _Runtime(sem=asyncio.Semaphore(job.runtime.max_concurrency))
            self._rt[job.id] = rt

        async with rt.sem:
            st = self._states.get(job.id, CronJobState())
            st.last_status = "running"
            self._states[job.id] = st
            _t0 = time.monotonic()

            try:
                await self._executor.execute(job)
                _elapsed = time.monotonic() - _t0
                st.last_status = "success"
                st.last_error = None
                self._record_execution(
                    job.id,
                    "success",
                    _elapsed,
                    trigger_type=trigger_type,
                    task_type=job.task_type,
                    dispatch_channel=job.dispatch.channel,
                )
                logger.info(
                    "cron _execute_once: job_id=%s status=success duration=%.2fs",
                    job.id,
                    _elapsed,
                )
            except asyncio.CancelledError:
                _elapsed = time.monotonic() - _t0
                st.last_status = "cancelled"
                st.last_error = "Job was cancelled"
                self._record_execution(
                    job.id,
                    "cancelled",
                    _elapsed,
                    error="Job was cancelled",
                    trigger_type=trigger_type,
                    task_type=job.task_type,
                    dispatch_channel=job.dispatch.channel,
                )
                logger.info(
                    "cron _execute_once: job_id=%s status=cancelled",
                    job.id,
                )
                raise
            except Exception as e:  # pylint: disable=broad-except
                _elapsed = time.monotonic() - _t0
                st.last_status = "error"
                st.last_error = repr(e)
                self._record_execution(
                    job.id,
                    "error",
                    _elapsed,
                    error=repr(e),
                    trigger_type=trigger_type,
                    task_type=job.task_type,
                    dispatch_channel=job.dispatch.channel,
                )
                logger.warning(
                    "cron _execute_once: job_id=%s status=error error=%s",
                    job.id,
                    repr(e),
                )
                raise
            finally:
                st.last_run_at = datetime.now(timezone.utc)
                self._states[job.id] = st
