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

"""User store - JSON-based user persistence (no database).

Stores:
- User credentials (username, password hash, salt)
- User profiles (display_name, avatar_url)
- User roles (admin, user)
- User metadata (created_at, last_login)

File: ~/.coapis/users/users.json
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import bcrypt

from ..constant import SYSTEM_DIR, USERS_FILE
from ..utils.file_lock import safe_read_json, safe_write_json

logger = logging.getLogger(__name__)


def _ensure_users_dir() -> None:
    """Ensure system directory exists with secure permissions."""
    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(SYSTEM_DIR), 0o700)
    except OSError:
        pass


def _load_users() -> Dict[str, Any]:
    """Load users from file with shared lock. Returns empty dict if missing."""
    _ensure_users_dir()
    data = safe_read_json(USERS_FILE, default={"users": {}})
    if not isinstance(data, dict) or "users" not in data:
        data = {"users": {}}
    return data


def _save_users(data: Dict[str, Any]) -> None:
    """Save users to file with exclusive lock and atomic write."""
    _ensure_users_dir()
    if not safe_write_json(USERS_FILE, data):
        logger.error("Failed to save users")


# ---------------------------------------------------------------------------
# Password hashing (bcrypt with SHA-256 backward compatibility)
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hash password. New passwords use bcrypt; legacy SHA-256 for verification."""
    if salt is None:
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        return hashed.decode("utf-8"), "$2b$"  # salt marker
    # Legacy SHA-256 path
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return h, salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify password against stored hash (supports bcrypt and SHA-256)."""
    if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    h, _ = _hash_password(password, salt)
    return secrets.compare_digest(h, stored_hash)


# ---------------------------------------------------------------------------
# User CRUD operations
# ---------------------------------------------------------------------------

def list_users() -> List[Dict[str, Any]]:
    """List all users (without password hashes)."""
    data = _load_users()
    result = []
    for username, info in data.get("users", {}).items():
        result.append({
            "username": username,
            "display_name": info.get("display_name", username),
            "role": info.get("role", "user"),
            "created_at": info.get("created_at"),
            "last_login": info.get("last_login"),
        })
    return result


def get_user(username: str) -> Optional[Dict[str, Any]]:
    """Get user by username (without password hash)."""
    data = _load_users()
    info = data.get("users", {}).get(username)
    if info is None:
        return None
    return {
        "username": username,
        "display_name": info.get("display_name", username),
        "role": info.get("role", "user"),
        "created_at": info.get("created_at"),
        "last_login": info.get("last_login"),
    }


def get_user_with_creds(username: str) -> Optional[Dict[str, Any]]:
    """Get user with credentials (for auth verification)."""
    data = _load_users()
    info = data.get("users", {}).get(username)
    if info is None:
        return None
    return {
        "username": username,
        "display_name": info.get("display_name", username),
        "role": info.get("role", "user"),
        "password_hash": info.get("password_hash"),
        "salt": info.get("salt"),
        "created_at": info.get("created_at"),
        "last_login": info.get("last_login"),
    }


def create_user(
    username: str,
    password: str,
    display_name: str = None,
    role: str = "user",
) -> bool:
    """Create a new user. Returns False if user already exists."""
    data = _load_users()
    if username in data.get("users", {}):
        return False

    pw_hash, salt = _hash_password(password)
    data["users"][username] = {
        "display_name": display_name or username,
        "password_hash": pw_hash,
        "salt": salt,
        "role": role,
        "is_active": True,
        "created_at": time.time(),
        "last_login": None,
    }
    _save_users(data)
    logger.info(f"Created user: {username}")

    # Create user's isolated data directories
    _create_user_dirs(username)

    return True


def update_user(
    username: str,
    display_name: str | None = None,
    new_password: str | None = None,
    current_password: str | None = None,
    is_active: bool | None = None,
    role: str | None = None,
    **kwargs: Any,
) -> bool:
    """Update user info safely.

    Supports updating individual fields without overwriting the entire user record.

    Args:
        username: Username to update
        display_name: New display name (optional)
        new_password: New password (optional, requires current_password)
        current_password: Current password for verification (required when changing password)
        is_active: User active status (optional)
        role: User role (optional)
        **kwargs: Additional fields to update safely

    Returns:
        True if successful, False if user doesn't exist or password mismatch

    Note:
        - Password change requires current_password verification
        - Only explicitly provided fields are updated
        - Critical fields (username, password_hash, salt) cannot be overwritten via kwargs
    """
    # Fields that should never be overwritten via kwargs
    PROTECTED_FIELDS = {"username", "password_hash", "salt", "created_at"}

    data = _load_users()
    if username not in data.get("users", {}):
        logger.warning(f"Cannot update user {username}: user does not exist")
        return False

    user_data = data["users"][username]

    # Verify current password if changing password
    if new_password is not None:
        if current_password is None:
            logger.warning(f"Cannot update password for {username}: current_password required")
            return False
        if not verify_password(
            current_password,
            user_data.get("password_hash", ""),
            user_data.get("salt", ""),
        ):
            logger.warning(f"Password update failed for {username}: incorrect current password")
            return False
        pw_hash, salt = _hash_password(new_password)
        user_data["password_hash"] = pw_hash
        user_data["salt"] = salt

    # Update individual fields (only if explicitly provided)
    if display_name is not None:
        user_data["display_name"] = display_name

    if is_active is not None:
        user_data["is_active"] = is_active

    if role is not None:
        user_data["role"] = role

    # Update additional fields (but protect critical fields)
    for key, value in kwargs.items():
        if key in PROTECTED_FIELDS:
            logger.warning(
                f"Skipping protected field '{key}' for user {username}"
            )
            continue
        user_data[key] = value

    _save_users(data)
    logger.info(f"Updated user: {username}")
    return True


def delete_user(username: str) -> bool:
    """Delete a user. Returns False if user doesn't exist."""
    data = _load_users()
    if username not in data.get("users", {}):
        return False

    del data["users"][username]
    _save_users(data)
    logger.info(f"Deleted user: {username}")
    return True


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate user with username and password.

    Returns user info if valid, None if invalid.
    """
    user_creds = get_user_with_creds(username)
    if user_creds is None:
        return None

    if not verify_password(password, user_creds.get("password_hash", ""), user_creds.get("salt", "")):
        return None

    # Update last login
    data = _load_users()
    data["users"][username]["last_login"] = time.time()
    _save_users(data)

    return {
        "username": username,
        "display_name": user_creds.get("display_name", username),
        "role": user_creds.get("role", "user"),
    }


def has_registered_users() -> bool:
    """Check if any users are registered."""
    data = _load_users()
    return len(data.get("users", {})) > 0


# ---------------------------------------------------------------------------
# User directory management
# ---------------------------------------------------------------------------

def _create_user_dirs(username: str) -> None:
    """Create isolated data directories for a user."""
    from ..constant import WORKSPACES_DIR

    user_base = WORKSPACES_DIR / username
    dirs = [
        user_base / "agents",
        user_base / "skills",
        user_base / "workflows",
        user_base / "chat",
        user_base / "files",
        user_base / "crons",
        user_base / "backups",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    logger.info(f"Created user directories for: {username}")


def get_user_workspace_dir(username: str) -> Path:
    """Get user's workspace directory (unified user data path)."""
    from ..constant import WORKSPACES_DIR
    return WORKSPACES_DIR / username


def get_user_agents_dir(username: str) -> Path:
    """Get user's agents directory."""
    return get_user_workspace_dir(username) / "agents"


def get_user_skills_dir(username: str) -> Path:
    """Get user's skills directory."""
    return get_user_workspace_dir(username) / "skills"


def get_user_workflows_dir(username: str) -> Path:
    """Get user's workflows directory."""
    return get_user_workspace_dir(username) / "workflows"


def get_user_chats_dir(username: str) -> Path:
    """Get user's chats directory."""
    return get_user_workspace_dir(username) / "chat"

