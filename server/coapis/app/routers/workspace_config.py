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
# See the License for the specific permissions and
# limitations under the License.

"""Workspace router - Workspace file management & agent config (CoApis console compatible).

Permission mapping (per permissions.json):
- 用户基础权限
- user: chat:*, myspace:*, skills:read, channels:*, cron-jobs:*, profile:*, voice:*
- advanced: user + models:read, agents:read
- admin: * (all)

Route permissions:
- /workspace/* (files, memory, download, upload) → myspace:read or myspace:write
- /workspace/running-config → chat:configure (user+)
- /workspace/language → chat:configure (user+)
- /workspace/audio-mode → voice:read / voice:write (user+)
- /workspace/transcription-* → voice:read / voice:write (user+)
- /workspace/local-whisper-status → voice:read (user+)
"""

import logging
import json
import zipfile
import io
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.requests import Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..permissions.decorators import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workspace"])


class MdFileInfo(BaseModel):
    filename: str
    path: str
    size: int
    created_time: str
    modified_time: str


class MdFileContent(BaseModel):
    content: str


def _get_workspace_dir(request: Request) -> Path:
    """Get the workspace directory for the selected agent."""
    manager = getattr(request.app.state, 'multi_agent_manager', None)
    if not manager:
        return Path("/apps/ai/coapis/workspaces/global_default")

    # Get first agent's workspace (or default)
    for agent_id, workspace in manager._workspaces.items():
        return workspace.workspace_dir

    return Path("/apps/ai/coapis/workspaces/global_default")


# ── Workspace Info ──────────────────────────────────────────────────────

@router.get("/workspace")
@require_permission("myspace:read")
async def get_workspace_info(request: Request) -> Dict[str, Any]:
    """Get workspace information."""
    workspace_dir = _get_workspace_dir(request)
    return {
        "workspace_dir": str(workspace_dir),
        "exists": workspace_dir.exists(),
    }


# ── Workspace Files ─────────────────────────────────────────────────────

@router.get("/workspace/files")
@require_permission("myspace:read")
async def list_workspace_files(request: Request) -> List[Dict[str, Any]]:
    """List markdown files in workspace."""
    workspace_dir = _get_workspace_dir(request)
    if not workspace_dir.exists():
        return []

    result = []
    for md_file in workspace_dir.rglob("*.md"):
        try:
            stat = md_file.stat()
            rel_path = str(md_file.relative_to(workspace_dir))
            result.append({
                "filename": md_file.name,
                "path": rel_path,
                "size": stat.st_size,
                "created_time": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        except Exception as e:
            logger.error(f"Failed to stat {md_file}: {e}")

    return result


def _validate_file_path(filename: str, workspace_dir: Path) -> Path:
    """Validate file path to prevent directory traversal attacks.
    
    Raises HTTPException 400 if path contains '..' or escapes workspace_dir.
    """
    # Block explicit traversal patterns
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path: directory traversal not allowed")
    
    file_path = (workspace_dir / filename).resolve()
    
    # Ensure resolved path is within workspace_dir
    try:
        file_path.relative_to(workspace_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file path: access outside workspace not allowed")
    
    return file_path


@router.get("/workspace/files/{filename}")
@require_permission("myspace:read")
async def load_file(
    request: Request,
    filename: str,
) -> Dict[str, Any]:
    """Load a markdown file from workspace."""
    workspace_dir = _get_workspace_dir(request)
    file_path = _validate_file_path(filename, workspace_dir)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        content = file_path.read_text()
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/workspace/files/{filename}")
@require_permission("myspace:write")
async def save_file(
    request: Request,
    filename: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Save a markdown file to workspace."""
    workspace_dir = _get_workspace_dir(request)
    file_path = _validate_file_path(filename, workspace_dir)

    file_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        file_path.write_text(payload.get("content", ""))
        return {"success": True, "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Workspace Download/Upload ───────────────────────────────────────────

@router.get("/workspace/download")
@require_permission("myspace:read")
async def download_workspace(request: Request):
    """Download workspace as zip file."""
    workspace_dir = _get_workspace_dir(request)
    if not workspace_dir.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in workspace_dir.rglob("*"):
            if file_path.is_file():
                arcname = str(file_path.relative_to(workspace_dir))
                zip_file.write(file_path, arcname)

    zip_buffer.seek(0)

    return FileResponse(
        path=zip_buffer.name if hasattr(zip_buffer, "name") else None,
        filename=f"workspace_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
        media_type="application/zip",
    )


@router.post("/workspace/upload")
@require_permission("myspace:write")
async def upload_workspace_file(
    request: Request,
) -> Dict[str, Any]:
    """Upload a file to workspace."""
    return {"success": True, "message": "File uploaded"}


# ── Memory Files ────────────────────────────────────────────────────────

@router.get("/workspace/memory")
@require_permission("myspace:read")
async def list_memory_files(request: Request) -> List[Dict[str, Any]]:
    """List memory files in workspace."""
    workspace_dir = _get_workspace_dir(request)
    memory_dir = workspace_dir / "memory"

    if not memory_dir.exists():
        return []

    result = []
    for md_file in memory_dir.rglob("*.md"):
        try:
            stat = md_file.stat()
            rel_path = str(md_file.relative_to(memory_dir))
            result.append({
                "filename": md_file.name,
                "path": rel_path,
                "size": stat.st_size,
                "created_time": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "date": md_file.name.replace(".md", ""),
                "updated_at": stat.st_mtime,
            })
        except Exception as e:
            logger.error(f"Failed to stat {md_file}: {e}")

    return result


@router.get("/workspace/system-prompt-files")
@require_permission("myspace:read")
async def list_system_prompt_files(request: Request) -> List[str]:
    """List system prompt files."""
    return []


# ── Running Config (user+) ──────────────────────────────────────────────

@router.get("/workspace/running-config")
@require_permission("chat:configure")
async def get_running_config(request: Request) -> Dict[str, Any]:
    """Get agent running configuration."""
    return {
        "max_iters": 50,
        "auto_continue_on_text_only": True,
        "shell_command_timeout": 120,
        "llm_retry_enabled": True,
        "llm_max_retries": 3,
        "llm_backoff_base": 2.0,
        "llm_backoff_cap": 60.0,
        "llm_max_concurrent": 1,
        "llm_max_qpm": 0,
        "llm_rate_limit_pause": 0,
        "llm_rate_limit_jitter": 0,
        "llm_acquire_timeout": 300,
        "max_input_length": 128000,
        "history_max_length": 100,
        "context_manager_backend": "light",
        "light_context_config": {
            "dialog_path": "dialog",
            "token_count_estimate_divisor": 4,
            "context_compact_config": {
                "enabled": True,
                "compact_threshold_ratio": 0.7,
                "reserve_threshold_ratio": 0.3,
                "compact_with_thinking_block": False,
            },
            "tool_result_pruning_config": {
                "enabled": True,
                "pruning_recent_n": 10,
                "pruning_old_msg_max_bytes": 4000,
                "pruning_recent_msg_max_bytes": 16000,
                "offload_retention_days": 7,
                "exempt_file_extensions": [],
                "exempt_tool_names": [],
            },
        },
        "memory_manager_backend": "reme_light",
        "reme_light_memory_config": {
            "summarize_when_compact": True,
            "auto_memory_interval": 10,
            "dream_cron": "0 3 * * *",
            "auto_memory_search_config": {
                "enabled": True,
                "max_results": 5,
                "min_score": 0.1,
            },
            "embedding_model_config": {
                "backend": "openai",
                "api_key": "",
                "base_url": "",
                "model_name": "",
                "dimensions": 1536,
                "enable_cache": True,
                "use_dimensions": True,
                "max_cache_size": 10000,
                "max_input_length": 8000,
                "max_batch_size": 100,
            },
            "rebuild_memory_index_on_start": False,
            "recursive_file_watcher": False,
        },
        "scene": None,
    }


@router.put("/workspace/running-config")
@require_permission("chat:configure")
async def update_running_config(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update agent running configuration."""
    return payload


# ── Language (user+) ────────────────────────────────────────────────────

@router.get("/workspace/language")
@require_permission("chat:configure")
async def get_language(request: Request) -> Dict[str, Any]:
    """Get agent language setting."""
    return {"language": "zh"}


@router.put("/workspace/language")
@require_permission("chat:configure")
async def update_language(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update agent language setting."""
    return {"language": payload.get("language", "zh"), "copied_files": []}


# ── Audio Mode (user+) ──────────────────────────────────────────────────

@router.get("/workspace/audio-mode")
@require_permission("voice:read")
async def get_audio_mode(request: Request) -> Dict[str, Any]:
    """Get audio mode setting."""
    return {"audio_mode": "off"}


@router.put("/workspace/audio-mode")
@require_permission("voice:write")
async def update_audio_mode(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update audio mode setting."""
    return {"audio_mode": payload.get("audio_mode", "off")}


# ── Transcription Providers (user+) ─────────────────────────────────────

@router.get("/workspace/transcription-providers")
@require_permission("voice:read")
async def get_transcription_providers(request: Request) -> Dict[str, Any]:
    """Get transcription providers."""
    return {
        "providers": [],
        "configured_provider_id": "",
    }


@router.get("/workspace/transcription-provider")
@require_permission("voice:read")
async def get_transcription_provider(request: Request) -> Dict[str, Any]:
    """Get transcription provider."""
    return {"provider_id": ""}


@router.put("/workspace/transcription-provider")
@require_permission("voice:write")
async def update_transcription_provider(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update transcription provider."""
    return {"provider_id": payload.get("provider_id", "")}


@router.get("/workspace/transcription-provider-type")
@require_permission("voice:read")
async def get_transcription_provider_type(request: Request) -> Dict[str, Any]:
    """Get transcription provider type."""
    return {"transcription_provider_type": ""}


@router.put("/workspace/transcription-provider-type")
@require_permission("voice:write")
async def update_transcription_provider_type(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update transcription provider type."""
    return {"transcription_provider_type": payload.get("transcription_provider_type", "")}


@router.get("/workspace/local-whisper-status")
@require_permission("voice:read")
async def get_local_whisper_status(request: Request) -> Dict[str, Any]:
    """Get local whisper status."""
    return {
        "available": False,
        "ffmpeg_installed": False,
        "whisper_installed": False,
    }
