"""SSE plan broadcasting and live plan cache."""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
import time

from coapis.plan.lifecycle import PLAN_META_SAVED_AT
from typing import Any

logger = logging.getLogger(__name__)

# Per-agent SSE clients
_sse_clients: dict[str, set[asyncio.Queue]] = {}

# agent_id -> {session_key -> plan_data} live cache, bounded per agent.
# ``session_key`` may be the channel session id (e.g. ``console:admin``)
# *and* the chat UUID: both are registered for the same plan so the UI can
# query with whichever id it actually holds (see ``broadcast_plan_update``).
_plan_live_cache: dict[str, OrderedDict[str, dict[str, Any] | None]] = {}
_MAX_LIVE_SESSIONS = 64


def register_sse_client(agent_id: str) -> asyncio.Queue:
    """Register an SSE client for an agent and return its queue."""
    q: asyncio.Queue = asyncio.Queue()
    _sse_clients.setdefault(agent_id, set()).add(q)
    return q


def unregister_sse_client(agent_id: str, q: asyncio.Queue) -> None:
    """Unregister an SSE client queue."""
    clients = _sse_clients.get(agent_id)
    if clients:
        clients.discard(q)
        if not clients:
            _sse_clients.pop(agent_id, None)


def _cache_put(
    agent_id: str,
    key: str,
    plan_data: dict[str, Any] | None,
) -> None:
    """Write one session key into the bounded per-agent live cache."""
    sessions = _plan_live_cache.setdefault(agent_id, OrderedDict())
    sessions[key] = plan_data
    sessions.move_to_end(key)
    while len(sessions) > _MAX_LIVE_SESSIONS:
        sessions.popitem(last=False)


def broadcast_plan_update(
    agent_id: str,
    payload: dict[str, Any],
    session_id: str | None = None,
    session_ids: list[str] | None = None,
) -> None:
    """Broadcast a plan update to all SSE clients of an agent.

    ``session_id`` keeps the historical single-key behaviour; ``session_ids``
    registers extra aliases — typically the channel session id **and** the
    chat UUID — so a UI that queries ``/plan/current`` with the chat UUID
    finds the plan the runtime cached under the channel session id.

    The payload forwarded to SSE clients carries ``session_ids`` so the
    subscriber can match on whichever id it knows.
    """
    # 每次广播都重新盖落盘时刻：读取侧据此判断"这还是不是当前那一轮的计划"，
    # 避免一小时前的计划在新一轮里继续顶着"当前计划"显示。
    if payload.get("type") == "plan_update":
        payload = {**payload, PLAN_META_SAVED_AT: time.time()}

    out = payload
    if payload.get("type") == "plan_update":
        plan_data = payload.get("plan")

        keys: list[str] = []
        for candidate in [session_id, *(session_ids or [])]:
            if candidate and candidate not in keys:
                keys.append(candidate)

        # Merge aliases already recorded for any of these keys so a plan that
        # was first cached under one id keeps matching the other id.
        known: list[str] = list(keys)
        if plan_data is not None:
            for key in keys:
                prev = _plan_live_cache.get(agent_id, {}).get(key)
                if isinstance(prev, dict):
                    for alias in prev.get("session_ids") or []:
                        if alias not in known:
                            known.append(alias)
            plan_data = dict(plan_data)
            plan_data["session_ids"] = known
            out = dict(payload)
            out["plan"] = plan_data

        out = dict(out)
        out["session_id"] = session_id or (keys[0] if keys else None)
        out["session_ids"] = known

        for key in keys:
            _cache_put(agent_id, key, plan_data)

        logger.info(
            "plan_update broadcast: agent=%s keys=%s plan=%s state=%s "
            "subtasks=%s",
            agent_id,
            keys,
            (plan_data or {}).get("name") if plan_data else None,
            (plan_data or {}).get("state") if plan_data else None,
            len((plan_data or {}).get("subtasks") or []) if plan_data else 0,
        )

    clients = _sse_clients.get(agent_id)
    if not clients:
        return

    enriched = _enrich_with_usage(agent_id, out)
    dead: list[asyncio.Queue] = []
    for q in clients:
        try:
            q.put_nowait(enriched)
        except asyncio.QueueFull:
            dead.append(q)

    for q in dead:
        clients.discard(q)


def get_live_plan(
    agent_id: str,
    session_id: str | None = None,
) -> tuple[bool, dict | None]:
    """Return ``(found, plan_data)`` from the live cache.

    ``plan_data`` may be ``None`` when no plan exists for that session.
    Matches either on the cache key itself or on any alias recorded in the
    cached payload, so a query by chat UUID hits a plan cached under the
    channel session id (and vice versa).
    """
    sessions = _plan_live_cache.get(agent_id)
    if not sessions:
        return False, None
    if session_id:
        cached = sessions.get(session_id)
        if cached is not None:
            return True, cached
        for cached in sessions.values():
            if isinstance(cached, dict) and session_id in (
                cached.get("session_ids") or []
            ):
                return True, cached
        return False, None
    # No specific session: most recent non-empty plan.
    for cached in reversed(list(sessions.values())):
        if cached is not None:
            return True, cached
    return False, None


def get_cached_session_keys(agent_id: str) -> list[str]:
    """Return the session keys currently held for ``agent_id`` (debug aid)."""
    return list(_plan_live_cache.get(agent_id, {}).keys())


def _enrich_with_usage(
    agent_id: str,
    payload: dict,
) -> dict:
    """Attach LLM usage metrics to a plan_update payload."""
    if payload.get("type") != "plan_update":
        return payload
    try:
        from ..tokens.usage import get_llm_metrics

        metrics = get_llm_metrics()
        enriched = dict(payload)
        enriched["usage"] = {
            "total_inference_time_ms": round(
                metrics["total_inference_time"] * 1000, 1
            ),
            "last_inference_time_ms": round(
                metrics["last_inference_time"] * 1000, 1
            ),
            "total_prompt_tokens": metrics["total_prompt_tokens"],
            "total_completion_tokens": metrics["total_completion_tokens"],
            "model_name": metrics["model_name"],
        }
        return enriched
    except Exception:
        return payload
