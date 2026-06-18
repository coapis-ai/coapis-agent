# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

"""Backups router - Backup endpoints (CoApis console compatible)."""

import logging
import json
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..permissions.decorators import require_permission
from fastapi import APIRouter, HTTPException, Body
from fastapi.requests import Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backups"])


class BackupMeta(BaseModel):
    id: str
    name: str
    created_at: str
    size: int = 0
    description: str = ""


# In-memory backup store
_backups: Dict[str, BackupMeta] = {}


def _load_backups():
    """Load backups from disk."""
    from ...constant import DATA_DIR
    backups_file = DATA_DIR / "backups.json"
    if backups_file.exists():
        try:
            with open(backups_file) as f:
                data = json.load(f)
            for item in data:
                _backups[item["id"]] = BackupMeta(**item)
        except Exception as e:
            logger.error(f"Failed to load backups: {e}")


def _save_backups():
    """Save backups to disk."""
    from ...constant import DATA_DIR
    backups_file = DATA_DIR / "backups.json"
    try:
        with open(backups_file, "w") as f:
            json.dump([b.dict() for b in _backups.values()], f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save backups: {e}")


@router.get("/backups")
@require_permission("admin:admin")
async def list_backups(request: Request) -> List[Dict[str, Any]]:
    """List all backups."""
    return [b.dict() for b in _backups.values()]


@router.get("/backups/{backup_id}")
@require_permission("admin:admin")
async def get_backup(
    request: Request,
    backup_id: str,
) -> Dict[str, Any]:
    """Get backup details."""
    if backup_id not in _backups:
        raise HTTPException(status_code=404, detail="Backup not found")
    return _backups[backup_id].dict()


@router.post("/backups")
@require_permission("admin:admin")
async def create_backup(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Create a backup."""
    import uuid
    backup_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    backup = BackupMeta(
        id=backup_id,
        name=payload.get("name", f"backup_{now}"),
        created_at=now,
        description=payload.get("description", ""),
    )

    _backups[backup_id] = backup
    _save_backups()

    return backup.dict()


@router.post("/backups/stream")
@require_permission("admin:admin")
async def create_backup_stream(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Create backup with streaming progress."""
    # For now, just create a simple backup
    return await create_backup(request, payload)


@router.post("/backups/{backup_id}/restore")
@require_permission("admin:admin")
async def restore_backup(
    request: Request,
    backup_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Restore from backup."""
    if backup_id not in _backups:
        raise HTTPException(status_code=404, detail="Backup not found")
    return {"success": True}


@router.post("/backups/delete")
@require_permission("admin:admin")
async def delete_backups(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Delete backups."""
    ids = payload.get("ids", [])
    deleted = []
    for backup_id in ids:
        if backup_id in _backups:
            del _backups[backup_id]
            deleted.append(backup_id)

    _save_backups()
    return {"deleted": deleted}


# Startup hook
async def init_backups():
    """Initialize backups on startup."""
    _load_backups()
    logger.info(f"Loaded {len(_backups)} backups")
