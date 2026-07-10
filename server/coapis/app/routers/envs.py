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

"""Envs router - Environment variables endpoints (CoApis console compatible)."""

import logging
import json
from pathlib import Path
from typing import Dict, Any, List

from ..permissions.decorators import require_permission
from fastapi import APIRouter, HTTPException, Body
from fastapi.requests import Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["envs"])


class EnvVar(BaseModel):
    key: str
    value: str


# In-memory env store
_envs: Dict[str, str] = {}


def _load_envs():
    """Load envs from disk."""
    from ...constant import DATA_DIR
    envs_file = DATA_DIR / "envs.json"
    if envs_file.exists():
        try:
            with open(envs_file) as f:
                _envs.update(json.load(f))
        except Exception as e:
            logger.error(f"Failed to load envs: {e}")


def _save_envs():
    """Save envs to disk."""
    from ...constant import DATA_DIR
    envs_file = DATA_DIR / "envs.json"
    try:
        with open(envs_file, "w") as f:
            json.dump(_envs, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save envs: {e}")


@router.get("/envs")
@require_permission("admin:admin")
async def list_envs(request: Request) -> List[Dict[str, Any]]:
    """List all environment variables."""
    return [{"key": k, "value": v} for k, v in _envs.items()]


@router.put("/envs")
@require_permission("admin:admin")
async def save_envs(
    request: Request,
    payload: Dict[str, str] = Body(...),
) -> List[Dict[str, Any]]:
    """Batch save environment variables (full replacement)."""
    _envs.clear()
    _envs.update(payload)
    _save_envs()
    return [{"key": k, "value": v} for k, v in _envs.items()]


@router.delete("/envs/{key}")
@require_permission("admin:admin")
async def delete_env(
    request: Request,
    key: str,
) -> List[Dict[str, Any]]:
    """Delete an environment variable."""
    if key in _envs:
        del _envs[key]
        _save_envs()
    return [{"key": k, "value": v} for k, v in _envs.items()]


# Startup hook
async def init_envs():
    """Initialize envs on startup."""
    _load_envs()
    logger.info(f"Loaded {len(_envs)} env vars")
