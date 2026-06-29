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
