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

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from .models import CronJobSpec

logger = logging.getLogger(__name__)


class CronExecutor:
    def __init__(self, *, runner: Any, channel_manager: Any, owner_user_id: Optional[str] = None):
        self._runner = runner
        self._channel_manager = channel_manager
        self._owner_user_id = owner_user_id

    async def execute(self, job: CronJobSpec) -> None:
        """Execute one job once.

        - task_type text: send fixed text to channel
        - task_type agent: ask agent with prompt, send reply to channel (
            stream_query + send_event)
        """
        # ── Input Guard: 内容安全检测 ──
        from coapis.security.input_guard import get_input_guard_engine
        _guard = get_input_guard_engine()
        check_texts = []
        if job.text:
            check_texts.append(("text", job.text))
        if job.request and hasattr(job.request, "input") and job.request.input:
            for msg in job.request.input:
                if isinstance(msg, dict) and msg.get("content"):
                    check_texts.append(("prompt", msg["content"]))
        for label, text in check_texts:
            guard_result = _guard.check(text)
            if not guard_result.is_safe:
                logger.warning(
                    "Input guard blocked cron job=%s (%s): %s",
                    job.id, label, [f.rule_id for f in guard_result.findings],
                )
                return

        target_user_id = job.dispatch.target.user_id
        target_session_id = job.dispatch.target.session_id

        # Security: enforce owner_user_id at execution time
        if self._owner_user_id and target_user_id and target_user_id != self._owner_user_id:
            logger.error(
                "Cron execute ABORTED: job_id=%s target_user_id=%s "
                "does not match owner=%s",
                job.id, target_user_id, self._owner_user_id,
            )
            return
        dispatch_meta: Dict[str, Any] = dict(job.dispatch.meta or {})
        logger.info(
            "cron execute: job_id=%s channel=%s task_type=%s "
            "target_user_id=%s target_session_id=%s",
            job.id,
            job.dispatch.channel,
            job.task_type,
            target_user_id[:40] if target_user_id else "",
            target_session_id[:40] if target_session_id else "",
        )

        if job.task_type == "text" and job.text:
            logger.info(
                "cron send_text: job_id=%s channel=%s len=%s",
                job.id,
                job.dispatch.channel,
                len(job.text or ""),
            )
            if self._channel_manager is not None:
                await self._channel_manager.send_text(
                    channel=job.dispatch.channel,
                    user_id=target_user_id,
                    session_id=target_session_id,
                    text=job.text.strip(),
                    meta=dispatch_meta,
                )
            else:
                logger.debug(
                    "cron send_text (no channel_manager): job_id=%s",
                    job.id,
                )
            return

        # agent: run request as the dispatch target user so context matches
        logger.info(
            "cron agent: job_id=%s channel=%s stream_query then send_event",
            job.id,
            job.dispatch.channel,
        )
        assert job.request is not None
        req: Dict[str, Any] = job.request.model_dump(mode="json")
        req["user_id"] = target_user_id or "cron"

        # Always use an isolated session_id per cron execution to prevent
        # cron context from polluting the user's main chat history.
        # Format: cron:{job_id}:{timestamp} — unique per run.
        import time
        cron_session_id = f"cron:{job.id}:{int(time.time())}"
        req["session_id"] = cron_session_id
        logger.info(
            "cron isolated session: job_id=%s session_id=%s",
            job.id, cron_session_id,
        )

        async def _run() -> None:
            collected_text = ""
            async for event in self._runner.stream_query(req):
                # Collect response text from stream events
                if isinstance(event, dict):
                    etype = event.get("type", "")
                    if etype == "text_delta":
                        collected_text += event.get("delta", "")
                    elif etype == "message" and event.get("content"):
                        collected_text += event.get("content", "")

            # Save cron response to session state (aligned with CoApis pattern)
            if collected_text.strip():
                try:
                    manager = getattr(self._runner, "_manager", None)
                    if manager:
                        user_cm = manager.get_user_chat_manager(target_user_id)
                        if user_cm:
                            chat = await user_cm.get_or_create_chat(
                                session_id=cron_session_id,
                                user_id=target_user_id,
                                channel=job.dispatch.channel,
                                name=f"定时: {job.name[:20]}",
                                agent_id=job.id,
                            )
                            # Persist to session state
                            session_obj = self._runner.session
                            if session_obj:
                                state = await session_obj.get_session_state_dict(
                                    cron_session_id, target_user_id,
                                    allow_not_exist=True,
                                )
                                memory_state = (state or {}).get("agent", {}).get("memory", {})
                                from agentscope.memory import InMemoryMemory
                                mem = InMemoryMemory()
                                mem.load_state_dict(memory_state, strict=False)
                                from agentscope.message import Msg, TextBlock
                                await mem.add(Msg(name="assistant", content=[TextBlock(text=collected_text.strip())], role="assistant"))
                                await session_obj.update_session_state(
                                    session_id=cron_session_id,
                                    key="agent.memory",
                                    value=mem.state_dict(),
                                    user_id=target_user_id,
                                )
                                logger.info(
                                    "cron response saved to session: job_id=%s chat=%s len=%d",
                                    job.id, chat.id, len(collected_text),
                                )
                except Exception as save_err:
                    logger.warning(f"Failed to save cron response: {save_err}")
            else:
                logger.warning(f"cron execute: job_id={job.id} collected empty response")

        try:
            await asyncio.wait_for(
                _run(),
                timeout=job.runtime.timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "cron execute: job_id=%s timed out after %ss",
                job.id,
                job.runtime.timeout_seconds,
            )
            raise
        except asyncio.CancelledError:
            logger.info("cron execute: job_id=%s cancelled", job.id)
            raise
        except Exception as e:
            logger.error("cron execute: job_id=%s failed: %s", job.id, e)
            raise
