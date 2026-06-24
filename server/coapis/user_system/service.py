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

"""User service - core business logic for user management.

Handles:
- User CRUD (create, read, update, delete)
- Password hashing (salted SHA-256)
- Token quota management

Simplified: no user levels, no points system.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import Any, Dict, List, Optional

from ..user_system.database import get_db
from ..user_system.models import (
    UserCreate, UserUpdate, UserResponse, UserListResponse,
)
from ..user_system.config import get_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Password hashing (salted SHA-256, no external deps)
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hash password with salt. Returns (hash_hex, salt_hex)."""
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return h, salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify password against stored hash. Supports both bcrypt and SHA-256."""
    if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
        import bcrypt
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    # Legacy SHA-256
    h, _ = _hash_password(password, salt)
    return hmac.compare_digest(h, stored_hash)


# Alias for backward compatibility
_verify_password = verify_password


# ---------------------------------------------------------------------------
# User row → response mapping
# ---------------------------------------------------------------------------

def _today_str() -> str:
    """Return today's date string (YYYY-MM-DD) in local time."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def _user_row_to_response(row: Any) -> UserResponse:
    """Convert a database row to UserResponse."""
    if row is None:
        return None
    return UserResponse(
        id=row["id"],
        username=row["username"],
        email=row.get("email"),
        display_name=row.get("display_name"),
        avatar_url=row.get("avatar_url"),
        token_quota_monthly=row.get("token_quota_monthly", 1_000_000),
        token_used_monthly=row.get("token_used_monthly", 0),
        role=row.get("role", "user"),
        is_active=bool(row.get("is_active", 1)),
        created_at=row.get("created_at"),
        last_login_at=row.get("last_login_at"),
        muga_key=row.get("muga_key"),
    )


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def create_user(req: UserCreate) -> UserResponse:
    """Create a new user. Raises ValueError if username exists."""
    db = get_db()

    if db.user_exists(req.username):
        raise ValueError(f"Username '{req.username}' already exists")

    if req.email and db.email_exists(req.email):
        raise ValueError(f"Email '{req.email}' already registered")

    password_hash, salt = _hash_password(req.password)
    now = time.time()
    cfg = get_config()

    import uuid
    muga_key = req.muga_key or str(uuid.uuid4())

    user_data = {
        "username": req.username,
        "email": req.email,
        "display_name": req.display_name or req.username,
        "password_hash": password_hash,
        "salt": salt,
        "token_quota_monthly": cfg.default_token_quota,
        "token_used_monthly": 0,
        "role": req.role,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "last_login_at": now,
        "muga_key": muga_key,
    }
    user_id = db.insert_user(user_data)
    user_data["id"] = user_id
    return _user_row_to_response(user_data)


def get_user_by_username(username: str) -> Optional[UserResponse]:
    """Get user by username."""
    db = get_db()
    row = db.get_user_by_username(username)
    return _user_row_to_response(row) if row else None


# Alias for backward compatibility
get_user = get_user_by_username


def get_user_by_id(user_id: int) -> Optional[UserResponse]:
    """Get user by ID."""
    db = get_db()
    row = db.get_user_by_id(user_id)
    return _user_row_to_response(row) if row else None


def get_user_by_email(email: str) -> Optional[UserResponse]:
    """Get user by email."""
    db = get_db()
    row = db.get_user_by_email(email)
    return _user_row_to_response(row) if row else None


def update_user(username: str, req: UserUpdate) -> UserResponse:
    """Update user profile."""
    db = get_db()
    existing = db.get_user_by_username(username)
    if not existing:
        raise ValueError(f"User '{username}' not found")

    updates = {}

    if req.email is not None:
        if req.email != existing.get("email"):
            if db.email_exists(req.email):
                raise ValueError(f"Email '{req.email}' already registered")
        updates["email"] = req.email

    if req.display_name is not None:
        updates["display_name"] = req.display_name

    if req.avatar_url is not None:
        updates["avatar_url"] = req.avatar_url

    if req.password is not None:
        password_hash, salt = _hash_password(req.password)
        updates["password_hash"] = password_hash
        updates["salt"] = salt

    if req.role is not None:
        updates["role"] = req.role

    if req.token_quota_monthly is not None:
        updates["token_quota_monthly"] = req.token_quota_monthly

    if req.is_active is not None:
        updates["is_active"] = req.is_active

    if updates:
        updates["updated_at"] = time.time()
        db.update_user(username, updates)

    return get_user_by_username(username)


def delete_user(username: str) -> bool:
    """Delete a user."""
    db = get_db()
    return db.delete_user(username)


def list_users(page: int = 1, page_size: int = 20) -> UserListResponse:
    """List users with pagination."""
    db = get_db()
    rows, total = db.list_users_page(page, page_size)
    users = [_user_row_to_response(r) for r in rows]
    return UserListResponse(users=users, total=total, page=page, page_size=page_size)


def authenticate(username: str, password: str) -> Optional[UserResponse]:
    """Authenticate user by username and password."""
    db = get_db()
    row = db.get_user_by_username(username)
    if not row:
        return None

    stored_hash = row["password_hash"]
    salt = row["salt"]
    if not verify_password(password, stored_hash, salt):
        return None

    db.update_user(username, {"last_login_at": time.time()})

    return _user_row_to_response(row)
