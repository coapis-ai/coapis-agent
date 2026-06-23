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

"""Users router - CRUD endpoints for user management.

Simplified: no level recalculation, no points auto-earning.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import (
    UserCreate, UserUpdate, UserResponse, UserListResponse,
)
from ..service import (
    create_user, get_user_by_username, update_user, delete_user,
    list_users, authenticate,
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
    """Register a new user with complete workspace initialization."""

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

    # Step 3: Initialize user workspace
    try:
        from ...app.user_provisioning import init_user_workspace
        agent_id = init_user_workspace(
            username=user.username,
            display_name=req.display_name or user.username,
        )
        logger.info(f"User {user.username} workspace initialized, agent={agent_id}")
    except Exception as e:
        logger.warning(f"Failed to initialize workspace for {user.username}: {e}")

    return user


@router.get("/users/me", response_model=UserResponse)
async def get_current_user(request: Request):
    """Get current authenticated user info."""
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/users/list", response_model=UserListResponse)
async def list_users_endpoint(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List all users with pagination."""
    return list_users(page, page_size)


@router.get("/users/{username}", response_model=UserResponse)
async def get_user(username: str):
    """Get user by username."""
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/users/{username}", response_model=UserResponse)
async def update_user_endpoint(username: str, req: UserUpdate):
    """Update user profile."""
    try:
        return update_user(username, req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/users/{username}")
async def delete_user_endpoint(username: str):
    """Delete a user."""
    success = delete_user(username)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True, "username": username}
