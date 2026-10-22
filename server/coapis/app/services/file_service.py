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

"""File Service Abstraction Layer.

Provides a unified interface for file operations, supporting multiple
backends (Seafile, Local) with seamless switching capability.

Usage:
    from coapis.app.services.file_service import FileServiceFactory
    
    # Get file service instance
    file_service = FileServiceFactory.get_service()
    
    # List files
    files = await file_service.list_files(username, "/")
    
    # Upload file
    await file_service.upload_file(username, "/test.txt", file)
"""
from __future__ import annotations

import logging
import os
import shutil
import time
import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from enum import Enum

from fastapi import UploadFile, HTTPException
from fastapi.responses import FileResponse

# 噪音目录口径与台账巡检共用同一份定义：搜索排除的目录必须和台账登记的
# 目录一致，否则会出现"台账里有、搜索搜不到"这类对不上的口径。
from ...foundation.resource_ledger import NOISE_DIR_PARTS

logger = logging.getLogger(__name__)

# ── 搜索参数（单一来源）─────────────────────────────────────────────
# 搜索只有一个实现（``FileService.search_files``），两个入口
# （``GET /myfiles/search`` 与 ``GET /myfiles/list?search=``）都走它，
# 因此这些上限对两条路径同时生效，不会各定一套。
SEARCH_LIMIT = 200        # 单次最多返回多少条命中

# 会话目录绑定表是系统状态文件（chat_id → 目录），不是用户产出。列进文件列表
# 会让人以为空间里凭空多了两个看不懂的隐藏文件，列表与搜索都把它摘掉。
from ...agents.context.session_dir import BINDING_FILE as _SESSION_BINDING_FILE, BINDING_LOCK_FILE as _SESSION_BINDING_LOCK
HIDDEN_ENTRY_NAMES = frozenset({_SESSION_BINDING_FILE, _SESSION_BINDING_LOCK})
SEARCH_MAX_DEPTH = 12     # 相对搜索起点的最大递归深度
SEARCH_MAX_SCAN = 20000   # 单次最多遍历多少个条目（防超大树把请求卡死）


def sort_file_infos(files: List[FileInfo], order: str = "name") -> List[FileInfo]:
    """文件条目排序的**唯一**实现：目录在前，组内按 ``order`` 键。

    ``GET /myfiles/list`` 与搜索（``/search``、``/list?search=``）共用它，
    两个入口的排序口径不会分叉。``order`` 前缀 ``-`` 表示倒序，
    支持 ``name`` / ``time`` / ``size``。
    """
    reverse = order.startswith("-")
    key = order.lstrip("-") or "name"
    if key == "time":
        rank = lambda f: f.modified_at
    elif key == "size":
        rank = lambda f: f.size
    else:
        rank = lambda f: f.name.lower()
    out = list(files)
    out.sort(key=rank, reverse=reverse)
    # 稳定排序把目录整体提到前面，组内保留上一步的排序结果
    out.sort(key=lambda f: not f.is_dir)
    return out


# ═══════════════════════════════════════════════════════════
# File Info Model
# ═══════════════════════════════════════════════════════════

class FileInfo:
    """File information model."""
    
    def __init__(
        self,
        path: str,
        name: str,
        size: int = 0,
        is_dir: bool = False,
        mime_type: str = "",
        created_at: float = 0.0,
        modified_at: float = 0.0,
        id: str = "",
        parent_dir: str = "",
        repo_id: str = "",
        extra: Dict[str, Any] = None
    ):
        self.path = path
        self.name = name
        self.size = size
        self.is_dir = is_dir
        self.mime_type = mime_type
        self.created_at = created_at
        self.modified_at = modified_at
        self.id = id
        self.parent_dir = parent_dir
        self.repo_id = repo_id
        self.extra = extra or {}
    
    @property
    def is_file(self) -> bool:
        return not self.is_dir
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "path": self.path,
            "name": self.name,
            "size": self.size,
            "is_dir": self.is_dir,
            "mime_type": self.mime_type,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "id": self.id,
            "parent_dir": self.parent_dir,
            "repo_id": self.repo_id,
        }


# ═══════════════════════════════════════════════════════════
# File Service Abstract Base Class
# ═══════════════════════════════════════════════════════════

class FileService(ABC):
    """Abstract base class for file services.
    
    All file backends must implement these methods.
    """
    
    @abstractmethod
    async def list_files(
        self,
        username: str,
        path: str = "/",
        category: str = "files",
        order: str = "name"
    ) -> List[FileInfo]:
        """List files in a directory.
        
        Args:
            username: Username for data isolation
            path: Directory path
            category: File category (files, agents, skills, workflows, chats)
            order: Sort order
            
        Returns:
            List of FileInfo
        """
        pass
    
    @abstractmethod
    async def upload_file(
        self,
        username: str,
        path: str,
        file: UploadFile,
        category: str = "files"
    ) -> FileInfo:
        """Upload a file.
        
        Args:
            username: Username for data isolation
            path: Target path
            file: UploadFile object
            category: File category
            
        Returns:
            Uploaded FileInfo
        """
        pass
    
    @abstractmethod
    async def download_file(
        self,
        username: str,
        path: str,
        category: str = "files"
    ) -> FileResponse:
        """Download a file.
        
        Args:
            username: Username for data isolation
            path: File path
            category: File category
            
        Returns:
            FileResponse
        """
        pass
    
    @abstractmethod
    async def preview_file(
        self,
        username: str,
        path: str,
        category: str = "files"
    ) -> Dict[str, Any]:
        """Preview a file (text content or image URL).
        
        Args:
            username: Username for data isolation
            path: File path
            category: File category
            
        Returns:
            Preview data
        """
        pass
    
    @abstractmethod
    async def delete_file(
        self,
        username: str,
        path: str,
        category: str = "files"
    ) -> bool:
        """Delete a file or directory.
        
        Args:
            username: Username for data isolation
            path: File/directory path
            category: File category
            
        Returns:
            True if deleted successfully
        """
        pass
    
    @abstractmethod
    async def rename_file(
        self,
        username: str,
        old_path: str,
        new_name: str,
        category: str = "files"
    ) -> bool:
        """Rename a file or directory.
        
        Args:
            username: Username for data isolation
            old_path: Current path
            new_name: New name
            category: File category
            
        Returns:
            True if renamed successfully
        """
        pass
    
    @abstractmethod
    async def mkdir(
        self,
        username: str,
        path: str,
        category: str = "files"
    ) -> bool:
        """Create a new directory.
        
        Args:
            username: Username for data isolation
            path: Directory path
            category: File category
            
        Returns:
            True if created successfully
        """
        pass
    
    @abstractmethod
    async def move_file(
        self,
        username: str,
        source_path: str,
        dest_path: str,
        category: str = "files"
    ) -> bool:
        """Move a file or directory.
        
        Args:
            username: Username for data isolation
            source_path: Source path
            dest_path: Destination path
            category: File category
            
        Returns:
            True if moved successfully
        """
        pass
    
    @abstractmethod
    async def copy_file(
        self,
        username: str,
        source_path: str,
        dest_path: str,
        category: str = "files"
    ) -> bool:
        """Copy a file or directory.
        
        Args:
            username: Username for data isolation
            source_path: Source path
            dest_path: Destination path
            category: File category
            
        Returns:
            True if copied successfully
        """
        pass
    
    @abstractmethod
    async def search_files(
        self,
        username: str,
        query: str,
        category: str = "files",
        path: str = "/",
        limit: int = SEARCH_LIMIT,
    ) -> Tuple[List[FileInfo], int]:
        """Search files recursively under ``path``.

        这是"搜索"这个功能**唯一**的实现。两个入口都走它：

        - ``GET /myfiles/search``（我的空间搜索框、资源选择器的跨目录检索）
        - ``GET /myfiles/list?search=``（当前目录内筛选）

        语义因此天然一致，不会一个递归一个平铺、一个排噪音目录一个不排。

        Args:
            username: Username for data isolation
            query: 不区分大小写的子串，匹配对象是**完整相对路径**
                （所以 ``a/b`` 能命中目录 ``a`` 下的 ``b.txt``）
            category: File category
            path: 搜索起点（``/`` = 整个 category 子树）
            limit: 最多返回多少条

        Returns:
            ``(matches, total)``：上限内的命中列表（目录在前、按名排序）与
            **命中总数**。``total > len(matches)`` 即表示被 ``limit`` 截断，
            调用方据此渲染"还有 N 条"，不静默吞掉。
        """
        pass
    
    @abstractmethod
    async def get_usage(
        self,
        username: str,
        category: str = "files"
    ) -> int:
        """Get storage usage.
        
        Args:
            username: Username for data isolation
            category: File category
            
        Returns:
            Usage in bytes
        """
        pass


# ═══════════════════════════════════════════════════════════
# Local File Backend (Existing Implementation)
# ═══════════════════════════════════════════════════════════

class LocalFileBackend(FileService):
    """Local filesystem backend (existing implementation).
    
    Uses workspaces/{username}/{category}/ for file storage.
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
    
    def _get_user_dir(self, username: str, category: str) -> Path:
        """Get user's file directory."""
        user_dir = self.data_dir / username / category
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def _resolve_path(self, user_dir: Path, rel_path: str) -> Path:
        """Resolve and validate path (prevent path traversal)."""
        # Normalize path
        rel_path = rel_path.strip("/")
        if rel_path:
            target = user_dir / rel_path
        else:
            target = user_dir
        
        # Prevent path traversal
        try:
            target.resolve().relative_to(user_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Invalid path")
        
        return target
    
    async def list_files(
        self,
        username: str,
        path: str = "/",
        category: str = "files",
        order: str = "name"
    ) -> List[FileInfo]:
        user_dir = self._get_user_dir(username, category)
        target = self._resolve_path(user_dir, path)
        
        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory")
        
        files = []
        for item in target.iterdir():
            if item.name in HIDDEN_ENTRY_NAMES:
                continue
            # Skip broken symlinks (target doesn't exist)
            if item.is_symlink() and not item.exists():
                logger.warning(f"Skipping broken symlink: {item}")
                continue
            stat = item.stat()
            mime_type, _ = mimetypes.guess_type(item.name)
            files.append(FileInfo(
                path=f"/{str(item.relative_to(user_dir))}",
                name=item.name,
                size=stat.st_size if item.is_file() else 0,
                is_dir=item.is_dir(),
                mime_type=mime_type or "",
                created_at=stat.st_ctime,
                modified_at=stat.st_mtime,
                parent_dir=path
            ))
        
        # 排序走统一实现（与搜索同一份口径）
        return sort_file_infos(files, order)
    
    async def upload_file(
        self,
        username: str,
        path: str,
        file: UploadFile,
        category: str = "files",
        overwrite: bool = False
    ) -> FileInfo:
        content = await file.read()
        return await self.upload_file_with_content(
            username=username,
            path=path,
            filename=file.filename or "unnamed",
            content=content,
            category=category,
            overwrite=overwrite,
        )

    async def upload_file_with_content(
        self,
        username: str,
        path: str,
        filename: str,
        content: bytes,
        category: str = "files",
        overwrite: bool = False
    ) -> FileInfo:
        """Upload file with pre-read content (avoids double-read issue)."""
        user_dir = self._get_user_dir(username, category)
        parent_dir = self._resolve_path(user_dir, path)
        
        # Ensure parent directory exists
        parent_dir.mkdir(parents=True, exist_ok=True)
        
        # Target is parent_dir + filename
        target = parent_dir / filename
        
        if target.exists() and not overwrite:
            raise HTTPException(status_code=409, detail="File already exists")
        
        # Write file
        target.write_bytes(content)
        
        stat = target.stat()
        mime_type, _ = mimetypes.guess_type(filename)
        
        return FileInfo(
            path=f"/{str(target.relative_to(user_dir))}",
            name=target.name,
            size=stat.st_size,
            is_dir=False,
            mime_type=mime_type or "",
            created_at=stat.st_ctime,
            modified_at=stat.st_mtime,
            parent_dir=path
        )
    
    async def download_file(
        self,
        username: str,
        path: str,
        category: str = "files"
    ) -> FileResponse:
        user_dir = self._get_user_dir(username, category)
        target = self._resolve_path(user_dir, path)
        
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found")
        
        if target.is_dir():
            raise HTTPException(status_code=400, detail="Cannot download directory")
        
        return FileResponse(
            path=str(target),
            filename=target.name,
            media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        )
    
    async def preview_file(
        self,
        username: str,
        path: str,
        category: str = "files"
    ) -> Dict[str, Any]:
        user_dir = self._get_user_dir(username, category)
        target = self._resolve_path(user_dir, path)
        
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found")
        
        mime_type, _ = mimetypes.guess_type(target.name)

        # Text files: return content.  mimetypes 认不出 .md/.markdown（不在标准
        # 表里），而答案侧产出卡默认就是 Markdown —— 预览抽屉要渲染正文，所以
        # 按扩展名补一层，不能只信 mime_type。
        _TEXT_SUFFIXES = {
            ".md", ".markdown", ".txt", ".text", ".log", ".json", ".jsonl",
            ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".csv", ".tsv",
            ".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".sql", ".sh", ".bash",
            ".xml", ".rst",
        }
        if (mime_type and mime_type.startswith("text/")) or (
            target.suffix.lower() in _TEXT_SUFFIXES
        ):
            content = target.read_text(encoding="utf-8", errors="replace")
            return {
                "type": "text",
                "content": content,
                "mime_type": mime_type or "text/plain",
            }
        
        # Images: return base64 or URL
        if mime_type and mime_type.startswith("image/"):
            return {
                "type": "image",
                "mime_type": mime_type,
                "url": f"/myfiles/preview?path={path}&category={category}"
            }
        
        # Other: return metadata only
        return {
            "type": "other",
            "mime_type": mime_type or "application/octet-stream",
            "size": target.stat().st_size
        }
    
    async def delete_file(
        self,
        username: str,
        path: str,
        category: str = "files"
    ) -> bool:
        user_dir = self._get_user_dir(username, category)
        target = self._resolve_path(user_dir, path)
        
        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        
        return True
    
    async def rename_file(
        self,
        username: str,
        old_path: str,
        new_name: str,
        category: str = "files"
    ) -> bool:
        user_dir = self._get_user_dir(username, category)
        target = self._resolve_path(user_dir, old_path)
        
        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        
        new_path = target.parent / new_name
        target.rename(new_path)
        
        return True
    
    async def mkdir(
        self,
        username: str,
        path: str,
        category: str = "files"
    ) -> bool:
        user_dir = self._get_user_dir(username, category)
        target = self._resolve_path(user_dir, path)
        
        if target.exists():
            raise HTTPException(status_code=409, detail="Directory already exists")
        
        target.mkdir(parents=True)
        
        return True
    
    async def move_file(
        self,
        username: str,
        source_path: str,
        dest_path: str,
        category: str = "files"
    ) -> bool:
        user_dir = self._get_user_dir(username, category)
        source = self._resolve_path(user_dir, source_path)
        dest = self._resolve_path(user_dir, dest_path)
        
        if not source.exists():
            raise HTTPException(status_code=404, detail="Source not found")
        
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        
        return True
    
    async def copy_file(
        self,
        username: str,
        source_path: str,
        dest_path: str,
        category: str = "files"
    ) -> bool:
        user_dir = self._get_user_dir(username, category)
        source = self._resolve_path(user_dir, source_path)
        dest = self._resolve_path(user_dir, dest_path)
        
        if not source.exists():
            raise HTTPException(status_code=404, detail="Source not found")
        
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        if source.is_dir():
            shutil.copytree(str(source), str(dest))
        else:
            shutil.copy2(str(source), str(dest))
        
        return True
    
    async def search_files(
        self,
        username: str,
        query: str,
        category: str = "files",
        path: str = "/",
        limit: int = SEARCH_LIMIT,
    ) -> Tuple[List[FileInfo], bool]:
        user_dir = self._get_user_dir(username, category)
        # 搜索起点同样过越权校验：传 ../other_user 必须 403，与 /list 同口径
        root = self._resolve_path(user_dir, path)

        if not root.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        if not root.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory")

        query_lower = query.lower()
        root_rel = root.relative_to(user_dir)
        root_depth = len(root_rel.parts)
        limit = max(1, min(int(limit or SEARCH_LIMIT), SEARCH_LIMIT))

        hits: List[FileInfo] = []
        total = 0          # 命中总数（不受 limit 影响，供前端折算「还有 N 条」）
        scanned = 0
        capped = False

        # 用 os.walk 而不是 Path.walk：镜像跑的是 Python 3.11，Path.walk 是
        # 3.12 才加的方法，在这里会直接 AttributeError（实测）。
        for cur, dirnames, filenames in os.walk(root):
            cur_path = Path(cur)
            rel = cur_path.relative_to(user_dir)

            # 深度封顶 + 噪音目录（.trash/.temp/.git/... 与台账同一份口径）：
            # 从 dirnames 里摘掉，os.walk 就不会再往下走。
            if len(rel.parts) - root_depth >= SEARCH_MAX_DEPTH:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames if d not in NOISE_DIR_PARTS]

            for name in sorted(dirnames) + sorted(filenames):
                if name in HIDDEN_ENTRY_NAMES:
                    continue
                scanned += 1
                if scanned > SEARCH_MAX_SCAN:
                    capped = True
                    break
                if query_lower not in str(rel / name).lower():
                    continue
                item = cur_path / name
                try:
                    stat = item.stat()
                except OSError:  # 断链 symlink、并发删除
                    continue
                total += 1
                if len(hits) >= limit:
                    continue  # 达到上限后只计数不收集：计数不额外增加遍历成本
                mime_type, _ = mimetypes.guess_type(name)
                hits.append(FileInfo(
                    path=f"/{rel / name}",
                    name=name,
                    size=stat.st_size if item.is_file() else 0,
                    is_dir=item.is_dir(),
                    mime_type=mime_type or "",
                    created_at=stat.st_ctime,
                    modified_at=stat.st_mtime,
                    parent_dir=f"/{rel}" if rel.parts else "/",
                ))
            if capped:
                break

        # 目录在前、名字在后：与 /list 共用同一份排序实现
        return sort_file_infos(hits, "name"), total
    
    async def get_usage(
        self,
        username: str,
        category: str = "files"
    ) -> int:
        user_dir = self._get_user_dir(username, category)
        
        total = 0
        for item in user_dir.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
        
        return total


# ═══════════════════════════════════════════════════════════
# Seafile File Backend
class FileServiceFactory:
    """Factory for the file service (local workspace backend)."""
    
    _instance: Optional[FileService] = None

    @classmethod
    def get_service(cls) -> FileService:
        """Get the file service instance.

        只有一种后端：本地工作区。Seafile 已随产品移出，代码一并移除，
        所以这里不再有后端切换分支——"文件功能"从此只有一条实现路径。
        """
        if cls._instance is None:
            from ...constant import WORKSPACES_DIR
            cls._instance = LocalFileBackend(WORKSPACES_DIR)

        return cls._instance
    
    @classmethod
    def reset(cls):
        """Reset factory (for testing)."""
        cls._instance = None
        cls._backend_type = "local"
