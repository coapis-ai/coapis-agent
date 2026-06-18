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

"""
CoApis MySpace - 用户个人文件管理 API

统一存储架构：所有用户文件存储在 CoApis 本地文件系统
- 路径格式: workspaces/{username}/{category}/
- 支持按用户隔离，每个用户只能访问自己的文件

功能：
- 文件列表浏览（支持搜索、排序、分页）
- 文件上传/下载（带认证）
- 文件预览（文本/图片）
- 文件管理（重命名、删除、移动、复制、创建目录）
- 存储用量统计
"""
import os
import shutil
import mimetypes
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth import get_current_user
from ..permissions import require_permission
from ...constant import WORKSPACES_DIR
from ..services.file_service import FileServiceFactory, FileInfo as ServiceFileInfo

router = APIRouter(prefix="/myfiles", tags=["MySpace"])

# All myfiles endpoints require at least "user" role
# This prevents low-level roles from accessing file management

# ═══════════════════════════════════════════════════════════
# 配置（从 config.json 加载，支持运行时覆盖）
# ═══════════════════════════════════════════════════════════

_DEFAULT_MAX_FILE_SIZE_MB = 500  # MB
_DEFAULT_MAX_USER_SPACE_GB = 50  # GB
_DEFAULT_MAX_UPLOAD_FILES = 10   # 单次上传最大文件数

# 仅限制可执行文件，允许开发常用文件类型
FORBIDDEN_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr",
    ".vbs", ".jsf", ".wsf",
}


def _get_myspace_config():
    """从环境变量 + config.json 加载 myspace 配置，支持运行时读取。

    优先级：环境变量 > config.json > 默认值
    """
    import os
    from ...config import load_config

    # 先从 config.json 读取基础配置
    try:
        cfg = load_config()
        ms = getattr(cfg, "myspace", None) or {}
        max_file_mb = ms.get("max_file_size_mb", _DEFAULT_MAX_FILE_SIZE_MB)
        max_space_gb = ms.get("max_user_space_gb", _DEFAULT_MAX_USER_SPACE_GB)
    except Exception:
        max_file_mb = _DEFAULT_MAX_FILE_SIZE_MB
        max_space_gb = _DEFAULT_MAX_USER_SPACE_GB

    # 环境变量覆盖（COAPIS_UPLOAD_* 系列）
    env_max_file_mb = os.environ.get("COAPIS_UPLOAD_MAX_FILE_SIZE_MB")
    if env_max_file_mb is not None:
        max_file_mb = float(env_max_file_mb)

    env_max_files = os.environ.get("COAPIS_UPLOAD_MAX_FILES")
    max_upload_files = int(env_max_files) if env_max_files is not None else _DEFAULT_MAX_UPLOAD_FILES

    return {
        "max_file_size": int(max_file_mb) * 1024 * 1024,
        "max_file_size_mb": float(max_file_mb),
        "max_upload_files": max_upload_files,
        "max_user_space": int(max_space_gb) * 1024 * 1024 * 1024,
        "max_user_space_gb": float(max_space_gb),
    }


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

class FileInfo(BaseModel):
    name: str
    type: str  # "file" or "directory"
    path: str
    size: int = 0
    mimeType: str = ""
    previewable: bool = False
    downloadable: bool = True
    modified: Optional[str] = None
    items_count: int = 0


class FileListResponse(BaseModel):
    items: List[FileInfo]
    total: int
    path: str

    model_config = {"populate_by_name": True}


class FileOperationResponse(BaseModel):
    success: bool
    message: str
    file: Optional[FileInfo] = None


class RenameRequest(BaseModel):
    path: str
    newName: str


class MkdirRequest(BaseModel):
    path: str
    name: str


class MoveRequest(BaseModel):
    source: str
    target: str


class CopyRequest(BaseModel):
    source: str
    target: str


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _service_info_to_file_info(info: ServiceFileInfo) -> FileInfo:
    """将 ServiceFileInfo 转换为前端 FileInfo"""
    return FileInfo(
        name=info.name,
        type="directory" if info.is_dir else "file",
        path=info.path,
        size=info.size,
        mimeType=info.mime_type,
        previewable=info.mime_type.startswith(("text/", "image/")) or info.mime_type == "application/pdf",
        modified=str(info.modified_at) if info.modified_at else None,
    )


def _check_extension(filename: str) -> None:
    """检查文件扩展名"""
    ext = os.path.splitext(filename)[1].lower()
    if ext in FORBIDDEN_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"禁止的文件类型: {ext}")


def _check_size(size: int) -> None:
    """检查文件大小"""
    cfg = _get_myspace_config()
    if size > cfg["max_file_size"]:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大：最大允许 {cfg['max_file_size_mb']:.0f}MB"
        )


# ═══════════════════════════════════════════════════════════
# API 端点
# ═══════════════════════════════════════════════════════════

@router.get("/list")
@require_permission("chat:read")
async def list_files(
    path: str = "/",
    category: str = "files",
    search: str = "",
    sort_by: str = "name",
    sort_order: str = "asc",
    page: int = 1,
    page_size: int = 100,
    request: Request = None,
):
    """列出文件/目录"""
    username = get_current_user(request)["username"]
    
    # Build sort order string for service
    order = f"-{sort_by}" if sort_order == "desc" else sort_by
    
    file_service = FileServiceFactory.get_service()
    service_files = await file_service.list_files(
        username=username,
        path=path,
        category=category,
        order=order,
    )
    
    # Apply search filter
    if search:
        service_files = [f for f in service_files if search.lower() in f.name.lower()]
    
    # Apply pagination
    total = len(service_files)
    start = (page - 1) * page_size
    service_files = service_files[start:start + page_size]
    
    # Convert to frontend format
    files = [_service_info_to_file_info(f) for f in service_files]
    
    return FileListResponse(items=files, total=total, path=path)


@router.post("/upload")
@require_permission("chat:read")
async def upload_file(
    file: UploadFile = File(...),
    path: str = Form("/"),
    category: str = Form("files"),
    overwrite: str = Form("false"),
    request: Request = None,
):
    """上传文件"""
    if category != "files":
        raise HTTPException(status_code=403, detail="仅支持在文件类别中上传")

    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    # Handle overwrite as string from form data
    overwrite = overwrite.lower() in ("true", "1", "yes")

    username = get_current_user(request)["username"]
    _check_extension(file.filename)

    # Read file content and check size
    content = await file.read()
    total_size = len(content)
    _check_size(total_size)

    # Check quota
    file_service = FileServiceFactory.get_service()
    usage = await file_service.get_usage(username, category)
    cfg = _get_myspace_config()
    if usage + total_size > cfg["max_user_space"]:
        raise HTTPException(status_code=400, detail="存储空间不足")

    # Upload - pass content directly since we already read it
    try:
        result = await file_service.upload_file_with_content(
            username=username,
            path=path,
            filename=file.filename,
            content=content,
            category=category,
            overwrite=overwrite,
        )
    except HTTPException:
        raise
    except Exception as e:
        if "already exists" in str(e).lower() and not overwrite:
            raise HTTPException(status_code=409, detail="文件已存在")
        raise HTTPException(status_code=500, detail=f"上传文件失败: {e}")

    return FileOperationResponse(success=True, message="文件上传成功")


@router.get("/download")
@require_permission("chat:read")
async def download_file(path: str, category: str = "files", request: Request = None):
    """下载文件"""
    username = get_current_user(request)["username"]
    
    file_service = FileServiceFactory.get_service()
    response = await file_service.download_file(
        username=username,
        path=path,
        category=category,
    )
    return response


@router.get("/preview")
@require_permission("chat:read")
async def preview_file(path: str, category: str = "files", request: Request = None):
    """预览文件（文本/图片/PDF）"""
    username = get_current_user(request)["username"]
    
    file_service = FileServiceFactory.get_service()
    response = await file_service.preview_file(
        username=username,
        path=path,
        category=category,
    )
    return response


@router.put("/rename")
@require_permission("chat:read")
async def rename_file(
    req: RenameRequest,
    category: str = "files",
    request: Request = None,
):
    """重命名文件/目录"""
    username = get_current_user(request)["username"]

    if not req.newName or not req.newName.strip():
        raise HTTPException(status_code=400, detail="新名称不能为空")

    file_service = FileServiceFactory.get_service()
    try:
        await file_service.rename_file(
            username=username,
            old_path=req.path,
            new_name=req.newName.strip(),
            category=category,
        )
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="文件/目录不存在")
        if "already exists" in str(e).lower():
            raise HTTPException(status_code=409, detail="同名文件/目录已存在")
        raise HTTPException(status_code=500, detail=f"重命名失败: {e}")

    return FileOperationResponse(success=True, message="重命名成功")


@router.delete("/delete")
@require_permission("chat:read")
async def delete_file(path: str, category: str = "files", request: Request = None):
    """删除文件/目录"""
    username = get_current_user(request)["username"]

    file_service = FileServiceFactory.get_service()
    try:
        await file_service.delete_file(
            username=username,
            path=path,
            category=category,
        )
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="文件/目录不存在")
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")

    return FileOperationResponse(success=True, message="删除成功")


@router.post("/mkdir")
@require_permission("chat:read")
async def mkdir(req: MkdirRequest, category: str = "files", request: Request = None):
    """创建目录"""
    username = get_current_user(request)["username"]

    # Validate name
    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="目录名称不能为空")

    file_service = FileServiceFactory.get_service()
    try:
        await file_service.mkdir(
            username=username,
            path=req.path + "/" + req.name,
            category=category,
        )
    except HTTPException:
        raise
    except Exception as e:
        if "already exists" in str(e).lower():
            raise HTTPException(status_code=409, detail="已存在")
        raise HTTPException(status_code=500, detail=f"创建目录失败: {e}")

    return FileOperationResponse(success=True, message="目录创建成功")


@router.post("/move")
@require_permission("chat:read")
async def move_file(req: MoveRequest, category: str = "files", request: Request = None):
    """移动文件/目录"""
    username = get_current_user(request)["username"]

    file_service = FileServiceFactory.get_service()
    try:
        await file_service.move_file(
            username=username,
            source_path=req.source,
            dest_path=req.target,
            category=category,
        )
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="源文件不存在")
        if "already exists" in str(e).lower():
            raise HTTPException(status_code=409, detail="目标已存在")
        raise HTTPException(status_code=500, detail=f"移动失败: {e}")

    return FileOperationResponse(success=True, message="移动成功")


@router.post("/copy")
@require_permission("chat:read")
async def copy_file(req: CopyRequest, category: str = "files", request: Request = None):
    """复制文件/目录"""
    username = get_current_user(request)["username"]

    file_service = FileServiceFactory.get_service()
    try:
        await file_service.copy_file(
            username=username,
            source_path=req.source,
            dest_path=req.target,
            category=category,
        )
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="源文件不存在")
        if "already exists" in str(e).lower():
            raise HTTPException(status_code=409, detail="目标已存在")
        raise HTTPException(status_code=500, detail=f"复制失败: {e}")

    return FileOperationResponse(success=True, message="复制成功")


@router.get("/config")
@require_permission("chat:read")
async def get_config(request: Request = None):
    """获取 MySpace 配置（文件大小限制等）"""
    return _get_myspace_config()


@router.get("/usage")
@require_permission("chat:read")
async def get_usage(request: Request = None):
    """获取存储用量"""
    username = get_current_user(request)["username"]

    file_service = FileServiceFactory.get_service()
    usage = await file_service.get_usage(username, category="files")
    cfg = _get_myspace_config()

    return {
        "usage_bytes": usage,
        "usage_mb": round(usage / 1024 / 1024, 2),
        "max_bytes": cfg["max_user_space"],
        "max_gb": cfg["max_user_space_gb"],
        "percent": round(usage / cfg["max_user_space"] * 100, 2) if cfg["max_user_space"] > 0 else 0,
    }
