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

"""Users router - CRUD endpoints for user management."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import (
    UserCreate, UserUpdate, UserResponse, UserListResponse,
    PointsConfigResponse,
)
from ..service import (
    create_user, get_user_by_username, update_user, delete_user,
    list_users, authenticate, recalculate_level,
)
from ..config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["user-system/users"])


@router.get("/users/config")
async def get_users_config():
    """Get current user system configuration."""
    cfg = get_config()
    return cfg.to_dict()


@router.post("/users/register", response_model=UserResponse)
async def register_user(req: UserCreate):
    """Register a new user with complete workspace initialization.

    Creates:
    1. User database record (SQLite)
    2. Auth user_store entry (JSON)
    3. User workspace directory (workspaces/{username}/)
    4. Default agent with agent.json
    5. Essential JSON files (chats.json, jobs.json, skill.json)
    6. Agent registration in config.json agents.profiles
    7. User data directories (data/{username}/agents, skills, workflows, chats)
    """
    cfg = get_config()
    if not cfg.enabled:
        raise HTTPException(status_code=403, detail="User system is disabled")

    # Step 1: Create user in database
    try:
        user = create_user(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Step 2: Sync to auth user_store (JSON) so /api/auth/login works
    try:
        from ...app.user_store import create_user as auth_create_user
        auth_create_user(
            username=user.username,
            password=req.password,
            display_name=req.display_name or user.username,
            role=user.role,
        )
        logger.info(f"User {user.username} synced to auth user_store")
    except Exception as e:
        logger.warning(f"Failed to sync user {user.username} to auth store: {e}")

    # Step 3: Initialize user workspace (agent, skills, workflows, etc.) — pass request for runtime registration
    try:
        from ...app.user_provisioning import init_user_workspace
        agent_id = init_user_workspace(
            username=user.username,
            display_name=req.display_name or user.username,
            request=request,
        )
        logger.info(f"User {user.username} workspace initialized (agent: {agent_id})")
    except Exception as e:
        logger.error(
            f"Failed to initialize workspace for {user.username}: {e}. "
            "User created but workspace may be incomplete.",
            exc_info=True,
        )
        # Don't fail registration - workspace can be initialized later

    # Step 4: Award first login bonus
    from ..points import add_points
    add_points(user.username, cfg.points_first_login, "first_login")

    return user


@router.post("/users/login", response_model=UserResponse)
async def login_user(req: UserCreate):
    """Login and get user info."""
    cfg = get_config()
    if not cfg.enabled:
        raise HTTPException(status_code=403, detail="User system is disabled")

    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Award daily login bonus
    from ..points import add_points
    add_points(user.username, cfg.points_login_daily, "daily_login")

    return user


@router.get("/users/me", response_model=Optional[UserResponse])
async def get_current_user(request: Request):
    """Get current user info from request context."""
    user_info = getattr(request.state, "user_info", None)
    if user_info is None:
        return None
    # Return user info from request state (set by auth middleware)
    return {
        "id": user_info.get("id", 0),
        "username": user_info.get("username", ""),
        "display_name": user_info.get("display_name", user_info.get("username", "")),
        "role": user_info.get("role", "user"),
        "email": user_info.get("email", ""),
    }


@router.get("/users/{username}", response_model=UserResponse)
async def get_user(username: str):
    """Get user by username."""
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/users/{username}", response_model=UserResponse)
async def update_user_profile(username: str, req: UserUpdate):
    """Update user profile."""
    try:
        user = update_user(username, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return user


@router.delete("/users/{username}")
async def delete_user_endpoint(username: str):
    """Delete user."""
    if not delete_user(username):
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True}


@router.get("/users", response_model=UserListResponse)
async def list_users_endpoint(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List users with pagination. Requires admin role."""
    # Require admin role for listing all users
    from ...app.auth import require_admin
    require_admin(request)
    return list_users(page, page_size)


@router.post("/users/{username}/recalculate-level")
async def recalculate_user_level(username: str):
    """Recalculate user level based on total points."""
    level = recalculate_level(username)
    return {"username": username, "level": level}
