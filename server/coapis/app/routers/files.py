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
import logging
import mimetypes
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth import get_current_user
from ..permissions import require_permission
from ...constant import WORKSPACES_DIR
from ..services.file_service import (
    FileServiceFactory,
    FileInfo as ServiceFileInfo,
    SEARCH_LIMIT,
    sort_file_infos,
)

logger = logging.getLogger(__name__)

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
    # 搜索命中达到上限时的诚实标记（带 search 时才会为 True），不静默截断
    truncated: bool = False
    limit: int = 0

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


class MkdirBatchRequest(BaseModel):
    """批量创建目录请求"""
    paths: List[str]


class MoveRequest(BaseModel):
    source: str
    target: str


class CopyRequest(BaseModel):
    source: str
    target: str


class RecordStatusUpdate(BaseModel):
    status: str  # draft / delivered / archived
    title: Optional[str] = None
    description: Optional[str] = None


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

    # 搜索走服务层那**一份**实现（与 GET /myfiles/search 完全同一份代码）：
    # 递归子树、匹配完整相对路径、排除噪音目录、目录在前。
    # 这里不再另写一个"只筛当前目录文件名"的过滤——同一功能只允许一条
    # 实现路径，两个入口的语义、排序、上限因此天然一致。
    if search:
        service_files, hit_total = await file_service.search_files(
            username=username,
            query=search,
            category=category,
            path=path,
        )
        service_files = sort_file_infos(service_files, order)
    else:
        service_files = await file_service.list_files(
            username=username,
            path=path,
            category=category,
            order=order,
        )
        hit_total = len(service_files)
    
    # Apply pagination
    total = hit_total
    start = (page - 1) * page_size
    service_files = service_files[start:start + page_size]
    
    # Convert to frontend format
    files = [_service_info_to_file_info(f) for f in service_files]
    
    return FileListResponse(
        items=files, total=total, path=path,
        truncated=hit_total > len(files), limit=SEARCH_LIMIT if search else 0,
    )


@router.get("/search")
@require_permission("chat:read")
async def search_files(
    keyword: str = Query(..., min_length=1, description="Search keyword"),
    path: str = Query("/", description="Search subtree root"),
    category: str = Query("files", description="File category"),
    limit: int = Query(SEARCH_LIMIT, ge=1, le=SEARCH_LIMIT, description="Max hits"),
    request: Request = None,
):
    """搜索文件（递归子树）。

    与 `/list?search=` 共用服务层 `FileService.search_files` **同一份实现**：
    递归、匹配完整相对路径（`a/b` 能命中 `a/b.pptx`）、排除噪音目录
    （`.trash`/`.temp`/`.git`…，与资源台账同一份口径）、目录在前按名排序。
    命中达到 `limit` 时 `truncated=true`，不静默吞掉。

    响应形状与 `/list` 对齐（`items` 里是同一套 FileInfo），前端两个视图
    渲染逻辑可以完全复用。
    """
    username = get_current_user(request)["username"]
    file_service = FileServiceFactory.get_service()
    hits, hit_total = await file_service.search_files(
        username=username, query=keyword, category=category, path=path, limit=limit,
    )
    return {
        "items": [_service_info_to_file_info(f) for f in hits],
        "total": hit_total,
        "truncated": hit_total > len(hits),
        "limit": limit,
        "path": path,
        "keyword": keyword,
    }


@router.post("/upload")
@require_permission("chat:read")
async def upload_file(
    file: UploadFile = File(...),
    path: str = Form("/"),
    category: str = Form("files"),
    overwrite: str = Form("true"),
    relative_path: str = Form(""),  # 文件夹上传时的完整相对路径
    chat_id: str = Form(""),  # 聊天 UUID，用于"本会话文件"归属（D1）
    session_id: str = Form(""),  # 前端本地会话 id，新会话建号前上传时唯一可用标识
    request: Request = None,
):
    """上传文件"""
    logger.info(f"[UPLOAD] Start: file={file.filename}, path={path}, category={category}, relative_path={relative_path}")
    
    if category != "files":
        raise HTTPException(status_code=403, detail="仅支持在文件类别中上传")

    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    # Handle overwrite as string from form data.
    # Default is overwrite: the workspace is the user's own isolated space, so
    # re-uploading the same name means "update this file". Keeping versions is
    # the user's choice (save-as / _v2 names), not something the server decides
    # by rejecting the upload with 409.
    overwrite = overwrite.lower() in ("true", "1", "yes")

    username = get_current_user(request)["username"]
    logger.info(f"[UPLOAD] username={username}")
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

    # Determine target path: use relative_path if provided (folder upload)
    if relative_path:
        # relative_path = "/docs/a/a.md" -> parent_dir = "/docs/a", filename = "a.md"
        relative_path = relative_path.strip("/")
        last_slash = relative_path.rfind("/")
        if last_slash > 0:
            target_path = "/" + relative_path[:last_slash]
            target_filename = relative_path[last_slash + 1:]
        else:
            target_path = "/"
            target_filename = relative_path
    else:
        target_path = path
        target_filename = file.filename

    # Upload - pass content directly since we already read it
    try:
        result = await file_service.upload_file_with_content(
            username=username,
            path=target_path,
            filename=target_filename,
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

    # File ledger hook (fire-and-forget, never breaks the upload)
    try:
        from ...config.session_context import (
            get_current_agent_id,
            get_current_session_id,
        )
        from ...foundation.file_ledger import record_file_event

        led_abs = WORKSPACES_DIR / username / category / str(result.path).lstrip("/")
        record_file_event(
            username,
            str(led_abs),
            session_id=session_id or get_current_session_id(),
            chat_id=chat_id or None,
            agent_id=get_current_agent_id(),
            source="upload",
            title=file.filename,
        )
    except Exception:
        pass

    # Return format expected by frontend ChatUploadResponse: {url, file_name}
    return {
        "success": True,
        "message": "文件上传成功",
        "url": result.path,
        "file_name": result.name,
        "stored_name": result.path,
    }


@router.get("/records")
@require_permission("chat:read")
async def list_file_records(
    session_id: Optional[str] = Query(None, description="按会话过滤"),
    chat_id: Optional[str] = Query(None, description="按聊天 UUID 过滤（本会话文件）"),
    source: Optional[str] = Query(None, description="按来源过滤: upload/write_file/edit_file/append_file/reconcile"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
):
    """文件台账列表（按文件去重，最新一次写入为准）"""
    from ...foundation.file_ledger import get_file_ledger

    username = get_current_user(request)["username"]
    return get_file_ledger().list_records(
        username,
        session_id=session_id,
        chat_id=chat_id,
        source=source,
        limit=limit,
        offset=offset,
    )


@router.get("/records/stats")
@require_permission("chat:read")
async def file_records_stats(request: Request = None):
    """文件台账汇总统计（文件数/总大小/来源分布/扩展名分布）"""
    from ...foundation.file_ledger import get_file_ledger

    username = get_current_user(request)["username"]
    return get_file_ledger().stats(username)


@router.patch("/records/{file_id}/status")
@require_permission("chat:read")
async def update_file_record_status(
    file_id: int,
    req: RecordStatusUpdate,
    request: Request = None,
):
    """更新文件台账状态（draft/delivered/archived），可同时附 title/description"""
    from ...foundation.file_ledger import VALID_STATUSES, get_file_ledger

    username = get_current_user(request)["username"]
    if req.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"无效状态: {req.status}")
    led = get_file_ledger()
    file_path = led.resolve_path(username, file_id)
    if file_path is None:
        raise HTTPException(status_code=404, detail="台账条目不存在")
    ok = led.update_record_status(
        username, file_path, req.status,
        title=req.title, description=req.description,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="台账条目不存在")
    return {"success": True, "file_id": file_id, "status": req.status}


@router.get("/deliverables")
@require_permission("chat:read")
async def list_deliverables(
    status: Optional[str] = Query(None, description="按状态过滤: draft/delivered/archived"),
    session_id: Optional[str] = Query(None, description="按会话过滤"),
    limit: int = Query(50, ge=1, le=200),
    request: Request = None,
):
    """成果台账：按文件去重（最新行代表当前状态），按最近活动排序"""
    from ...foundation.file_ledger import get_file_ledger

    username = get_current_user(request)["username"]
    led = get_file_ledger()
    items = led.list_deliverables(
        username, status=status, session_id=session_id, limit=limit,
    )
    # total reflects the FULL filtered set, not the truncated page
    total = led.count_deliverables(username, status=status, session_id=session_id)
    return {"items": items, "total": total}


@router.post("/records/attach-chat")
@require_permission("chat:read")
async def attach_chat_records(
    body: dict,
    request: Request = None,
):
    """把建会话之前上传的台账行补写 chat_id。

    新会话在首条消息发出前没有 chat UUID，此时上传的文件 ``chat_id`` 为
    null。会话创建后前端调用本端点，把该会话里尚未归属会话的行补上 chat_id。
    只更新 ``chat_id IS NULL`` 的行，已归属其他会话的历史行不会被改写。
    """
    from ...foundation.file_ledger import get_file_ledger

    username = get_current_user(request)["username"]
    session_id = str(body.get("session_id") or "")
    chat_id = str(body.get("chat_id") or "")
    if not session_id or not chat_id:
        raise HTTPException(
            status_code=400,
            detail="session_id 与 chat_id 均不能为空",
        )
    count = get_file_ledger().attach_chat(
        username,
        session_id=session_id,
        chat_id=chat_id,
    )
    return {"success": True, "updated": count}


@router.post("/records/{file_id}/archive")
@require_permission("chat:read")
async def archive_file_record(file_id: int, request: Request = None):
    """归档一条文件台账（软归档，不物理删除）"""
    from ...foundation.file_ledger import get_file_ledger

    username = get_current_user(request)["username"]
    led = get_file_ledger()
    file_path = led.resolve_path(username, file_id)
    if file_path is None:
        raise HTTPException(status_code=404, detail="台账条目不存在")
    if not led.archive_file(username, file_path):
        raise HTTPException(status_code=404, detail="台账条目不存在")
    return {"success": True, "file_id": file_id, "status": "archived"}


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


@router.post("/mkdir-batch")
@require_permission("chat:read")
async def mkdir_batch(req: MkdirBatchRequest, category: str = "files", request: Request = None):
    """批量创建目录（用于上传文件夹时预建目录结构）"""
    username = get_current_user(request)["username"]

    if not req.paths or len(req.paths) == 0:
        raise HTTPException(status_code=400, detail="路径列表不能为空")

    file_service = FileServiceFactory.get_service()
    created = 0
    skipped = 0
    errors = []

    for path in req.paths:
        try:
            await file_service.mkdir(
                username=username,
                path=path,
                category=category,
            )
            created += 1
        except Exception as e:
            if "already exists" in str(e).lower():
                skipped += 1
            else:
                errors.append({"path": path, "error": str(e)})

    return {
        "success": True,
        "message": f"批量创建目录完成",
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }


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


# ═══════════════════════════════════════════════════════════
# 资源清单面（R1）：resources / resource_refs 的读面与巡检
# ═══════════════════════════════════════════════════════════

@router.get("/resources")
@require_permission("chat:read")
async def list_resources(
    kind: Optional[str] = Query(None, description="按类型过滤: file/db/kb/mcp/web"),
    status: Optional[str] = Query(None, description="按状态过滤: draft/official/orphan/archived"),
    chat_id: Optional[str] = Query(
        None,
        description="按会话过滤：经 resource_refs 反查该会话引用过的资源（不读冗余列）",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    request: Request = None,
):
    """资源清单（每资源一行，含引用者计数）。软删行不出现。"""
    from ...foundation.resource_ledger import get_resource_ledger

    username = get_current_user(request)["username"]
    ledger = get_resource_ledger()
    items = ledger.list_resources(
        owner_scope="user",
        owner_id=username,
        kind=kind,
        status=status,
        chat_id=chat_id,
        limit=limit,
        offset=offset,
    )
    # total 是分页前的总数：前端把差额渲染成「还有 N 项未加载」尾巴行，
    # 缺 total 会让被 limit 截断的记录静默消失。
    total = ledger.count_resources(
        owner_scope="user",
        owner_id=username,
        kind=kind,
        status=status,
        chat_id=chat_id,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/resources/stats")
@require_permission("chat:read")
async def resource_stats(request: Request = None):
    """资源清单汇总（状态/类型分布、孤儿数、FS 缺失数）"""
    from ...foundation.resource_ledger import get_resource_ledger

    username = get_current_user(request)["username"]
    return get_resource_ledger().stats(owner_scope="user", owner_id=username)


@router.post("/resources/sweep")
@require_permission("admin:admin")
async def resource_sweep(
    full: bool = Query(True, description="full=true 时同时报告 FS 有但无台账行的文件"),
    backfill: bool = Query(
        False,
        description="backfill=true 时把存量文件补登记进台账（仅限用户表里真实存在的 owner）",
    ),
    request: Request = None,
):
    """巡检（FS → DB 单向）。**永不删除 FS 文件**。

    报告四类：FS 已消失的台账行、refs 清空的孤儿资源、FS 有但无台账行的文件、
    以及"根本不是用户的工作区目录"里的文件（``unowned``，只报告不补登记）。
    """
    from ...foundation.resource_ledger import get_resource_ledger

    report = get_resource_ledger().sweep(full=full, backfill=backfill)
    logger.info("resource sweep by admin: %s", {k: v for k, v in report.items() if not isinstance(v, list)})
    return report
