# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

"""Auth router - Authentication API endpoints.

Endpoints:
- POST /auth/login       - 用户名密码登录
- POST /auth/register    - 注册新用户
- GET  /auth/status      - 查询认证状态
- GET  /auth/verify      - 验证 token 有效性
- POST /auth/logout      - 注销（撤销 token）
- GET  /auth/users       - 列出所有用户（admin only）
- POST /auth/update-profile - 更新个人资料
- DELETE /auth/users/{username} - 删除用户（admin only）
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import (
    authenticate,
    has_registered_users,
    is_auth_enabled,
    register_user,
    revoke_token,
    verify_token,
    get_current_user,
    require_admin,
)
from ..user_store import list_users, get_user, update_user, delete_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str
    expires_in: Optional[int] = None


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    expires_in: Optional[int] = None


class LoginResponse(BaseModel):
    token: str
    username: str


class AuthStatusResponse(BaseModel):
    enabled: bool
    has_users: bool


class UpdateProfileRequest(BaseModel):
    current_password: str
    new_username: Optional[str] = None
    new_password: Optional[str] = None


class UserInfoResponse(BaseModel):
    username: str
    display_name: str
    role: str
    created_at: Optional[float] = None
    last_login: Optional[float] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/login")
async def login(req: LoginRequest):
    """用户名密码登录。

    expires_in:
    - 正整数: token 在 N 秒后过期
    - 0 或 -1: 永久 token（100 年）
    - None/省略: 默认 7 天
    """
    if not is_auth_enabled():
        return LoginResponse(token="", username="")

    token = authenticate(req.username, req.password, req.expires_in)
    if token is None:
        # Log failed login attempt
        try:
            from .audit import _append_audit_entry
            _append_audit_entry({
                "timestamp": time.time(),
                "event_type": "auth",
                "action": "login_failed",
                "user_id": req.username,
                "source": "auth",
                "detail": "用户名或密码错误",
            })
        except Exception:
            pass
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # Log successful login
    try:
        from .audit import _append_audit_entry
        _append_audit_entry({
            "timestamp": time.time(),
            "event_type": "auth",
            "action": "login_success",
            "user_id": req.username,
            "source": "auth",
            "detail": "登录成功",
        })
    except Exception:
        pass

    return LoginResponse(token=token, username=req.username)


@router.post("/register")
async def register(req: RegisterRequest):
    """注册新用户。

    注意：需要 COAPIS_AUTH_ENABLED=true 才能注册。
    首次注册的用户自动成为 admin。
    """
    if not is_auth_enabled():
        raise HTTPException(status_code=403, detail="认证未启用")

    if not req.username.strip() or not req.password.strip():
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    username = req.username.strip()
    # Check if user already exists (JSON store)
    if get_user(username):
        raise HTTPException(status_code=409, detail="用户已存在")

    # First user gets admin role
    role = "admin" if not has_registered_users() else "user"

    from ..user_store import create_user
    if not create_user(username, req.password, role=role):
        raise HTTPException(status_code=409, detail="注册失败")

    # Also create in SQLite user_system for /user/me endpoint
    try:
        from ...user_system.database import get_db
        get_db()  # Initialize DB (creates tables lazily)
        from ...user_system.service import create_user as create_user_sql
        from ...user_system.models import UserCreate
        user_create = UserCreate(
            username=username,
            password=req.password,
            email=getattr(req, 'email', None),
            display_name=username,
            role=role
        )
        create_user_sql(user_create)
        logger.info(f"User {username} created in both JSON store and SQLite (role={role})")
    except Exception as e:
        logger.error(f"Failed to create user {username} in SQLite: {e}")
        # Don't fail registration if SQLite creation fails
        # But log the error for debugging

    # Initialize user workspace (agent, skills, workflows, etc.) — pass request for runtime registration
    try:
        from ..user_provisioning import init_user_workspace
        agent_id = init_user_workspace(username, display_name=username, request=request)
        logger.info(f"User {username} workspace initialized (agent: {agent_id})")
    except Exception as e:
        logger.error(
            f"Failed to initialize workspace for {username}: {e}. "
            "User created but workspace may be incomplete.",
            exc_info=True,
        )
        # Don't fail registration - workspace can be initialized later

    token = create_token_with_expiry(username, req.expires_in)
    return LoginResponse(token=token, username=username)


def create_token_with_expiry(username: str, expires_in: Optional[int] = None) -> str:
    from ..auth import create_token
    return create_token(username, expires_in)


@router.get("/status")
async def auth_status():
    """查询认证状态。"""
    return AuthStatusResponse(
        enabled=is_auth_enabled(),
        has_users=has_registered_users(),
    )


@router.get("/verify")
async def verify(request: Request):
    """验证 token 有效性。"""
    user_info = get_current_user(request)
    return {
        "valid": True,
        "username": user_info.get("username"),
        "role": user_info.get("role"),
    }


@router.post("/logout")
async def logout(request: Request):
    """注销当前用户（撤销 token）。"""
    token = getattr(request.state, "token", None)
    if token:
        revoke_token(token)
    return {"message": "已注销"}


@router.get("/users")
async def list_all_users(request: Request):
    """列出所有用户（需要 admin 权限）。"""
    require_admin(request)
    return list_users()


@router.get("/users/me")
async def get_my_profile(request: Request):
    """获取当前用户资料。"""
    user_info = get_current_user(request)
    logger.info(f"get_my_profile: user_info={user_info}")
    # Return the user info already resolved by middleware (SQLite-first)
    # instead of re-reading from JSON which may be out of sync
    return {
        "username": user_info.get("username", ""),
        "display_name": user_info.get("display_name", user_info.get("username", "")),
        "role": user_info.get("role", "user"),
        "email": user_info.get("email", ""),
    }


@router.post("/update-profile")
async def update_profile(request: Request, payload: UpdateProfileRequest):
    """更新个人资料。"""
    user_info = get_current_user(request)
    username = user_info["username"]

    if not update_user(
        username,
        display_name=payload.new_username,
        new_password=payload.new_password,
        current_password=payload.current_password,
    ):
        raise HTTPException(status_code=400, detail="更新失败，请检查当前密码")

    return {"message": "资料已更新"}


@router.delete("/users/{username}")
async def delete_a_user(request: Request, username: str):
    """删除用户（需要 admin 权限）。"""
    require_admin(request)

    if not delete_user(username):
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"message": f"用户 {username} 已删除"}


@router.post("/seafile-token")
async def get_seafile_token(request: Request):
    """获取 Seafile SSO Token。
    
    用于前端 iframe 集成，将 CoApis 用户认证映射到 Seafile。
    
    Request Body:
        username: CoApis 用户名
    
    Response:
        token: Seafile auth token
        service_url: Seafile 服务地址
    """
    user_info = get_current_user(request)
    username = user_info["username"]
    
    # 获取用户密码（用于 Seafile 认证）
    user_data = get_user_with_creds(username)
    if not user_data:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 使用 SeafileClient 获取 Token
    try:
        from ..services import SeafileClient, SeafileConfig
        
        # 从环境变量或配置加载 Seafile 配置
        import os
        seafile_config = SeafileConfig(
            service_url=os.getenv("SEAFILE_SERVICE_URL", "http://localhost:9000"),
            admin_username=os.getenv("SEAFILE_ADMIN_USER", "admin"),
            admin_password=os.getenv("SEAFILE_ADMIN_PASSWORD", "CoApis2026!"),
        )
        
        client = SeafileClient(seafile_config)
        
        # 使用用户凭据登录 Seafile
        # Seafile 使用 email 作为用户名
        email = f"{username}@coapis.local"
        password = user_data.get("password_hash", "")
        
        # 注意：这里需要原始密码，但 user_store 只存储 hash
        # 实际实现时需要同步原始密码或使用其他方式
        # 暂时使用 admin token 为用户生成 token
        admin_token = await client.login(seafile_config.admin_username, seafile_config.admin_password)
        
        # 为用户创建临时 token（简化实现）
        # 生产环境应使用 Seafile 的 SSO 功能
        return {
            "token": admin_token,
            "service_url": seafile_config.service_url,
            "username": username,
        }
    except ImportError:
        raise HTTPException(status_code=503, detail="Seafile 服务未配置")
    except Exception as e:
        logger.error(f"Failed to get Seafile token for {username}: {e}")
        raise HTTPException(status_code=500, detail=f"获取 Seafile Token 失败: {str(e)}")


# Import get_user_with_creds for the seafile-token endpoint
from ..user_store import get_user_with_creds
