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

"""Security configuration routes (CoApis console compatible).

Handles Tool Guard, File Guard, Skill Scanner, and Allow-No-Auth-Hosts
security settings. All persisted in DATA_DIR/config/security/*.json.
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

from ...constant import DATA_DIR

from ..permissions.decorators import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["security"])

# ── Storage paths ───────────────────────────────────────────────────
SECURITY_DIR = DATA_DIR / "config" / "security"
TOOL_GUARD_FILE = SECURITY_DIR / "tool_guard.json"
FILE_GUARD_FILE = SECURITY_DIR / "file_guard.json"
SKILL_SCANNER_FILE = SECURITY_DIR / "skill_scanner.json"
ALLOW_NO_AUTH_FILE = SECURITY_DIR / "allow_no_auth_hosts.json"
BLOCKED_HISTORY_FILE = SECURITY_DIR / "blocked_history.json"
SHELL_GUARD_FILE = SECURITY_DIR / "shell_guard.json"


# ── Default configs ─────────────────────────────────────────────────

DEFAULT_TOOL_GUARD: Dict[str, Any] = {
    "enabled": True,
    "guarded_tools": None,
    "denied_tools": [],
    "custom_rules": [],
    "disabled_rules": [],
    "shell_evasion_checks": {
        "backtick_execution": True,
        "subshell_execution": True,
        "variable_expansion": True,
        "command_substitution": True,
    },
}

DEFAULT_FILE_GUARD: Dict[str, Any] = {
    "enabled": True,
    "paths": ["/etc/shadow", "/etc/passwd", "/root/.ssh"],
}

DEFAULT_SKILL_SCANNER: Dict[str, Any] = {
    "mode": "warn",
    "timeout": 30,
    "whitelist": [],
}

DEFAULT_ALLOW_NO_AUTH: Dict[str, Any] = {
    "hosts": [],
}

BUILTIN_RULES: List[Dict[str, Any]] = [
    {
        "id": "TOOL_CMD_PROCESS_KILL",
        "tools": ["execute_shell_command"],
        "params": ["command"],
        "category": "process",
        "severity": "critical",
        "patterns": ["kill", "pkill", "killall", "docker kill", "docker restart"],
        "exclude_patterns": [],
        "description": "Blocks process kill/restart commands",
        "remediation": "Use docker compose up -d --force-recreate instead",
    },
    {
        "id": "TOOL_CMD_DANGEROUS_RM",
        "tools": ["execute_shell_command"],
        "params": ["command"],
        "category": "filesystem",
        "severity": "high",
        "patterns": ["rm -rf /", "rm -rf /*", "rm -rf ~"],
        "exclude_patterns": [],
        "description": "Blocks dangerous rm commands",
        "remediation": "Use trash instead of rm",
    },
    {
        "id": "TOOL_CMD_SHELL_EVASION",
        "tools": ["execute_shell_command"],
        "params": ["command"],
        "category": "evasion",
        "severity": "critical",
        "patterns": ["eval", "exec", "bash -c", "sh -c"],
        "exclude_patterns": [],
        "description": "Blocks shell evasion techniques",
        "remediation": "Avoid indirect command execution",
    },
]


# ── Helpers ─────────────────────────────────────────────────────────

def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    """Load JSON config, return default if missing/invalid."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.warning(f"Failed to load {path}: {e}, using default")
    return default.copy()


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    """Save JSON config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ── Tool Guard ──────────────────────────────────────────────────────

@router.get("/config/security/tool-guard")
@require_permission("admin:admin")
async def get_tool_guard(request: Request) -> Dict[str, Any]:
    """Get Tool Guard configuration."""
    return _load_json(TOOL_GUARD_FILE, DEFAULT_TOOL_GUARD)


@router.put("/config/security/tool-guard")
@require_permission("admin:admin")
async def update_tool_guard(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update Tool Guard configuration."""
    cfg = _load_json(TOOL_GUARD_FILE, DEFAULT_TOOL_GUARD)
    # Merge updates
    for key in ("enabled", "guarded_tools", "denied_tools", "custom_rules",
                "disabled_rules", "shell_evasion_checks"):
        if key in body:
            cfg[key] = body[key]
    _save_json(TOOL_GUARD_FILE, cfg)
    return cfg


@router.get("/config/security/tool-guard/builtin-rules")
@require_permission("admin:admin")
async def get_builtin_rules(request: Request) -> List[Dict[str, Any]]:
    """Get built-in Tool Guard rules from YAML file."""
    import yaml
    rules_file = Path(__file__).resolve().parents[2] / "security" / "tool_guard" / "rules" / "dangerous_shell_commands.yaml"
    if rules_file.exists():
        try:
            data = yaml.safe_load(rules_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception as e:
            logger.warning(f"Failed to load YAML rules: {e}")
    return BUILTIN_RULES


# ── File Guard ──────────────────────────────────────────────────────

@router.get("/config/security/file-guard")
@require_permission("admin:admin")
async def get_file_guard(request: Request) -> Dict[str, Any]:
    """Get File Guard configuration."""
    return _load_json(FILE_GUARD_FILE, DEFAULT_FILE_GUARD)


@router.put("/config/security/file-guard")
@require_permission("admin:admin")
async def update_file_guard(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update File Guard configuration."""
    cfg = _load_json(FILE_GUARD_FILE, DEFAULT_FILE_GUARD)
    for key in ("enabled", "paths"):
        if key in body:
            cfg[key] = body[key]
    _save_json(FILE_GUARD_FILE, cfg)
    return cfg


# ── Skill Scanner ───────────────────────────────────────────────────

@router.get("/config/security/skill-scanner")
@require_permission("admin:admin")
async def get_skill_scanner(request: Request) -> Dict[str, Any]:
    """Get Skill Scanner configuration."""
    return _load_json(SKILL_SCANNER_FILE, DEFAULT_SKILL_SCANNER)


@router.put("/config/security/skill-scanner")
@require_permission("admin:admin")
async def update_skill_scanner(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update Skill Scanner configuration."""
    cfg = _load_json(SKILL_SCANNER_FILE, DEFAULT_SKILL_SCANNER)
    for key in ("mode", "timeout", "whitelist"):
        if key in body:
            cfg[key] = body[key]
    _save_json(SKILL_SCANNER_FILE, cfg)
    return cfg


@router.get("/config/security/skill-scanner/blocked-history")
@require_permission("admin:admin")
async def get_blocked_history(request: Request) -> List[Dict[str, Any]]:
    """Get blocked skill history."""
    return _load_json(BLOCKED_HISTORY_FILE, [])


@router.delete("/config/security/skill-scanner/blocked-history")
@require_permission("admin:admin")
async def clear_blocked_history(request: Request) -> Dict[str, Any]:
    """Clear blocked skill history."""
    _save_json(BLOCKED_HISTORY_FILE, [])
    return {"cleared": True}


@router.delete("/config/security/skill-scanner/blocked-history/{index}")
@require_permission("admin:admin")
async def remove_blocked_entry(
    request: Request,
    index: int,
) -> Dict[str, Any]:
    """Remove a specific entry from blocked history."""
    history = _load_json(BLOCKED_HISTORY_FILE, [])
    if isinstance(history, list) and 0 <= index < len(history):
        history.pop(index)
        _save_json(BLOCKED_HISTORY_FILE, history)
        return {"removed": True}
    raise HTTPException(status_code=404, detail="Entry not found")


@router.post("/config/security/skill-scanner/whitelist")
@require_permission("admin:admin")
async def add_to_whitelist(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Add a skill to the whitelist."""
    cfg = _load_json(SKILL_SCANNER_FILE, DEFAULT_SKILL_SCANNER)
    skill_name = body.get("skill_name", "").strip()
    content_hash = body.get("content_hash", "").strip()
    if not skill_name:
        raise HTTPException(status_code=400, detail="skill_name is required")

    # Check if already whitelisted
    for entry in cfg.get("whitelist", []):
        if entry.get("skill_name") == skill_name:
            return {"whitelisted": False, "skill_name": skill_name}

    cfg.setdefault("whitelist", []).append({
        "skill_name": skill_name,
        "content_hash": content_hash or hashlib.sha256(skill_name.encode()).hexdigest(),
        "added_at": datetime.utcnow().isoformat(),
    })
    _save_json(SKILL_SCANNER_FILE, cfg)
    return {"whitelisted": True, "skill_name": skill_name}


@router.delete("/config/security/skill-scanner/whitelist/{skill_name}")
@require_permission("admin:admin")
async def remove_from_whitelist(
    request: Request,
    skill_name: str,
) -> Dict[str, Any]:
    """Remove a skill from the whitelist."""
    cfg = _load_json(SKILL_SCANNER_FILE, DEFAULT_SKILL_SCANNER)
    whitelist = cfg.get("whitelist", [])
    original_len = len(whitelist)
    cfg["whitelist"] = [e for e in whitelist if e.get("skill_name") != skill_name]
    if len(cfg["whitelist"]) < original_len:
        _save_json(SKILL_SCANNER_FILE, cfg)
        return {"removed": True, "skill_name": skill_name}
    return {"removed": False, "skill_name": skill_name}


# ── Allow No Auth Hosts ────────────────────────────────────────────

@router.get("/config/security/allow-no-auth-hosts")
@require_permission("admin:admin")
async def get_allow_no_auth_hosts(request: Request) -> Dict[str, Any]:
    """Get hosts allowed without authentication."""
    return _load_json(ALLOW_NO_AUTH_FILE, DEFAULT_ALLOW_NO_AUTH)


@router.put("/config/security/allow-no-auth-hosts")
@require_permission("admin:admin")
async def update_allow_no_auth_hosts(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update hosts allowed without authentication."""
    cfg = _load_json(ALLOW_NO_AUTH_FILE, DEFAULT_ALLOW_NO_AUTH)
    if "hosts" in body:
        cfg["hosts"] = body["hosts"]
    _save_json(ALLOW_NO_AUTH_FILE, cfg)
    return cfg


# ── Shell Guard (独立端点) ──────────────────────────────────────────
# 从 tool_guard 拆分出来的 Shell 防护独立 API：
# - YAML 规则读取/替换（来自 dangerous_shell_commands.yaml）
# - shell_evasion_checks 配置读取/更新

from pathlib import Path as _Path

_SHELL_RULES_FILE = (
    _Path(__file__).resolve().parent.parent.parent
    / "security" / "tool_guard" / "rules" / "dangerous_shell_commands.yaml"
)


def _load_shell_yaml_rules() -> List[Dict[str, Any]]:
    """Load shell rules from YAML file."""
    import yaml
    if not _SHELL_RULES_FILE.exists():
        return []
    try:
        with open(_SHELL_RULES_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error("Failed to load shell rules YAML: %s", e)
        return []


def _save_shell_yaml_rules(rules: List[Dict[str, Any]]) -> None:
    """Save shell rules to YAML file."""
    import yaml
    try:
        with open(_SHELL_RULES_FILE, "w", encoding="utf-8") as f:
            yaml.dump(rules, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        logger.info("Saved %d shell rules to %s", len(rules), _SHELL_RULES_FILE)
    except Exception as e:
        logger.error("Failed to save shell rules YAML: %s", e)


DEFAULT_SHELL_GUARD: Dict[str, Any] = {
    "evasion_checks": {
        "command_substitution": True,
        "obfuscated_flags": True,
        "backslash_escaped_whitespace": True,
        "backslash_escaped_operators": True,
        "newlines": True,
        "comment_quote_desync": True,
        "quoted_newline": True,
    },
}


@router.get("/config/security/shell-guard/rules")
@require_permission("security:read")
async def get_shell_guard_rules(request: Request) -> List[Dict[str, Any]]:
    """Get all shell detection rules from YAML."""
    return _load_shell_yaml_rules()


@router.put("/config/security/shell-guard/rules")
@require_permission("security:write")
async def update_shell_guard_rules(
    request: Request,
    body: List[Dict[str, Any]] = Body(...),
) -> Dict[str, Any]:
    """Replace all shell detection rules (full list)."""
    _save_shell_yaml_rules(body)
    return {"status": "saved", "count": len(body)}


@router.get("/config/security/shell-guard/evasion-checks")
@require_permission("security:read")
async def get_shell_evasion_checks(request: Request) -> Dict[str, Any]:
    """Get shell evasion check toggles."""
    # 优先从独立 shell_guard.json 读取，兼容从 tool_guard 读取
    cfg = _load_json(SHELL_GUARD_FILE, DEFAULT_SHELL_GUARD)
    if "evasion_checks" in cfg:
        return {"evasion_checks": cfg["evasion_checks"]}
    # 兼容：从 tool_guard 读取
    tg = _load_json(TOOL_GUARD_FILE, DEFAULT_TOOL_GUARD)
    return {"evasion_checks": tg.get("shell_evasion_checks", DEFAULT_SHELL_GUARD["evasion_checks"])}


@router.put("/config/security/shell-guard/evasion-checks")
@require_permission("security:write")
async def update_shell_evasion_checks(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update shell evasion check toggles."""
    checks = body.get("evasion_checks", body)
    cfg = _load_json(SHELL_GUARD_FILE, DEFAULT_SHELL_GUARD)
    cfg["evasion_checks"] = checks
    _save_json(SHELL_GUARD_FILE, cfg)
    # 同步到 tool_guard 兼容字段
    tg = _load_json(TOOL_GUARD_FILE, DEFAULT_TOOL_GUARD)
    tg["shell_evasion_checks"] = checks
    _save_json(TOOL_GUARD_FILE, tg)
    return {"evasion_checks": checks}


@router.get("/config/security/shell-guard/config")
@require_permission("security:read")
async def get_shell_guard_config(request: Request) -> Dict[str, Any]:
    """Get full shell guard config (rules count + evasion checks)."""
    rules = _load_shell_yaml_rules()
    evasion_cfg = _load_json(SHELL_GUARD_FILE, DEFAULT_SHELL_GUARD)
    return {
        "rules_count": len(rules),
        "evasion_checks": evasion_cfg.get("evasion_checks", DEFAULT_SHELL_GUARD["evasion_checks"]),
    }
