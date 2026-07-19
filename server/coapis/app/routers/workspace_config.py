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
    """Get the workspace directory for the current user (not agent)."""
    from ...constant import WORKSPACES_DIR
    
    # Get username from request state
    username = getattr(request.state, 'username', None)
    
    # If username available, return user's workspace directory
    if username:
        user_workspace = WORKSPACES_DIR / username
        if user_workspace.exists():
            return user_workspace
    
    # Fallback: use first agent's workspace (backward compatibility)
    from ...constant import AGENTS_DIR
    manager = getattr(request.app.state, 'multi_agent_manager', None)
    if not manager:
        return AGENTS_DIR / "global_default"

    # Get first agent's workspace (or default)
    for agent_id, workspace in manager._workspaces.items():
        return workspace.workspace_dir

    return AGENTS_DIR / "global_default"


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

    # Debug log
    logger.info(f"[list_memory_files] workspace_dir={workspace_dir}, memory_dir={memory_dir}, exists={memory_dir.exists()}")

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


@router.get("/workspace/memory/{date}.md")
@require_permission("myspace:read")
async def load_daily_memory(
    request: Request,
    date: str,
) -> Dict[str, Any]:
    """Load daily memory file content.
    
    Args:
        date: Date string in YYYY-MM-DD format
    
    Returns:
        { content: str, exists: bool, path: str }
    """
    workspace_dir = _get_workspace_dir(request)
    memory_dir = workspace_dir / "memory"
    
    # Validate date format
    if not date.endswith(".md"):
        date = f"{date}.md"
    
    # Security: prevent path traversal
    if ".." in date or "/" in date or "\\" in date:
        raise HTTPException(400, "Invalid date format")
    
    memory_file = memory_dir / date
    
    if not memory_file.exists():
        return {
            "content": "",
            "exists": False,
            "path": str(memory_file.relative_to(workspace_dir)),
        }
    
    try:
        content = memory_file.read_text(encoding="utf-8")
        return {
            "content": content,
            "exists": True,
            "path": str(memory_file.relative_to(workspace_dir)),
        }
    except Exception as e:
        logger.error(f"Failed to read memory file {memory_file}: {e}")
        raise HTTPException(500, f"Failed to read memory file: {e}")


@router.put("/workspace/memory/{date}.md")
@require_permission("myspace:write")
async def save_daily_memory(
    request: Request,
    date: str,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Save daily memory file content.
    
    Args:
        date: Date string in YYYY-MM-DD format
        body: { content: str }
    
    Returns:
        { ok: bool, path: str, size: int }
    """
    workspace_dir = _get_workspace_dir(request)
    memory_dir = workspace_dir / "memory"
    
    # Validate date format
    if not date.endswith(".md"):
        date = f"{date}.md"
    
    # Security: prevent path traversal
    if ".." in date or "/" in date or "\\" in date:
        raise HTTPException(400, "Invalid date format")
    
    # Create memory directory if not exists
    memory_dir.mkdir(parents=True, exist_ok=True)
    
    memory_file = memory_dir / date
    content = body.get("content", "")
    
    try:
        memory_file.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "path": str(memory_file.relative_to(workspace_dir)),
            "size": len(content.encode("utf-8")),
        }
    except Exception as e:
        logger.error(f"Failed to save memory file {memory_file}: {e}")
        raise HTTPException(500, f"Failed to save memory file: {e}")


@router.get("/workspace/memory/content")
@require_permission("myspace:read")
async def get_memory_content(
    request: Request,
    level: str = Query("user", description="Memory level: 'user' or 'agent'"),
    agent_id: Optional[str] = Query(None, description="Agent ID (required when level=agent)"),
) -> Dict[str, Any]:
    """Read MEMORY.md content at user or agent level.

    - level=user: reads workspaces/{username}/MEMORY.md
    - level=agent: reads agent's workspace_dir/MEMORY.md
    """
    username = getattr(request.state, "username", None)

    if level == "user":
        if not username:
            raise HTTPException(400, "username required for user-level memory")
        from ...constant import WORKSPACES_DIR
        memory_path = WORKSPACES_DIR / username / "MEMORY.md"
    elif level == "agent":
        # Resolve agent workspace_dir
        resolved_id = agent_id or _get_selected_agent_id(request)
        if not resolved_id:
            raise HTTPException(400, "agent_id required for agent-level memory")
        from ...config.config import derive_workspace_dir
        try:
            memory_path = derive_workspace_dir(resolved_id, username) / "MEMORY.md"
        except Exception as e:
            raise HTTPException(404, f"Agent not found: {e}")
    else:
        raise HTTPException(400, f"Invalid level: {level}, must be 'user' or 'agent'")

    content = ""
    if memory_path.exists():
        content = memory_path.read_text(encoding="utf-8")

    return {
        "level": level,
        "path": str(memory_path),
        "content": content,
        "exists": memory_path.exists(),
    }


class MemoryContentUpdate(BaseModel):
    content: str
    level: str = "user"
    agent_id: Optional[str] = None


@router.put("/workspace/memory/content")
@require_permission("myspace:write")
async def update_memory_content(
    request: Request,
    body: MemoryContentUpdate,
) -> Dict[str, Any]:
    """Write MEMORY.md content at user or agent level."""
    username = getattr(request.state, "username", None)
    level = body.level

    if level == "user":
        if not username:
            raise HTTPException(400, "username required for user-level memory")
        from ...constant import WORKSPACES_DIR
        memory_path = WORKSPACES_DIR / username / "MEMORY.md"
    elif level == "agent":
        resolved_id = body.agent_id or _get_selected_agent_id(request)
        if not resolved_id:
            raise HTTPException(400, "agent_id required for agent-level memory")
        from ...config.config import derive_workspace_dir
        try:
            memory_path = derive_workspace_dir(resolved_id, username) / "MEMORY.md"
        except Exception as e:
            raise HTTPException(404, f"Agent not found: {e}")
    else:
        raise HTTPException(400, f"Invalid level: {level}")

    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(body.content, encoding="utf-8")

    return {
        "level": level,
        "path": str(memory_path),
        "size": len(body.content),
        "ok": True,
    }


@router.get("/workspace/system-prompt-files")
@require_permission("myspace:read")
async def list_system_prompt_files(
    request: Request,
    agent_id: Optional[str] = Query(None, description="Agent ID to query (defaults to current user's agent)"),
) -> List[str]:
    """List enabled system prompt files for an agent."""
    from ...config.config import load_agent_config

    # Resolve agent_id: explicit param > selected agent > user default
    resolved_agent_id = agent_id or _get_selected_agent_id(request)
    if not resolved_agent_id:
        # No agent context, return default list
        return ["AGENTS.md", "SOUL.md", "PROFILE.md"]

    try:
        config = load_agent_config(resolved_agent_id)
        return config.system_prompt_files or ["AGENTS.md", "SOUL.md", "PROFILE.md"]
    except Exception as e:
        logger.warning(f"Failed to load system_prompt_files for {resolved_agent_id}: {e}")
        return ["AGENTS.md", "SOUL.md", "PROFILE.md"]


@router.put("/workspace/system-prompt-files")
@require_permission("myspace:write")
async def set_system_prompt_files(
    request: Request,
    files: List[str] = Body(...),
    agent_id: Optional[str] = Query(None, description="Agent ID to update"),
) -> List[str]:
    """Update enabled system prompt files for an agent."""
    import json as _json
    from ...config.config import load_agent_config, derive_workspace_dir
    from ...config.utils import load_config

    resolved_agent_id = agent_id or _get_selected_agent_id(request)
    if not resolved_agent_id:
        raise HTTPException(status_code=400, detail="No agent_id specified")

    # Deduplicate and validate
    clean_files = list(dict.fromkeys(f for f in files if isinstance(f, str) and f.strip()))

    # Load current config, update system_prompt_files, save
    try:
        agent_config = load_agent_config(resolved_agent_id)
        agent_config.system_prompt_files = clean_files
    except Exception as e:
        logger.error(f"Failed to load agent config for {resolved_agent_id}: {e}")
        raise HTTPException(status_code=404, detail=f"Agent '{resolved_agent_id}' not found")

    # Write directly to agent.json to preserve all fields
    try:
        config = load_config()
        # Resolve workspace_dir from disk (no profiles dependency)
        from ..user_store import get_user_workspace_dir, get_user_agents_dir
        caller = ""  # caller not available here, derive from agent_id
        if resolved_agent_id.startswith("user:") and ":" in resolved_agent_id:
            caller = resolved_agent_id.split(":", 1)[1]
        if caller:
            user_ws = get_user_workspace_dir(caller)
            user_agents = get_user_agents_dir(caller)
            if (user_ws / "agent.json").exists():
                workspace_dir = user_ws
            else:
                workspace_dir = user_agents / resolved_agent_id.split(":", 1)[1]
        else:
            from ...constant import AGENTS_DIR
            workspace_dir = AGENTS_DIR / resolved_agent_id
        agent_json_path = workspace_dir / "agent.json"

        if agent_json_path.exists():
            data = _json.loads(agent_json_path.read_text(encoding="utf-8"))
        else:
            data = {}

        data["system_prompt_files"] = clean_files
        agent_json_path.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Updated system_prompt_files for {resolved_agent_id}: {clean_files}")
    except Exception as e:
        logger.error(f"Failed to save system_prompt_files for {resolved_agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save configuration")

    return clean_files


def _get_selected_agent_id(request: Request) -> Optional[str]:
    """Extract selected agent ID from request context."""
    # Try from query param or header
    agent_id = request.headers.get("X-Agent-Id")
    if agent_id:
        return agent_id
    # Try from multi_agent_manager state
    manager = getattr(request.app.state, 'multi_agent_manager', None)
    if manager:
        username = getattr(request.state, 'username', None)
        if username:
            return f"user:{username}"
    return None


# ── Running Config (user+) ──────────────────────────────────────────────

@router.get("/workspace/running-config")
@require_permission("chat:configure")
async def get_running_config(request: Request) -> Dict[str, Any]:
    """Get agent running configuration."""
    from coapis.config.config import AgentsRunningConfig
    
    # Use default values from AgentsRunningConfig
    default_config = AgentsRunningConfig()
    config_dict = default_config.model_dump()
    
    # Add scene field (not part of AgentsRunningConfig)
    config_dict["scene"] = None
    
    return config_dict


@router.put("/workspace/running-config")
@require_permission("chat:configure")
async def update_running_config(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update agent running configuration."""
    from coapis.config.config import load_agent_config, save_agent_config
    from coapis.agents.workspace import get_request_agent_id
    
    agent_id = get_request_agent_id(request)
    if not agent_id:
        raise HTTPException(status_code=400, detail="Agent ID not found")
    
    # Load current agent config
    agent_config = load_agent_config(agent_id)
    
    # Update running config fields
    for key, value in payload.items():
        if hasattr(agent_config.running, key):
            setattr(agent_config.running, key, value)
    
    # Save to agent.json
    save_agent_config(agent_id, agent_config)
    
    return agent_config.running.model_dump()


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
