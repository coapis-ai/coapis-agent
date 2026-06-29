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
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.requests import Request
from fastapi.responses import StreamingResponse

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
    in-memory cache.  Falls back to workspace.config if file read fails."""
    try:
        agent_json = os.path.join(str(workspace.workspace_dir), "agent.json")
        with open(agent_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        plan_section = data.get("plan")
        if isinstance(plan_section, dict):
            return bool(plan_section.get("enabled", False))
    except Exception:
        pass
    # Fallback: use workspace.config
    try:
        cfg = workspace.config
        plan_cfg = getattr(cfg, "plan", None)
        if plan_cfg:
            return bool(getattr(plan_cfg, "enabled", False))
    except Exception:
        pass
    return False


def _normalize_plan_data(raw: dict) -> dict:
    """Normalize a plan dict into the shape expected by the frontend."""
    subtasks = []
    for st in raw.get("subtasks", []):
        if isinstance(st, dict):
            subtasks.append({
                "name": st.get("name", ""),
                "description": st.get("description", ""),
                "expected_outcome": st.get("expected_outcome", ""),
                "outcome": st.get("outcome"),
                "state": st.get("state", "todo"),
                "created_at": st.get("created_at"),
                "finished_at": st.get("finished_at"),
            })
    return {
        "id": raw.get("id", ""),
        "name": raw.get("name", ""),
        "description": raw.get("description", ""),
        "expected_outcome": raw.get("expected_outcome", ""),
        "state": raw.get("state", "todo"),
        "subtasks": subtasks,
        "created_at": raw.get("created_at"),
        "finished_at": raw.get("finished_at"),
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

@router.get("/plan/current")
async def get_current_plan(
    request: Request,
    session_id: str = Query(None),
) -> Dict[str, Any]:
    """Get current plan from live cache or session store."""
    manager, username = _get_request_context(request)
    agent_id = _resolve_agent_id(request, username)

    plan_data = None

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
                session_store = getattr(workspace, "session", None)
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
            pass

    return {
        "plan": plan_data,
        "session_id": session_id,
        "usage": {
            "sessions_used": 0,
            "sessions_limit": 0,
            "messages_used": 0,
            "messages_limit": 0,
        },
    }


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
