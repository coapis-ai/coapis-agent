# -*- coding: utf-8 -*-
"""Unified Tool Guard API routes.

Replaces the old separate shell-guard and tool-guard endpoints with a
single unified API backed by ``system/tool_guard.yaml``.

Endpoints:
  GET/PUT /tool-guard/access-control   — guarded/denied tools + custom rules
  GET/PUT /tool-guard/commands         — L0-L4 command classification
  GET/PUT /tool-guard/global-rules     — cross-command pattern detection rules
  GET/PUT /tool-guard/evasion-checks   — evasion detection toggles
  GET      /tool-guard/config          — full unified config
  POST     /tool-guard/test            — test a command against the engine
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

from ...security.tool_guard.unified_engine import get_unified_engine, reset_engine
from ...security.tool_guard.unified_models import ToolGuardConfig
from ..permissions.decorators import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tool-guard"])

# ── Config file path (single source, C2/C3) ─────────────────────────
# The unified engine resolves the very same path; a console write is always
# visible to the engine after reload.  ``COAPIS_TOOL_GUARD_YAML`` overrides.
from ...security.tool_guard.config_store import (  # noqa: E402
    load_raw as _store_load,
    resolve_yaml_path,
    save_raw as _store_save,
)

TOOL_GUARD_YAML = resolve_yaml_path()


def config_file_path() -> Path:
    """Expose the resolved single-source path (tests / diagnostics)."""
    return resolve_yaml_path()


# ── Helpers ─────────────────────────────────────────────────────────

def _load_yaml_config() -> dict:
    """Load the raw YAML config as a dict (single source)."""
    return _store_load()


def _save_yaml_config(data: dict) -> None:
    """Save the full YAML config and reload the engine.

    The reload is part of the save, not an optional extra: the engine is a
    process-wide singleton holding a parsed copy of this file, so a console
    write that skips it stays invisible until the service restarts.  Measured
    on dev 2026-10-15: every guard PUT wrote the YAML and none reloaded, so
    flipping the master switch had no effect on running sessions.
    """
    _store_save(data)
    _reload_engine()


def _reload_engine() -> None:
    """Reload the unified engine after config change."""
    try:
        engine = get_unified_engine()
        engine.reload()
    except Exception as e:
        logger.warning("Failed to reload engine: %s", e)
        reset_engine()


# ── GET/PUT /tool-guard/config — full config ────────────────────────

@router.get("/config/security/tool-guard/config")
@require_permission("security:read")
async def get_full_config(request: Request) -> Dict[str, Any]:
    """Get the full unified tool guard config."""
    data = _load_yaml_config()
    return {
        "version": data.get("version", "1.0"),
        "description": data.get("description", ""),
        "access_control": data.get("access_control", {}),
        "commands_count": len(data.get("commands", {})),
        "global_rules_count": len(data.get("global_rules", [])),
        "evasion_checks": data.get("evasion_checks", {}),
    }


# ── GET/PUT /tool-guard/access-control ──────────────────────────────

@router.get("/config/security/tool-guard/access-control")
@require_permission("security:read")
async def get_access_control(request: Request) -> Dict[str, Any]:
    """Get tool access control settings (guarded/denied tools + custom rules)."""
    data = _load_yaml_config()
    return data.get("access_control", {})


@router.put("/config/security/tool-guard/access-control")
@require_permission("security:write")
async def update_access_control(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update tool access control settings."""
    data = _load_yaml_config()
    ac = data.get("access_control", {})
    for key in ("enabled", "guarded_tools", "denied_tools", "custom_rules", "disabled_rules"):
        if key in body:
            ac[key] = body[key]
    data["access_control"] = ac
    _save_yaml_config(data)
    return ac


# ── GET/PUT /tool-guard/commands ────────────────────────────────────

@router.get("/config/security/tool-guard/commands")
@require_permission("security:read")
async def get_commands(request: Request) -> Dict[str, Any]:
    """Get all L0-L4 command classifications."""
    data = _load_yaml_config()
    return data.get("commands", {})


@router.put("/config/security/tool-guard/commands")
@require_permission("security:write")
async def update_commands(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update command classifications (full replacement)."""
    data = _load_yaml_config()
    data["commands"] = body
    _save_yaml_config(data)
    return body


@router.put("/config/security/tool-guard/commands/{cmd_name}")
@require_permission("security:write")
async def update_single_command(
    request: Request,
    cmd_name: str,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update a single command's classification."""
    data = _load_yaml_config()
    cmds = data.get("commands", {})
    if cmd_name not in cmds:
        raise HTTPException(status_code=404, detail=f"Command '{cmd_name}' not found")
    entry = cmds[cmd_name]
    for key in ("level", "desc", "action", "exceptions", "demotion_rules"):
        if key in body:
            entry[key] = body[key]
    cmds[cmd_name] = entry
    data["commands"] = cmds
    _save_yaml_config(data)
    return entry


# ── GET/PUT /tool-guard/global-rules ─────────────────────────────────

@router.get("/config/security/tool-guard/global-rules")
@require_permission("security:read")
async def get_global_rules(request: Request) -> List[Dict[str, Any]]:
    """Get all cross-command pattern detection rules."""
    data = _load_yaml_config()
    return data.get("global_rules", [])


@router.put("/config/security/tool-guard/global-rules")
@require_permission("security:write")
async def update_global_rules(
    request: Request,
    body: List[Dict[str, Any]] = Body(...),
) -> Dict[str, Any]:
    """Replace all global rules (full list)."""
    data = _load_yaml_config()
    data["global_rules"] = body
    _save_yaml_config(data)
    return {"status": "saved", "count": len(body)}


@router.put("/config/security/tool-guard/global-rules/{rule_id}")
@require_permission("security:write")
async def update_single_global_rule(
    request: Request,
    rule_id: str,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update a single global rule."""
    data = _load_yaml_config()
    rules = data.get("global_rules", [])
    for i, rule in enumerate(rules):
        if rule.get("id") == rule_id:
            for key in ("severity", "category", "patterns",
                        "exclude_patterns", "description", "remediation", "action"):
                if key in body:
                    rule[key] = body[key]
            rules[i] = rule
            data["global_rules"] = rules
            _save_yaml_config(data)
            return rule
    raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")


# ── GET/PUT /tool-guard/evasion-checks ──────────────────────────────

@router.get("/config/security/tool-guard/evasion-checks")
@require_permission("security:read")
async def get_evasion_checks(request: Request) -> Dict[str, Any]:
    """Get evasion detection toggles."""
    data = _load_yaml_config()
    return {"evasion_checks": data.get("evasion_checks", {})}


@router.put("/config/security/tool-guard/evasion-checks")
@require_permission("security:write")
async def update_evasion_checks(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update evasion detection toggles."""
    checks = body.get("evasion_checks", body)
    data = _load_yaml_config()
    data["evasion_checks"] = checks
    _save_yaml_config(data)
    return {"evasion_checks": checks}


# ── POST /tool-guard/test ───────────────────────────────────────────

@router.post("/config/security/tool-guard/test")
@require_permission("security:read")
async def test_command(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Test a command against the unified engine.

    Body: {"command": "rm -rf /"}
    """
    command = body.get("command", "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")

    engine = get_unified_engine()
    result = engine.process_command("execute_shell_command", {"command": command})

    # ── Enrich: identify rule source ──
    reason = result.get("reason", "")
    rule_source = "default"
    if "global_rule_override" in reason:
        rule_source = "global"
    elif "rule:" in reason:
        rule_id = reason.split("rule:")[1].split(" —")[0].split(" ")[0].strip()
        # Check which field the matched rule came from
        cmd_name = result.get("command")
        if cmd_name and cmd_name in engine._config.commands:
            entry = engine._config.commands[cmd_name]
            exc_ids = {r.id for r in entry.exceptions}
            dem_ids = {r.id for r in entry.demotion_rules}
            legacy_ids = {r.id for r in entry.rules}
            if rule_id in exc_ids:
                rule_source = "exception"
            elif rule_id in dem_ids:
                rule_source = "demotion"
            elif rule_id in legacy_ids:
                rule_source = "exception"  # backward compat: old rules treated as exceptions
            else:
                rule_source = "exception"  # fallback
    elif "sub_command:" in reason:
        rule_source = "sub_command"
    elif "Command-level default" in reason:
        rule_source = "default"
    elif "Evasion" in reason:
        rule_source = "evasion"

    result["rule_source"] = rule_source
    return result


# ── Legacy compatibility endpoints ──────────────────────────────────
# These keep the old /tool-guard and /shell-guard paths working
# so that existing frontend code doesn't break during migration.

@router.get("/config/security/tool-guard")
@require_permission("security:read")
async def get_tool_guard_config(request: Request) -> Dict[str, Any]:
    """Tool guard master config (``access_control`` + evasion toggles).

    C3: this is the *only* implementation of this path — the old
    ``config.py`` handler that read ``config.json`` was removed, so the
    console switch and the engine share one source.
    """
    data = _load_yaml_config()
    ac = data.get("access_control", {})
    return {
        "enabled": ac.get("enabled", True),
        "guarded_tools": ac.get("guarded_tools", []),
        "denied_tools": ac.get("denied_tools", []),
        "custom_rules": ac.get("custom_rules", []),
        "disabled_rules": ac.get("disabled_rules", []),
        "shell_evasion_checks": data.get("evasion_checks", {}),
    }


@router.put("/config/security/tool-guard")
@require_permission("security:write")
async def update_tool_guard_config(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update the tool guard master config and reload the engine."""
    data = _load_yaml_config()
    ac = data.get("access_control", {})
    for key in ("enabled", "guarded_tools", "denied_tools", "custom_rules", "disabled_rules"):
        if key in body:
            ac[key] = body[key]
    data["access_control"] = ac
    if "shell_evasion_checks" in body:
        data["evasion_checks"] = body["shell_evasion_checks"]
    _save_yaml_config(data)
    return body


# ── File guard (path layer) — reads/writes the same YAML (C3) ─────────


class FileGuardResponse(BaseModel):
    enabled: bool = True
    paths: List[str] = []


class FileGuardUpdateBody(BaseModel):
    enabled: Optional[bool] = None
    paths: Optional[List[str]] = None


@router.get("/config/security/file-guard")
@require_permission("security:read")
async def get_file_guard(request: Request) -> FileGuardResponse:
    """Path-layer settings (``path_guard`` section of the single source)."""
    data = _load_yaml_config()
    pg = data.get("path_guard", {}) or {}
    from ...security.tool_guard.guardians.file_guardian import (
        ensure_file_guard_paths,
    )

    return FileGuardResponse(
        enabled=bool(pg.get("enabled", True)),
        paths=ensure_file_guard_paths(pg.get("sensitive_files") or []),
    )


@router.put("/config/security/file-guard")
@require_permission("security:write")
async def update_file_guard(
    request: Request,
    body: FileGuardUpdateBody = Body(...),
) -> FileGuardResponse:
    """Update path-layer settings; the engine reloads on save."""
    data = _load_yaml_config()
    pg = data.get("path_guard", {}) or {}

    if body.enabled is not None:
        pg["enabled"] = body.enabled
    if body.paths is not None:
        from ...security.tool_guard.guardians.file_guardian import (
            ensure_file_guard_paths,
        )

        pg["sensitive_files"] = ensure_file_guard_paths(body.paths)
    data["path_guard"] = pg
    _save_yaml_config(data)

    return await get_file_guard(request)


# ── Shell evasion toggles (UI panel; same YAML source) ───────────────


@router.get("/config/security/shell-guard/evasion-checks")
@require_permission("security:read")
async def get_shell_evasion_checks(request: Request) -> Dict[str, Any]:
    """Shell evasion toggles (``evasion_checks`` section)."""
    data = _load_yaml_config()
    return {"evasion_checks": data.get("evasion_checks", {})}


@router.put("/config/security/shell-guard/evasion-checks")
@require_permission("security:write")
async def update_shell_evasion_checks(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update shell evasion toggles."""
    checks = body.get("evasion_checks", body)
    data = _load_yaml_config()
    data["evasion_checks"] = checks
    _save_yaml_config(data)
    return {"evasion_checks": checks}
