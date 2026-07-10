# -*- coding: utf-8 -*-
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

"""Workspace Security router - user-level security settings.

每个用户管理自己的密码、API Key、登录设备。
"""
from __future__ import annotations

import logging
import hashlib
import secrets
import time
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel

from ....user_system.database import UserSystemDB
from ....user_system.service import update_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workspace/security"])


# ── Pydantic models ─────────────────────────────────────────────────────

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CreateAPIKeyRequest(BaseModel):
    name: str = ""
    rate_limit: int = 10
    quota_monthly: int = 1000


class APIKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    rate_limit: int
    quota_monthly: int
    quota_used: int
    is_active: bool
    created_at: Optional[float] = None
    last_used_at: Optional[float] = None


class DeviceInfo(BaseModel):
    id: str
    device_name: str = ""
    ip_address: str = ""
    last_active: Optional[float] = None
    is_current: bool = False


# ── Helper functions ─────────────────────────────────────────────────────

def _get_username(request: Request) -> str:
    """获取当前用户名."""
    username = getattr(request.state, "username", "anonymous")
    if username == "anonymous":
        raise HTTPException(status_code=401, detail="需要登录")
    return username


def _hash_api_key(key: str) -> str:
    """Hash API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()


def _generate_api_key() -> tuple:
    """Generate API key, return (full_key, prefix, hash)."""
    key = secrets.token_urlsafe(32)
    prefix = key[:8]
    key_hash = _hash_api_key(key)
    return key, prefix, key_hash


# ── Routes ───────────────────────────────────────────────────────────────

@router.put("/workspace/security/password")
async def change_password(
    request: Request,
    payload: ChangePasswordRequest = Body(...),
) -> Dict[str, Any]:
    """修改密码."""
    username = _get_username(request)
    db = UserSystemDB()
    
    user = db.get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # Verify current password
    from ....user_system.service import _verify_password
    if not _verify_password(payload.current_password, user["password_hash"], user["salt"]):
        raise HTTPException(status_code=400, detail="当前密码错误")
    
    # Update password
    try:
        from ....app.user_store import _hash_password
        pw_hash, salt = _hash_password(payload.new_password)
        from ....app.user_store import _load_users, _save_users
        data = _load_users()
        data["users"][username]["password_hash"] = pw_hash
        data["users"][username]["salt"] = salt
        _save_users(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Record audit log
    db.insert_audit_log(
        user_id=user["id"],
        username=username,
        action="change_password",
        resource_type="security",
        resource_id="password",
    )
    
    return {"success": True, "message": "密码修改成功"}


@router.get("/workspace/security/api-keys")
async def list_api_keys(request: Request) -> Dict[str, Any]:
    """列出 API Key."""
    username = _get_username(request)
    db = UserSystemDB()
    
    keys = db.execute(
        "SELECT id, name, key_prefix, rate_limit, quota_monthly, "
        "quota_used, is_active, created_at, last_used_at "
        "FROM api_keys WHERE username = ? ORDER BY created_at DESC",
        (username,),
    ).fetchall()
    
    api_keys = []
    for row in keys:
        api_keys.append(APIKeyResponse(
            id=row["id"],
            name=row["name"] or "",
            key_prefix=row["key_prefix"],
            rate_limit=row["rate_limit"],
            quota_monthly=row["quota_monthly"],
            quota_used=row["quota_used"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
        ))
    
    return {
        "keys": [k.model_dump() for k in api_keys],
        "total": len(api_keys),
    }


@router.post("/workspace/security/api-keys")
async def create_api_key(
    request: Request,
    payload: CreateAPIKeyRequest = Body(...),
) -> Dict[str, Any]:
    """创建 API Key."""
    username = _get_username(request)
    db = UserSystemDB()
    
    user = db.get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # Generate key
    full_key, prefix, key_hash = _generate_api_key()
    now = time.time()
    
    db.execute(
        "INSERT INTO api_keys "
        "(user_id, username, key_hash, key_prefix, name, rate_limit, quota_monthly, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user["id"], username, key_hash, prefix, payload.name, payload.rate_limit, payload.quota_monthly, now),
    )
    db.commit()
    
    # Record audit log
    db.insert_audit_log(
        user_id=user["id"],
        username=username,
        action="create_api_key",
        resource_type="security",
        resource_id=prefix,
    )
    
    return {
        "success": True,
        "key": full_key,  # Only returned once!
        "key_prefix": prefix,
        "name": payload.name,
        "message": "请保存此 Key，它将不再显示",
    }


@router.delete("/workspace/security/api-keys/{key_id}")
async def delete_api_key(
    request: Request,
    key_id: int,
) -> Dict[str, Any]:
    """删除 API Key."""
    username = _get_username(request)
    db = UserSystemDB()
    
    key = db.execute(
        "SELECT id, username, key_prefix FROM api_keys WHERE id = ?",
        (key_id,),
    ).fetchone()
    
    if not key:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    
    if key["username"] != username:
        raise HTTPException(status_code=403, detail="无权操作此 API Key")
    
    db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
    db.commit()
    
    # Record audit log
    user = db.get_user_by_username(username)
    if user:
        db.insert_audit_log(
            user_id=user["id"],
            username=username,
            action="delete_api_key",
            resource_type="security",
            resource_id=key["key_prefix"],
        )
    
    return {"success": True, "key_id": key_id}


@router.get("/workspace/security/devices")
async def list_devices(request: Request) -> Dict[str, Any]:
    """查看登录设备（从审计日志中提取）."""
    username = _get_username(request)
    db = UserSystemDB()
    
    # Get unique devices from audit logs
    rows = db.execute(
        "SELECT DISTINCT ip_address, user_agent, MAX(created_at) as last_active "
        "FROM audit_logs WHERE username = ? GROUP BY ip_address, user_agent "
        "ORDER BY last_active DESC LIMIT 20",
        (username,),
    ).fetchall()
    
    devices = []
    for i, row in enumerate(rows):
        devices.append(DeviceInfo(
            id=f"device_{i}",
            device_name=row["user_agent"][:50] if row["user_agent"] else "Unknown",
            ip_address=row["ip_address"] or "",
            last_active=row["last_active"],
            is_current=(i == 0),
        ))
    
    return {
        "devices": [d.model_dump() for d in devices],
        "total": len(devices),
    }


@router.post("/workspace/security/devices/{device_id}/revoke")
async def revoke_device(
    request: Request,
    device_id: str,
) -> Dict[str, Any]:
    """注销设备（清除该设备的 session）."""
    username = _get_username(request)
    
    # Note: This is a simplified implementation.
    # In production, you'd track sessions properly.
    return {
        "success": True,
        "message": "设备已注销",
    }
