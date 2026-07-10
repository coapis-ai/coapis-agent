# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
"""Tools router — global registry-based tool management.

All tools come from the live registry (coapis.agents.tools.registry).
State (enabled/disabled) is managed in the global config.json under
``tools.builtin_tools`` so that administrators have a single source of
truth and every user sees the same tool set.

Audit log is written per user for traceability but does not affect
tool availability.
"""
from __future__ import annotations
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from ..permissions.decorators import require_permission
from coapis.tools.registry import TOOL_GROUPS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tools"])

# ── Models ─────────────────────────────────────────────────────────────────

class ToolInfo(BaseModel):
    name: str
    enabled: bool = True
    description: str = ""
    category: str = "builtin"
    group: str = "rarely"
    tags: list[str] = []
    scene: str = "general"
    async_execution: bool = False
    icon: str = ""
    builtin: bool = True


class ToolToggleRequest(BaseModel):
    enabled: Optional[bool] = None


class ToolAsyncRequest(BaseModel):
    async_execution: bool


# ── Global config helpers ────────────────────────────────────────────────

def _load_global_config() -> "Config":
    """Load the global Config model."""
    try:
        from coapis.config.utils import load_config
        return load_config()
    except Exception as e:
        logger.warning("Failed to load global config: %s", e)
        from coapis.config.config import Config
        return Config()


def _save_global_config(config: "Config") -> None:
    """Persist the global config."""
    try:
        from coapis.config.utils import save_config
        save_config(config)
    except Exception as e:
        logger.warning("Failed to save global config: %s", e)
        raise


def _get_default_tool_states() -> Dict[str, bool]:
    """Return the canonical default enabled state from code (config.py)."""
    try:
        from coapis.config.config import _default_builtin_tools
        defaults = _default_builtin_tools()
        return {name: tc.enabled for name, tc in defaults.items()}
    except Exception as e:
        logger.warning("Failed to load default tool states: %s", e)
        return {}


def _get_current_tool_states() -> Dict[str, bool]:
    """Return current enabled state merging global config over code defaults."""
    defaults = _get_default_tool_states()
    config = _load_global_config()
    current = dict(defaults)
    if config.tools and config.tools.builtin_tools:
        for name, tc in config.tools.builtin_tools.items():
            current[name] = bool(tc.enabled)
    return current


# ── Per-user audit helpers ─────────────────────────────────────────────────

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
        fallback = Path(
            os.environ.get("COAPIS_WORKING_DIR", str(Path.home() / ".coapis"))
        ) / "workspaces" / username / "files" / "tmp"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _get_audit_path(ws: Path) -> Path:
    return ws / "tool_audit.json"


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

def _tool_group(name: str) -> str:
    """Return TOOL_GROUPS group for a tool name; default to 'other'."""
    for group, spec in TOOL_GROUPS.items():
        if name in spec.get("tools", set()):
            return group
    return "other"


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
        "file": "📄", "read": "📖", "write": "✏️", "edit": "🔨", "append": "📝",
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


def _merge_state(registry_tools: Dict[str, Dict[str, Any]]) -> list[dict]:
    """Merge registry tools with global enabled state."""
    states = _get_current_tool_states()
    result = []
    for name, info in sorted(registry_tools.items()):
        result.append({
            "name": name,
            "enabled": states.get(name, True),
            "description": info["description"],
            "category": info["category"],
            "group": _tool_group(name),
            "tags": info["tags"],
            "scene": info.get("scene", "general"),
            "async_execution": info.get("async_execution", False),
            "icon": _tool_icon(name, info["category"]),
            "builtin": info["category"] == "builtin",
        })
    return result


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/tools/scenes")
async def list_scenes(request: Request):
    registry = _get_registry_tools()
    tools = _merge_state(registry)
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
    group: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    enabled_only: Optional[bool] = Query(None),
):
    registry = _get_registry_tools()
    tools = _merge_state(registry)

    if tag:
        tools = [t for t in tools if tag in t["tags"]]
    if category:
        tools = [t for t in tools if t["category"] == category]
    if scene:
        tools = [t for t in tools if t.get("scene", "general") == scene]
    if group:
        tools = [t for t in tools if t.get("group", "rarely") == group]
    if search:
        q = search.lower()
        tools = [t for t in tools if q in t["name"].lower() or q in t["description"].lower()]
    if enabled_only is not None:
        tools = [t for t in tools if t["enabled"] == enabled_only]

    return tools


@router.get("/tools/tags")
async def list_tags(request: Request):
    registry = _get_registry_tools()
    tools = _merge_state(registry)
    tag_counts: Dict[str, int] = {}
    for t in tools:
        for tag in t["tags"]:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return [{"tag": tag, "count": count}
            for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])]


@router.get("/tools/categories")
async def list_categories(request: Request):
    registry = _get_registry_tools()
    tools = _merge_state(registry)
    cat_counts: Dict[str, int] = {}
    for t in tools:
        cat_counts[t["category"]] = cat_counts.get(t["category"], 0) + 1
    return [{"category": c, "count": cnt}
            for c, cnt in sorted(cat_counts.items(), key=lambda x: -x[1])]


@router.get("/tools/groups")
async def list_groups(request: Request):
    registry = _get_registry_tools()
    tools = _merge_state(registry)
    group_counts: Dict[str, int] = {}
    for t in tools:
        g = t.get("group", "rarely")
        group_counts[g] = group_counts.get(g, 0) + 1
    return [{"group": g, "count": c} for g, c in sorted(group_counts.items(), key=lambda x: -x[1])]


@router.get("/tools/stats")
async def tool_stats_summary(request: Request):
    registry = _get_registry_tools()
    tools = _merge_state(registry)
    enabled = sum(1 for t in tools if t["enabled"])
    groups: Dict[str, int] = {}
    for t in tools:
        g = t.get("group", "rarely")
        groups[g] = groups.get(g, 0) + 1
    builtin = sum(1 for t in tools if t["builtin"])
    return {
        "total": len(tools), "enabled": enabled,
        "disabled": len(tools) - enabled,
        "groups": groups,
        "categories": {t["category"]: groups.get(t.get("group", "rarely"), 0) for t in tools},
        "builtin_count": builtin,
        "plugin_count": len(tools) - builtin,
    }


@router.get("/tools/{tool_name}")
async def get_tool(request: Request, tool_name: str):
    registry = _get_registry_tools()
    tools = _merge_state(registry)
    for t in tools:
        if t["name"] == tool_name:
            return t
    raise HTTPException(404, f"Tool not found: {tool_name}")


@router.patch("/tools/{tool_name}/toggle")
@require_permission("tools:write")
async def toggle_tool(request: Request, tool_name: str):
    username = getattr(request.state, "username", "system")
    config = _load_global_config()

    if config.tools is None:
        from coapis.config.config import ToolsConfig
        config.tools = ToolsConfig()
    if config.tools.builtin_tools is None:
        config.tools.builtin_tools = {}

    current = _get_current_tool_states().get(tool_name, True)
    new_enabled = not current

    from coapis.config.config import BuiltinToolConfig
    config.tools.builtin_tools[tool_name] = BuiltinToolConfig(
        name=tool_name,
        enabled=new_enabled,
        description="",
        icon="",
    )

    _save_global_config(config)

    ws = _get_workspace(request)
    _add_user_audit(ws, "toggle", tool_name, f"enabled={new_enabled}", user=username)

    return {"name": tool_name, "enabled": new_enabled}


@router.patch("/tools/{tool_name}/enable")
@require_permission("tools:write")
async def enable_tool(request: Request, tool_name: str):
    username = getattr(request.state, "username", "system")
    config = _load_global_config()

    if config.tools is None:
        from coapis.config.config import ToolsConfig
        config.tools = ToolsConfig()
    if config.tools.builtin_tools is None:
        config.tools.builtin_tools = {}

    from coapis.config.config import BuiltinToolConfig
    config.tools.builtin_tools[tool_name] = BuiltinToolConfig(
        name=tool_name,
        enabled=True,
        description="",
        icon="",
    )
    _save_global_config(config)

    ws = _get_workspace(request)
    _add_user_audit(ws, "enable", tool_name, "enabled=True", user=username)
    return {"name": tool_name, "enabled": True}


@router.patch("/tools/{tool_name}/disable")
@require_permission("tools:write")
async def disable_tool(request: Request, tool_name: str):
    username = getattr(request.state, "username", "system")
    config = _load_global_config()

    if config.tools is None:
        from coapis.config.config import ToolsConfig
        config.tools = ToolsConfig()
    if config.tools.builtin_tools is None:
        config.tools.builtin_tools = {}

    from coapis.config.config import BuiltinToolConfig
    config.tools.builtin_tools[tool_name] = BuiltinToolConfig(
        name=tool_name,
        enabled=False,
        description="",
        icon="",
    )
    _save_global_config(config)

    ws = _get_workspace(request)
    _add_user_audit(ws, "disable", tool_name, "enabled=False", user=username)
    return {"name": tool_name, "enabled": False}


@router.patch("/tools/{tool_name}/async-execution")
@require_permission("tools:write")
async def set_async_execution(request: Request, tool_name: str, body: ToolAsyncRequest):
    """Set async execution flag for a tool (global)."""
    config = _load_global_config()

    if config.tools is None:
        from coapis.config.config import ToolsConfig
        config.tools = ToolsConfig()
    if config.tools.builtin_tools is None:
        config.tools.builtin_tools = {}

    from coapis.config.config import BuiltinToolConfig
    existing = config.tools.builtin_tools.get(tool_name)
    enabled = existing.enabled if existing else _get_default_tool_states().get(tool_name, True)
    config.tools.builtin_tools[tool_name] = BuiltinToolConfig(
        name=tool_name,
        enabled=enabled,
        async_execution=body.async_execution,
        description="",
        icon="",
    )
    _save_global_config(config)
    return {"name": tool_name, "async_execution": body.async_execution}


@router.post("/tools/enable-all")
@require_permission("tools:write")
async def enable_all_tools(request: Request):
    username = getattr(request.state, "username", "system")
    config = _load_global_config()

    if config.tools is None:
        from coapis.config.config import ToolsConfig
        config.tools = ToolsConfig()
    if config.tools.builtin_tools is None:
        config.tools.builtin_tools = {}

    registry = _get_registry_tools()
    from coapis.config.config import BuiltinToolConfig
    for name in registry:
        existing = config.tools.builtin_tools.get(name)
        config.tools.builtin_tools[name] = BuiltinToolConfig(
            name=name,
            enabled=True,
            async_execution=getattr(existing, "async_execution", False) if existing else False,
            description="",
            icon="",
        )
    _save_global_config(config)

    ws = _get_workspace(request)
    _add_user_audit(ws, "enable_all", "ALL", "enabled=True", user=username)
    return {"ok": True, "enabled": list(registry.keys())}


@router.post("/tools/disable-all")
@require_permission("tools:write")
async def disable_all_tools(request: Request):
    username = getattr(request.state, "username", "system")
    config = _load_global_config()

    if config.tools is None:
        from coapis.config.config import ToolsConfig
        config.tools = ToolsConfig()
    if config.tools.builtin_tools is None:
        config.tools.builtin_tools = {}

    registry = _get_registry_tools()
    from coapis.config.config import BuiltinToolConfig
    for name in registry:
        existing = config.tools.builtin_tools.get(name)
        config.tools.builtin_tools[name] = BuiltinToolConfig(
            name=name,
            enabled=False,
            async_execution=getattr(existing, "async_execution", False) if existing else False,
            description="",
            icon="",
        )
    _save_global_config(config)

    ws = _get_workspace(request)
    _add_user_audit(ws, "disable_all", "ALL", "enabled=False", user=username)
    return {"ok": True, "disabled": list(registry.keys())}


@router.get("/tools/audit/log")
async def list_audit_log(request: Request, limit: int = Query(100, ge=1, le=500)):
    ws = _get_workspace(request)
    log = _load_user_audit(ws)
    return log[-limit:]


@router.delete("/tools/{tool_name}")
@require_permission("tools:write")
async def delete_tool(request: Request, tool_name: str):
    """Built-in tools cannot be deleted. Only custom plugins can be removed."""
    registry = _get_registry_tools()
    if tool_name in registry and registry[tool_name]["category"] == "builtin":
        raise HTTPException(400, "Cannot delete built-in tools")
    raise HTTPException(404, f"Tool not found: {tool_name}")
