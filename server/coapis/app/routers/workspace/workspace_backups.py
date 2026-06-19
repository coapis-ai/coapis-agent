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

"""Workspace Backups router - user-level backup management.

每个用户可以备份/恢复自己的数据（Agent 配置、聊天历史、技能配置）。
"""
from __future__ import annotations

import logging
import json
import shutil
import tarfile
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Body, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ....constant import WORKSPACES_DIR
from ....user_system.database import UserSystemDB

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workspace/backups"])


# ── Pydantic models ─────────────────────────────────────────────────────

class BackupInfo(BaseModel):
    id: str
    name: str = ""
    size: int = 0
    created_at: Optional[float] = None
    scope: str = "full"  # full / agents / skills / chats
    file_path: str = ""


class CreateBackupRequest(BaseModel):
    name: str = ""
    scope: str = "full"  # full / agents / skills / chats


class BackupScope(BaseModel):
    agents: bool = True
    skills: bool = True
    chats: bool = True
    models: bool = True
    files: bool = True


# ── Helper functions ─────────────────────────────────────────────────────

def _get_username(request: Request) -> str:
    """获取当前用户名."""
    username = getattr(request.state, "username", "anonymous")
    if username == "anonymous":
        raise HTTPException(status_code=401, detail="需要登录")
    return username


def _get_user_backups_dir(username: str) -> Path:
    """获取用户备份目录."""
    backups_dir = WORKSPACES_DIR / username / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    return backups_dir


def _get_user_workspace_dir(username: str) -> Path:
    """获取用户工作区目录."""
    return WORKSPACES_DIR / username


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/workspace/backups")
async def list_backups(request: Request) -> Dict[str, Any]:
    """列出当前用户的备份."""
    username = _get_username(request)
    backups_dir = _get_user_backups_dir(username)
    
    backups = []
    if backups_dir.exists():
        for backup_file in sorted(backups_dir.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True):
            # 尝试读取备份元数据
            meta_file = backup_file.with_suffix(".json")
            meta = {}
            if meta_file.exists():
                with open(meta_file, "r") as f:
                    meta = json.load(f)
            
            backups.append(BackupInfo(
                id=meta.get("id", backup_file.stem),
                name=meta.get("name", backup_file.stem),
                size=int(backup_file.stat().st_size),
                created_at=meta.get("created_at", backup_file.stat().st_mtime),
                scope=meta.get("scope", "full"),
                file_path=str(backup_file),
            ))
    
    return {
        "username": username,
        "backups": [b.model_dump() for b in backups],
        "total": len(backups),
    }


@router.post("/workspace/backups")
async def create_backup(
    request: Request,
    payload: CreateBackupRequest = Body(...),
) -> Dict[str, Any]:
    """创建备份."""
    username = _get_username(request)
    backups_dir = _get_user_backups_dir(username)
    data_dir = _get_user_workspace_dir(username)
    
    backup_id = str(uuid.uuid4())[:8]
    backup_name = payload.name or f"backup_{backup_id}"
    backup_file = backups_dir / f"{backup_name}.tar.gz"
    
    # 创建 tar.gz 备份
    with tarfile.open(backup_file, "w:gz") as tar:
        if payload.scope == "full" or payload.scope == "agents":
            agents_dir = data_dir / "agents"
            if agents_dir.exists():
                tar.add(agents_dir, arcname="agents")
        
        if payload.scope == "full" or payload.scope == "skills":
            skills_dir = data_dir / "skills"
            if skills_dir.exists():
                tar.add(skills_dir, arcname="skills")
        
        if payload.scope == "full" or payload.scope == "chats":
            chats_dir = data_dir / "chat"
            if chats_dir.exists():
                tar.add(chats_dir, arcname="chat")
        
        if payload.scope == "full" or payload.scope == "models":
            models_file = data_dir / "models.json"
            if models_file.exists():
                tar.add(models_file, arcname="models.json")
        
        if payload.scope == "full" or payload.scope == "files":
            files_dir = data_dir / "files"
            if files_dir.exists():
                tar.add(files_dir, arcname="files")
    
    # 保存元数据
    meta = {
        "id": backup_id,
        "name": backup_name,
        "username": username,
        "scope": payload.scope,
        "size": int(backup_file.stat().st_size),
        "created_at": time.time(),
    }
    
    meta_file = backup_file.with_suffix(".json")
    with open(meta_file, "w") as f:
        json.dump(meta, f, indent=2)
    
    # Record audit log
    db = UserSystemDB()
    user = db.get_user_by_username(username)
    if user:
        db.insert_audit_log(
            user_id=user["id"],
            username=username,
            action="create_backup",
            resource_type="backup",
            resource_id=backup_id,
            details={"name": backup_name, "scope": payload.scope},
        )
    
    return {
        "success": True,
        "backup": BackupInfo(
            id=backup_id,
            name=backup_name,
            size=meta["size"],
            created_at=meta["created_at"],
            scope=payload.scope,
            file_path=str(backup_file),
        ).model_dump(),
    }


@router.get("/workspace/backups/{backup_id}")
async def get_backup_info(
    request: Request,
    backup_id: str,
) -> Dict[str, Any]:
    """获取备份详情."""
    username = _get_username(request)
    backups_dir = _get_user_backups_dir(username)
    
    # 查找备份文件
    meta_file = backups_dir / f"{backup_id}.json"
    if not meta_file.exists():
        # 尝试按名称查找
        for f in backups_dir.glob("*.json"):
            with open(f, "r") as fp:
                data = json.load(fp)
                if data.get("id") == backup_id or data.get("name") == backup_id:
                    meta_file = f
                    break
    
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="备份不存在")
    
    with open(meta_file, "r") as f:
        meta = json.load(f)
    
    if meta.get("username") != username:
        raise HTTPException(status_code=403, detail="无权访问此备份")
    
    return meta


@router.post("/workspace/backups/{backup_id}/restore")
async def restore_backup(
    request: Request,
    backup_id: str,
) -> Dict[str, Any]:
    """恢复备份."""
    username = _get_username(request)
    backups_dir = _get_user_backups_dir(username)
    data_dir = _get_user_workspace_dir(username)
    
    # 查找备份文件
    backup_file = None
    for f in backups_dir.glob("*.tar.gz"):
        meta_file = f.with_suffix(".json")
        if meta_file.exists():
            with open(meta_file, "r") as fp:
                data = json.load(fp)
                if data.get("id") == backup_id or data.get("name") == backup_id:
                    backup_file = f
                    break
    
    if not backup_file:
        raise HTTPException(status_code=404, detail="备份不存在")
    
    # 恢复数据
    with tarfile.open(backup_file, "r:gz") as tar:
        tar.extractall(path=data_dir)
    
    # Record audit log
    db = UserSystemDB()
    user = db.get_user_by_username(username)
    if user:
        db.insert_audit_log(
            user_id=user["id"],
            username=username,
            action="restore_backup",
            resource_type="backup",
            resource_id=backup_id,
        )
    
    return {
        "success": True,
        "message": "备份恢复成功",
    }


@router.delete("/workspace/backups/{backup_id}")
async def delete_backup(
    request: Request,
    backup_id: str,
) -> Dict[str, Any]:
    """删除备份."""
    username = _get_username(request)
    backups_dir = _get_user_backups_dir(username)
    
    # 查找备份文件
    backup_file = None
    meta_file = None
    for f in backups_dir.glob("*.tar.gz"):
        mf = f.with_suffix(".json")
        if mf.exists():
            with open(mf, "r") as fp:
                data = json.load(fp)
                if data.get("id") == backup_id or data.get("name") == backup_id:
                    backup_file = f
                    meta_file = mf
                    break
    
    if not backup_file:
        raise HTTPException(status_code=404, detail="备份不存在")
    
    # 删除文件
    backup_file.unlink()
    if meta_file:
        meta_file.unlink()
    
    # Record audit log
    db = UserSystemDB()
    user = db.get_user_by_username(username)
    if user:
        db.insert_audit_log(
            user_id=user["id"],
            username=username,
            action="delete_backup",
            resource_type="backup",
            resource_id=backup_id,
        )
    
    return {
        "success": True,
        "backup_id": backup_id,
    }


@router.get("/workspace/backups/{backup_id}/download")
async def download_backup(
    request: Request,
    backup_id: str,
) -> FileResponse:
    """下载备份文件."""
    username = _get_username(request)
    backups_dir = _get_user_backups_dir(username)
    
    # 查找备份文件
    backup_file = None
    for f in backups_dir.glob("*.tar.gz"):
        meta_file = f.with_suffix(".json")
        if meta_file.exists():
            with open(meta_file, "r") as fp:
                data = json.load(fp)
                if data.get("id") == backup_id or data.get("name") == backup_id:
                    backup_file = f
                    break
    
    if not backup_file:
        raise HTTPException(status_code=404, detail="备份不存在")
    
    return FileResponse(
        path=str(backup_file),
        filename=backup_file.name,
        media_type="application/gzip",
    )
