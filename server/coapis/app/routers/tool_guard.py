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
from typing import Any, Dict, List

import yaml
from fastapi import APIRouter, Body, HTTPException, Request

from ...constant import DATA_DIR
from ...security.tool_guard.unified_engine import get_unified_engine, reset_engine
from ...security.tool_guard.unified_models import ToolGuardConfig
from ..permissions.decorators import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tool-guard"])

# ── Config file path ────────────────────────────────────────────────
TOOL_GUARD_YAML = DATA_DIR.parent / "system" / "tool_guard.yaml"
# Fallback: server/coapis/system/tool_guard.yaml
if not TOOL_GUARD_YAML.exists():
    TOOL_GUARD_YAML = Path(__file__).resolve().parents[2] / "system" / "tool_guard.yaml"


# ── Helpers ─────────────────────────────────────────────────────────

def _load_yaml_config() -> dict:
    """Load the raw YAML config as a dict."""
    if not TOOL_GUARD_YAML.exists():
        logger.warning("tool_guard.yaml not found at %s", TOOL_GUARD_YAML)
        return {}
    try:
        with open(TOOL_GUARD_YAML, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to load tool_guard.yaml: %s", e)
        return {}


def _save_yaml_config(data: dict) -> None:
    """Save the full YAML config."""
    TOOL_GUARD_YAML.parent.mkdir(parents=True, exist_ok=True)
    with open(TOOL_GUARD_YAML, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)
    # Reload the engine
    reset_engine()
    logger.info("Saved tool_guard.yaml and reset engine")


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
async def get_tool_guard_legacy(request: Request) -> Dict[str, Any]:
    """Legacy: Get tool guard config (access_control + evasion_checks)."""
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
async def update_tool_guard_legacy(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Legacy: Update tool guard config."""
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


@router.get("/config/security/tool-guard/builtin-rules")
@require_permission("security:read")
async def get_builtin_rules_legacy(request: Request) -> List[Dict[str, Any]]:
    """Legacy: Get built-in rules (redirects to unified rules)."""
    data = _load_yaml_config()
    return data.get("rules", [])


@router.get("/config/security/shell-guard/rules")
@require_permission("security:read")
async def get_shell_guard_rules_legacy(request: Request) -> List[Dict[str, Any]]:
    """Legacy: Get shell guard rules (redirects to unified rules)."""
    data = _load_yaml_config()
    return data.get("rules", [])


@router.put("/config/security/shell-guard/rules")
@require_permission("security:write")
async def update_shell_guard_rules_legacy(
    request: Request,
    body: List[Dict[str, Any]] = Body(...),
) -> Dict[str, Any]:
    """Legacy: Update shell guard rules."""
    data = _load_yaml_config()
    data["rules"] = body
    _save_yaml_config(data)
    return {"status": "saved", "count": len(body)}


@router.get("/config/security/shell-guard/evasion-checks")
@require_permission("security:read")
async def get_shell_evasion_checks_legacy(request: Request) -> Dict[str, Any]:
    """Legacy: Get shell evasion checks."""
    data = _load_yaml_config()
    return {"evasion_checks": data.get("evasion_checks", {})}


@router.put("/config/security/shell-guard/evasion-checks")
@require_permission("security:write")
async def update_shell_evasion_checks_legacy(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Legacy: Update shell evasion checks."""
    checks = body.get("evasion_checks", body)
    data = _load_yaml_config()
    data["evasion_checks"] = checks
    _save_yaml_config(data)
    return {"evasion_checks": checks}


@router.get("/config/security/shell-guard/config")
@require_permission("security:read")
async def get_shell_guard_config_legacy(request: Request) -> Dict[str, Any]:
    """Legacy: Get shell guard summary config."""
    data = _load_yaml_config()
    return {
        "global_rules_count": len(data.get("global_rules", [])),
        "evasion_checks": data.get("evasion_checks", {}),
    }
