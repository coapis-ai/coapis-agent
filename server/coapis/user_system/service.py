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
    """Verify password against stored hash (constant-time comparison)."""
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

    # Check if username already exists
    existing = db.fetch_one("SELECT id FROM users WHERE username = ?", (req.username,))
    if existing:
        raise ValueError(f"Username '{req.username}' already exists")

    # Check email uniqueness if provided
    if req.email:
        email_exists = db.fetch_one("SELECT id FROM users WHERE email = ?", (req.email,))
        if email_exists:
            raise ValueError(f"Email '{req.email}' already registered")

    password_hash, salt = _hash_password(req.password)
    now = time.time()
    cfg = get_config()

    # Generate MuGA tenant key (UUID) for user-isolated file space
    import uuid
    muga_key = req.muga_key or str(uuid.uuid4())

    # Insert user
    cur = db.execute("""
        INSERT INTO users (
            username, email, display_name, password_hash, salt,
            token_quota_monthly, token_used_monthly,
            role, is_active, created_at, updated_at, last_login_at,
            muga_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        req.username,
        req.email,
        req.display_name or req.username,
        password_hash,
        salt,
        cfg.default_token_quota,
        0,
        req.role,
        1,
        now,
        now,
        now,
        muga_key,
    ))
    db.commit()

    user_id = cur.lastrowid
    return _user_row_to_response(db.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,)))


def get_user_by_username(username: str) -> Optional[UserResponse]:
    """Get user by username."""
    db = get_db()
    row = db.fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    return _user_row_to_response(row) if row else None


# Alias for backward compatibility
get_user = get_user_by_username


def get_user_by_id(user_id: int) -> Optional[UserResponse]:
    """Get user by ID."""
    db = get_db()
    row = db.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    return _user_row_to_response(row) if row else None


def get_user_by_email(email: str) -> Optional[UserResponse]:
    """Get user by email."""
    db = get_db()
    row = db.fetch_one("SELECT * FROM users WHERE email = ?", (email,))
    return _user_row_to_response(row) if row else None


def update_user(username: str, req: UserUpdate) -> UserResponse:
    """Update user profile."""
    db = get_db()
    existing = db.fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if not existing:
        raise ValueError(f"User '{username}' not found")

    updates = []
    params = []

    if req.email is not None:
        # Check email uniqueness
        if req.email != existing.get("email"):
            email_exists = db.fetch_one(
                "SELECT id FROM users WHERE email = ? AND username != ?",
                (req.email, username)
            )
            if email_exists:
                raise ValueError(f"Email '{req.email}' already registered")
        updates.append("email = ?")
        params.append(req.email)

    if req.display_name is not None:
        updates.append("display_name = ?")
        params.append(req.display_name)

    if req.avatar_url is not None:
        updates.append("avatar_url = ?")
        params.append(req.avatar_url)

    if req.password is not None:
        password_hash, salt = _hash_password(req.password)
        updates.append("password_hash = ?")
        updates.append("salt = ?")
        params.extend([password_hash, salt])

    if req.role is not None:
        updates.append("role = ?")
        params.append(req.role)

    if req.token_quota_monthly is not None:
        updates.append("token_quota_monthly = ?")
        params.append(req.token_quota_monthly)

    if req.is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if req.is_active else 0)

    if not updates:
        return get_user_by_username(username)

    updates.append("updated_at = ?")
    params.append(time.time())
    params.append(username)

    db.execute(
        f"UPDATE users SET {', '.join(updates)} WHERE username = ?",
        tuple(params),
    )
    db.commit()

    return get_user_by_username(username)


def delete_user(username: str) -> bool:
    """Delete a user."""
    db = get_db()
    existing = db.fetch_one("SELECT id FROM users WHERE username = ?", (username,))
    if not existing:
        return False

    db.execute("DELETE FROM users WHERE username = ?", (username,))
    db.commit()
    return True


def list_users(page: int = 1, page_size: int = 20) -> UserListResponse:
    """List users with pagination."""
    db = get_db()
    total = db.fetch_one("SELECT COUNT(*) as cnt FROM users")["cnt"]
    offset = (page - 1) * page_size
    rows = db.fetch_all(
        "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (page_size, offset),
    )
    users = [_user_row_to_response(r) for r in rows]
    return UserListResponse(users=users, total=total, page=page, page_size=page_size)


def authenticate(username: str, password: str) -> Optional[UserResponse]:
    """Authenticate user by username and password."""
    db = get_db()
    row = db.fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if not row:
        return None

    stored_hash = row["password_hash"]
    salt = row["salt"]
    if not verify_password(password, stored_hash, salt):
        return None

    # Update last login
    db.execute(
        "UPDATE users SET last_login_at = ? WHERE username = ?",
        (time.time(), username),
    )
    db.commit()

    return _user_row_to_response(row)
