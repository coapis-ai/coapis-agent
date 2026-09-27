# -*- coding: utf-8 -*-
"""Sampled online telemetry for the eval loop (best-effort).

Persists a lightweight ``AgentTrajectory`` row with ``run_id=NULL`` for a
random subset of production ``stream_chat`` turns so the weekly miner
(:mod:`coapis.agent_eval.miner`) can study real-world behaviour without
touching benchmark tables.

Env knobs:
    COAPIS_EVAL_ONLINE_SAMPLE    sample rate 0.0-1.0 (default 0.1)
    COAPIS_EVAL_ONLINE_DISABLE   "1" disables the hook entirely
    COAPIS_EVAL_RUNNER           when set (CLI runner), the hook stays
                                 quiet — the runner records its own rows
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random

logger = logging.getLogger(__name__)

_DEFAULT_RATE = 0.1


def _sample_rate() -> float:
    try:
        rate = float(os.environ.get("COAPIS_EVAL_ONLINE_SAMPLE", ""))
    except ValueError:
        rate = _DEFAULT_RATE
    return max(0.0, min(1.0, rate))


async def record_online_turn(*, context, final_answer: str, llm_calls: int = 1) -> None:
    """Record one sampled online turn. Must never raise (fire-and-forget)."""
    try:
        if os.environ.get("COAPIS_EVAL_ONLINE_DISABLE") == "1":
            return
        if os.environ.get("COAPIS_EVAL_RUNNER"):
            return
        if random.random() >= _sample_rate():
            return

        messages = context.get_messages() if context is not None else []
        tool_msgs = [
            m for m in messages
            if isinstance(m, dict) and m.get("role") == "tool"
        ]
        steps: list[dict] = [{"kind": "llm"} for _ in range(max(1, llm_calls))]
        steps += [
            {"kind": "tool", "ok": True, "name": str(m.get("name") or "?")}
            for m in tool_msgs
        ]

        from ..foundation.db.engine import get_session_factory
        from ..foundation.db.models import AgentTrajectory

        def _persist() -> None:
            import time

            factory = get_session_factory()
            with factory() as session:
                session.add(AgentTrajectory(
                    run_id=None,
                    steps=len(steps),
                    tool_calls=len(tool_msgs),
                    llm_calls=max(1, llm_calls),
                    input_tokens=0,
                    output_tokens=0,
                    cost_cents=0.0,
                    trace=json.dumps(steps, ensure_ascii=False),
                    final_answer=(final_answer or "")[:8000],
                    duration_ms=0,
                    created_at=time.time(),
                ))
                session.commit()

        await asyncio.to_thread(_persist)
    except Exception as exc:  # noqa: BLE001 - telemetry must not break chat
        logger.warning("[eval-hook] online turn recording failed: %s", exc)
