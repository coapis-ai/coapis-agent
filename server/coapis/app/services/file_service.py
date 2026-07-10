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
import shutil
import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from enum import Enum

from fastapi import UploadFile, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)


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
        category: str = "files"
    ) -> List[FileInfo]:
        """Search for files.
        
        Args:
            username: Username for data isolation
            query: Search query
            category: File category
            
        Returns:
            List of matching FileInfo
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
        
        # Sort
        reverse = order.startswith("-")
        key = order.lstrip("-")
        if key == "name":
            files.sort(key=lambda f: f.name.lower(), reverse=reverse)
        elif key == "time":
            files.sort(key=lambda f: f.modified_at, reverse=reverse)
        elif key == "size":
            files.sort(key=lambda f: f.size, reverse=reverse)
        
        return files
    
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
        
        # Text files: return content
        if mime_type and mime_type.startswith("text/"):
            content = target.read_text(encoding="utf-8", errors="replace")
            return {
                "type": "text",
                "content": content,
                "mime_type": mime_type
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
        category: str = "files"
    ) -> List[FileInfo]:
        user_dir = self._get_user_dir(username, category)
        
        results = []
        query_lower = query.lower()
        
        for root, dirs, files in user_dir.walk():
            for name in files:
                if query_lower in name.lower():
                    item = root / name
                    stat = item.stat()
                    mime_type, _ = mimetypes.guess_type(name)
                    results.append(FileInfo(
                        path=f"/{str(item.relative_to(user_dir))}",
                        name=name,
                        size=stat.st_size,
                        is_dir=False,
                        mime_type=mime_type or "",
                        created_at=stat.st_ctime,
                        modified_at=stat.st_mtime,
                        parent_dir="/" + "/".join(str(root.relative_to(user_dir)).split("/"))
                    ))
        
        return results
    
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
# ═══════════════════════════════════════════════════════════

class SeafileFileBackend(FileService):
    """Seafile backend for file operations.
    
    Maps each user to a Seafile repository for file storage.
    """
    
    def __init__(self, seafile_client: 'SeafileClient'):  # noqa: F821
        self.client = seafile_client
        self._repo_cache: Dict[str, str] = {}  # username -> repo_id
    
    async def _get_repo_id(self, username: str) -> str:
        """Get or create repository for user."""
        if username in self._repo_cache:
            return self._repo_cache[username]
        
        # Try to find existing repo
        repos = await self.client.list_repos(username)
        for repo in repos:
            if repo.name == f"{username}-files":
                self._repo_cache[username] = repo.repo_id
                return repo.repo_id
        
        # Create new repo
        repo = await self.client.create_repo(
            name=f"{username}-files",
            username=username,
            description=f"Files for user {username}"
        )
        self._repo_cache[username] = repo.repo_id
        return repo.repo_id
    
    async def list_files(
        self,
        username: str,
        path: str = "/",
        category: str = "files",
        order: str = "name"
    ) -> List[FileInfo]:
        repo_id = await self._get_repo_id(username)
        
        # Seafile stores files in repo root, use category as subdirectory
        seafile_path = f"/{category}{path}" if category != "files" else path
        
        files = await self.client.list_files(repo_id, seafile_path, order)
        
        # Convert Seafile FileInfo to our FileInfo
        result = []
        for f in files:
            result.append(FileInfo(
                path=f.path,
                name=f.name,
                size=f.size,
                is_dir=f.is_dir,
                mime_type=f.mime_type,
                created_at=f.created_at,
                modified_at=f.modified_at,
                id=f.id,
                parent_dir=f.parent_dir,
                repo_id=f.repo_id
            ))
        
        return result
    
    async def upload_file(
        self,
        username: str,
        path: str,
        file: UploadFile,
        category: str = "files"
    ) -> FileInfo:
        repo_id = await self._get_repo_id(username)
        
        seafile_path = f"/{category}{path}" if category != "files" else path
        
        result = await self.client.upload_file(repo_id, seafile_path, file)
        
        return FileInfo(
            path=result.path,
            name=result.name,
            size=result.size,
            is_dir=False,
            mime_type=result.mime_type,
            created_at=result.created_at,
            modified_at=result.modified_at,
            id=result.id,
            parent_dir=result.parent_dir,
            repo_id=result.repo_id
        )
    
    async def download_file(
        self,
        username: str,
        path: str,
        category: str = "files"
    ) -> FileResponse:
        repo_id = await self._get_repo_id(username)
        
        seafile_path = f"/{category}{path}" if category != "files" else path
        
        content = await self.client.download_file(repo_id, seafile_path)
        
        # Return as FileResponse
        import io
        from fastapi.responses import Response
        
        filename = path.split("/")[-1]
        mime_type, _ = mimetypes.guess_type(filename)
        
        return Response(
            content=content,
            media_type=mime_type or "application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    
    async def preview_file(
        self,
        username: str,
        path: str,
        category: str = "files"
    ) -> Dict[str, Any]:
        repo_id = await self._get_repo_id(username)
        
        seafile_path = f"/{category}{path}" if category != "files" else path
        
        file_info = await self.client.get_file_info(repo_id, seafile_path)
        mime_type, _ = mimetypes.guess_type(file_info.name)
        
        if mime_type and mime_type.startswith("text/"):
            content = await self.client.download_file(repo_id, seafile_path)
            return {
                "type": "text",
                "content": content.decode("utf-8", errors="replace"),
                "mime_type": mime_type
            }
        
        if mime_type and mime_type.startswith("image/"):
            return {
                "type": "image",
                "mime_type": mime_type,
                "url": f"/myfiles/preview?path={path}&category={category}"
            }
        
        return {
            "type": "other",
            "mime_type": mime_type or "application/octet-stream",
            "size": file_info.size
        }
    
    async def delete_file(
        self,
        username: str,
        path: str,
        category: str = "files"
    ) -> bool:
        repo_id = await self._get_repo_id(username)
        
        seafile_path = f"/{category}{path}" if category != "files" else path
        
        return await self.client.delete_file(repo_id, seafile_path)
    
    async def rename_file(
        self,
        username: str,
        old_path: str,
        new_name: str,
        category: str = "files"
    ) -> bool:
        repo_id = await self._get_repo_id(username)
        
        seafile_path = f"/{category}{old_path}" if category != "files" else old_path
        
        return await self.client.rename(repo_id, seafile_path, new_name)
    
    async def mkdir(
        self,
        username: str,
        path: str,
        category: str = "files"
    ) -> bool:
        repo_id = await self._get_repo_id(username)
        
        seafile_path = f"/{category}{path}" if category != "files" else path
        
        return await self.client.mkdir(repo_id, seafile_path)
    
    async def move_file(
        self,
        username: str,
        source_path: str,
        dest_path: str,
        category: str = "files"
    ) -> bool:
        repo_id = await self._get_repo_id(username)
        
        seafile_source = f"/{category}{source_path}" if category != "files" else source_path
        seafile_dest = f"/{category}{dest_path}" if category != "files" else dest_path
        
        return await self.client.move(repo_id, seafile_source, repo_id, seafile_dest)
    
    async def copy_file(
        self,
        username: str,
        source_path: str,
        dest_path: str,
        category: str = "files"
    ) -> bool:
        repo_id = await self._get_repo_id(username)
        
        seafile_source = f"/{category}{source_path}" if category != "files" else source_path
        seafile_dest = f"/{category}{dest_path}" if category != "files" else dest_path
        
        return await self.client.copy(repo_id, seafile_source, repo_id, seafile_dest)
    
    async def search_files(
        self,
        username: str,
        query: str,
        category: str = "files"
    ) -> List[FileInfo]:
        repo_id = await self._get_repo_id(username)
        
        seafile_path = f"/{category}" if category != "files" else "/"
        
        files = await self.client.search_files(query, repo_id, seafile_path)
        
        result = []
        for f in files:
            result.append(FileInfo(
                path=f.path,
                name=f.name,
                size=f.size,
                is_dir=f.is_dir,
                mime_type=f.mime_type,
                created_at=f.created_at,
                modified_at=f.modified_at,
                id=f.id,
                parent_dir=f.parent_dir,
                repo_id=f.repo_id
            ))
        
        return result
    
    async def get_usage(
        self,
        username: str,
        category: str = "files"
    ) -> int:
        repo_id = await self._get_repo_id(username)
        
        repo = await self.client.get_repo(repo_id)
        return repo.size


# ═══════════════════════════════════════════════════════════
# File Service Factory
# ═══════════════════════════════════════════════════════════

class FileServiceFactory:
    """Factory for creating file service instances.
    
    Supports switching between Local and Seafile backends
    based on configuration.
    """
    
    _instance: Optional[FileService] = None
    _backend_type: str = "local"  # "local" or "seafile"
    
    @classmethod
    def set_backend(cls, backend_type: str, **kwargs):
        """Set file backend type.
        
        Args:
            backend_type: "local" or "seafile"
            **kwargs: Backend-specific configuration
        """
        cls._backend_type = backend_type
        cls._instance = None  # Reset instance
    
    @classmethod
    def get_service(cls) -> FileService:
        """Get file service instance.
        
        Returns:
            FileService instance
        """
        if cls._instance is None:
            if cls._backend_type == "seafile":
                from .seafile_client import SeafileClient, SeafileConfig
                config = SeafileConfig(**kwargs)
                client = SeafileClient(config)
                cls._instance = SeafileFileBackend(client)
            else:
                from ...constant import WORKSPACES_DIR
                cls._instance = LocalFileBackend(WORKSPACES_DIR)
        
        return cls._instance
    
    @classmethod
    def reset(cls):
        """Reset factory (for testing)."""
        cls._instance = None
        cls._backend_type = "local"
