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

"""Plan router - Plan endpoints with real-time SSE broadcast.

Endpoints:
    GET  /plan/config   — read plan enabled state from agent config
    PUT  /plan/config   — toggle plan mode (persists to agent.json)
    GET  /plan/current  — return the active plan (live cache → session store)
    GET  /plan/stream   — SSE stream of plan_update events
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.requests import Request
from fastapi.responses import StreamingResponse

from coapis.plan.lifecycle import plan_really_done
from coapis.plan.schemas import outcome_pending as _outcome_pending

logger = logging.getLogger(__name__)

router = APIRouter(tags=["plan"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_request_context(request: Request):
    """Extract username, agent_id, and manager from the request."""
    manager = getattr(request.app.state, "multi_agent_manager", None)
    username = getattr(request.state, "username", None)
    if not username:
        user_info = getattr(request.state, "user_info", None)
        if user_info and isinstance(user_info, dict):
            username = user_info.get("username", "anonymous")
    if not username:
        username = "anonymous"
    return manager, username


def _resolve_agent_id(request: Request, username: str) -> str:
    """Resolve agent_id from query/header or fall back to user default."""
    agent_id = (
        request.query_params.get("agent_id")
        or request.headers.get("X-Agent-Id")
    )
    if not agent_id or agent_id == "default":
        agent_id = f"user:{username}"
    return agent_id


def _get_workspace(manager, agent_id: str, username: str):
    """Get workspace from the multi-agent manager."""
    if not manager:
        return None
    return manager.get_workspace(agent_id, username=username)


def _read_plan_from_agent_json(workspace) -> bool:
    """Read plan.enabled directly from agent.json on disk, bypassing any
    in-memory cache.  Falls back to workspace.config if file read fails.

    默认开（2026-11-12 D4 拍板）：未显式配置过的 agent 视为开启；
    用户通过 PUT /plan/config 显式关闭后写盘 plan.enabled=false，尊重选择。
    """
    try:
        agent_json = os.path.join(str(workspace.workspace_dir), "agent.json")
        with open(agent_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        plan_section = data.get("plan")
        if isinstance(plan_section, dict):
            return bool(plan_section.get("enabled", True))
    except Exception:
        pass
    # Fallback: use workspace.config
    try:
        cfg = workspace.config
        plan_cfg = getattr(cfg, "plan", None)
        if plan_cfg:
            return bool(getattr(plan_cfg, "enabled", True))
    except Exception:
        pass
    return True


def _normalize_plan_data(raw: dict) -> dict:
    """Normalize a plan dict into the shape expected by the frontend."""
    subtasks = []
    for st in raw.get("subtasks", []):
        if isinstance(st, dict):
            entry = {
                "name": st.get("name", ""),
                "description": st.get("description", ""),
                "expected_outcome": st.get("expected_outcome", ""),
                "outcome": st.get("outcome"),
                "state": st.get("state", "todo"),
                "created_at": st.get("created_at"),
                "finished_at": st.get("finished_at"),
            }
            # Same ruler as plan_to_response, so a snapshot persisted before
            # this field existed still reports "结果待补" truthfully.
            entry["outcome_pending"] = bool(st.get("outcome_pending")) or (
                _outcome_pending(
                    entry["expected_outcome"],
                    entry["outcome"],
                    entry["state"],
                )
            )
            subtasks.append(entry)
    return {
        "id": raw.get("id", ""),
        "name": raw.get("name", ""),
        "description": raw.get("description", ""),
        "expected_outcome": raw.get("expected_outcome", ""),
        "state": raw.get("state", "todo"),
        "subtasks": subtasks,
        "created_at": raw.get("created_at"),
        "finished_at": raw.get("finished_at"),
        # finished 的唯一尺子见 plan.lifecycle.plan_really_done：runner 只在
        # 新开计划时才清 current，不能靠「它还是不是 current」判定在跑。
        "finished": bool(raw.get("finished")) or plan_really_done(raw),
        "outcome": raw.get("outcome"),
    }


# ---------------------------------------------------------------------------
# GET /plan/config
# ---------------------------------------------------------------------------

@router.get("/plan/config")
async def get_plan_config(request: Request) -> Dict[str, Any]:
    """Get plan configuration from agent config (reads directly from disk)."""
    manager, username = _get_request_context(request)
    agent_id = _resolve_agent_id(request, username)

    if not manager:
        return {"enabled": False, "agent_id": agent_id}

    workspace = _get_workspace(manager, agent_id, username)
    if not workspace:
        return {"enabled": False, "agent_id": agent_id}

    enabled = _read_plan_from_agent_json(workspace)
    return {"enabled": enabled, "agent_id": agent_id}


# ---------------------------------------------------------------------------
# PUT /plan/config
# ---------------------------------------------------------------------------

@router.put("/plan/config")
async def update_plan_config(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Toggle plan mode and persist to agent.json + invalidate cache."""
    manager, username = _get_request_context(request)
    agent_id = _resolve_agent_id(request, username)
    new_enabled = bool(payload.get("enabled", False))

    if not manager:
        raise HTTPException(status_code=503, detail="Service unavailable")

    workspace = _get_workspace(manager, agent_id, username)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # 1. Update agent.json on disk
    agent_json = os.path.join(str(workspace.workspace_dir), "agent.json")
    try:
        if os.path.exists(agent_json):
            with open(agent_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
        if "plan" not in data:
            data["plan"] = {}
        data["plan"]["enabled"] = new_enabled
        with open(agent_json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        logger.warning("Failed to write plan config to agent.json", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to persist config")

    # 2. Invalidate the load_agent_config cache so workspace.config reloads
    try:
        from ...config.config import load_agent_config
        from ...config.utils import _agent_config_cache, _agent_config_lock
        with _agent_config_lock:
            if agent_id in _agent_config_cache:
                del _agent_config_cache[agent_id]
    except Exception:
        pass

    # 3. Update in-memory config if workspace.config is already loaded
    try:
        cfg = workspace.config
        if hasattr(cfg, "plan"):
            cfg.plan.enabled = new_enabled
    except Exception:
        pass

    return {"enabled": new_enabled, "agent_id": agent_id}


# ---------------------------------------------------------------------------
# GET /plan/current
# ---------------------------------------------------------------------------

@router.post("/plan/confirm")
async def confirm_plan(
    session_id: str = Body(...),
    plan_title: str | None = Body(default=None),
) -> Dict[str, Any]:
    """确认方案：放行该会话的待确认授权域。

    确认前，计划里涉及「出入」的动作一律回落为逐次单独审批；
    确认后在授权域内自动放行，破坏性动作仍需单独确认。
    """
    from ...plan.scope import confirm_session_scope

    scope = confirm_session_scope(session_id, plan_title=plan_title)
    if scope is None:
        raise HTTPException(
            status_code=404,
            detail="no pending plan to confirm (confirmed or expired)",
        )
    logger.info(
        "plan-confirmed: session=%s plan=%s max=%s",
        session_id,
        scope.title,
        scope.max_semantics.value,
    )
    return {
        "ok": True,
        "status": scope.status,
        "plan_title": scope.title,
        "max_semantics": scope.max_semantics.value,
        "remaining_seconds": round(scope.remaining_seconds(), 1),
    }
@router.get("/plan/current")
async def get_current_plan(
    request: Request,
    session_id: str = Query(None),
) -> Dict[str, Any]:
    """Get current plan from live cache or session store."""
    manager, username = _get_request_context(request)
    agent_id = _resolve_agent_id(request, username)

    plan_data = None
    workspace = None

    # 1. Try live broadcast cache
    try:
        from ...plan.broadcast import get_live_plan
        found, cached = get_live_plan(agent_id, session_id)
        if found and cached is not None:
            plan_data = cached
    except Exception:
        pass

    # 2. Fall back to session store
    if plan_data is None and session_id and manager:
        try:
            workspace = _get_workspace(manager, agent_id, username)
            if workspace:
                session_store = getattr(getattr(workspace, "runner", None), "session", None)
                if session_store and hasattr(session_store, "get_session_state_dict"):
                    states = await session_store.get_session_state_dict(
                        session_id=session_id,
                        user_id=username,
                        allow_not_exist=True,
                    )
                    agent_state = states.get("agent", {})
                    nb_state = agent_state.get("plan_notebook")
                    if nb_state and isinstance(nb_state, dict):
                        current_plan = nb_state.get("current_plan")
                        if current_plan and isinstance(current_plan, dict):
                            plan_data = _normalize_plan_data(current_plan)
        except Exception:
            logger.warning(
                "plan/current: session-state notebook fallback failed",
                exc_info=True,
            )

    # 3. A finished plan: ``current_plan`` is cleared by ``finish_plan``, so
    #    fall back to the snapshot the runtime persisted for this session.
    if plan_data is None and session_id and manager:
        try:
            workspace = _get_workspace(manager, agent_id, username)
            if workspace:
                plan_data = await _get_finished_plan(workspace, session_id, username)
        except Exception:
            logger.warning("Finished plan fallback lookup failed", exc_info=True)

    from ...plan.scope import peek_scope

    # 方案确认态：前端据此显示「确认执行」按钮或已确认标记
    scope = peek_scope(session_id)
    scope_view: Optional[Dict[str, Any]] = None
    if scope is not None:
        scope_view = {
            "plan_title": scope.title,
            "status": scope.status,
            "max_semantics": scope.max_semantics.value,
            "reason": scope.reason,
            "remaining_seconds": round(scope.remaining_seconds(), 1),
            "hits": scope.hits,
            "denials": scope.denials,
        }
    # Plan history needs the session store even when the live plan came from
    # the broadcast cache, so resolve the workspace once here.
    if workspace is None and session_id and manager:
        try:
            workspace = _get_workspace(manager, agent_id, username)
        except Exception:  # pragma: no cover - defensive
            workspace = None

    plans = _build_plan_history(
        plan_data,
        await _get_finished_plans(workspace, session_id, username),
    )
    return {
        "plans": plans,
        "plan": plan_data,
        "session_id": session_id,
        "scope": scope_view,
        "usage": {
            "sessions_used": 0,
            "sessions_limit": 0,
            "messages_used": 0,
            "messages_limit": 0,
        },
    }


async def _get_finished_plans(
    workspace,
    session_id: str,
    username: str,
) -> list[dict]:
    """Every persisted plan of this session, oldest first.

    2026-11-19 (计划执行能力优化) — 一个会话会跑很多次计划，此前只回最后一份，
    用户刷新后看不见"这个会话到底做过哪几件事"。新键 ``coapis_finished_plans``
    存列表；老会话只有单键 ``coapis_finished_plan``，读到时同样成列表。
    """
    if workspace is None:
        return []
    # ``Workspace`` exposes the store as ``runner.session``; keep the legacy
    # ``session`` attribute as a fallback for minimal workspace stubs.
    session_store = getattr(getattr(workspace, "runner", None), "session", None)
    if session_store is None:
        session_store = getattr(workspace, "session", None)
    if session_store is None or not hasattr(session_store, "get_session_state_dict"):
        return []
    try:
        states = await session_store.get_session_state_dict(
            session_id=session_id,
            user_id=username or "default",
            allow_not_exist=True,
        )
        agent_state = states.get("agent") or {}
        raw = agent_state.get("coapis_finished_plans")
        if not isinstance(raw, list) or not raw:
            legacy = agent_state.get("coapis_finished_plan")
            raw = [legacy] if isinstance(legacy, dict) and legacy else []
        plans = []
        for item in raw:
            if not isinstance(item, dict) or not item:
                continue
            entry = _normalize_plan_data(dict(item))
            entry["finished"] = True
            plans.append(entry)
        return plans
    except Exception:
        logger.debug(
            "Failed to read persisted plan history for session=%s",
            session_id,
            exc_info=True,
        )
        return []


async def _get_finished_plan(
    workspace,
    session_id: str,
    username: str,
) -> dict | None:
    """Read the newest persisted snapshot (kept for older callers)."""
    plans = await _get_finished_plans(workspace, session_id, username)
    if not plans:
        return None
    return plans[-1]


def _build_plan_history(
    current: Optional[dict],
    finished: list[dict],
) -> list[dict]:
    """One ordered view of everything this session has planned.

    Chronological, oldest first, de-duplicated by plan id; the live plan is
    flagged ``finished=False`` so the UI can pin it on top while still being
    able to show everything underneath.
    """
    history: list[dict] = []
    seen: set = set()
    for item in finished:
        key = item.get("id") or item.get("name")
        if key in seen:
            continue
        seen.add(key)
        history.append(item)
    if current:
        key = current.get("id") or current.get("name")
        # 同一把尺子：每一步都勾掉的计划，不再因为「还是当前那份」而被抹成
        # unfinished——否则卡片永远显示「进行中」且一直轮询（1e9c20b7 实测）。
        really_done = bool(current.get("finished")) or plan_really_done(current)
        if key in seen:
            for idx, item in enumerate(history):
                if (item.get("id") or item.get("name")) == key:
                    entry = dict(current)
                    entry["finished"] = really_done
                    history[idx] = entry
                    break
        else:
            entry = dict(current)
            entry["finished"] = really_done
            history.append(entry)
    return history


# ---------------------------------------------------------------------------
# GET /plan/stream (SSE)
# ---------------------------------------------------------------------------

@router.get("/plan/stream")
async def stream_plan_updates(request: Request):
    """Stream plan updates via SSE with heartbeat keep-alive."""
    manager, username = _get_request_context(request)
    agent_id = _resolve_agent_id(request, username)

    from ...plan.broadcast import register_sse_client, unregister_sse_client

    queue = register_sse_client(agent_id)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    data = json.dumps(event, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unregister_sse_client(agent_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
