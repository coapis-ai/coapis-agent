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

"""Seafile API Client - Async HTTP wrapper for Seafile REST API.

Provides:
- Authentication (Token-based)
- File operations (CRUD, search, preview)
- Directory operations (mkdir, rename, move, copy)
- Share link management
- User management (Admin API)
- Connection pooling and retry logic
- Circuit breaker pattern

Seafile API Reference:
https://seafile-api.readthedocs.io/
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

import httpx
from httpx import Limits, AsyncClient

# Lazy import to avoid FastAPI dependency at import time
UploadFile = None
def _get_uploadfile():
    global UploadFile
    if UploadFile is None:
        from fastapi import UploadFile as _UploadFile
        UploadFile = _UploadFile
    return UploadFile

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════════════════════

class SeafileError(Exception):
    """Base exception for Seafile API errors."""
    def __init__(self, message: str, status_code: int = 0, response: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class SeafileAuthError(SeafileError):
    """Authentication failed."""
    pass


class SeafileNotFoundError(SeafileError):
    """Resource not found."""
    pass


class SeafilePermissionError(SeafileError):
    """Permission denied."""
    pass


class SeafileRateLimitError(SeafileError):
    """Rate limit exceeded."""
    pass


class SeafileServerError(SeafileError):
    """Server error."""
    pass


# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

class FileType(str, Enum):
    """File type classification."""
    FILE = "file"
    DIR = "dir"


@dataclass
class FileInfo:
    """File/Directory information from Seafile."""
    path: str
    name: str
    size: int = 0
    type: FileType = FileType.FILE
    mime_type: str = ""
    created_at: float = 0.0
    modified_at: float = 0.0
    id: str = ""
    parent_dir: str = ""
    repo_id: str = ""
    
    @property
    def is_dir(self) -> bool:
        return self.type == FileType.DIR
    
    @property
    def is_file(self) -> bool:
        return self.type == FileType.FILE


@dataclass
class RepoInfo:
    """Repository information."""
    repo_id: str
    name: str
    owner: str
    description: str = ""
    visibility: str = "private"
    created_at: float = 0.0
    modified_at: float = 0.0
    size: int = 0
    storage_id: str = ""


@dataclass
class ShareLink:
    """Share link information."""
    token: str
    share_id: int
    file_path: str
    repo_id: str
    username: str
    password: str = ""
    days: int = 7
    view_cnt: int = 0
    created_at: float = 0.0
    expire_date: float = 0.0
    download_cnt: int = 0
    
    @property
    def link_url(self) -> str:
        if self.password:
            return f"/share/{self.token}"
        return f"/share/{self.token}"


@dataclass
class UserInfo:
    """User information."""
    email: str
    name: str
    created_at: float = 0.0
    last_login: float = 0.0
    is_active: bool = True
    is_staff: bool = False
    contact_email: str = ""
    affiliation: str = ""
    avatar: str = ""


@dataclass
class SeafileConfig:
    """Seafile client configuration."""
    service_url: str = "http://localhost:9000"
    file_server_root: str = "http://localhost:9001"
    admin_username: str = "admin"
    admin_password: str = "CoApis2026!"
    timeout: float = 30.0
    max_connections: int = 100
    max_keepalive_connections: int = 20
    retry_attempts: int = 3
    retry_delay: float = 1.0
    token_cache_ttl: int = 3600  # seconds
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 60


# ═══════════════════════════════════════════════════════════
# Circuit Breaker
# ═══════════════════════════════════════════════════════════

class CircuitBreaker:
    """Simple circuit breaker implementation.
    
    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Failures exceeded threshold, requests blocked
    - HALF_OPEN: After timeout, allow one test request
    """
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "CLOSED"
    
    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"
    
    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
    
    def can_execute(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = "HALF_OPEN"
                return True
            return False
        # HALF_OPEN - allow one test request
        return True


# ═══════════════════════════════════════════════════════════
# Seafile Client
# ═══════════════════════════════════════════════════════════

class SeafileClient:
    """Async Seafile API client.
    
    Usage:
        config = SeafileConfig(
            service_url="http://localhost:9000",
            admin_username="admin",
            admin_password="password"
        )
        client = SeafileClient(config)
        
        # Login
        token = await client.login("admin", "password")
        
        # List repos
        repos = await client.list_repos()
        
        # List files
        files = await client.list_files(repo_id, "/")
        
        # Upload file
        await client.upload_file(repo_id, "/test.txt", file_data)
    """
    
    def __init__(self, config: SeafileConfig):
        self.config = config
        self._token: Optional[str] = None
        self._token_expires: float = 0.0
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=config.circuit_breaker_threshold,
            recovery_timeout=config.circuit_breaker_timeout
        )
        
        # Initialize HTTP client with connection pooling
        self._client = AsyncClient(
            base_url=config.service_url,
            timeout=httpx.Timeout(config.timeout),
            limits=Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_keepalive_connections
            ),
            http2=False  # Seafile doesn't support HTTP/2
        )
    
    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()
    
    # ─── Authentication ──────────────────────────────────
    
    async def login(self, username: str, password: str) -> str:
        """Login and get auth token.
        
        Args:
            username: User email or username
            password: User password
            
        Returns:
            Auth token string
            
        Raises:
            SeafileAuthError: If authentication fails
        """
        try:
            resp = await self._client.post(
                "/api2/auth-token/",
                data={"username": username, "password": password}
            )
            
            if resp.status_code == 200:
                data = resp.json()
                self._token = data.get("token")
                self._token_expires = time.time() + self.config.token_cache_ttl
                self._circuit_breaker.record_success()
                logger.info(f"Seafile login successful for {username}")
                return self._token
            
            # Handle error
            self._circuit_breaker.record_failure()
            error_msg = resp.json().get("error_msg", "Unknown error")
            raise SeafileAuthError(f"Login failed: {error_msg}", resp.status_code)
            
        except httpx.ConnectError as e:
            self._circuit_breaker.record_failure()
            raise SeafileError(f"Cannot connect to Seafile: {e}", 0)
        except httpx.TimeoutException as e:
            self._circuit_breaker.record_failure()
            raise SeafileError(f"Seafile connection timeout: {e}", 0)
    
    async def ensure_token(self) -> str:
        """Ensure we have a valid token, refresh if needed."""
        if not self._token or time.time() >= self._token_expires:
            await self.login(self.config.admin_username, self.config.admin_password)
        return self._token
    
    async def get_token(self) -> str:
        """Get current auth token."""
        return await self.ensure_token()
    
    # ─── Repositories ────────────────────────────────────
    
    async def list_repos(self, username: Optional[str] = None) -> List[RepoInfo]:
        """List repositories.
        
        Args:
            username: Optional username filter
            
        Returns:
            List of RepoInfo
        """
        token = await self.ensure_token()
        
        params = {}
        if username:
            params["username"] = username
        
        resp = await self._client.get(
            "/api2/repos/",
            headers={"Authorization": f"Token {token}"},
            params=params
        )
        
        if resp.status_code == 200:
            data = resp.json()
            repos = []
            for repo_data in data.get("repos", []):
                repos.append(RepoInfo(
                    repo_id=repo_data.get("id", ""),
                    name=repo_data.get("name", ""),
                    owner=repo_data.get("owner", ""),
                    description=repo_data.get("description", ""),
                    visibility=repo_data.get("visibility", "private"),
                    created_at=repo_data.get("created_at", 0),
                    modified_at=repo_data.get("last_modified", 0),
                    size=repo_data.get("size", 0)
                ))
            return repos
        
        raise SeafileError(f"Failed to list repos: {resp.text}", resp.status_code)
    
    async def create_repo(
        self,
        name: str,
        username: str,
        description: str = "",
        visibility: str = "private"
    ) -> RepoInfo:
        """Create a new repository for a user.
        
        Args:
            name: Repository name
            username: Owner username
            description: Repository description
            visibility: "private" or "public"
            
        Returns:
            Created RepoInfo
        """
        token = await self.ensure_token()
        
        # Use admin API to create repo for user
        resp = await self._client.post(
            f"/api2/admin/repos/",
            headers={"Authorization": f"Token {token}"},
            data={
                "repo_name": name,
                "username": username,
                "description": description,
                "visibility": visibility
            }
        )
        
        if resp.status_code == 200:
            data = resp.json()
            return RepoInfo(
                repo_id=data.get("repo_id", ""),
                name=name,
                owner=username,
                description=description,
                visibility=visibility
            )
        
        # Check if repo already exists
        if resp.status_code == 400:
            error = resp.json().get("error_msg", "")
            if "already exists" in error.lower():
                # Return existing repo
                repos = await self.list_repos(username)
                for repo in repos:
                    if repo.name == name:
                        return repo
            raise SeafileError(f"Failed to create repo: {error}", resp.status_code)
        
        raise SeafileError(f"Failed to create repo: {resp.text}", resp.status_code)
    
    async def get_repo(self, repo_id: str) -> RepoInfo:
        """Get repository information."""
        repos = await self.list_repos()
        for repo in repos:
            if repo.repo_id == repo_id:
                return repo
        raise SeafileNotFoundError(f"Repository {repo_id} not found", 404)
    
    # ─── File Operations ─────────────────────────────────
    
    async def list_files(
        self,
        repo_id: str,
        path: str = "/",
        order: str = "name"
    ) -> List[FileInfo]:
        """List files in a directory.
        
        Args:
            repo_id: Repository ID
            path: Directory path (default: root)
            order: Sort order ("name", "time", "-name", "-time")
            
        Returns:
            List of FileInfo
        """
        token = await self.ensure_token()
        
        resp = await self._client.get(
            f"/api2/repos/{repo_id}/dir/",
            headers={"Authorization": f"Token {token}"},
            params={"p": path, "order": order}
        )
        
        if resp.status_code == 200:
            data = resp.json()
            files = []
            for item in data.get("dir_commit", {}).get("entries", []):
                file_type = FileType.DIR if item.get("dirent_type") == "dir" else FileType.FILE
                files.append(FileInfo(
                    path=item.get("path", path),
                    name=item.get("obj_name", ""),
                    size=item.get("size", 0),
                    type=file_type,
                    id=item.get("oid", ""),
                    parent_dir=path,
                    repo_id=repo_id,
                    modified_at=item.get("last_modified", 0)
                ))
            return files
        
        if resp.status_code == 404:
            raise SeafileNotFoundError(f"Path {path} not found in repo {repo_id}", 404)
        
        raise SeafileError(f"Failed to list files: {resp.text}", resp.status_code)
    
    async def get_file_info(self, repo_id: str, path: str) -> FileInfo:
        """Get information about a specific file."""
        token = await self.ensure_token()
        
        resp = await self._client.get(
            f"/api2/repos/{repo_id}/file/",
            headers={"Authorization": f"Token {token}"},
            params={"p": path}
        )
        
        if resp.status_code == 200:
            data = resp.json()
            return FileInfo(
                path=path,
                name=data.get("filename", path.split("/")[-1]),
                size=data.get("size", 0),
                type=FileType.FILE,
                id=data.get("id", ""),
                repo_id=repo_id,
                modified_at=data.get("last_modified", 0)
            )
        
        if resp.status_code == 404:
            raise SeafileNotFoundError(f"File {path} not found", 404)
        
        raise SeafileError(f"Failed to get file info: {resp.text}", resp.status_code)
    
    async def upload_file(
        self,
        repo_id: str,
        path: str,
        file: Union[UploadFile, bytes, Path],
        progress_callback = None
    ) -> FileInfo:
        """Upload a file to Seafile.
        
        Args:
            repo_id: Repository ID
            path: Target path (e.g., "/documents/file.txt")
            file: UploadFile, bytes, or Path object
            progress_callback: Optional callback for upload progress
            
        Returns:
            Uploaded FileInfo
        """
        token = await self.ensure_token()
        
        # Extract parent directory and filename
        parent_dir = "/".join(path.split("/")[:-1]) or "/"
        filename = path.split("/")[-1]
        
        # Prepare file data
        if isinstance(file, UploadFile):
            file_content = await file.read()
        elif isinstance(file, Path):
            file_content = file.read_bytes()
        else:
            file_content = file
        
        # Upload using Seafile upload API
        # Seafile uses a two-step upload for large files
        # For simplicity, use the simple upload API for files < 100MB
        if len(file_content) > 100 * 1024 * 1024:
            # Large file - use chunked upload
            return await self._upload_large_file(repo_id, path, file_content, token)
        else:
            # Small file - use simple upload
            return await self._upload_small_file(repo_id, path, filename, file_content, token)
    
    async def _upload_small_file(
        self,
        repo_id: str,
        path: str,
        filename: str,
        file_content: bytes,
        token: str
    ) -> FileInfo:
        """Upload small file using simple API."""
        parent_dir = "/".join(path.split("/")[:-1]) or "/"
        
        # Step 1: Upload file to upload session
        upload_url = f"/api2/repos/{repo_id}/upload-file/"
        
        files = {
            "file": (filename, file_content),
            "parent_dir": (None, parent_dir),
        }
        
        resp = await self._client.post(
            upload_url,
            headers={"Authorization": f"Token {token}"},
            files=files
        )
        
        if resp.status_code == 200:
            data = resp.json()
            return FileInfo(
                path=path,
                name=filename,
                size=len(file_content),
                type=FileType.FILE,
                repo_id=repo_id,
                parent_dir=parent_dir
            )
        
        raise SeafileError(f"Upload failed: {resp.text}", resp.status_code)
    
    async def _upload_large_file(
        self,
        repo_id: str,
        path: str,
        file_content: bytes,
        token: str,
        chunk_size: int = 10 * 1024 * 1024  # 10MB chunks
    ) -> FileInfo:
        """Upload large file using chunked upload API."""
        filename = path.split("/")[-1]
        parent_dir = "/".join(path.split("/")[:-1]) or "/"
        
        # Step 1: Create upload session
        session_resp = await self._client.post(
            f"/api2/repos/{repo_id}/upload-attach-session/",
            headers={"Authorization": f"Token {token}"},
            data={
                "parent_dir": parent_dir,
                "total_size": len(file_content),
                "chunk_size": chunk_size,
                "file_name": filename
            }
        )
        
        if session_resp.status_code != 200:
            raise SeafileError(f"Failed to create upload session: {session_resp.text}")
        
        session_id = session_resp.json().get("upload_id")
        
        # Step 2: Upload chunks
        offset = 0
        chunk_index = 0
        while offset < len(file_content):
            chunk = file_content[offset:offset + chunk_size]
            
            files = {
                "file": (filename, chunk),
            }
            
            chunk_resp = await self._client.post(
                f"/api2/repos/{repo_id}/api/upload-chunk/?upload_id={session_id}&parent_dir={parent_dir}&total_size={len(file_content)}&chunk_size={chunk_size}&offset={offset}&file_name={filename}",
                headers={"Authorization": f"Token {token}"},
                files=files
            )
            
            if chunk_resp.status_code != 200:
                raise SeafileError(f"Failed to upload chunk {chunk_index}: {chunk_resp.text}")
            
            offset += chunk_size
            chunk_index += 1
        
        return FileInfo(
            path=path,
            name=filename,
            size=len(file_content),
            type=FileType.FILE,
            repo_id=repo_id,
            parent_dir=parent_dir
        )
    
    async def download_file(self, repo_id: str, path: str) -> bytes:
        """Download a file from Seafile.
        
        Args:
            repo_id: Repository ID
            path: File path
            
        Returns:
            File content as bytes
        """
        token = await self.ensure_token()
        
        # Get raw file URL
        resp = await self._client.get(
            f"/api2/repos/{repo_id}/file/raw/",
            headers={"Authorization": f"Token {token}"},
            params={"p": path}
        )
        
        if resp.status_code == 200:
            return resp.content
        
        if resp.status_code == 404:
            raise SeafileNotFoundError(f"File {path} not found", 404)
        
        raise SeafileError(f"Failed to download file: {resp.text}", resp.status_code)
    
    async def delete_file(self, repo_id: str, path: str) -> bool:
        """Delete a file or directory.
        
        Args:
            repo_id: Repository ID
            path: File/directory path
            
        Returns:
            True if deleted successfully
        """
        token = await self.ensure_token()
        
        resp = await self._client.post(
            f"/api2/repos/{repo_id}/dir/set-empty/",
            headers={"Authorization": f"Token {token}"},
            data={"p": path}
        )
        
        if resp.status_code == 200:
            return True
        
        raise SeafileError(f"Failed to delete: {resp.text}", resp.status_code)
    
    # ─── Directory Operations ────────────────────────────
    
    async def mkdir(self, repo_id: str, path: str) -> bool:
        """Create a new directory.
        
        Args:
            repo_id: Repository ID
            path: Directory path (e.g., "/documents/new-folder")
            
        Returns:
            True if created successfully
        """
        token = await self.ensure_token()
        
        parent_dir = "/".join(path.split("/")[:-1]) or "/"
        dirname = path.split("/")[-1]
        
        resp = await self._client.post(
            f"/api2/repos/{repo_id}/dir/set-empty/",
            headers={"Authorization": f"Token {token}"},
            data={"p": parent_dir, "obj_name": dirname, "obj_type": "dir"}
        )
        
        if resp.status_code == 200:
            return True
        
        raise SeafileError(f"Failed to create directory: {resp.text}", resp.status_code)
    
    async def rename(self, repo_id: str, old_path: str, new_name: str) -> bool:
        """Rename a file or directory.
        
        Args:
            repo_id: Repository ID
            old_path: Current path
            new_name: New name (not full path)
            
        Returns:
            True if renamed successfully
        """
        token = await self.ensure_token()
        
        parent_dir = "/".join(old_path.split("/")[:-1]) or "/"
        
        resp = await self._client.post(
            f"/api2/repos/{repo_id}/dir/rename/",
            headers={"Authorization": f"Token {token}"},
            data={
                "p": parent_dir,
                "old_name": old_path.split("/")[-1],
                "new_name": new_name
            }
        )
        
        if resp.status_code == 200:
            return True
        
        raise SeafileError(f"Failed to rename: {resp.text}", resp.status_code)
    
    async def move(
        self,
        repo_id: str,
        path: str,
        dest_repo_id: str,
        dest_path: str
    ) -> bool:
        """Move a file or directory.
        
        Args:
            repo_id: Source repository ID
            path: Source path
            dest_repo_id: Destination repository ID
            dest_path: Destination path
            
        Returns:
            True if moved successfully
        """
        token = await self.ensure_token()
        
        # Use operation API for move
        pks = [{"repo_id": repo_id, "path": path}]
        
        resp = await self._client.post(
            "/api2/repos/operations/move/",
            headers={"Authorization": f"Token {token}"},
            json={
                "pks": pks,
                "dst_repo_id": dest_repo_id,
                "dst_dir": "/".join(dest_path.split("/")[:-1]) or "/"
            }
        )
        
        if resp.status_code == 200:
            return True
        
        raise SeafileError(f"Failed to move: {resp.text}", resp.status_code)
    
    async def copy(
        self,
        repo_id: str,
        path: str,
        dest_repo_id: str,
        dest_path: str
    ) -> bool:
        """Copy a file or directory.
        
        Args:
            repo_id: Source repository ID
            path: Source path
            dest_repo_id: Destination repository ID
            dest_path: Destination path
            
        Returns:
            True if copied successfully
        """
        token = await self.ensure_token()
        
        pks = [{"repo_id": repo_id, "path": path}]
        
        resp = await self._client.post(
            "/api2/repos/operations/copy/",
            headers={"Authorization": f"Token {token}"},
            json={
                "pks": pks,
                "dst_repo_id": dest_repo_id,
                "dst_dir": "/".join(dest_path.split("/")[:-1]) or "/"
            }
        )
        
        if resp.status_code == 200:
            return True
        
        raise SeafileError(f"Failed to copy: {resp.text}", resp.status_code)
    
    # ─── Share Links ─────────────────────────────────────
    
    async def create_share_link(
        self,
        repo_id: str,
        path: str,
        days: int = 7,
        password: Optional[str] = None,
        can_download: bool = True
    ) -> ShareLink:
        """Create a share link.
        
        Args:
            repo_id: Repository ID
            path: File/directory path
            days: Link expiration in days
            password: Optional password protection
            can_download: Allow download
            
        Returns:
            ShareLink object
        """
        token = await self.ensure_token()
        
        resp = await self._client.post(
            "/api2/share-link/",
            headers={"Authorization": f"Token {token}"},
            data={
                "repo_id": repo_id,
                "path": path,
                "days": days,
                "password": password or "",
                "can_download": str(can_download).lower()
            }
        )
        
        if resp.status_code == 201:
            data = resp.json()
            return ShareLink(
                token=data.get("token", ""),
                share_id=data.get("share_id", 0),
                file_path=path,
                repo_id=repo_id,
                username=data.get("username", ""),
                password=password or "",
                days=days,
                created_at=data.get("timestamp", 0)
            )
        
        raise SeafileError(f"Failed to create share link: {resp.text}", resp.status_code)
    
    async def list_shares(self, repo_id: Optional[str] = None) -> List[ShareLink]:
        """List share links.
        
        Args:
            repo_id: Optional repository filter
            
        Returns:
            List of ShareLink
        """
        token = await self.ensure_token()
        
        params = {}
        if repo_id:
            params["repo_id"] = repo_id
        
        resp = await self._client.get(
            "/api2/share-links/",
            headers={"Authorization": f"Token {token}"},
            params=params
        )
        
        if resp.status_code == 200:
            data = resp.json()
            shares = []
            for item in data.get("shares", []):
                shares.append(ShareLink(
                    token=item.get("token", ""),
                    share_id=item.get("share_id", 0),
                    file_path=item.get("path", ""),
                    repo_id=item.get("repo_id", ""),
                    username=item.get("username", ""),
                    view_cnt=item.get("view_cnt", 0),
                    download_cnt=item.get("download_cnt", 0),
                    created_at=item.get("timestamp", 0)
                ))
            return shares
        
        raise SeafileError(f"Failed to list shares: {resp.text}", resp.status_code)
    
    async def delete_share_link(self, share_id: int) -> bool:
        """Delete a share link.
        
        Args:
            share_id: Share link ID
            
        Returns:
            True if deleted successfully
        """
        token = await self.ensure_token()
        
        resp = await self._client.delete(
            f"/api2/share-links/{share_id}/",
            headers={"Authorization": f"Token {token}"}
        )
        
        if resp.status_code == 200:
            return True
        
        raise SeafileError(f"Failed to delete share link: {resp.text}", resp.status_code)
    
    # ─── Search ──────────────────────────────────────────
    
    async def search_files(
        self,
        query: str,
        repo_id: Optional[str] = None,
        path: str = "/"
    ) -> List[FileInfo]:
        """Search for files.
        
        Args:
            query: Search query
            repo_id: Optional repository filter
            path: Optional path filter
            
        Returns:
            List of matching FileInfo
        """
        token = await self.ensure_token()
        
        params = {"q": query, "path": path}
        if repo_id:
            params["repo_id"] = repo_id
        
        resp = await self._client.get(
            "/api2/search/",
            headers={"Authorization": f"Token {token}"},
            params=params
        )
        
        if resp.status_code == 200:
            data = resp.json()
            files = []
            for repo_results in data.get("repos", []):
                for item in repo_results.get("paths", []):
                    file_type = FileType.DIR if "/dir/" in item.get("path", "") else FileType.FILE
                    files.append(FileInfo(
                        path=item.get("path", ""),
                        name=item.get("path", "").split("/")[-1],
                        type=file_type,
                        repo_id=repo_results.get("repo_id", "")
                    ))
            return files
        
        raise SeafileError(f"Search failed: {resp.text}", resp.status_code)
    
    # ─── User Management (Admin API) ─────────────────────
    
    async def create_user(
        self,
        email: str,
        password: str,
        name: str = "",
    is_staff: bool = False,
        contact_email: str = "",
        affiliation: str = ""
    ) -> UserInfo:
        """Create a new user (Admin API).
        
        Args:
            email: User email
            password: User password
            name: Display name
            is_staff: Admin privileges
            contact_email: Contact email
            affiliation: Organization
            
        Returns:
            Created UserInfo
        """
        token = await self.ensure_token()
        
        resp = await self._client.post(
            "/api2/admin/users/create/",
            headers={"Authorization": f"Token {token}"},
            data={
                "email": email,
                "password": password,
                "name": name or email.split("@")[0],
                "is_staff": "true" if is_staff else "false",
                "contact_email": contact_email,
                "affiliation": affiliation
            }
        )
        
        if resp.status_code == 200:
            data = resp.json()
            return UserInfo(
                email=email,
                name=name or email.split("@")[0],
                is_active=True,
                is_staff=is_staff,
                contact_email=contact_email,
                affiliation=affiliation
            )
        
        # Check if user already exists
        if resp.status_code == 400:
            error = resp.json().get("error_msg", "")
            if "already exists" in error.lower():
                # Return existing user
                users = await self.list_users()
                for user in users:
                    if user.email == email:
                        return user
            raise SeafileError(f"Failed to create user: {error}", resp.status_code)
        
        raise SeafileError(f"Failed to create user: {resp.text}", resp.status_code)
    
    async def list_users(self) -> List[UserInfo]:
        """List all users (Admin API).
        
        Returns:
            List of UserInfo
        """
        token = await self.ensure_token()
        
        resp = await self._client.get(
            "/api2/admin/users/",
            headers={"Authorization": f"Token {token}"},
            params={"expected": 1000}
        )
        
        if resp.status_code == 200:
            data = resp.json()
            users = []
            for user_data in data.get("users", []):
                users.append(UserInfo(
                    email=user_data.get("email", ""),
                    name=user_data.get("name", ""),
                    created_at=user_data.get("date_joined", 0),
                    last_login=user_data.get("last_login", 0),
                    is_active=user_data.get("is_active", True),
                    is_staff=user_data.get("is_staff", False),
                    contact_email=user_data.get("contact_email", ""),
                    affiliation=user_data.get("affiliation", "")
                ))
            return users
        
        raise SeafileError(f"Failed to list users: {resp.text}", resp.status_code)
    
    async def get_user(self, email: str) -> Optional[UserInfo]:
        """Get user information by email.
        
        Args:
            email: User email
            
        Returns:
            UserInfo or None if not found
        """
        users = await self.list_users()
        for user in users:
            if user.email == email:
                return user
        return None
    
    async def update_user(
        self,
        email: str,
        name: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_staff: Optional[bool] = None
    ) -> UserInfo:
        """Update user information (Admin API).
        
        Args:
            email: User email
            name: New display name
            is_active: Activate/deactivate user
            is_staff: Grant/revoke admin privileges
            
        Returns:
            Updated UserInfo
        """
        token = await self.ensure_token()
        
        data = {}
        if name is not None:
            data["name"] = name
        if is_active is not None:
            data["is_active"] = "true" if is_active else "false"
        if is_staff is not None:
            data["is_staff"] = "true" if is_staff else "false"
        
        resp = await self._client.put(
            f"/api2/admin/users/{email}/",
            headers={"Authorization": f"Token {token}"},
            data=data
        )
        
        if resp.status_code == 200:
            return await self.get_user(email)
        
        raise SeafileError(f"Failed to update user: {resp.text}", resp.status_code)
    
    async def delete_user(self, email: str) -> bool:
        """Delete a user (Admin API).
        
        Args:
            email: User email
            
        Returns:
            True if deleted successfully
        """
        token = await self.ensure_token()
        
        resp = await self._client.delete(
            f"/api2/admin/users/{email}/",
            headers={"Authorization": f"Token {token}"}
        )
        
        if resp.status_code == 200:
            return True
        
        raise SeafileError(f"Failed to delete user: {resp.text}", resp.status_code)
    
    async def reset_user_password(self, email: str, new_password: str) -> bool:
        """Reset user password (Admin API).
        
        Args:
            email: User email
            new_password: New password
            
        Returns:
            True if password reset successfully
        """
        token = await self.ensure_token()
        
        resp = await self._client.post(
            f"/api2/admin/users/{email}/set-password/",
            headers={"Authorization": f"Token {token}"},
            data={"password": new_password}
        )
        
        if resp.status_code == 200:
            return True
        
        raise SeafileError(f"Failed to reset password: {resp.text}", resp.status_code)
