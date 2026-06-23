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

"""Authentication module - JWT tokens, middleware, and user auth.

Features:
- Password hashing (salted SHA-256, no external deps)
- JWT-like token generation (HMAC-SHA256)
- Token verification and revocation
- FastAPI middleware for request authentication
- Auth is always enabled in the multi-user system.

File: ~/.coapis/auth/auth.json (JWT secret + revoked tokens)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets

import bcrypt
import time
from typing import Optional

from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..constant import (
    SYSTEM_DIR, AUTH_FILE,
    TOKEN_EXPIRY_SECONDS, TOKEN_EXPIRY_MAX,
    PUBLIC_PATHS, PUBLIC_PREFIXES,
)
from ..utils.file_lock import safe_read_json, safe_write_json
from .user_store import authenticate_user, has_registered_users, get_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Password hashing (bcrypt with SHA-256 backward compatibility)
# ---------------------------------------------------------------------------

_BCRYPT_PREFIX = "$2b$"


def _hash_password(
    password: str,
    salt: Optional[str] = None,
) -> tuple[str, str]:
    """Hash *password* with *salt*.

    New passwords use bcrypt (``salt=None``).
    Legacy SHA-256 verification passes the original *salt*.
    Returns ``(hash_hex_or_bcrypt, salt_hex)``.
    """
    if salt is None:
        # New password → bcrypt
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        return hashed.decode("utf-8"), _BCRYPT_PREFIX  # salt marker
    # Legacy SHA-256 path (for verifying old hashes)
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return h, salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify *password* against a stored hash.

    Supports both bcrypt (new) and SHA-256 (legacy) hashes.
    """
    if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
        # bcrypt hash
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    # Legacy SHA-256
    h, _ = _hash_password(password, salt)
    return hmac.compare_digest(h, stored_hash)


def needs_rehash(stored_hash: str) -> bool:
    """Return True if the hash should be upgraded to bcrypt."""
    return not (stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"))


# ---------------------------------------------------------------------------
# Auth data persistence
# ---------------------------------------------------------------------------

def _ensure_auth_dir() -> None:
    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(SYSTEM_DIR), 0o700)
    except OSError:
        pass


def _load_auth_data() -> dict:
    _ensure_auth_dir()
    data = safe_read_json(AUTH_FILE, default={"jwt_secret": "", "revoked_tokens": {}})
    if "jwt_secret" not in data:
        data["jwt_secret"] = ""
    if "revoked_tokens" not in data:
        data["revoked_tokens"] = {}
    return data


def _save_auth_data(data: dict) -> None:
    _ensure_auth_dir()
    if not safe_write_json(AUTH_FILE, data):
        logger.error("Failed to save auth data")


# ---------------------------------------------------------------------------
# Auth enabled check
# ---------------------------------------------------------------------------

def is_auth_enabled() -> bool:
    """Check if authentication is enabled.

    Multi-user system always requires authentication.
    """
    return True


# ---------------------------------------------------------------------------
# Token generation / verification
# ---------------------------------------------------------------------------

def _get_jwt_secret() -> str:
    """Return the signing secret, creating one if absent."""
    data = _load_auth_data()
    secret = data.get("jwt_secret", "")
    if not secret:
        secret = secrets.token_hex(32)
        data["jwt_secret"] = secret
        _save_auth_data(data)
    return secret


def create_token(username: str, expiry_seconds: Optional[int] = None) -> str:
    """Create HMAC-signed token: base64(payload).signature"""
    if expiry_seconds is None:
        expiry_seconds = TOKEN_EXPIRY_SECONDS
    elif expiry_seconds <= 0:
        expiry_seconds = TOKEN_EXPIRY_MAX
    else:
        expiry_seconds = min(expiry_seconds, TOKEN_EXPIRY_MAX)

    secret = _get_jwt_secret()
    token_id = secrets.token_hex(16)
    payload = json.dumps({
        "sub": username,
        "exp": int(time.time()) + expiry_seconds,
        "iat": int(time.time()),
        "jti": token_id,
    })
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_token(token: str) -> Optional[str]:
    """Verify token, return username if valid, None otherwise."""
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        secret = _get_jwt_secret()
        expected_sig = hmac.new(
            secret.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None
        jti = payload.get("jti")
        if jti and _is_token_revoked(jti):
            return None
        return payload.get("sub")
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Token revocation
# ---------------------------------------------------------------------------

def _is_token_revoked(jti: str) -> bool:
    data = _load_auth_data()
    return jti in data.get("revoked_tokens", {})


def revoke_token(token: str) -> bool:
    """Revoke a single token by extracting its jti."""
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return False
        payload = json.loads(base64.urlsafe_b64decode(parts[0]))
        jti = payload.get("jti")
        if not jti:
            return False
        data = _load_auth_data()
        data.setdefault("revoked_tokens", {})[jti] = time.time()
        _save_auth_data(data)
        return True
    except Exception:
        return False


def revoke_all_tokens_for_user(username: str) -> int:
    """Revoke all tokens for a user (force logout all sessions).

    Returns number of tokens revoked.
    """
    # This requires scanning all stored tokens - simplified approach:
    # Change the JWT secret, which invalidates all tokens
    data = _load_auth_data()
    old_secret = data.get("jwt_secret", "")
    # We don't change the secret (would invalidate ALL users)
    # Instead, we add username to a blocklist
    # For now, just return 0 - proper implementation needs token storage
    return 0


# ---------------------------------------------------------------------------
# High-level auth functions
# ---------------------------------------------------------------------------

def authenticate(username: str, password: str,
                 expiry_seconds: Optional[int] = None) -> Optional[str]:
    """Authenticate user and return token.
    
    Checks JSON user_store first, then falls back to user_system SQLite.
    This ensures users registered via /api/users/register can login via /api/auth/login.
    """
    user_info = authenticate_user(username, password)
    if user_info is not None:
        return create_token(username, expiry_seconds)
    
    # Fallback: try user_system SQLite
    try:
        from ..user_system.service import authenticate as us_authenticate
        us_user = us_authenticate(username, password)
        if us_user:
            # Sync to JSON user_store for future logins
            try:
                from .user_store import get_user as json_get_user
                if not json_get_user(username):
                    from .user_store import create_user as json_create_user
                    json_create_user(username, password)
                    logger.info(f"Synced user_system user {username} to auth store")
            except Exception as sync_err:
                logger.warning(f"Failed to sync {username} to auth store: {sync_err}")
            
            return create_token(username, expiry_seconds)
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"user_system auth fallback failed: {e}")
    
    return None


def register_user(username: str, password: str,
                  expiry_seconds: Optional[int] = None, request: Any = None) -> Optional[str]:
    """Register new user and return token. Returns None if failed.
    
    Syncs to both JSON user_store and SQLite user_system for dual-store consistency.
    
    Args:
        username: Username to register
        password: Password
        expiry_seconds: Token expiry
        request: Optional FastAPI Request for runtime MultiAgentManager registration
    """
    from .user_store import create_user
    if not create_user(username, password):
        return None
    
    # Sync to SQLite user_system for dual-store consistency
    try:
        from ..user_system.database import UserSystemDB
        from ..user_system.config import get_config
        config = get_config()
        if config.enabled:
            db = UserSystemDB()
            # Hash password for SQLite
            import secrets, hashlib
            salt = secrets.token_hex(16)
            pw_hash, _ = _hash_password(password, salt)
            db.create_user(username, pw_hash, salt, role="user")
            logger.info(f"Synced user '{username}' to SQLite user_system")
    except Exception as e:
        logger.warning(f"Failed to sync user '{username}' to SQLite: {e}")

    # Initialize user workspace (agent, skills, workflows, etc.) — pass request for runtime registration
    try:
        from .user_provisioning import init_user_workspace
        agent_id = init_user_workspace(username, display_name=username, request=request)
        logger.info(f"User {username} workspace initialized (agent: {agent_id})")
    except Exception as e:
        logger.error(
            f"Failed to initialize workspace for {username}: {e}. "
            "User created but workspace may be incomplete.",
            exc_info=True,
        )
        # Don't fail registration - workspace can be initialized later

    return create_token(username, expiry_seconds)


# ---------------------------------------------------------------------------
# FastAPI middleware
# ---------------------------------------------------------------------------

class AuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for JWT authentication.

    - Skips public paths
    - Extracts token from Authorization header
    - Sets request.state.user_info on success
    - Returns 401 on failure
    """

    async def dispatch(self, request: Request, call_next):
        # Skip SSE streaming endpoints — BaseHTTPMiddleware deadlocks with async generators
        if request.url.path == "/api/console/chat":
            # Extract token and set user info inline (avoid deadlock)
            auth_header = request.headers.get("authorization", "")
            username = "anonymous"
            role = "user"
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                username = verify_token(token) or "anonymous"
                if username != "anonymous":
                    user_info = get_user(username)
                    if user_info:
                        role = user_info.get("role", "user")
            # SECURITY: When auth is enabled, reject unauthenticated requests
            if username == "anonymous" and is_auth_enabled():
                return JSONResponse(
                    status_code=401,
                    content={"detail": "需要登录"}
                )
            request.state.username = username
            request.state.role = role
            request.state.user_info = {"username": username, "role": role}
            return await call_next(request)

        # Skip if auth is disabled
        if not is_auth_enabled():
            request.state.user_info = {"username": "anonymous", "role": "user"}
            request.state.username = "anonymous"
            request.state.role = "user"
            return await call_next(request)

        path = request.url.path

        # Check public paths
        if path in PUBLIC_PATHS:
            return await call_next(request)

        # Check public prefixes
        is_public = False
        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix):
                is_public = True
                break
        if is_public:
            return await call_next(request)

        # Extract token
        auth_header = request.headers.get("authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing authentication token"},
            )

        username = verify_token(token)
        if username is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        # Set user info on request
        # Try JSON user_store first, then fall back to user_system SQLite
        user_info = get_user(username)
        if user_info is None:
            # Fallback: try user_system SQLite
            try:
                from ..user_system.service import get_user as us_get_user
                us_user = us_get_user(username)
                if us_user:
                    # Build user_info dict from user_system model
                    user_info = {
                        "username": us_user.username,
                        "role": us_user.role,
                        "email": getattr(us_user, "email", ""),
                        "display_name": getattr(us_user, "display_name", us_user.username),
                    }
                    logger.info(f"Resolved user {username} from user_system SQLite")
            except (ImportError, Exception) as e:
                logger.warning(f"user_system lookup fallback failed: {e}")

        if user_info is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "User not found"},
            )

        request.state.user_info = user_info
        request.state.token = token
        # Also set username and role for compatibility with other middleware
        request.state.username = user_info.get("username", username)
        request.state.role = user_info.get("role", "user")

        response = await call_next(request)
        return response


# ---------------------------------------------------------------------------
# Helper: get current user from request
# ---------------------------------------------------------------------------

def get_current_user(request: Request) -> dict:
    """Get current user from request state. Raises 401 if not authenticated."""
    user_info = getattr(request.state, "user_info", None)
    if user_info is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_info


def require_admin(request: Request) -> dict:
    """Require admin role. Raises 403 if not admin."""
    user_info = get_current_user(request)
    if user_info.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_info


def require_role(request: Request, role: str) -> dict:
    """Require specific role. Raises 403 if not authorized.
    
    Args:
        request: The request object.
        role: Required role (e.g., "user", "admin").
    
    Returns:
        User info dict.
    
    Raises:
        HTTPException: 401 if not authenticated, 403 if not authorized.
    """
    user_info = get_current_user(request)
    user_role = user_info.get("role", "user")
    
    # Role hierarchy: admin > advanced > user
    role_hierarchy = {"admin": 4, "advanced": 3, "user": 2}
    required_level = role_hierarchy.get(role, 0)
    user_level = role_hierarchy.get(user_role, 0)
    
    if user_level < required_level:
        raise HTTPException(status_code=403, detail=f"Role '{role}' required")
    return user_info


# ---------------------------------------------------------------------------
# Auto-register from environment variables
# ---------------------------------------------------------------------------

def auto_register_from_env() -> None:
    """Auto-register admin user from environment variables.

    Called once during application startup.  If both ``COAPIS_AUTH_USERNAME``
    and ``COAPIS_AUTH_PASSWORD`` are set, the admin account is created
    automatically — useful for Docker, Kubernetes, server-panel, and other
    automated deployments where interactive web registration is not practical.

    Skips silently when:
    - a user has already been registered
    - either env var is missing or empty
    """
    if has_registered_users():
        return

    username = os.environ.get("COAPIS_AUTH_USERNAME", "").strip()
    password = os.environ.get("COAPIS_AUTH_PASSWORD", "").strip()
    if not username or not password:
        return

    token = register_user(username, password)
    if token:
        logger.info(
            "Auto-registered user '%s' from environment variables",
            username,
        )
