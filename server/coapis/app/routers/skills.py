# -*- coding: utf-8 -*-
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

"""Workspace and skill-pool APIs."""

from __future__ import annotations

import asyncio
import copy
import io
import json
import logging
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)

from ..permissions.decorators import require_permission

from ...agents.skills_hub import (
    SkillImportCancelled,
    search_hub_skills,
    import_pool_skill_from_hub,
    install_skill_from_hub,
)
from ...agents.skills_manager import (
    _BUILTIN_SKILL_LANGUAGES,
    SkillConflictError,
    SkillPoolService,
    SkillInfo,
    SkillService,
    _default_pool_manifest,
    _default_workspace_manifest,
    _get_skill_mtime,
    _mutate_json,
    _read_skill_from_dir,
    ensure_skills_initialized,
    get_pool_builtin_update_notice,
    get_pool_builtin_sync_status,
    get_pool_skill_manifest_path,
    get_skill_pool_dir,
    get_workspace_skill_manifest_path,
    get_workspace_skills_dir,
    import_builtin_skills,
    list_builtin_import_candidates,
    list_workspaces,
    read_skill_pool_manifest,
    read_skill_manifest,
    reconcile_pool_manifest,
    reconcile_workspace_manifest,
    suggest_conflict_name,
    update_single_builtin,
)
from ...security.skill_scanner import SkillScanError
from ..utils import schedule_agent_reload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skills", tags=["skills"])

MAX_TAGS = 8
MAX_TAG_LENGTH = 16


def _scan_error_payload(exc: SkillScanError) -> dict[str, Any]:
    """Normalize scanner exceptions into a stable API payload.

    Example response body:
        {
            "type": "security_scan_failed",
            "skill_name": "blocked_skill",
            "max_severity": "high",
            "findings": [...]
        }
    """
    result = exc.result
    return {
        "type": "security_scan_failed",
        "detail": str(exc),
        "skill_name": result.skill_name,
        "max_severity": result.max_severity.value,
        "findings": [
            {
                "severity": f.severity.value,
                "title": f.title,
                "description": f.description,
                "file_path": f.file_path,
                "line_number": f.line_number,
                "rule_id": f.rule_id,
            }
            for f in result.findings
        ],
    }


def _scan_error_response(exc: SkillScanError) -> JSONResponse:
    """Build a 422 JSON response for skill scan failures.

    Returns a JSONResponse so callers receive structured scan
    details rather than a bare HTTP error.
    """
    return JSONResponse(
        status_code=422,
        content=_scan_error_payload(exc),
    )


class SkillSpec(SkillInfo):
    enabled: bool = False
    channels: list[str] = Field(default_factory=lambda: ["all"])
    tags: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    last_updated: str = ""
    category: str = ""
    priority: str = ""
    source: str = ""


class PoolSkillSpec(SkillInfo):
    protected: bool = False
    commit_text: str = ""
    sync_status: str = ""
    latest_version_text: str = ""
    builtin_language: str = ""
    available_builtin_languages: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    last_updated: str = ""


class WorkspaceSkillSummary(BaseModel):
    agent_id: str
    agent_name: str = ""
    workspace_dir: str
    skills: list[SkillSpec] = Field(default_factory=list)


class HubSkillSpec(BaseModel):
    slug: str
    name: str
    description: str = ""
    version: str = ""
    source_url: str = ""


class BuiltinImportSpec(BaseModel):
    name: str
    description: str = ""
    version_text: str = ""
    current_version_text: str = ""
    current_source: str = ""
    current_language: str = ""
    available_languages: list[str] = Field(default_factory=list)
    languages: dict[str, dict[str, Any]] = Field(default_factory=dict)
    status: str = ""


class BuiltinRemovedSpec(BaseModel):
    name: str
    description: str = ""
    current_version_text: str = ""
    current_source: str = ""


class BuiltinUpdateNotice(BaseModel):
    fingerprint: str = ""
    has_updates: bool = False
    total_changes: int = 0
    actionable_skill_names: list[str] = Field(default_factory=list)
    added: list[BuiltinImportSpec] = Field(default_factory=list)
    missing: list[BuiltinImportSpec] = Field(default_factory=list)
    updated: list[BuiltinImportSpec] = Field(default_factory=list)
    removed: list[BuiltinRemovedSpec] = Field(default_factory=list)


class BuiltinImportSelection(BaseModel):
    skill_name: str
    language: str = ""


class ImportBuiltinRequest(BaseModel):
    skill_names: list[str] = Field(
        default_factory=list,
    )  # Deprecated: use imports
    imports: list[BuiltinImportSelection] = Field(default_factory=list)
    overwrite_conflicts: bool = False


class UpdateBuiltinRequest(BaseModel):
    language: str = ""


class CreateSkillRequest(BaseModel):
    name: str
    content: str
    references: dict[str, Any] | None = None
    scripts: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    enable: bool = True


class UploadToPoolRequest(BaseModel):
    workspace_id: str
    skill_name: str
    overwrite: bool = False
    preview_only: bool = False


class PoolDownloadTarget(BaseModel):
    workspace_id: str


class DownloadFromPoolRequest(BaseModel):
    skill_name: str
    targets: list[PoolDownloadTarget] = Field(default_factory=list)
    all_workspaces: bool = False
    overwrite: bool = False
    preview_only: bool = False


class SkillConfigRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class SavePoolSkillRequest(BaseModel):
    name: str
    content: str
    source_name: str | None = None
    config: dict[str, Any] | None = None
    overwrite: bool = False


class SaveSkillRequest(BaseModel):
    name: str
    content: str
    source_name: str | None = None
    config: dict[str, Any] | None = None
    category: str | None = None
    overwrite: bool = False


class HubInstallRequest(BaseModel):
    bundle_url: str = Field(..., description="Skill URL")
    version: str = Field(default="", description="Optional version tag")
    enable: bool = Field(default=True, description="Enable after import")
    target_name: str = Field(default="", description="Optional renamed skill")


class ExportSkillsRequest(BaseModel):
    skill_names: list[str] = Field(..., description="技能名称列表")
    workspace_id: str = Field(default="", description="工作区ID（为空时使用当前用户）")


class HubInstallTaskStatus(str, Enum):
    PENDING = "pending"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HubInstallTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bundle_url: str
    version: str = ""
    enable: bool = True
    status: HubInstallTaskStatus = HubInstallTaskStatus.PENDING
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


_hub_install_tasks: dict[str, HubInstallTask] = {}
_hub_install_runtime_tasks: dict[str, asyncio.Task] = {}
_hub_install_cancel_events: dict[str, threading.Event] = {}
_hub_install_lock = asyncio.Lock()

_ALLOWED_ZIP_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


def _workspace_dir_for_agent(agent_id: str) -> Path:
    for workspace in list_workspaces():
        if workspace["agent_id"] == agent_id:
            return Path(workspace["workspace_dir"])
    raise HTTPException(
        status_code=404,
        detail=f"Workspace '{agent_id}' not found",
    )


def _snapshot_workspace_skill(
    workspace_dir: Path,
    skill_name: str,
) -> dict[str, Any]:
    manifest = read_skill_manifest(workspace_dir)
    entry = manifest.get("skills", {}).get(skill_name)
    skill_dir = workspace_dir / "skills" / skill_name
    backup_dir: Path | None = None
    if skill_dir.exists():
        backup_root = Path(
            tempfile.mkdtemp(prefix=f"coapis_skill_rollback_{skill_name}_"),
        )
        backup_dir = backup_root / skill_name
        shutil.copytree(skill_dir, backup_dir)
    return {
        "workspace_dir": workspace_dir,
        "skill_name": skill_name,
        "entry": copy.deepcopy(entry) if entry is not None else None,
        "backup_dir": backup_dir,
    }


def _restore_workspace_skill(snapshot: dict[str, Any]) -> None:
    workspace_dir = Path(snapshot["workspace_dir"])
    skill_name = str(snapshot["skill_name"])
    skill_dir = workspace_dir / "skills" / skill_name
    backup_dir = snapshot.get("backup_dir")
    entry = snapshot.get("entry")

    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    if backup_dir is not None and Path(backup_dir).exists():
        shutil.copytree(Path(backup_dir), skill_dir)

    def _restore(payload: dict[str, Any]) -> None:
        payload.setdefault("skills", {})
        if entry is None:
            payload["skills"].pop(skill_name, None)
            return
        payload["skills"][skill_name] = copy.deepcopy(entry)

    _mutate_json(
        get_workspace_skill_manifest_path(workspace_dir),
        _default_workspace_manifest(),
        _restore,
    )
    reconcile_workspace_manifest(workspace_dir)
    if backup_dir is not None:
        shutil.rmtree(Path(backup_dir).parent, ignore_errors=True)


async def _request_workspace_dir(request: Request) -> Path:
    from ..agent_context import get_agent_for_request

    # If no agent_id is set, derive it from the authenticated username
    if not hasattr(request.state, "agent_id") or not request.state.agent_id:
        username = getattr(request.state, "username", None)
        if not username:
            user_info = getattr(request.state, "user_info", None)
            if user_info and isinstance(user_info, dict):
                username = user_info.get("username")
        if username and username != "anonymous":
            request.state.agent_id = f"user:{username}"

    workspace = await get_agent_for_request(request)
    return Path(workspace.workspace_dir)


async def _hub_task_set_status(
    task_id: str,
    status: HubInstallTaskStatus,
    *,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    async with _hub_install_lock:
        task = _hub_install_tasks.get(task_id)
        if task is None:
            return
        task.status = status
        task.updated_at = time.time()
        if error is not None:
            task.error = error
        if result is not None:
            task.result = result


async def _hub_task_get(task_id: str) -> HubInstallTask | None:
    async with _hub_install_lock:
        return _hub_install_tasks.get(task_id)


async def _hub_task_register_runtime(task_id: str, task: asyncio.Task) -> None:
    async with _hub_install_lock:
        _hub_install_runtime_tasks[task_id] = task


async def _hub_task_pop_runtime(task_id: str) -> asyncio.Task | None:
    async with _hub_install_lock:
        return _hub_install_runtime_tasks.pop(task_id, None)


async def _read_validated_zip_upload(file: UploadFile) -> bytes:
    if file.content_type and file.content_type not in _ALLOWED_ZIP_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Expected a zip file, "
                f"got content-type: {file.content_type}"
            ),
        )

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File too large ({len(data) // (1024 * 1024)} MB). "
                f"Maximum is {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            ),
        )
    return data


def _cleanup_imported_skill(workspace_dir: Path, skill_name: str) -> None:
    if not skill_name:
        return
    try:
        skill_service = SkillService(workspace_dir)
        skill_service.disable_skill(skill_name)
        skill_service.delete_skill(skill_name)
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Cleanup after cancelled import failed for '%s': %s",
            skill_name,
            exc,
        )


async def _run_hub_install_task(
    *,
    task_id: str,
    workspace_dir: Path,
    body: HubInstallRequest,
    cancel_event: threading.Event,
) -> None:
    await _hub_task_set_status(task_id, HubInstallTaskStatus.IMPORTING)
    imported_skill_name: str | None = None
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: install_skill_from_hub(
                workspace_dir=workspace_dir,
                bundle_url=body.bundle_url,
                version=body.version,
                enable=body.enable,
                target_name=body.target_name,
                cancel_checker=cancel_event.is_set,
            ),
        )
        imported_skill_name = result.name
        if cancel_event.is_set():
            _cleanup_imported_skill(workspace_dir, result.name)
            await _hub_task_set_status(
                task_id,
                HubInstallTaskStatus.CANCELLED,
                result={
                    "installed": False,
                    "name": result.name,
                    "enabled": False,
                    "source_url": result.source_url,
                },
            )
            return
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.COMPLETED,
            result={
                "installed": True,
                "name": result.name,
                "enabled": result.enabled,
                "source_url": result.source_url,
            },
        )
    except SkillImportCancelled:
        if imported_skill_name:
            _cleanup_imported_skill(workspace_dir, imported_skill_name)
        await _hub_task_set_status(task_id, HubInstallTaskStatus.CANCELLED)
    except SkillScanError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
            result=_scan_error_payload(exc),
        )
    except (ValueError, AppBaseException) as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
        )
    except SkillConflictError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
            result=exc.detail,
        )
    except RuntimeError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
        )
    except Exception as exc:  # pragma: no cover
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=f"Skill hub import failed: {exc}",
        )
    finally:
        await _hub_task_pop_runtime(task_id)


def _build_workspace_skill_specs(workspace_dir: Path) -> list[SkillSpec]:
    manifest = read_skill_manifest(workspace_dir)
    entries = manifest.get("skills", {})

    # Handle case where entries might be a list instead of dict (malformed manifest)
    if isinstance(entries, list):
        entries = {}
    elif not isinstance(entries, dict):
        entries = {}

    skill_root = get_workspace_skills_dir(workspace_dir)
    # Skill pool for fallback when skill not in workspace
    from coapis.agents.skills_manager import get_skill_pool_dir
    pool_dir = get_skill_pool_dir()

    specs: list[SkillSpec] = []
    for skill_name, entry in sorted(entries.items()):
        entry_source = entry.get("source", "customized")
        skill_dir = skill_root / skill_name
        # Fallback: if not in workspace, try skill pool
        if not skill_dir.exists():
            pool_skill_dir = pool_dir / skill_name
            if pool_skill_dir.exists():
                skill_dir = pool_skill_dir
        skill = _read_skill_from_dir(skill_dir, entry_source)
        if skill is None:
            continue
        # Category fallback: if entry has no category, try global defaults
        entry_category = entry.get("category", "")
        if not entry_category:
            from coapis.agents.skills_manager import _read_global_defaults
            gdefs = _read_global_defaults()
            entry_category = gdefs.get("defaults", {}).get(skill_name, {}).get("category", "")
        dump = skill.model_dump()
        # Remove fields that will be explicitly set to avoid duplicate kwargs
        for conflict_key in ("source", "enabled", "channels", "config", "category", "priority"):
            dump.pop(conflict_key, None)
        dump["tags"] = entry.get("tags") or []
        specs.append(
            SkillSpec(
                **dump,
                enabled=entry.get("enabled", False),
                channels=entry.get("channels") or ["all"],
                config=entry.get("config") or {},
                last_updated=_get_skill_mtime(skill_dir),
                category=entry_category,
                priority=entry.get("priority", "core"),
                source=entry_source,
            ),
        )
    return specs


def _build_pool_skill_specs() -> list[PoolSkillSpec]:
    manifest = read_skill_pool_manifest()
    entries = manifest.get("skills", {})
    pool_dir = get_skill_pool_dir()
    sync_info = get_pool_builtin_sync_status(pool_skills=entries)
    specs: list[PoolSkillSpec] = []
    for skill_name, entry in sorted(entries.items()):
        source = entry.get("source", "customized")
        skill_dir = pool_dir / skill_name
        skill = _read_skill_from_dir(skill_dir, source)
        if skill is None:
            continue
        info = sync_info.get(skill_name, {})
        dump = skill.model_dump(exclude={"version_text"})
        dump["tags"] = entry.get("tags") or []
        specs.append(
            PoolSkillSpec(
                **dump,
                protected=bool(entry.get("protected", False)),
                version_text=str(entry.get("version_text", "") or ""),
                commit_text=str(entry.get("commit_text", "") or ""),
                sync_status=str(info.get("sync_status", "") or ""),
                latest_version_text=str(
                    info.get("latest_version_text", "") or "",
                ),
                builtin_language=str(
                    entry.get("builtin_language", "") or "",
                ),
                available_builtin_languages=[
                    str(language)
                    for language in (
                        info.get("available_languages")
                        or entry.get("available_builtin_languages")
                        or []
                    )
                    if str(language)
                ],
                config=entry.get("config") or {},
                last_updated=_get_skill_mtime(skill_dir),
            ),
        )
    return specs


@router.get("")
@require_permission("skills:read")
async def list_skills(request: Request) -> list[SkillSpec]:
    workspace_dir = await _request_workspace_dir(request)
    # Ensure global defaults are synced before listing
    ensure_skills_initialized(workspace_dir)
    all_skills = _build_workspace_skill_specs(workspace_dir)
    # "我的技能"只显示用户创建/导入的技能，不显示全局默认技能
    return [s for s in all_skills if s.source != "global"]


@router.post("/refresh")
@require_permission("skills:read")
async def refresh_skills(request: Request) -> list[SkillSpec]:
    """Force reconcile and return updated workspace skill list."""
    workspace_dir = await _request_workspace_dir(request)
    reconcile_workspace_manifest(workspace_dir)
    all_skills = _build_workspace_skill_specs(workspace_dir)
    # "我的技能"只显示用户创建/导入的技能，不显示全局默认技能
    return [s for s in all_skills if s.source != "global"]


@router.get("/hub/search")
@require_permission("skills:write")
async def search_hub(
    q: str = "",
    limit: int = 20,
) -> list[HubSkillSpec]:
    results = search_hub_skills(q, limit=limit)
    return [
        HubSkillSpec(
            slug=item.slug,
            name=item.name,
            description=item.description,
            version=item.version,
            source_url=item.source_url,
        )
        for item in results
    ]


@router.get("/workspaces")
@require_permission("skills:write")
async def list_workspace_skill_sources() -> list[WorkspaceSkillSummary]:
    summaries: list[WorkspaceSkillSummary] = []
    workspaces = list_workspaces()
    for workspace in workspaces:
        workspace_dir = Path(workspace["workspace_dir"])
        summaries.append(
            WorkspaceSkillSummary(
                agent_id=workspace["agent_id"],
                agent_name=workspace.get("agent_name", ""),
                workspace_dir=str(workspace_dir),
                skills=_build_workspace_skill_specs(workspace_dir),
            ),
        )
    return summaries


@router.post("/hub/install/start", response_model=HubInstallTask)
@require_permission("skills:write")
async def start_install_from_hub(
    request_body: HubInstallRequest,
    request: Request,
) -> HubInstallTask:
    workspace_dir = await _request_workspace_dir(request)
    task = HubInstallTask(
        bundle_url=request_body.bundle_url,
        version=request_body.version,
        enable=request_body.enable,
    )
    cancel_event = threading.Event()
    async with _hub_install_lock:
        _hub_install_tasks[task.task_id] = task
        _hub_install_cancel_events[task.task_id] = cancel_event

    runtime_task = asyncio.create_task(
        _run_hub_install_task(
            task_id=task.task_id,
            workspace_dir=workspace_dir,
            body=request_body,
            cancel_event=cancel_event,
        ),
        name=f"skill-hub-install-{task.task_id}",
    )
    await _hub_task_register_runtime(task.task_id, runtime_task)
    return task


@router.get("/hub/install/status/{task_id}", response_model=HubInstallTask)
@require_permission("skills:write")
async def get_hub_install_status(task_id: str) -> HubInstallTask:
    task = await _hub_task_get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="install task not found")
    return task


@router.post("/hub/install/cancel/{task_id}")
@require_permission("skills:write")
async def cancel_hub_install(request: Request, task_id: str) -> dict[str, Any]:
    async with _hub_install_lock:
        task = _hub_install_tasks.get(task_id)
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="install task not found",
            )
        if task.status in (
            HubInstallTaskStatus.COMPLETED,
            HubInstallTaskStatus.FAILED,
            HubInstallTaskStatus.CANCELLED,
        ):
            return {"task_id": task_id, "status": task.status.value}
        cancel_event = _hub_install_cancel_events.get(task_id)
        if cancel_event is not None:
            cancel_event.set()
        task.status = HubInstallTaskStatus.CANCELLED
        task.updated_at = time.time()
    return {"task_id": task_id, "status": "cancelled"}


@router.get("/pool")
@require_permission("skills:read")
async def list_pool_skills(request: Request) -> list[PoolSkillSpec]:
    return _build_pool_skill_specs()


@router.post("/pool/refresh")
@require_permission("skills:write")
async def refresh_pool_skills(request: Request) -> list[PoolSkillSpec]:
    """Force reconcile and return updated pool skill list."""
    reconcile_pool_manifest()
    return _build_pool_skill_specs()


@router.get("/pool/builtin-sources")
@require_permission("skills:read")
async def list_pool_builtin_sources(request: Request) -> list[BuiltinImportSpec]:
    return [
        BuiltinImportSpec(**item) for item in list_builtin_import_candidates()
    ]


@router.get("/pool/builtin-notice")
@require_permission("skills:read")
async def get_pool_builtin_notice(request: Request) -> BuiltinUpdateNotice:
    notice = get_pool_builtin_update_notice()
    return BuiltinUpdateNotice(
        fingerprint=str(notice.get("fingerprint", "") or ""),
        has_updates=bool(notice.get("has_updates", False)),
        total_changes=int(notice.get("total_changes", 0) or 0),
        actionable_skill_names=[
            str(name)
            for name in notice.get("actionable_skill_names", [])
            if str(name)
        ],
        added=[BuiltinImportSpec(**item) for item in notice.get("added", [])],
        missing=[
            BuiltinImportSpec(**item) for item in notice.get("missing", [])
        ],
        updated=[
            BuiltinImportSpec(**item) for item in notice.get("updated", [])
        ],
        removed=[
            BuiltinRemovedSpec(**item) for item in notice.get("removed", [])
        ],
    )


@router.post("")
@require_permission("skills:read")
async def create_skill(
    request: Request,
    body: CreateSkillRequest,
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    try:
        created = SkillService(workspace_dir).create_skill(
            name=body.name,
            content=body.content,
            references=body.references,
            scripts=body.scripts,
            config=body.config,
            enable=body.enable,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not created:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "conflict",
                "suggested_name": suggest_conflict_name(body.name),
            },
        )
    if body.enable:
        schedule_agent_reload(request, workspace.agent_id)
    return {"created": True, "name": created}


@router.post("/upload")
@require_permission("skills:read")
async def upload_skill_zip(
    request: Request,
    file: UploadFile = File(...),
    enable: bool = True,
    target_name: str = "",
    rename_map: str = "",
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    data = await _read_validated_zip_upload(file)
    parsed_rename: dict[str, str] | None = None
    if rename_map.strip():
        try:
            parsed_rename = json.loads(rename_map)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="rename_map must be valid JSON",
            ) from exc
        if not isinstance(parsed_rename, dict):
            raise HTTPException(
                status_code=400,
                detail="rename_map must be a JSON object",
            )
    try:
        result = await asyncio.to_thread(
            SkillService(workspace_dir).import_from_zip,
            data=data,
            enable=enable,
            target_name=target_name,
            rename_map=parsed_rename,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("conflicts"):
        raise HTTPException(status_code=409, detail=result)
    if enable and result.get("count", 0) > 0:
        schedule_agent_reload(request, workspace.agent_id)
    return result


@router.post("/export")
@require_permission("skills:read")
async def export_skills(
    request: Request,
    body: ExportSkillsRequest,
) -> StreamingResponse:
    """将指定技能打包为 ZIP 流式返回。"""
    workspace_id = body.workspace_id
    if not workspace_id:
        raise HTTPException(
            status_code=400,
            detail="workspace_id is required",
        )
    if workspace_id == "pool":
        skill_root = get_skill_pool_dir()
    else:
        workspace_dir = _workspace_dir_for_agent(workspace_id)
        skill_root = get_workspace_skills_dir(workspace_dir)

    buf = io.BytesIO()
    exported: list[str] = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in body.skill_names:
            skill_dir = skill_root / name
            if not skill_dir.exists() or not skill_dir.is_dir():
                continue
            for file_path in sorted(skill_dir.rglob("*")):
                if file_path.is_file():
                    arcname = f"{name}/{file_path.relative_to(skill_dir)}"
                    zf.write(file_path, arcname)
            exported.append(name)

    if not exported:
        raise HTTPException(
            status_code=404,
            detail="No valid skills found for the given names",
        )

    buf.seek(0)
    filename = (
        f"{exported[0]}.zip"
        if len(exported) == 1
        else f"skills_{len(exported)}.zip"
    )
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/pool/create")
@require_permission("skills:write")
async def create_pool_skill(request: Request, body: CreateSkillRequest) -> dict[str, Any]:
    try:
        created = SkillPoolService().create_skill(
            name=body.name,
            content=body.content,
            references=body.references,
            scripts=body.scripts,
            config=body.config,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not created:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "conflict",
                "suggested_name": suggest_conflict_name(body.name),
            },
        )
    return {"created": True, "name": created}


@router.put("/pool/save")
@require_permission("skills:write")
async def save_pool_skill(request: Request, body: SavePoolSkillRequest) -> dict[str, Any]:
    """Save one pool skill.

    ``overwrite`` only matters when the save would replace an existing target
    skill during rename/save-as.
    """
    service = SkillPoolService()
    try:
        result = service.save_pool_skill(
            skill_name=body.source_name or body.name,
            target_name=body.name,
            content=body.content,
            config=body.config,
            overwrite=body.overwrite,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        reason = result.get("reason")
        status = 404 if reason == "not_found" else 409
        raise HTTPException(status_code=status, detail=result)
    return result


@router.post("/pool/upload-zip")
@require_permission("skills:write")
async def upload_skill_pool_zip(request: Request,
    file: UploadFile = File(...),
    target_name: str = "",
    rename_map: str = "",
) -> dict[str, Any]:
    data = await _read_validated_zip_upload(file)
    parsed_rename: dict[str, str] | None = None
    if rename_map.strip():
        try:
            parsed_rename = json.loads(rename_map)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="rename_map must be valid JSON",
            ) from exc
        if not isinstance(parsed_rename, dict):
            raise HTTPException(
                status_code=400,
                detail="rename_map must be a JSON object",
            )
    try:
        result = await asyncio.to_thread(
            SkillPoolService().import_from_zip,
            data=data,
            target_name=target_name,
            rename_map=parsed_rename,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("conflicts"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/pool/import")
@require_permission("skills:write")
async def import_skill_pool_from_hub(request: Request,
    body: HubInstallRequest,
) -> dict[str, Any]:
    try:
        result = import_pool_skill_from_hub(
            bundle_url=body.bundle_url,
            version=body.version,
            target_name=body.target_name,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SkillConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "installed": True,
        "name": result.name,
        "enabled": False,
        "source_url": result.source_url,
    }


@router.post("/pool/upload")
@require_permission("skills:write")
async def upload_workspace_skill_to_pool(request: Request,
    body: UploadToPoolRequest,
) -> dict[str, Any]:
    workspace_dir = _workspace_dir_for_agent(body.workspace_id)
    try:
        result = SkillPoolService().upload_from_workspace(
            workspace_dir=workspace_dir,
            skill_name=body.skill_name,
            overwrite=body.overwrite,
            preview_only=body.preview_only,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        status = 404 if result.get("reason") == "not_found" else 409
        raise HTTPException(status_code=status, detail=result)
    return result


def _preflight_download_conflicts(
    hub_service: SkillPoolService,
    targets: list[PoolDownloadTarget],
    skill_name: str,
    overwrite: bool,
) -> list[dict[str, Any]]:
    """Check all targets for conflicts before downloading."""
    conflicts: list[dict[str, Any]] = []
    for target in targets:
        workspace_dir = _workspace_dir_for_agent(target.workspace_id)
        result = hub_service.preflight_download_to_workspace(
            skill_name=skill_name,
            workspace_dir=workspace_dir,
            overwrite=overwrite,
        )
        if not result.get("success"):
            conflicts.append(result)
    return conflicts


def _resolve_and_preflight(
    body: DownloadFromPoolRequest,
) -> tuple[list[PoolDownloadTarget], SkillPoolService]:
    """Resolve targets and reject if any conflicts exist."""
    targets = list(body.targets)
    if body.all_workspaces:
        targets = [
            PoolDownloadTarget(workspace_id=workspace["agent_id"])
            for workspace in list_workspaces()
        ]
    if not targets:
        raise HTTPException(
            status_code=400,
            detail="No workspace targets provided",
        )
    hub_service = SkillPoolService()
    try:
        conflicts = _preflight_download_conflicts(
            hub_service,
            targets,
            body.skill_name,
            body.overwrite,
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail={
                "downloaded": [],
                "conflicts": conflicts,
            },
        )
    return targets, hub_service


def _build_download_plan(
    targets: list[PoolDownloadTarget],
    skill_name: str,
) -> list[dict[str, Any]]:
    """Build execution plan with rollback snapshots."""
    plan: list[dict[str, Any]] = []
    for target in targets:
        workspace_dir = _workspace_dir_for_agent(target.workspace_id)
        snapshot = _snapshot_workspace_skill(
            workspace_dir,
            str(skill_name),
        )
        plan.append(
            {
                "workspace_id": target.workspace_id,
                "workspace_dir": workspace_dir,
                "snapshot": snapshot,
            },
        )
    return plan


@router.post("/pool/download")
@require_permission("skills:read")
async def download_pool_skill_to_workspaces(request: Request,
    body: DownloadFromPoolRequest,
) -> dict[str, Any]:
    """Download one pool skill into one or more workspaces.

    All-or-nothing: if any target conflicts, reject everything.

    Security: Non-admin users can only download to their own workspace.
    Admin users can download to any workspace.
    """
    # User isolation: non-admin can only download to their own workspace
    username = request.state.username
    role = getattr(request.state, "role", "user")

    if role != "admin":
        # Build set of allowed agent IDs for this user
        allowed_agent_ids = set()
        for workspace in list_workspaces():
            ws_username = workspace.get("username", "")
            if ws_username == username:
                allowed_agent_ids.add(workspace["agent_id"])

        # Filter explicit targets — keep only those belonging to this user
        filtered_targets = [
            t for t in body.targets
            if t.workspace_id in allowed_agent_ids
        ]

        # If no valid targets found, handle based on the target type:
        if not filtered_targets:
            if body.targets:
                # Check if any target belongs to another user (security violation)
                for t in body.targets:
                    for workspace in list_workspaces():
                        if workspace["agent_id"] == t.workspace_id:
                            ws_username = workspace.get("username", "")
                            if ws_username and ws_username != username:
                                # Target belongs to another user → reject
                                raise HTTPException(
                                    status_code=403,
                                    detail="Cannot download to other users' workspaces",
                                )
                            break
                # Target is a global/workspace-less agent → fallback to user's own agent
                if allowed_agent_ids:
                    filtered_targets = [
                        PoolDownloadTarget(workspace_id=aid)
                        for aid in allowed_agent_ids
                    ]
                else:
                    raise HTTPException(
                        status_code=403,
                        detail="No workspace found for current user",
                    )
            elif allowed_agent_ids:
                # No targets specified at all → auto-fallback to user's own agent
                filtered_targets = [
                    PoolDownloadTarget(workspace_id=aid)
                    for aid in allowed_agent_ids
                ]
            else:
                raise HTTPException(
                    status_code=403,
                    detail="No workspace found for current user",
                )

        body.targets = filtered_targets

        # CRITICAL: Disable all_workspaces for non-admin users
        # Otherwise _resolve_and_preflight will override our filter
        body.all_workspaces = False

    targets, hub_service = _resolve_and_preflight(body)
    if body.preview_only:
        return {"downloaded": []}

    execution_plan = _build_download_plan(targets, body.skill_name)

    downloaded: list[dict[str, str]] = []
    try:
        for plan in execution_plan:
            result = hub_service.download_to_workspace(
                skill_name=body.skill_name,
                workspace_dir=plan["workspace_dir"],
                overwrite=body.overwrite,
            )
            if not result.get("success"):
                for rollback in reversed(execution_plan):
                    _restore_workspace_skill(rollback["snapshot"])
                raise HTTPException(
                    status_code=409,
                    detail={
                        "downloaded": [],
                        "conflicts": [result],
                    },
                )
            downloaded.append(
                {
                    "workspace_id": str(plan["workspace_id"]),
                    "workspace_name": str(
                        result.get("workspace_name", "") or "",
                    ),
                    "name": str(result.get("name", "")),
                },
            )
    except HTTPException:
        raise
    except SkillScanError as exc:
        for rollback in reversed(execution_plan):
            _restore_workspace_skill(rollback["snapshot"])
        return _scan_error_response(exc)
    except Exception:
        for rollback in reversed(execution_plan):
            _restore_workspace_skill(rollback["snapshot"])
        raise
    finally:
        for plan in execution_plan:
            backup_dir = plan["snapshot"].get("backup_dir")
            if backup_dir is not None:
                shutil.rmtree(Path(backup_dir).parent, ignore_errors=True)

    return {"downloaded": downloaded}


@router.post("/pool/import-builtin")
@require_permission("skills:write")
async def import_pool_builtins(request: Request,
    body: ImportBuiltinRequest,
) -> dict[str, Any]:
    imports: list[dict[str, Any]] = (
        [item.model_dump() for item in body.imports]
        if body.imports
        else [{"skill_name": skill_name} for skill_name in body.skill_names]
    )
    result = import_builtin_skills(
        imports,
        overwrite_conflicts=body.overwrite_conflicts,
    )
    if result.get("conflicts") and not body.overwrite_conflicts:
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/pool/{skill_name}/update-builtin")
@require_permission("skills:write")
async def update_pool_builtin(request: Request,
    skill_name: str,
    body: UpdateBuiltinRequest | None = Body(default=None),
) -> dict[str, Any]:
    language = body.language if body is not None else ""
    if language and language not in _BUILTIN_SKILL_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid language '{language}', "
            f"must be one of {_BUILTIN_SKILL_LANGUAGES}",
        )
    try:
        return update_single_builtin(skill_name, language=language or None)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/pool/{skill_name}")
@require_permission("skills:write")
async def delete_pool_skill(request: Request, skill_name: str) -> dict[str, Any]:
    deleted = SkillPoolService().delete_skill(skill_name)
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Skill pool entry cannot be deleted",
        )
    return {"deleted": True}


@router.get("/pool/{skill_name}/config")
@require_permission("skills:write")
async def get_pool_skill_config(request: Request, skill_name: str) -> dict[str, Any]:
    manifest = read_skill_pool_manifest()
    entry = manifest.get("skills", {}).get(skill_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return {"config": entry.get("config", {})}


@router.put("/pool/{skill_name}/config")
@require_permission("skills:write")
async def update_pool_skill_config(request: Request,
    skill_name: str,
    body: SkillConfigRequest,
) -> dict[str, Any]:
    manifest_path = get_pool_skill_manifest_path()

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry["config"] = dict(body.config)
        return True

    updated = _mutate_json(manifest_path, _default_pool_manifest(), _update)
    if not updated:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return {"updated": True}


@router.delete("/pool/{skill_name}/config")
@require_permission("skills:write")
async def delete_pool_skill_config(request: Request, skill_name: str) -> dict[str, Any]:
    manifest_path = get_pool_skill_manifest_path()

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry.pop("config", None)
        return True

    updated = _mutate_json(manifest_path, _default_pool_manifest(), _update)
    if not updated:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return {"cleared": True}


def _validate_tags(tags: list[str]) -> list[str]:
    if len(tags) > MAX_TAGS:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_TAGS} tags allowed",
        )
    cleaned: list[str] = []
    for t in tags:
        t = str(t).strip()[:MAX_TAG_LENGTH]
        if t:
            cleaned.append(t)
    return cleaned


@router.put("/pool/{skill_name}/tags")
@require_permission("skills:write")
async def update_pool_skill_tags(request: Request,
    skill_name: str,
    tags: list[str],
) -> dict[str, Any]:
    tags = _validate_tags(tags)
    updated = SkillPoolService().set_pool_skill_tags(skill_name, tags)
    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Pool skill not found",
        )
    return {"updated": True, "tags": tags}


@router.post("/batch-delete")
@require_permission("skills:write")
async def batch_delete_skills(
    request: Request,
    skills: list[str],
) -> dict[str, Any]:
    """Auto-disable then delete each skill. Per-skill results."""
    workspace_dir = await _request_workspace_dir(request)
    service = SkillService(workspace_dir)
    results: dict[str, Any] = {}
    for skill_name in skills:
        try:
            service.disable_skill(skill_name)
            deleted = service.delete_skill(skill_name)
            results[skill_name] = {
                "success": deleted,
                "reason": None if deleted else "delete_failed",
            }
        except Exception as exc:
            results[skill_name] = {
                "success": False,
                "reason": str(exc),
            }
    return {"results": results}


@router.post("/pool/batch-delete")
@require_permission("skills:write")
async def batch_delete_pool_skills(request: Request,
    skills: list[str],
) -> dict[str, Any]:
    """Delete multiple pool skills. Per-skill results."""
    service = SkillPoolService()
    results: dict[str, Any] = {}
    for skill_name in skills:
        try:
            deleted = service.delete_skill(skill_name)
            results[skill_name] = {
                "success": deleted,
                "reason": None if deleted else "delete_failed",
            }
        except Exception as exc:
            results[skill_name] = {
                "success": False,
                "reason": str(exc),
            }
    return {"results": results}


@router.post("/batch-disable")
@require_permission("skills:write")
async def batch_disable_skills(
    request: Request,
    skills: list[str],
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    service = SkillService(workspace_dir)
    results = {skill: service.disable_skill(skill) for skill in skills}
    return {"results": results}


@router.post("/batch-enable")
@require_permission("skills:write")
async def batch_enable_skills(
    request: Request,
    skills: list[str],
) -> dict[str, Any]:
    """Enable each requested skill independently and collect per-skill results.

    Example:
        enabling ``["ok_skill", "blocked_skill"]`` returns success for the
        first item and ``reason="security_scan_failed"`` for the second,
        rather than aborting the entire batch.
    """
    workspace_dir = await _request_workspace_dir(request)
    service = SkillService(workspace_dir)
    results: dict[str, Any] = {}
    for skill in skills:
        try:
            results[skill] = service.enable_skill(skill)
        except SkillScanError as exc:
            results[skill] = {
                "success": False,
                "reason": "security_scan_failed",
                "detail": _scan_error_payload(exc),
            }
    return {"results": results}


@router.post("/{skill_name}/disable")
@require_permission("skills:write")
async def disable_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    result = SkillService(workspace_dir).disable_skill(skill_name)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail="Skill not found")
    schedule_agent_reload(request, workspace.agent_id)
    return {"disabled": True, **result}


@router.post("/{skill_name}/enable")
@require_permission("skills:write")
async def enable_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    """Enable one workspace skill after a fresh scan."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    try:
        result = SkillService(workspace_dir).enable_skill(skill_name)
    except SkillScanError as exc:
        return _scan_error_response(exc)
    if not result.get("success"):
        raise HTTPException(
            status_code=404,
            detail=result.get("reason", "Skill not found"),
        )
    schedule_agent_reload(request, workspace.agent_id)
    return {"enabled": True, **result}


@router.delete("/{skill_name}")
@require_permission("skills:write")
async def delete_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    service = SkillService(workspace_dir)
    service.disable_skill(skill_name)
    deleted = service.delete_skill(skill_name)
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Only disabled workspace skills can be deleted",
        )
    return {"deleted": True}


@router.get("/{skill_name}/files/{file_path:path}")
@require_permission("skills:read")
async def load_skill_file(
    request: Request,
    skill_name: str,
    file_path: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    content = SkillService(workspace_dir).load_skill_file(
        skill_name=skill_name,
        file_path=file_path,
    )
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"content": content}


@router.put("/save")
@require_permission("skills:write")
async def save_workspace_skill(
    request: Request,
    body: SaveSkillRequest,
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    try:
        result = SkillService(workspace_dir).save_skill(
            skill_name=body.source_name or body.name,
            content=body.content,
            target_name=body.name if body.source_name else None,
            config=body.config,
            category=body.category,
            overwrite=body.overwrite,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        if result.get("reason") == "conflict":
            raise HTTPException(status_code=409, detail=result)
        raise HTTPException(status_code=404, detail="Skill not found")
    if result.get("mode") != "noop":
        schedule_agent_reload(request, workspace.agent_id)
    return result


@router.put("/{skill_name}/channels")
@require_permission("skills:write")
async def update_skill_channels_endpoint(
    request: Request,
    skill_name: str,
    channels: list[str],
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    updated = SkillService(workspace_dir).set_skill_channels(
        skill_name,
        channels,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    schedule_agent_reload(request, workspace.agent_id)
    return {"updated": True, "channels": channels}


@router.put("/{skill_name}/tags")
@require_permission("skills:write")
async def update_skill_tags(
    request: Request,
    skill_name: str,
    tags: list[str],
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    tags = _validate_tags(tags)
    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    updated = SkillService(workspace_dir).set_skill_tags(
        skill_name,
        tags,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"updated": True, "tags": tags}


@router.get("/{skill_name}/config")
@require_permission("skills:read")
async def get_skill_config_endpoint(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    manifest = read_skill_manifest(workspace_dir)
    entry = manifest.get("skills", {}).get(skill_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"config": entry.get("config", {})}


@router.put("/{skill_name}/config")
@require_permission("skills:write")
async def update_skill_config_endpoint(
    request: Request,
    skill_name: str,
    body: SkillConfigRequest,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    manifest_path = get_workspace_skill_manifest_path(workspace_dir)

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry["config"] = dict(body.config)
        return True

    updated = _mutate_json(
        manifest_path,
        _default_workspace_manifest(),
        _update,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"updated": True}


@router.delete("/{skill_name}/config")
@require_permission("skills:write")
async def delete_skill_config_endpoint(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    manifest_path = get_workspace_skill_manifest_path(workspace_dir)

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry.pop("config", None)
        return True

    updated = _mutate_json(
        manifest_path,
        _default_workspace_manifest(),
        _update,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"cleared": True}


# ─── Skill Categories CRUD ──────────────────────────────────────────────────

_CATEGORIES_PATH = Path("/apps/ai/coapis/system/skill_categories.json")


def _read_categories() -> dict[str, Any]:
    if _CATEGORIES_PATH.exists():
        with open(_CATEGORIES_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"categories": []}


def _write_categories(data: dict[str, Any]) -> None:
    with open(_CATEGORIES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@router.get("/categories")
@require_permission("skills:read")
async def list_categories() -> list[dict[str, Any]]:
    data = _read_categories()
    return sorted(data.get("categories", []), key=lambda c: c.get("sort_order", 99))


@router.post("/categories")
@require_permission("skills:write")
async def create_category(request: Request) -> dict[str, Any]:
    body = await request.json()
    key = body.get("key", "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="key is required")
    data = _read_categories()
    cats = data.get("categories", [])
    if any(c["key"] == key for c in cats):
        raise HTTPException(status_code=409, detail=f"Category '{key}' already exists")
    cat = {
        "key": key,
        "label": body.get("label", key),
        "emoji": body.get("emoji", ""),
        "sort_order": body.get("sort_order", len(cats) + 1),
    }
    cats.append(cat)
    data["categories"] = cats
    _write_categories(data)
    return cat


@router.put("/categories/{key}")
@require_permission("skills:write")
async def update_category(key: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    data = _read_categories()
    cats = data.get("categories", [])
    for cat in cats:
        if cat["key"] == key:
            cat["label"] = body.get("label", cat.get("label", key))
            cat["emoji"] = body.get("emoji", cat.get("emoji", ""))
            cat["sort_order"] = body.get("sort_order", cat.get("sort_order", 0))
            if "new_key" in body and body["new_key"] and body["new_key"] != key:
                cat["key"] = body["new_key"]
            _write_categories(data)
            return cat
    raise HTTPException(status_code=404, detail=f"Category '{key}' not found")


@router.delete("/categories/{key}")
@require_permission("skills:write")
async def delete_category(key: str) -> dict[str, Any]:
    data = _read_categories()
    cats = data.get("categories", [])
    data["categories"] = [c for c in cats if c["key"] != key]
    if len(data["categories"]) == len(cats):
        raise HTTPException(status_code=404, detail=f"Category '{key}' not found")
    _write_categories(data)
    return {"deleted": key}


# ──────────────────────────────────────────
# 效能评估 API
# ──────────────────────────────────────────

@router.get("/metrics")
@require_permission("skills:read")
async def get_skill_metrics(
    sort_by: str = "composite_score",
    limit: int = 100,
    refresh: bool = False,
) -> dict[str, Any]:
    """获取所有技能的效能指标，按 sort_by 降序排列。"""
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    metrics = engine.get_all_metrics(
        force_refresh=refresh, sort_by=sort_by, limit=limit
    )
    funnel = engine.get_funnel_data()
    return {
        "metrics": metrics,
        "funnel": funnel,
        "total_skills": len(metrics),
    }


@router.get("/metrics/{skill_name}")
@require_permission("skills:read")
async def get_skill_metric_detail(skill_name: str) -> dict[str, Any]:
    """获取单个技能的效能指标详情。"""
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    metric = engine.get_skill_metric(skill_name)
    if metric is None:
        raise HTTPException(
            status_code=404, detail=f"No metrics for skill '{skill_name}'"
        )
    return metric


@router.post("/metrics/refresh")
@require_permission("skills:write")
async def refresh_skill_metrics() -> dict[str, Any]:
    """强制刷新效能指标缓存。"""
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    summary = engine.refresh()
    return summary


@router.get("/metrics/user/{user_id}")
@require_permission("skills:read")
async def get_user_skill_metrics(user_id: str) -> dict[str, Any]:
    """获取指定用户在所有技能上的效能指标概览。"""
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    overview = engine.get_user_overview(user_id)
    return {
        "user_id": user_id,
        "skills": overview,
        "total_skills": len(overview),
    }


@router.get("/metrics/{skill_name}/user/{user_id}")
@require_permission("skills:read")
async def get_user_skill_metric_detail(skill_name: str, user_id: str) -> dict[str, Any]:
    """获取指定用户在指定技能上的效能指标详情。"""
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    metric = engine.get_user_skill_metric(skill_name, user_id)
    if metric is None:
        raise HTTPException(
            status_code=404,
            detail=f"No metrics for skill '{skill_name}' user '{user_id}'",
        )
    return metric


# ──────────────────────────────────────────
# 版本管理 API
# ──────────────────────────────────────────

@router.get("/{skill_name}/versions")
@require_permission("skills:read")
async def get_skill_versions(skill_name: str) -> dict[str, Any]:
    """获取技能的版本历史列表。"""
    from coapis.skill_evolution.version_manager import list_versions

    versions = list_versions(skill_name)
    return {
        "skill_name": skill_name,
        "versions": versions,
        "total": len(versions),
    }


@router.post("/{skill_name}/rollback/{version}")
@require_permission("skills:write")
async def rollback_skill_version(
    skill_name: str,
    version: str,
    request: Request,
) -> dict[str, Any]:
    """回滚技能到指定版本。"""
    from coapis.skill_evolution.version_manager import (
        restore_version, get_version_content, list_versions,
    )

    # 验证版本存在
    content = get_version_content(skill_name, version)
    if content is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version '{version}' not found for skill '{skill_name}'",
        )

    # 获取用户 workspace（复用已有方法）
    workspace_dir = await _request_workspace_dir(request)
    skill_root = workspace_dir / "skills" / skill_name

    # 执行回滚：将历史版本内容写入技能目录
    success = restore_version(skill_name, version, skill_root)
    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restore version '{version}'",
        )

    # 重新读取回滚后的版本号
    from coapis.skill_evolution.version_manager import get_version
    restored_version = get_version(content)

    return {
        "success": True,
        "skill_name": skill_name,
        "restored_version": restored_version,
        "versions_count": len(list_versions(skill_name)),
    }


# ──────────────────────────────────────────
# 触发词用户级覆盖 API
# ──────────────────────────────────────────

@router.get("/{skill_name}/triggers")
@require_permission("skills:read")
async def get_skill_triggers(
    skill_name: str,
    request: Request,
) -> dict[str, Any]:
    """获取技能的触发词（含用户级覆盖）。"""
    import json as _json
    from coapis.agents.react_agent import CoApisAgent

    workspace_dir = await _request_workspace_dir(request)
    skill_root = workspace_dir / "skills" / skill_name

    # 获取基础触发词（SKILL.md frontmatter）
    base_triggers = CoApisAgent._get_skill_triggers(skill_root, None)

    # 读取用户覆盖
    override_path = workspace_dir / "skill_triggers" / f"{skill_name}.json"
    overrides = {}
    if override_path.exists():
        try:
            overrides = _json.loads(override_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 获取合并后的最终触发词
    effective_triggers = CoApisAgent._get_skill_triggers(skill_root, workspace_dir)

    return {
        "skill_name": skill_name,
        "base_triggers": base_triggers,
        "effective_triggers": effective_triggers,
        "overrides": {
            "added_keywords": overrides.get("added_keywords", []),
            "removed_keywords": overrides.get("removed_keywords", []),
            "refined_keywords": overrides.get("refined_keywords", []),
        },
    }


@router.put("/{skill_name}/triggers")
@require_permission("skills:write")
async def update_skill_triggers(
    skill_name: str,
    request: Request,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """更新用户级触发词覆盖。不修改原始 SKILL.md。

    Body:
      - added_keywords: list[str] — 额外添加的触发词
      - removed_keywords: list[str] — 移除的触发词
      - refined_keywords: list[str] — 完全替换触发词列表（优先级最高）
      - reset: bool — 清除所有覆盖，恢复默认
    """
    import json as _json
    from coapis.agents.react_agent import CoApisAgent

    workspace_dir = await _request_workspace_dir(request)
    triggers_dir = workspace_dir / "skill_triggers"
    triggers_dir.mkdir(parents=True, exist_ok=True)
    override_path = triggers_dir / f"{skill_name}.json"

    if body and body.get("reset"):
        # 清除覆盖
        override_path.unlink(missing_ok=True)
        base_triggers = CoApisAgent._get_skill_triggers(
            workspace_dir / "skills" / skill_name, None
        )
        return {
            "success": True,
            "skill_name": skill_name,
            "action": "reset",
            "effective_triggers": base_triggers,
        }

    # 构建覆盖数据
    data: dict[str, Any] = {}
    if body:
        for key in ("added_keywords", "removed_keywords", "refined_keywords"):
            val = body.get(key)
            if isinstance(val, list):
                data[key] = [str(v).lower().strip() for v in val if v]

    override_path.write_text(
        _json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 返回合并后的最终触发词
    effective = CoApisAgent._get_skill_triggers(
        workspace_dir / "skills" / skill_name, workspace_dir
    )
    return {
        "success": True,
        "skill_name": skill_name,
        "action": "updated",
        "overrides": data,
        "effective_triggers": effective,
    }


# ──────────────────────────────────────────
# 技能自进化 API
# ──────────────────────────────────────────

@router.get("/{skill_name}/improve/analyze")
@require_permission("skills:read")
async def analyze_skill_issues(skill_name: str) -> dict[str, Any]:
    """分析技能的触发词问题和内容问题。

    返回：
    - trigger_issues: 误触发/漏触发分析
    - content_issues: 执行失败分析
    """
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    trigger_issues = engine.analyze_trigger_issues(skill_name)
    content_issues = engine.analyze_content_issues(skill_name)

    return {
        "skill_name": skill_name,
        "trigger_issues": trigger_issues,
        "content_issues": content_issues,
        "has_issues": bool(
            trigger_issues.get("false_positive_keywords")
            or trigger_issues.get("false_negative_hints")
            or content_issues.get("common_errors")
        ),
    }


@router.post("/{skill_name}/improve/suggest")
@require_permission("skills:write")
async def generate_skill_suggestion(
    skill_name: str,
    body: dict[str, Any] = None,
) -> dict[str, Any]:
    """生成技能改进建议草稿。

    Body:
      - type: "trigger_optimization" | "content_improvement" (默认自动判断)
      - removes: list[str] — 建议移除的触发词
      - adds: list[str] — 建议添加的触发词
      - improvements: list[str] — 内容改进建议
    """
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    body = body or {}
    suggestion_type = body.get("type", "auto")

    suggestions = []

    if suggestion_type in ("auto", "trigger_optimization"):
        trig_sug = engine.generate_trigger_suggestion(
            skill_name,
            removes=body.get("removes"),
            adds=body.get("adds"),
        )
        suggestions.append(trig_sug)

    if suggestion_type in ("auto", "content_improvement"):
        cont_sug = engine.generate_content_suggestion(
            skill_name,
            improvements=body.get("improvements"),
        )
        suggestions.append(cont_sug)

    return {
        "skill_name": skill_name,
        "suggestions": suggestions,
        "total": len(suggestions),
    }


@router.get("/suggestions")
@require_permission("skills:read")
async def list_skill_suggestions(
    skill_name: str = None,
    status: str = None,
) -> dict[str, Any]:
    """列出技能改进建议草稿。

    Query:
      - skill_name: 按技能名过滤
      - status: 按状态过滤 (pending/approved/rejected)
    """
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    suggestions = engine.list_suggestions(skill_name=skill_name, status=status)

    return {
        "suggestions": suggestions,
        "total": len(suggestions),
    }


@router.post("/suggestions/{suggestion_id}/approve")
@require_permission("skills:write")
async def approve_skill_suggestion(suggestion_id: str) -> dict[str, Any]:
    """审批通过技能改进建议。"""
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    result = engine.approve_suggestion(suggestion_id)
    if not result:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    # 通知桥接层
    try:
        from coapis.skill_evolution.bridge import get_skill_evolution_bridge
        bridge = get_skill_evolution_bridge()
        if result.get("type") == "trigger_optimization":
            bridge.notify_trigger_enhanced(
                result["skill_name"],
                result.get("adds", []),
            )
        bridge.notify_skill_improved(
            skill_name=result["skill_name"],
            improvement_type=result.get("type", "unknown"),
            description=f"Suggestion {suggestion_id} approved",
        )
    except Exception:
        pass  # 不影响审批流程

    return {"success": True, "suggestion": result}


# ──────────────────────────────────────────
# 晋升/退役管理 API
# ──────────────────────────────────────────

@router.get("/promotion/candidates")
@require_permission("skills:read")
async def get_promotion_candidates() -> dict[str, Any]:
    """获取晋升候选技能列表。

    晋升条件：≥3 用户使用、效能分≥0.7、存在≥30 天。
    """
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    candidates = engine.detect_promotion_candidates()
    return {
        "candidates": candidates,
        "total": len(candidates),
    }


@router.post("/promotion/{skill_name}/approve")
@require_permission("skills:write")
async def approve_promotion(skill_name: str) -> dict[str, Any]:
    """审批通过技能晋升为全局技能。"""
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    result = engine.approve_promotion(skill_name)
    if not result:
        raise HTTPException(status_code=404, detail="Promotion candidate not found")

    # 通知桥接层
    try:
        from coapis.skill_evolution.bridge import get_skill_evolution_bridge
        bridge = get_skill_evolution_bridge()
        bridge.notify_skill_improved(
            skill_name=skill_name,
            improvement_type="promoted_to_global",
            description=f"技能晋升为全局技能（composite_score={result['composite_score']}，users={result['user_count']}）",
        )
    except Exception:
        pass

    return {"success": True, "candidate": result}


@router.post("/promotion/{skill_name}/reject")
@require_permission("skills:write")
async def reject_promotion(skill_name: str) -> dict[str, Any]:
    """拒绝技能晋升。"""
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    result = engine.reject_promotion(skill_name)
    if not result:
        raise HTTPException(status_code=404, detail="Promotion candidate not found")

    return {"success": True, "candidate": result}


@router.get("/retirement/candidates")
@require_permission("skills:read")
async def get_retirement_candidates() -> dict[str, Any]:
    """获取退役候选技能列表。

    退役条件：90 天零触发 或 连续 5 次执行失败。
    """
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    candidates = engine.detect_retirement_candidates()
    return {
        "candidates": candidates,
        "total": len(candidates),
    }


@router.post("/cross-agent/trigger-optimization")
@require_permission("skills:write")
async def report_trigger_optimization(
    request: Request,
    body: dict[str, Any] = None,
) -> dict[str, Any]:
    """上报触发词优化信号到跨 Agent 进化系统。

    当 ≥3 个不同用户独立提出相同优化时，该优化可晋升为全局。
    """
    from coapis.evolution.cross_agent_evolution import CrossAgentEvolution

    body = body or {}
    skill_name = body.get("skill_name", "")
    trigger_keyword = body.get("trigger_keyword", "")
    signal_type = body.get("signal_type", "false_negative")
    confidence = body.get("confidence", 0.7)

    if not skill_name or not trigger_keyword:
        raise HTTPException(status_code=400, detail="skill_name and trigger_keyword required")

    # 获取用户信息
    workspace_dir = await _request_workspace_dir(request)
    user_id = body.get("user_id", "anonymous")

    # 获取或创建 CrossAgentEvolution 实例
    cae = CrossAgentEvolution(data_dir=workspace_dir.parent.parent / "system")
    entry = cae.report_trigger_enhancement(
        skill_name=skill_name,
        trigger_keyword=trigger_keyword,
        signal_type=signal_type,
        source_user=user_id,
        confidence=confidence,
    )

    # 聚合检查
    aggregated = cae.aggregate_trigger_enhancements(skill_name, signal_type)

    return {
        "success": True,
        "entry_id": entry.id,
        "aggregated": aggregated,
        "promotable_items": [a for a in aggregated if a.get("promotable")],
    }


@router.get("/cross-agent/trigger-aggregation/{skill_name}")
@require_permission("skills:read")
async def get_trigger_aggregation(
    skill_name: str,
    signal_type: str = None,
) -> dict[str, Any]:
    """获取跨用户的触发词优化聚合结果。"""
    from coapis.evolution.cross_agent_evolution import CrossAgentEvolution

    cae = CrossAgentEvolution(data_dir=Path("/apps/ai/coapis/system"))
    aggregated = cae.aggregate_trigger_enhancements(skill_name, signal_type)

    return {
        "skill_name": skill_name,
        "signal_type": signal_type,
        "aggregation": aggregated,
        "total": len(aggregated),
        "promotable_count": len([a for a in aggregated if a.get("promotable")]),
    }


@router.post("/debug/trigger-analysis")
@require_permission("skills:read")
async def debug_trigger_analysis(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """调试技能触发分析 — 输入消息，返回完整的触发决策链路。

    Request body:
        {
            "message": "帮我写个报告",
            "channel": "wecom",  // optional, default "console"
            "workspace_dir": "/path/to/workspace"  // optional
        }

    Response:
        {
            "available_skills": [...],
            "llm_classification": [...],
            "keyword_matches": {skill: {triggers, matched, result}},
            "filtered_out": [...],
            "would_load": [...]
        }
    """
    from ...agents.skills_manager import (
        ensure_skills_initialized,
        get_workspace_skills_dir,
        resolve_effective_skills,
    )
    from ...agents.react_agent import CoApisAgent
    from pathlib import Path as P

    message = payload.get("message", "")
    channel = payload.get("channel", "console")
    ws_dir = payload.get("workspace_dir", "")

    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    # 确定 workspace
    if not ws_dir:
        from ...constant import WORKING_DIR
        workspace_dir = P(WORKING_DIR)
    else:
        workspace_dir = P(ws_dir)

    # 初始化技能
    ensure_skills_initialized(workspace_dir)
    working_skills_dir = get_workspace_skills_dir(workspace_dir)

    from ...agents.skills_manager import get_skill_pool_dir
    skill_pool_dir = get_skill_pool_dir()

    # 获取有效技能
    effective_skills = resolve_effective_skills(workspace_dir, channel)

    # 分类 core / on-demand
    core_skills = []
    on_demand_skills = {}

    for skill_name in effective_skills:
        skill_dir = working_skills_dir / skill_name
        if not skill_dir.exists():
            pool_dir = skill_pool_dir / skill_name
            if pool_dir.exists():
                skill_dir = pool_dir
            else:
                continue

        priority = CoApisAgent._get_skill_priority(skill_dir)
        if priority == "on-demand":
            triggers = CoApisAgent._get_skill_triggers(skill_dir, workspace_dir)
            on_demand_skills[skill_name] = {
                "skill_dir": str(skill_dir),
                "triggers": triggers,
                "triggers_count": len(triggers),
            }
        else:
            core_skills.append(skill_name)

    # 模拟关键词匹配
    msg_lower = message.lower()
    keyword_matches = {}
    would_load_llm = []
    would_load_keyword = []
    filtered_out = []

    for skill_name, info in on_demand_skills.items():
        triggers = info["triggers"]
        matched = [kw for kw in triggers if kw in msg_lower]
        result = "matched" if matched else "no_match"
        if not triggers:
            result = "no_triggers"
        keyword_matches[skill_name] = {
            "triggers_sample": triggers[:10],
            "triggers_count": len(triggers),
            "matched": matched,
            "result": result,
        }
        if matched:
            would_load_keyword.append(skill_name)
        elif result != "no_triggers":
            filtered_out.append(skill_name)

    # 尝试 LLM 分类（best-effort）
    llm_classification = []
    try:
        from ...agents.utils.intent_classifier import classify_intent_llm
        summaries = {}
        for name, info in on_demand_skills.items():
            # 读取描述
            skill_md = P(info["skill_dir"]) / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")[:2000]
                if "---" in content:
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        import yaml
                        meta = yaml.safe_load(parts[1]) or {}
                        desc = str(meta.get("description", ""))[:200]
                        hints = meta.get("triggers", {}).get("intent_hints", [])
                        if hints:
                            summaries[name] = f"{desc} ||| {', '.join(hints)}"
                        elif desc:
                            summaries[name] = desc
        if summaries:
            import asyncio
            result = await classify_intent_llm(message, summaries, timeout=5.0)
            llm_classification = result if result else []
    except Exception as e:
        llm_classification = [f"error: {str(e)[:100]}"]

    # 汇总
    all_would_load = list(set(would_load_llm + would_load_keyword))

    return {
        "message": message,
        "channel": channel,
        "workspace": str(workspace_dir),
        "summary": {
            "core_skills_count": len(core_skills),
            "on_demand_skills_count": len(on_demand_skills),
            "llm_matched_count": len(llm_classification),
            "keyword_matched_count": len(would_load_keyword),
            "would_load_count": len(all_would_load),
        },
        "core_skills": core_skills,
        "available_on_demand": list(on_demand_skills.keys()),
        "llm_classification": llm_classification,
        "keyword_matches": keyword_matches,
        "would_load": all_would_load,
        "filtered_out": filtered_out,
    }


@router.post("/suggestions/{suggestion_id}/reject")
@require_permission("skills:write")
async def reject_skill_suggestion(suggestion_id: str) -> dict[str, Any]:
    """拒绝技能改进建议。"""
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    result = engine.reject_suggestion(suggestion_id)
    if not result:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    return {"success": True, "suggestion": result}


# ──────────────────────────────────────────
# 晋升/退役管理 API
# ──────────────────────────────────────────

@router.get("/promotion/candidates")
@require_permission("skills:read")
async def get_promotion_candidates() -> dict[str, Any]:
    """获取晋升候选技能列表。

    晋升条件：≥3 用户使用、效能分≥0.7、存在≥30 天。
    """
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    candidates = engine.detect_promotion_candidates()
    return {
        "candidates": candidates,
        "total": len(candidates),
    }


@router.post("/promotion/{skill_name}/approve")
@require_permission("skills:write")
async def approve_promotion(skill_name: str) -> dict[str, Any]:
    """审批通过技能晋升为全局技能。"""
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    result = engine.approve_promotion(skill_name)
    if not result:
        raise HTTPException(status_code=404, detail="Promotion candidate not found")

    # 通知桥接层
    try:
        from coapis.skill_evolution.bridge import get_skill_evolution_bridge
        bridge = get_skill_evolution_bridge()
        bridge.notify_skill_improved(
            skill_name=skill_name,
            improvement_type="promoted_to_global",
            description=f"技能晋升为全局技能（composite_score={result['composite_score']}，users={result['user_count']}）",
        )
    except Exception:
        pass

    return {"success": True, "candidate": result}


@router.post("/promotion/{skill_name}/reject")
@require_permission("skills:write")
async def reject_promotion(skill_name: str) -> dict[str, Any]:
    """拒绝技能晋升。"""
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    result = engine.reject_promotion(skill_name)
    if not result:
        raise HTTPException(status_code=404, detail="Promotion candidate not found")

    return {"success": True, "candidate": result}


@router.get("/retirement/candidates")
@require_permission("skills:read")
async def get_retirement_candidates() -> dict[str, Any]:
    """获取退役候选技能列表。

    退役条件：90 天零触发 或 连续 5 次执行失败。
    """
    from coapis.skill_evolution.engine import get_evolution_engine

    engine = get_evolution_engine()
    candidates = engine.detect_retirement_candidates()
    return {
        "candidates": candidates,
        "total": len(candidates),
    }


@router.post("/cross-agent/trigger-optimization")
@require_permission("skills:write")
async def report_trigger_optimization(
    request: Request,
    body: dict[str, Any] = None,
) -> dict[str, Any]:
    """上报触发词优化信号到跨 Agent 进化系统。

    当 ≥3 个不同用户独立提出相同优化时，该优化可晋升为全局。
    """
    from coapis.evolution.cross_agent_evolution import CrossAgentEvolution

    body = body or {}
    skill_name = body.get("skill_name", "")
    trigger_keyword = body.get("trigger_keyword", "")
    signal_type = body.get("signal_type", "false_negative")
    confidence = body.get("confidence", 0.7)

    if not skill_name or not trigger_keyword:
        raise HTTPException(status_code=400, detail="skill_name and trigger_keyword required")

    # 获取用户信息
    workspace_dir = await _request_workspace_dir(request)
    user_id = body.get("user_id", "anonymous")

    # 获取或创建 CrossAgentEvolution 实例
    cae = CrossAgentEvolution(data_dir=workspace_dir.parent.parent / "system")
    entry = cae.report_trigger_enhancement(
        skill_name=skill_name,
        trigger_keyword=trigger_keyword,
        signal_type=signal_type,
        source_user=user_id,
        confidence=confidence,
    )

    # 聚合检查
    aggregated = cae.aggregate_trigger_enhancements(skill_name, signal_type)

    return {
        "success": True,
        "entry_id": entry.id,
        "aggregated": aggregated,
        "promotable_items": [a for a in aggregated if a.get("promotable")],
    }


@router.get("/cross-agent/trigger-aggregation/{skill_name}")
@require_permission("skills:read")
async def get_trigger_aggregation(
    skill_name: str,
    signal_type: str = None,
) -> dict[str, Any]:
    """获取跨用户的触发词优化聚合结果。"""
    from coapis.evolution.cross_agent_evolution import CrossAgentEvolution

    cae = CrossAgentEvolution(data_dir=Path("/apps/ai/coapis/system"))
    aggregated = cae.aggregate_trigger_enhancements(skill_name, signal_type)

    return {
        "skill_name": skill_name,
        "signal_type": signal_type,
        "aggregation": aggregated,
        "total": len(aggregated),
        "promotable_count": len([a for a in aggregated if a.get("promotable")]),
    }


@router.post("/debug/trigger-analysis")
@require_permission("skills:read")
async def debug_trigger_analysis(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """调试技能触发分析 — 输入消息，返回完整的触发决策链路。

    Request body:
        {
            "message": "帮我写个报告",
            "channel": "wecom",  // optional, default "console"
            "workspace_dir": "/path/to/workspace"  // optional
        }

    Response:
        {
            "available_skills": [...],
            "llm_classification": [...],
            "keyword_matches": {skill: {triggers, matched, result}},
            "filtered_out": [...],
            "would_load": [...]
        }
    """
    from ...agents.skills_manager import (
        ensure_skills_initialized,
        get_workspace_skills_dir,
        resolve_effective_skills,
    )
    from ...agents.react_agent import CoApisAgent
    from pathlib import Path as P

    message = payload.get("message", "")
    channel = payload.get("channel", "console")
    ws_dir = payload.get("workspace_dir", "")

    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    # 确定 workspace
    if not ws_dir:
        from ...constant import WORKING_DIR
        workspace_dir = P(WORKING_DIR)
    else:
        workspace_dir = P(ws_dir)

    # 初始化技能
    ensure_skills_initialized(workspace_dir)
    working_skills_dir = get_workspace_skills_dir(workspace_dir)

    from ...agents.skills_manager import get_skill_pool_dir
    skill_pool_dir = get_skill_pool_dir()

    # 获取有效技能
    effective_skills = resolve_effective_skills(workspace_dir, channel)

    # 分类 core / on-demand
    core_skills = []
    on_demand_skills = {}

    for skill_name in effective_skills:
        skill_dir = working_skills_dir / skill_name
        if not skill_dir.exists():
            pool_dir = skill_pool_dir / skill_name
            if pool_dir.exists():
                skill_dir = pool_dir
            else:
                continue

        priority = CoApisAgent._get_skill_priority(skill_dir)
        if priority == "on-demand":
            triggers = CoApisAgent._get_skill_triggers(skill_dir, workspace_dir)
            on_demand_skills[skill_name] = {
                "skill_dir": str(skill_dir),
                "triggers": triggers,
                "triggers_count": len(triggers),
            }
        else:
            core_skills.append(skill_name)

    # 模拟关键词匹配
    msg_lower = message.lower()
    keyword_matches = {}
    would_load_llm = []
    would_load_keyword = []
    filtered_out = []

    for skill_name, info in on_demand_skills.items():
        triggers = info["triggers"]
        matched = [kw for kw in triggers if kw in msg_lower]
        result = "matched" if matched else "no_match"
        if not triggers:
            result = "no_triggers"
        keyword_matches[skill_name] = {
            "triggers_sample": triggers[:10],
            "triggers_count": len(triggers),
            "matched": matched,
            "result": result,
        }
        if matched:
            would_load_keyword.append(skill_name)
        elif result != "no_triggers":
            filtered_out.append(skill_name)

    # 尝试 LLM 分类（best-effort）
    llm_classification = []
    try:
        from ...agents.utils.intent_classifier import classify_intent_llm
        summaries = {}
        for name, info in on_demand_skills.items():
            # 读取描述
            skill_md = P(info["skill_dir"]) / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")[:2000]
                if "---" in content:
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        import yaml
                        meta = yaml.safe_load(parts[1]) or {}
                        desc = str(meta.get("description", ""))[:200]
                        hints = meta.get("triggers", {}).get("intent_hints", [])
                        if hints:
                            summaries[name] = f"{desc} ||| {', '.join(hints)}"
                        elif desc:
                            summaries[name] = desc
        if summaries:
            import asyncio
            result = await classify_intent_llm(message, summaries, timeout=5.0)
            llm_classification = result if result else []
    except Exception as e:
        llm_classification = [f"error: {str(e)[:100]}"]

    # 汇总
    all_would_load = list(set(would_load_llm + would_load_keyword))

    return {
        "message": message,
        "channel": channel,
        "workspace": str(workspace_dir),
        "summary": {
            "core_skills_count": len(core_skills),
            "on_demand_skills_count": len(on_demand_skills),
            "llm_matched_count": len(llm_classification),
            "keyword_matched_count": len(would_load_keyword),
            "would_load_count": len(all_would_load),
        },
        "core_skills": core_skills,
        "available_on_demand": list(on_demand_skills.keys()),
        "llm_classification": llm_classification,
        "keyword_matches": keyword_matches,
        "would_load": all_would_load,
        "filtered_out": filtered_out,
    }


