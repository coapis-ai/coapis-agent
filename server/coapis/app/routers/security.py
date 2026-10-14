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
from ...security.skill_scanner import (
    get_blocked_history as _get_blocked_history,
    clear_blocked_history as _clear_blocked_history,
    remove_blocked_entry as _remove_blocked_entry,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["security"])

# ── Storage paths ───────────────────────────────────────────────────
SECURITY_DIR = DATA_DIR / "config" / "security"
FILE_GUARD_FILE = SECURITY_DIR / "file_guard.json"
SKILL_SCANNER_FILE = SECURITY_DIR / "skill_scanner.json"
ALLOW_NO_AUTH_FILE = SECURITY_DIR / "allow_no_auth_hosts.json"
BLOCKED_HISTORY_FILE = SECURITY_DIR / "blocked_history.json"
# ── Default configs ─────────────────────────────────────────────────

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
    """Get blocked skill history from skill scanner."""
    records = _get_blocked_history()
    return [r.to_dict() for r in records]


@router.delete("/config/security/skill-scanner/blocked-history")
@require_permission("admin:admin")
async def clear_blocked_history(request: Request) -> Dict[str, Any]:
    """Clear blocked skill history."""
    _clear_blocked_history()
    return {"cleared": True}


@router.delete("/config/security/skill-scanner/blocked-history/{index}")
@require_permission("admin:admin")
async def remove_blocked_entry(
    request: Request,
    index: int,
) -> Dict[str, Any]:
    """Remove a specific entry from blocked history."""
    success = _remove_blocked_entry(index)
    if success:
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
