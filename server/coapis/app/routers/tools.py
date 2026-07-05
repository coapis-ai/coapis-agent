# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
"""Tools router — per-user dynamic registry-based tool management.

All tools come from the live registry (coapis.agents.tools.registry).
State (enabled/disabled, async_execution) is per-user: stored in
{workspace}/tool_state.json.
Audit log is per-user: stored in {workspace}/tool_audit.json.
"""
from __future__ import annotations
import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from ..permissions.decorators import require_permission

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tools"])

# ── Models ─────────────────────────────────────────────────────────────────

class ToolInfo(BaseModel):
    name: str
    enabled: bool = True
    description: str = ""
    category: str = "builtin"
    tags: list[str] = []
    scene: str = "general"
    async_execution: bool = False
    icon: str = ""
    builtin: bool = True

class ToolToggleRequest(BaseModel):
    enabled: Optional[bool] = None

class ToolAsyncRequest(BaseModel):
    async_execution: bool


# ── Per-user helpers ───────────────────────────────────────────────────────

def _get_workspace(request: Request) -> Path:
    """Get current user's workspace directory from request state."""
    username = getattr(request.state, "username", None)
    if not username:
        username = "default"
    try:
        from ....constant import WORKSPACES_DIR
        ws = WORKSPACES_DIR / username
        ws.mkdir(parents=True, exist_ok=True)
        return ws
    except Exception:
        # Fallback: use workspace/files/tmp instead of shared /tmp
        fallback = Path(os.environ.get("COAPIS_WORKING_DIR", str(Path.home() / ".coapis"))) / "workspaces" / username / "files" / "tmp"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

def _get_tool_state_path(ws: Path) -> Path:
    return ws / "tool_state.json"

def _get_audit_path(ws: Path) -> Path:
    return ws / "tool_audit.json"

def _load_user_tool_state(ws: Path) -> Dict[str, Any]:
    p = _get_tool_state_path(ws)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}

def _save_user_tool_state(ws: Path, state: Dict[str, Any]):
    p = _get_tool_state_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False))

def _load_user_audit(ws: Path) -> list[dict[str, Any]]:
    p = _get_audit_path(ws)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return []

def _save_user_audit(ws: Path, log: list[dict[str, Any]]):
    p = _get_audit_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(log[-500:], indent=2, ensure_ascii=False))

def _add_user_audit(ws: Path, action: str, tool_name: str,
                    detail: str = "", user: str = "system"):
    log = _load_user_audit(ws)
    entry = {
        "id": f"{int(time.time()*1000)}_{tool_name}",
        "action": action,
        "tool_name": tool_name,
        "detail": detail,
        "user": user,
        "timestamp": datetime.now().isoformat(),
    }
    log.append(entry)
    _save_user_audit(ws, log)


# ── Registry integration ──────────────────────────────────────────────────

def _get_registry_tools() -> Dict[str, Dict[str, Any]]:
    try:
        from coapis.agents.tools.registry import _registry
        tools = {}
        for name, reg in _registry.items():
            tools[name] = {
                "name": name,
                "description": (reg.description or "")[:500],
                "category": reg.category,
                "tags": reg.tags or [],
                "scene": getattr(reg, "scene", "general"),
                "async_execution": reg.async_execution,
            }
        return tools
    except Exception as e:
        logger.warning("Failed to read registry: %s", e)
        return {}

def _tool_icon(name: str, category: str) -> str:
    icon_map = {
        "file": "📄", "read": "📖", "write": "✏️", "edit": "🔨",
        "search": "🔍", "grep": "🔍", "glob": "📁", "shell": "💻",
        "browser": "🌐", "screenshot": "📸", "image": "🖼️", "video": "🎬",
        "send": "📤", "time": "🕐", "memory": "🧠", "todo": "📋",
        "git": "🔀", "deploy": "🚀", "test": "🧪", "code": "💻",
        "review": "📝", "diff": "📊", "http": "🌐", "tool": "🔧",
        "context": "🔗", "error": "⚠️", "batch": "📦", "data": "📊",
        "cron": "⏰", "text": "📝", "archive": "🗜️", "crypto": "🔐",
        "env": "⚙️", "clipboard": "📋", "perf": "📈", "heal": "🩹",
        "resource": "💰", "secret": "🔒", "dep": "📦", "audit": "📋",
        "llm": "🤖", "prompt": "💬", "embed": "📐", "knowledge": "📚",
        "rag": "🔎", "doc": "📄", "mock": "🎭", "schema": "📐",
        "changelog": "📝", "notify": "🔔", "share": "🤝", "task": "📤",
        "db": "🗃️", "cache": "⚡", "queue": "📬", "log": "📋",
        "trace": "🔗", "health": "💚", "skill": "🎯", "workflow": "⚙️",
        "optimizer": "📊", "checkpoint": "💾", "session": "🔍",
        "notes": "📝", "project": "📂", "ast": "🌳",
    }
    for key, emoji in icon_map.items():
        if key in name.lower():
            return emoji
    if category == "builtin":
        return "🔧"
    return "🧩"

def _merge_user_state(registry_tools: Dict, user_state: Dict) -> list[dict]:
    result = []
    for name, info in sorted(registry_tools.items()):
        state = user_state.get(name, {})
        result.append({
            "name": name,
            "enabled": state.get("enabled", True),
            "description": info["description"],
            "category": info["category"],
            "tags": info["tags"],
            "scene": info.get("scene", "general"),
            "async_execution": state.get("async_execution", info.get("async_execution", False)),
            "icon": _tool_icon(name, info["category"]),
            "builtin": info["category"] == "builtin",
        })
    return result


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/tools/scenes")
async def list_scenes(request: Request):
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    user_state = _load_user_tool_state(ws)
    tools = _merge_user_state(registry, user_state)
    scene_counts: Dict[str, int] = {}
    for t in tools:
        s = t.get("scene", "general")
        scene_counts[s] = scene_counts.get(s, 0) + 1
    return [{"scene": s, "count": c} for s, c in sorted(scene_counts.items(), key=lambda x: -x[1])]


@router.get("/tools")
async def list_tools(
    request: Request,
    tag: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    scene: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    enabled_only: Optional[bool] = Query(None),
):
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    user_state = _load_user_tool_state(ws)
    tools = _merge_user_state(registry, user_state)

    if tag:
        tools = [t for t in tools if tag in t["tags"]]
    if category:
        tools = [t for t in tools if t["category"] == category]
    if scene:
        tools = [t for t in tools if t.get("scene", "general") == scene]
    if search:
        q = search.lower()
        tools = [t for t in tools if q in t["name"].lower() or q in t["description"].lower()]
    if enabled_only is not None:
        tools = [t for t in tools if t["enabled"] == enabled_only]

    return tools

@router.get("/tools/tags")
async def list_tags(request: Request):
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    user_state = _load_user_tool_state(ws)
    tools = _merge_user_state(registry, user_state)
    tag_counts: Dict[str, int] = {}
    for t in tools:
        for tag in t["tags"]:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return [{"tag": tag, "count": count}
            for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])]

@router.get("/tools/categories")
async def list_categories(request: Request):
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    user_state = _load_user_tool_state(ws)
    tools = _merge_user_state(registry, user_state)
    cat_counts: Dict[str, int] = {}
    for t in tools:
        cat_counts[t["category"]] = cat_counts.get(t["category"], 0) + 1
    return [{"category": c, "count": cnt}
            for c, cnt in sorted(cat_counts.items(), key=lambda x: -x[1])]

@router.get("/tools/stats")
async def tool_stats_summary(request: Request):
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    user_state = _load_user_tool_state(ws)
    tools = _merge_user_state(registry, user_state)
    enabled = sum(1 for t in tools if t["enabled"])
    cats: Dict[str, int] = {}
    for t in tools:
        cats[t["category"]] = cats.get(t["category"], 0) + 1
    builtin = sum(1 for t in tools if t["builtin"])
    return {
        "total": len(tools), "enabled": enabled,
        "disabled": len(tools) - enabled,
        "categories": cats,
        "builtin_count": builtin,
        "plugin_count": len(tools) - builtin,
    }

@router.get("/tools/{tool_name}")
async def get_tool(request: Request, tool_name: str):
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    user_state = _load_user_tool_state(ws)
    tools = _merge_user_state(registry, user_state)
    for t in tools:
        if t["name"] == tool_name:
            return t
    raise HTTPException(404, f"Tool not found: {tool_name}")

@router.patch("/tools/{tool_name}/toggle")
@require_permission("tools:write")
async def toggle_tool(request: Request, tool_name: str):
    username = getattr(request.state, "username", "system")
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    if tool_name not in registry:
        raise HTTPException(404, f"Tool not found: {tool_name}")
    state = _load_user_tool_state(ws)
    current = state.get(tool_name, {}).get("enabled", True)
    state.setdefault(tool_name, {})["enabled"] = not current
    _save_user_tool_state(ws, state)
    action = "enable" if not current else "disable"
    _add_user_audit(ws, action, tool_name, user=username)
    info = registry[tool_name]
    s = state.get(tool_name, {})
    return {
        "name": tool_name, "enabled": s.get("enabled", True),
        "description": info["description"], "category": info["category"],
        "tags": info["tags"], "async_execution": s.get("async_execution", False),
        "icon": _tool_icon(tool_name, info["category"]),
        "builtin": info["category"] == "builtin",
    }

@router.patch("/tools/{tool_name}/enable")
@require_permission("tools:write")
async def enable_tool(request: Request, tool_name: str):
    username = getattr(request.state, "username", "system")
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    if tool_name not in registry:
        raise HTTPException(404, f"Tool not found: {tool_name}")
    state = _load_user_tool_state(ws)
    state.setdefault(tool_name, {})["enabled"] = True
    _save_user_tool_state(ws, state)
    _add_user_audit(ws, "enable", tool_name, user=username)
    info = registry[tool_name]
    s = state.get(tool_name, {})
    return {
        "name": tool_name, "enabled": True,
        "description": info["description"], "category": info["category"],
        "tags": info["tags"], "async_execution": s.get("async_execution", False),
        "icon": _tool_icon(tool_name, info["category"]),
        "builtin": info["category"] == "builtin",
    }

@router.patch("/tools/{tool_name}/disable")
@require_permission("tools:write")
async def disable_tool(request: Request, tool_name: str):
    username = getattr(request.state, "username", "system")
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    if tool_name not in registry:
        raise HTTPException(404, f"Tool not found: {tool_name}")
    state = _load_user_tool_state(ws)
    state.setdefault(tool_name, {})["enabled"] = False
    _save_user_tool_state(ws, state)
    _add_user_audit(ws, "disable", tool_name, user=username)
    info = registry[tool_name]
    s = state.get(tool_name, {})
    return {
        "name": tool_name, "enabled": False,
        "description": info["description"], "category": info["category"],
        "tags": info["tags"], "async_execution": s.get("async_execution", False),
        "icon": _tool_icon(tool_name, info["category"]),
        "builtin": info["category"] == "builtin",
    }

@router.patch("/tools/{tool_name}/async-execution")
@require_permission("tools:write")
async def update_async_execution(
    request: Request, tool_name: str, body: ToolAsyncRequest
):
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    if tool_name not in registry:
        raise HTTPException(404, f"Tool not found: {tool_name}")
    state = _load_user_tool_state(ws)
    state.setdefault(tool_name, {})["async_execution"] = body.async_execution
    _save_user_tool_state(ws, state)
    info = registry[tool_name]
    s = state.get(tool_name, {})
    return {
        "name": tool_name, "enabled": s.get("enabled", True),
        "description": info["description"], "category": info["category"],
        "tags": info["tags"], "async_execution": body.async_execution,
        "icon": _tool_icon(tool_name, info["category"]),
        "builtin": info["category"] == "builtin",
    }

@router.post("/tools/enable-all")
@require_permission("tools:write")
async def enable_all(request: Request):
    username = getattr(request.state, "username", "system")
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    state = _load_user_tool_state(ws)
    count = 0
    for name in registry:
        if not state.get(name, {}).get("enabled", True):
            count += 1
        state.setdefault(name, {})["enabled"] = True
    _save_user_tool_state(ws, state)
    _add_user_audit(ws, "enable_all", "*", detail=f"启用了 {count} 个工具", user=username)
    return {"enabled": count, "total": len(registry)}

@router.post("/tools/disable-all")
@require_permission("tools:write")
async def disable_all(request: Request):
    username = getattr(request.state, "username", "system")
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    state = _load_user_tool_state(ws)
    count = 0
    for name in registry:
        if state.get(name, {}).get("enabled", True):
            count += 1
        state.setdefault(name, {})["enabled"] = False
    _save_user_tool_state(ws, state)
    _add_user_audit(ws, "disable_all", "*", detail=f"禁用了 {count} 个工具", user=username)
    return {"disabled": count, "total": len(registry)}

@router.get("/tools/audit/log")
async def get_audit_log(
    request: Request,
    limit: int = Query(50),
    tool_name: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
):
    ws = _get_workspace(request)
    log = _load_user_audit(ws)
    if tool_name:
        log = [e for e in log if e.get("tool_name") == tool_name]
    if action:
        log = [e for e in log if e.get("action") == action]
    return log[-limit:]

@router.delete("/tools/{tool_name}")
@require_permission("tools:write")
async def delete_custom_tool(request: Request, tool_name: str):
    username = getattr(request.state, "username", "system")
    ws = _get_workspace(request)
    registry = _get_registry_tools()
    if tool_name not in registry:
        raise HTTPException(404, f"Tool not found: {tool_name}")
    if registry[tool_name]["category"] == "builtin":
        raise HTTPException(400, "Cannot delete builtin tools")
    state = _load_user_tool_state(ws)
    state.pop(tool_name, None)
    _save_user_tool_state(ws, state)
    _add_user_audit(ws, "delete", tool_name, user=username)
    return {"deleted": tool_name}
