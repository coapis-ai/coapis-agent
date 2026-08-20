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

"""Admin users router - global user management.

管理员可查看所有用户、修改角色、重置积分等。

数据源策略（企业版优先）：
- 企业版：RepositoryFactory → PostgreSQL（UUID 主键）
- 社区版 fallback：UserSystemDB → SQLite/JSON（int 主键）
"""
from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request, Body
from pydantic import BaseModel, ConfigDict
from uuid import UUID

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
    model_config = ConfigDict(extra='allow')
    
    role: Optional[str] = None
    display_name: Optional[str] = None
    token_quota_monthly: Optional[int] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    permission_overrides: Optional[Dict[str, Dict[str, bool]]] = None


class AdminUserListResponse(BaseModel):
    users: List[Dict[str, Any]]
    total: int
    page: int
    page_size: int


class UserDeleteRequest(BaseModel):
    """用户删除请求体."""
    backup: bool = False  # 是否备份用户数据


# ── Helper functions ─────────────────────────────────────────────────────


def _get_user_repo():
    """尝试获取 RepositoryFactory 的 UserRepository（企业版 PostgreSQL）。
    
    Returns:
        UserRepository 实例，或 None（社区版 fallback）
    """
    try:
        from ....foundation.repository_factory import RepositoryFactory
        return RepositoryFactory.get_user_repository()
    except RuntimeError:
        return None
    except Exception as e:
        logger.debug(f"RepositoryFactory not available: {e}")
        return None


def _adapt_pg_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """将 PostgreSQL 返回的用户字典适配为前端期望的格式。
    
    PG 字段 → 前端字段映射：
    - status("active"/"inactive") → is_active(bool)
    - id(UUID string) → id(string)
    - 其余字段保持不变
    """
    adapted = dict(user)
    # status → is_active
    if "status" in adapted:
        adapted["is_active"] = adapted.get("status") == "active"
    # 确保关键字段存在
    adapted.setdefault("is_active", True)
    adapted.setdefault("role", "user")
    return adapted


async def _resolve_pg_user(user_repo, user_id: str) -> Tuple[Optional[uuid.UUID], Optional[Dict[str, Any]]]:
    """按 UUID 字符串或 username 解析企业版（PostgreSQL）用户.

    前端用户管理页传的是 username（updateUser(username, ...)），
    禁用/删除接口传的是 int id，兼容三种形态。

    Returns:
        (uuid, user_dict)；未找到时返回 (None, None)
    """
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, AttributeError, TypeError):
        uid = None

    if uid is not None:
        user = await user_repo.get_user_by_id(uid)
        if user:
            return uid, user

    user = await user_repo.get_user_by_username(user_id)
    if user:
        raw_id = user.get("id")
        if isinstance(raw_id, str):
            try:
                uid = uuid.UUID(raw_id)
            except ValueError:
                uid = None
        return uid, user
    return None, None


def _resolve_community_user(db: UserSystemDB, user_id: str) -> Optional[Dict[str, Any]]:
    """按 int id 或 username 解析社区版（UserSystemDB）用户."""
    try:
        int_id = int(user_id)
    except (ValueError, TypeError):
        int_id = None

    if int_id is not None:
        user = db.get_user_by_id(int_id)
        if user:
            return user

    return db.get_user_by_username(user_id)


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
            db.insert_user({
                "username": admin_username,
                "email": store_user.get("email"),
                "display_name": store_user.get("display_name", admin_username),
                "role": store_user.get("role", "admin"),
                "is_active": 1,
            })
            admin_user = db.get_user_by_username(admin_username)
            if admin_user:
                logger.info(f"Synced admin user {admin_username} to DB (id={admin_user['id']})")
                return admin_user["id"]
    except Exception as e:
        logger.warning(f"Failed to sync admin user {admin_username} to DB: {e}")
    
    # 如果同步失败，返回 -1（系统用户）
    return -1


def _sync_user_store_role(username: str, role: str):
    """同步角色变更到 JSON user_store（认证系统依赖）。"""
    try:
        from ...user_store import _load_users, _save_users
        data = _load_users()
        if username in data.get("users", {}):
            data["users"][username]["role"] = role
            _save_users(data)
            logger.info(f"Synced role change for {username} to JSON user_store: {role}")
    except Exception as e:
        logger.error(f"Failed to sync role change to JSON user_store for {username}: {e}")


def _sync_user_store_password(username: str, password: str):
    """同步密码变更到 JSON user_store。"""
    try:
        from ...user_store import _load_users, _save_users, _hash_password
        data = _load_users()
        if username in data.get("users", {}):
            pw_hash, salt = _hash_password(password)
            data["users"][username]["password_hash"] = pw_hash
            data["users"][username]["salt"] = salt
            _save_users(data)
            logger.info(f"Synced password change for {username} to JSON user_store")
    except Exception as e:
        logger.error(f"Failed to sync password change to JSON user_store for {username}: {e}")


def _remove_user_store_user(username: str):
    """从 JSON user_store 删除用户。"""
    try:
        from ...user_store import _load_users, _save_users
        data = _load_users()
        if username in data.get("users", {}):
            del data["users"][username]
            _save_users(data)
            logger.info(f"Removed {username} from JSON user_store")
    except Exception as e:
        logger.error(f"Failed to remove {username} from JSON user_store: {e}")


async def _create_user_fallback(payload: "AdminUserCreate") -> Dict[str, Any]:
    """社区版 fallback：当 RepositoryFactory 不可用时，用 UserSystemDB + user_store 创建用户。
    
    注意：此函数是原代码中引用但未定义的 _create_user_fallback 的补全实现。
    """
    db = UserSystemDB()
    
    # 检查用户名是否已存在
    if db.get_user_by_username(payload.username):
        raise ValueError(f"Username '{payload.username}' already exists")
    
    # 哈希密码
    from ...user_store import _hash_password
    pw_hash, salt = _hash_password(payload.password)
    
    # 插入 UserSystemDB
    new_id = db.insert_user({
        "username": payload.username,
        "email": payload.email,
        "display_name": payload.display_name or payload.username,
        "password_hash": pw_hash,
        "salt": salt,
        "role": payload.role,
        "is_active": 1,
    })
    
    logger.info(f"Admin created user {payload.username} via UserSystemDB fallback (id={new_id})")
    
    return {
        "id": new_id,
        "username": payload.username,
        "email": payload.email,
        "display_name": payload.display_name or payload.username,
        "role": payload.role,
        "is_active": True,
    }


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
    # ⭐ 企业版：优先走 PostgreSQL
    user_repo = _get_user_repo()
    if user_repo:
        try:
            users, total = await user_repo.list_users_page(page=page, page_size=page_size, search=search)
            safe_users = []
            for u in users:
                safe_user = _adapt_pg_user(u)
                safe_user.pop("password_hash", None)
                safe_user.pop("salt", None)
                safe_users.append(safe_user)
            return AdminUserListResponse(
                users=safe_users,
                total=total,
                page=page,
                page_size=page_size,
            )
        except Exception as e:
            logger.warning(f"PG list_users failed, falling back to UserSystemDB: {e}")

    # 社区版 fallback：UserSystemDB
    db = UserSystemDB()
    users, total = db.list_users_page(page=page, page_size=page_size, search=search)

    safe_users = []
    for u in users:
        safe_user = dict(u)
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
    
    使用Repository模式：
    - 社区版：JSON存储
    - 企业版：PostgreSQL存储
    """

    # ⭐ 使用RepositoryFactory获取UserRepository
    try:
        from ....foundation.repository_factory import RepositoryFactory
        user_repo = RepositoryFactory.get_user_repository()
        
        # 准备用户数据（注意：企业版 PostgreSQL repository 需要 password_hash）
        from ...user_store import _hash_password
        pw_hash, salt = _hash_password(payload.password)
        
        user_data = {
            "username": payload.username,
            "password_hash": pw_hash,
            "salt": salt,
            "email": payload.email,
            "display_name": payload.display_name,
            "role": payload.role,
            "tenant_id": "default",  # PostgreSQL users 表要求 tenant_id 不为空（默认租户）
        }
        
        # 创建用户
        user = await user_repo.create_user(user_data)
        logger.info(f"Admin created user {user.get('username')} via Repository")
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        # RepositoryFactory未初始化，回退到旧方式
        logger.warning(f"RepositoryFactory not initialized, falling back to SQLite: {e}")
        user = await _create_user_fallback(payload)
    except Exception as e:
        # 捕获数据库约束错误或其他异常，回退到社区版 fallback
        logger.error(f"Failed to create user via Repository: {e}", exc_info=True)
        try:
            user = await _create_user_fallback(payload)
        except Exception as fb_e:
            raise HTTPException(status_code=500, detail=f"创建用户失败: {str(fb_e)}") from e
    
    # 2. 同步到 JSON user_store（认证用）
    try:
        from ...user_store import create_user as auth_create_user
        auth_create_user(
            username=user['username'],
            password=payload.password,
            display_name=payload.display_name or user.get('display_name') or user['username'],
            role=payload.role,
        )
        logger.info(f"Admin created user {user['username']} synced to auth user_store")
    except Exception as e:
        logger.warning(f"Failed to sync user {user['username']} to auth store: {e}")
    
    # 3. 初始化用户工作区
    try:
        from ...user_provisioning import init_user_workspace
        init_user_workspace(
            username=user['username'],
            display_name=payload.display_name or user.get('display_name') or user['username'],
            request=request,
        )
        logger.info(f"Admin created user {user['username']} workspace initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize workspace for {user['username']}: {e}")
    
    # 返回用户信息（不含密码）
    safe_user = user.copy() if isinstance(user, dict) else user.model_dump()
    safe_user.pop("password_hash", None)
    safe_user.pop("salt", None)

    # 4. Save permission_overrides if provided
    if payload.permission_overrides:
        try:
            from ...permissions.manager import PermissionManager
            pm = PermissionManager.get_instance()
            pm.update_user_overrides(user['username'], payload.permission_overrides)
        except Exception as e:
            logger.warning(f"Failed to save permission_overrides for {user['username']}: {e}")

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
    user_id: str,
) -> Dict[str, Any]:
    """获取用户详情（支持 UUID / username / int id）."""
    # ⭐ 企业版：优先走 PostgreSQL
    user_repo = _get_user_repo()
    if user_repo:
        try:
            uid, user = await _resolve_pg_user(user_repo, user_id)
            if user:
                safe_user = _adapt_pg_user(user)
                safe_user.pop("password_hash", None)
                safe_user.pop("salt", None)
                return safe_user
            raise HTTPException(status_code=404, detail="用户不存在")
        except ValueError:
            # user_id 不是有效 UUID，可能是社区版的 int ID
            logger.debug(f"user_id '{user_id}' is not a valid UUID, trying UserSystemDB")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"PG get_user failed, falling back to UserSystemDB: {e}")

    # 社区版 fallback：UserSystemDB
    db = UserSystemDB()
    user = _resolve_community_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    safe_user = dict(user)
    safe_user.pop("password_hash", None)
    safe_user.pop("salt", None)
    return safe_user


@router.put("/admin/users/{user_id}")
@require_permission("admin:admin")
async def update_user(
    request: Request,
    user_id: str,
    payload: AdminUserUpdate = Body(...),
) -> Dict[str, Any]:
    """更新用户信息（管理员操作，支持 UUID / username / int id）.
    
    企业版：更新 PostgreSQL users 表 + 同步 JSON user_store（认证系统依赖）
    社区版：更新 SQLite user_system + 同步 JSON user_store
    """
    admin_username = getattr(request.state, "username", "anonymous")

    # ⭐ 企业版：优先走 PostgreSQL
    user_repo = _get_user_repo()
    if user_repo:
        try:
            uid, user = await _resolve_pg_user(user_repo, user_id)
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

            username = user["username"]
            update_data: Dict[str, Any] = {}

            if payload.role is not None:
                update_data["role"] = payload.role
            if payload.display_name is not None:
                update_data["display_name"] = payload.display_name
            if payload.is_active is not None:
                update_data["status"] = "active" if payload.is_active else "inactive"
            
            # Handle password update for PostgreSQL
            if payload.password is not None:
                from ...user_store import _hash_password
                pw_hash, salt = _hash_password(payload.password)
                update_data["password_hash"] = pw_hash
                update_data["salt"] = salt

            if update_data:
                await user_repo.update_user(user_id, update_data)
                logger.info(f"Admin updated user {username} via PG Repository")

            # 同步到 JSON user_store（认证系统依赖）
            if payload.role is not None:
                _sync_user_store_role(username, payload.role)
            if payload.password is not None:
                _sync_user_store_password(username, payload.password)

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

        except ValueError:
            logger.debug(f"user_id '{user_id}' is not a valid UUID, trying UserSystemDB")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"PG update_user failed, falling back to UserSystemDB: {e}")

    # 社区版 fallback：UserSystemDB
    db = UserSystemDB()

    user = _resolve_community_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    int_id = user["id"]
    username = user["username"]
    update_data = {}

    if payload.role is not None:
        update_data["role"] = payload.role
    if payload.display_name is not None:
        update_data["display_name"] = payload.display_name
    if payload.token_quota_monthly is not None:
        update_data["token_quota_monthly"] = payload.token_quota_monthly
    if payload.is_active is not None:
        update_data["is_active"] = int(payload.is_active)

    if update_data:
        db.update_user_by_id(int_id, update_data)
        
        # 同步到 JSON user_store（认证系统依赖）
        if payload.role is not None:
            _sync_user_store_role(username, payload.role)
        if payload.password is not None:
            _sync_user_store_password(username, payload.password)
        
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


@router.delete("/admin/users/{user_id}")
@require_permission("admin:admin")
async def delete_user(
    request: Request,
    user_id: str,
    body: UserDeleteRequest = Body(default=UserDeleteRequest()),
) -> Dict[str, Any]:
    """删除用户（支持软删除和硬删除，支持 UUID / username / int id）.
    
    企业版：
    - 软删除（默认）：PG 软删除（deleted_at + status=inactive）+ 清理 JSON user_store
    - 硬删除（backup=True）：备份工作区 → PG 硬删除 → 清理 JSON user_store → 删除工作区
    社区版：同原逻辑
    """
    admin_username = getattr(request.state, "username", "anonymous")

    # ⭐ 企业版：优先走 PostgreSQL
    user_repo = _get_user_repo()
    if user_repo:
        try:
            uid, user = await _resolve_pg_user(user_repo, user_id)
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

                workspace_dir = WORKING_DIR / "workspaces" / username
                if workspace_dir.exists():
                    shutil.copytree(workspace_dir, backup_path / "workspace")
                    logger.info(f"Backed up workspace for {username} to {backup_path}")

                # PG 硬删除（设 deleted_at）
                await user_repo.delete_user(uid)

                # 从 JSON user_store 删除
                _remove_user_store_user(username)

                if workspace_dir.exists():
                    shutil.rmtree(workspace_dir)
                    logger.info(f"Deleted workspace for {username}")

                return {"success": True, "user_id": user_id, "username": username, "backup_path": str(backup_path)}
            else:
                # 软删除 - PG 软删除
                await user_repo.delete_user(uid)

                # 从 JSON user_store 删除（软删除也清理认证信息）
                _remove_user_store_user(username)

                logger.info(f"Admin soft-deleted user {username} (PG + user_store)")
                return {"success": True, "user_id": user_id, "username": username}

        except ValueError:
            logger.debug(f"user_id '{user_id}' is not a valid UUID, trying UserSystemDB")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"PG delete_user failed, falling back to UserSystemDB: {e}")

    # 社区版 fallback：UserSystemDB
    db = UserSystemDB()

    user = _resolve_community_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    int_id = user["id"]
    username = user["username"]

    if body.backup:
        # 硬删除 - 先备份
        from ....constant import WORKING_DIR
        backup_dir = WORKING_DIR / "backups" / "users"
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        backup_path = backup_dir / f"{username}_{timestamp}"

        workspace_dir = WORKING_DIR / "workspaces" / username
        if workspace_dir.exists():
            shutil.copytree(workspace_dir, backup_path / "workspace")
            logger.info(f"Backed up workspace for {username} to {backup_path}")

        chats_dir = WORKING_DIR / "workspaces" / username / "chat"
        if chats_dir.exists():
            shutil.copytree(chats_dir, backup_path / "chat", dirs_exist_ok=True)

        # 从数据库删除
        db.delete_user_by_id(int_id)

        # 从 JSON user_store 删除
        _remove_user_store_user(username)

        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
            logger.info(f"Deleted workspace for {username}")

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
        db.update_user_by_id(int_id, {"is_active": 0})

        # 从 JSON user_store 删除
        _remove_user_store_user(username)

        admin_user_id = _ensure_admin_in_db(db, admin_username)
        db.insert_audit_log(
            user_id=admin_user_id,
            username=admin_username,
            action="admin_soft_delete_user",
            resource_type="user",
            resource_id=str(user_id),
        )

        return {"success": True, "user_id": user_id, "username": username}


@router.post("/admin/users/{user_id}/reset-tokens")
@require_permission("admin:admin")
async def reset_user_tokens(
    request: Request,
    user_id: str,
) -> Dict[str, Any]:
    """重置用户 Token 用量（支持 UUID / username / int id）."""
    admin_username = getattr(request.state, "username", "anonymous")

    # ⭐ 企业版：优先走 PostgreSQL
    user_repo = _get_user_repo()
    if user_repo:
        try:
            uid, user = await _resolve_pg_user(user_repo, user_id)
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

            # 更新 quota（清零 token 使用量）
            quota = user.get("quota", {})
            quota["token_used_monthly"] = 0
            await user_repo.update_user(uid, {"quota": quota})

            logger.info(f"Admin reset tokens for {user['username']}")
            return {"success": True, "user_id": user_id, "username": user["username"]}

        except ValueError:
            logger.debug(f"user_id '{user_id}' is not a valid UUID, trying UserSystemDB")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"PG reset_tokens failed, falling back to UserSystemDB: {e}")

    # 社区版 fallback：UserSystemDB
    db = UserSystemDB()

    user = _resolve_community_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    int_id = user["id"]
    db.update_user_by_id(int_id, {"token_used_monthly": 0})

    admin_user = db.get_user_by_username(admin_username)
    if admin_user:
        db.insert_audit_log(
            user_id=admin_user["id"],
            username=admin_username,
            action="admin_reset_tokens",
            resource_type="user",
            resource_id=str(user_id),
        )

    return {"success": True, "user_id": user_id}
