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

"""Admin users router - global user management.

管理员可查看所有用户、修改角色、重置积分等。
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Body
from pydantic import BaseModel

from ....user_system.database import UserSystemDB
from ....user_system.models import UserResponse
from ...permissions import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin/users"])


# ── Pydantic models ─────────────────────────────────────────────────────

class AdminUserCreate(BaseModel):
    """管理员创建用户请求体."""
    username: str
    password: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: str = "user"  # admin, user
    permission_overrides: Optional[Dict[str, Dict[str, bool]]] = None


class AdminUserUpdate(BaseModel):
    role: Optional[str] = None
    token_quota_monthly: Optional[int] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    permission_overrides: Optional[Dict[str, Dict[str, bool]]] = None


class AdminUserListResponse(BaseModel):
    users: List[Dict[str, Any]]
    total: int
    page: int
    page_size: int


# ── Helper functions ─────────────────────────────────────────────────────


def _ensure_admin_in_db(db: UserSystemDB, admin_username: str) -> int:
    """确保 admin 用户在数据库中存在，返回 user_id.
    
    Admin 用户可能只在 JSON user_store 中，需要同步到数据库
    以避免 audit_log 外键约束失败。
    """
    admin_user = db.get_user_by_username(admin_username)
    if admin_user:
        return admin_user["id"]
    
    # 尝试从 JSON user_store 同步到数据库
    try:
        from ...user_store import get_user
        store_user = get_user(admin_username)
        if store_user:
            db.execute(
                "INSERT OR IGNORE INTO users (username, email, display_name, role, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (admin_username, store_user.get("email"), store_user.get("display_name", admin_username),
                 store_user.get("role", "admin"), 1, time.time(), time.time())
            )
            db.commit()
            admin_user = db.get_user_by_username(admin_username)
            if admin_user:
                logger.info(f"Synced admin user {admin_username} to DB (id={admin_user['id']})")
                return admin_user["id"]
    except Exception as e:
        logger.warning(f"Failed to sync admin user {admin_username} to DB: {e}")
    
    # 如果同步失败，返回 -1（系统用户）
    return -1


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/admin/users")
@require_permission("admin:admin")
async def list_all_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None, description="搜索用户名"),
) -> AdminUserListResponse:
    """列出所有用户."""
    db = UserSystemDB()
    
    conditions = []
    params: List[Any] = []
    
    if search:
        conditions.append("(username LIKE ? OR display_name LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    
    # 总数
    total_row = db.execute(f"SELECT COUNT(*) as total FROM users {where}", params).fetchone()
    total = total_row["total"] if total_row else 0
    
    # 分页
    offset = (page - 1) * page_size
    rows = db.execute(
        f"SELECT * FROM users {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()
    
    # 移除敏感字段
    safe_users = []
    for r in rows:
        safe_user = dict(r)
        safe_user.pop("password_hash", None)
        safe_user.pop("salt", None)
        safe_users.append(safe_user)
    
    return AdminUserListResponse(
        users=safe_users,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/admin/users")
@require_permission("admin:admin")
async def create_user_admin(
    request: Request,
    payload: AdminUserCreate = Body(...),
) -> Dict[str, Any]:
    """管理员创建用户（含角色分配）。
    
    同时创建：
    1. SQLite user_system 记录
    2. JSON user_store 认证记录
    3. 用户工作区目录
    """

    # 1. 创建到 SQLite user_system
    try:
        from ....user_system.service import create_user as create_user_sql
        from ....user_system.models import UserCreate
        user_create = UserCreate(
            username=payload.username,
            password=payload.password,
            email=payload.email,
            display_name=payload.display_name,
            role=payload.role,
        )
        user = create_user_sql(user_create)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create user in SQLite: {e}")
        raise HTTPException(status_code=500, detail=f"创建用户失败: {e}")
    
    # 2. 同步到 JSON user_store（认证用）
    try:
        from ...user_store import create_user as auth_create_user
        auth_create_user(
            username=user.username,
            password=payload.password,
            display_name=payload.display_name or user.username,
            role=user.role,
        )
        logger.info(f"Admin created user {user.username} synced to auth user_store")
    except Exception as e:
        logger.warning(f"Failed to sync user {user.username} to auth store: {e}")
        # 不阻断主流程，仅记录警告
    
    # 3. 初始化用户工作区 (pass request for runtime MultiAgentManager registration)
    try:
        from ...user_provisioning import init_user_workspace
        init_user_workspace(
            username=user.username,
            display_name=payload.display_name or user.username,
            request=request,
        )
        logger.info(f"Admin created user {user.username} workspace initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize workspace for {user.username}: {e}")
        # 不阻断主流程，仅记录警告
    
    # 返回用户信息（不含密码）
    safe_user = user.model_dump()
    safe_user.pop("password_hash", None)
    safe_user.pop("salt", None)

    # 4. Save permission_overrides if provided
    if payload.permission_overrides:
        try:
            from ...permissions.manager import PermissionManager
            pm = PermissionManager.get_instance()
            pm.update_user_overrides(user.username, payload.permission_overrides)
        except Exception as e:
            logger.warning(f"Failed to save permission_overrides for {user.username}: {e}")

    return {
        "id": safe_user.get("id"),
        "username": safe_user.get("username"),
        "display_name": safe_user.get("display_name"),
        "email": safe_user.get("email"),
        "role": safe_user.get("role"),
        "is_active": safe_user.get("is_active", True),
    }


@router.get("/admin/users/{user_id}")
@require_permission("admin:admin")
async def get_user_by_id(
    request: Request,
    user_id: int,
) -> Dict[str, Any]:
    """获取用户详情."""
    db = UserSystemDB()
    
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 软删除（排除 password_hash 和 salt）
    safe_user = dict(user)
    safe_user.pop("password_hash", None)
    safe_user.pop("salt", None)
    return safe_user


@router.put("/admin/users/{user_id}")
@require_permission("admin:admin")
async def update_user(
    request: Request,
    user_id: int,
    payload: AdminUserUpdate = Body(...),
) -> Dict[str, Any]:
    """更新用户信息（管理员操作）.
    
    同时更新 SQLite user_system 和 JSON user_store，
    确保角色变更对认证系统生效。
    """
    admin_username = getattr(request.state, "username", "anonymous")
    db = UserSystemDB()
    
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    username = user["username"]
    updates = []
    params = []
    
    if payload.role is not None:
        updates.append("role = ?")
        params.append(payload.role)
    
    if payload.token_quota_monthly is not None:
        updates.append("token_quota_monthly = ?")
        params.append(payload.token_quota_monthly)
    
    if payload.is_active is not None:
        updates.append("is_active = ?")
        params.append(int(payload.is_active))
    
    if updates:
        updates.append("updated_at = ?")
        params.append(time.time())
        params.append(user_id)
        
        sql = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
        db.execute(sql, params)
        db.commit()
        
        # ── 同步到 JSON user_store（认证系统依赖） ──
        if payload.role is not None:
            try:
                from ...user_store import _load_users, _save_users
                data = _load_users()
                if username in data.get("users", {}):
                    data["users"][username]["role"] = payload.role
                    _save_users(data)
                    logger.info(f"Synced role change for {username} to JSON user_store: {payload.role}")
            except Exception as e:
                logger.error(f"Failed to sync role change to JSON user_store for {username}: {e}")
        
        # ── 如果修改了密码，同步到 JSON user_store ──
        if hasattr(payload, 'password') and payload.password is not None:
            try:
                from ...user_store import _load_users, _save_users, _hash_password
                data = _load_users()
                if username in data.get("users", {}):
                    pw_hash, salt = _hash_password(payload.password)
                    data["users"][username]["password_hash"] = pw_hash
                    data["users"][username]["salt"] = salt
                    _save_users(data)
                    logger.info(f"Synced password change for {username} to JSON user_store")
            except Exception as e:
                logger.error(f"Failed to sync password change to JSON user_store for {username}: {e}")
        
        # Audit log
        admin_user_id = _ensure_admin_in_db(db, admin_username)
        db.insert_audit_log(
            user_id=admin_user_id,
            username=admin_username,
            action="admin_update_user",
            resource_type="user",
            resource_id=str(user_id),
            details={"updates": {k: v for k, v in payload.model_dump().items() if v is not None}},
        )

    # Save permission_overrides if provided
    if payload.permission_overrides is not None:
        try:
            from ...permissions.manager import PermissionManager
            pm = PermissionManager.get_instance()
            if payload.permission_overrides:
                pm.update_user_overrides(username, payload.permission_overrides)
            else:
                pm.delete_user_overrides(username)
        except Exception as e:
            logger.warning(f"Failed to save permission_overrides for {username}: {e}")

    return {"success": True, "user_id": user_id, "username": username}


class UserDeleteRequest(BaseModel):
    """用户删除请求体."""
    backup: bool = False  # 是否备份用户数据


@router.delete("/admin/users/{user_id}")
@require_permission("admin:admin")
async def delete_user(
    request: Request,
    user_id: int,
    body: UserDeleteRequest = Body(default=UserDeleteRequest()),
) -> Dict[str, Any]:
    """删除用户（支持软删除和硬删除）.
    
    - 默认软删除：标记为非活跃
    - backup=True 时硬删除：先备份用户数据，然后从数据库和文件系统中删除
    """
    admin_username = getattr(request.state, "username", "anonymous")
    db = UserSystemDB()
    
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    username = user["username"]
    
    if body.backup:
        # 硬删除 - 先备份
        from ....constant import WORKING_DIR
        backup_dir = WORKING_DIR / "backups" / "users"
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = int(time.time())
        backup_path = backup_dir / f"{username}_{timestamp}"
        
        # 备份用户工作区
        workspace_dir = WORKING_DIR / "workspaces" / username
        if workspace_dir.exists():
            shutil.copytree(workspace_dir, backup_path / "workspace")
            logger.info(f"Backed up workspace for {username} to {backup_path}")
        
        # 备份用户聊天记录
        chats_dir = WORKING_DIR / "workspaces" / username / "chat"
        if chats_dir.exists():
            shutil.copytree(chats_dir, backup_path / "chat", dirs_exist_ok=True)
        
        # 从数据库删除
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
        
        # 从 JSON user_store 删除
        try:
            from ...user_store import _load_users, _save_users
            data = _load_users()
            if username in data.get("users", {}):
                del data["users"][username]
                _save_users(data)
                logger.info(f"Removed {username} from JSON user_store")
        except Exception as e:
            logger.error(f"Failed to remove {username} from JSON user_store: {e}")
        
        # 删除用户工作区
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
            logger.info(f"Deleted workspace for {username}")
        
        # Audit log
        admin_user_id = _ensure_admin_in_db(db, admin_username)
        db.insert_audit_log(
            user_id=admin_user_id,
            username=admin_username,
            action="admin_hard_delete_user",
            resource_type="user",
            resource_id=str(user_id),
            details={"username": username, "backup_path": str(backup_path)},
        )
        
        return {"success": True, "user_id": user_id, "username": username, "backup_path": str(backup_path)}
    else:
        # 软删除 - 标记为非活跃
        db.execute("UPDATE users SET is_active = 0, updated_at = ? WHERE id = ?", (time.time(), user_id))
        db.commit()
        
        # Audit log
        admin_user_id = _ensure_admin_in_db(db, admin_username)
        db.insert_audit_log(
            user_id=admin_user_id,
            username=admin_username,
            action="admin_soft_delete_user",
            resource_type="user",
            resource_id=str(user_id),
        )
        
        return {"success": True, "user_id": user_id}


@router.post("/admin/users/{user_id}/reset-tokens")
@require_permission("admin:admin")
async def reset_user_tokens(
    request: Request,
    user_id: int,
) -> Dict[str, Any]:
    """重置用户 Token 用量."""
    admin_username = getattr(request.state, "username", "anonymous")
    db = UserSystemDB()
    
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    db.execute("UPDATE users SET token_used_monthly = 0, updated_at = ? WHERE id = ?", (time.time(), user_id))
    db.commit()
    
    db.insert_audit_log(
        user_id=db.get_user_by_username(admin_username)["id"],
        username=admin_username,
        action="admin_reset_tokens",
        resource_type="user",
        resource_id=str(user_id),
    )
    
    return {"success": True, "user_id": user_id}
