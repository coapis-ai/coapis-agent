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

"""Local models router - Local model endpoints (CoApis console compatible)."""

import logging
from typing import Dict, Any, List, Optional

from ..permissions.decorators import require_permission
from fastapi import APIRouter, HTTPException, Body
from fastapi.requests import Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["local-models"])


@router.get("/local-models")
@require_permission("admin:admin")
async def get_local_models_info(request: Request) -> Dict[str, Any]:
    """Get local models information."""
    return {
        "available": False,
        "models": [],
    }


@router.get("/local-models/config")
@require_permission("admin:admin")
async def get_local_model_config(request: Request) -> Dict[str, Any]:
    """Get local model configuration."""
    return {
        "max_context_length": 128000,
        "port": None,
        "generate_kwargs": {},
    }


@router.put("/local-models/config")
@require_permission("admin:admin")
async def update_local_model_config(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update local model configuration."""
    return payload


@router.get("/local-models/server")
@require_permission("admin:admin")
async def get_local_server_status(request: Request) -> Dict[str, Any]:
    """Get local model server status."""
    return {
        "available": False,
        "installable": False,
        "installed": False,
        "port": None,
        "model_name": None,
        "message": "Local model server not configured",
    }


@router.put("/local-models/server")
@require_permission("admin:admin")
async def update_local_server(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update local model server configuration."""
    return {"success": True}


@router.post("/local-models/server/download")
@require_permission("admin:admin")
async def download_local_server(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Download local model server."""
    return {"success": False, "message": "Not supported"}


@router.get("/local-models/server/download")
@require_permission("admin:admin")
async def get_download_progress(request: Request) -> Dict[str, Any]:
    """Get download progress."""
    return {"progress": 0, "status": "idle"}


@router.post("/local-models/server/update")
@require_permission("admin:admin")
async def update_local_server_update(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update local model server."""
    return {"success": False, "message": "Not supported"}


@router.get("/local-models/models")
@require_permission("admin:admin")
async def list_local_models(request: Request) -> List[Dict[str, Any]]:
    """List available local models."""
    return []


@router.post("/local-models/models/download")
@require_permission("admin:admin")
async def download_local_model(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Download a local model."""
    return {"success": False, "message": "Not supported"}


@router.get("/local-models/models/download")
@require_permission("admin:admin")
async def get_model_download_progress(request: Request) -> Dict[str, Any]:
    """Get model download progress."""
    return {"progress": 0, "status": "idle"}
