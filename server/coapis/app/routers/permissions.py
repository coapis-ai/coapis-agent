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

"""Permission management API routes — v2.0 CRUD Matrix.

Endpoints:
  Public (all authenticated users):
    GET  /permissions/modules          — allowed modules for current user
    GET  /permissions/menu             — menu config with adminOnly markers
    POST /permissions/check            — check specific permission
    GET  /permissions/effective        — full effective permissions for current user

  Admin only:
    GET  /permissions/config           — full config (roles + modules + overrides)
    GET  /permissions/role/{role}      — get role config
    PUT  /permissions/role/{role}      — update role with CRUD matrix
    GET  /permissions/roles            — list all roles
    GET  /permissions/user/{username}  — get user overrides
    PUT  /permissions/user/{username}  — set user overrides
    DEL  /permissions/user/{username}  — clear user overrides
    POST /permissions/reload           — reload config from file
    PUT  /permissions/shell/{role}     — update shell permissions
    GET  /permissions/audit            — audit logs
"""

from __future__ import annotations

import json
from ..permissions.decorators import require_permission
from fastapi import APIRouter, HTTPException, Request
from ..permissions.manager import PermissionManager

router = APIRouter(prefix="/permissions", tags=["permissions"])


# ── Public endpoints (all authenticated users) ────────────────────────

@router.get("/modules")
async def get_allowed_modules(request: Request) -> dict:
    """Get allowed modules for current user (role + per-user overrides)."""
    role = getattr(request.state, "role", "user")
    username = getattr(request.state, "username", "")
    pm = PermissionManager.get_instance()
    if role == "admin":
        modules = ["all"]
    else:
        matrix = pm._get_user_matrix(username, role)
        modules = [mod for mod, crud in matrix.items() if isinstance(crud, dict) and any(crud.values())]
    return {"modules": modules, "role": role, "username": username}


@router.get("/menu")
async def get_menu_config(request: Request) -> dict:
    """Get menu configuration for current user (role + per-user overrides)."""
    role = getattr(request.state, "role", "user")
    username = getattr(request.state, "username", "")
    pm = PermissionManager.get_instance()
    return pm.get_menu_config(role, username)


@router.post("/check")
async def check_permission(request: Request, body: dict) -> dict:
    """Check if current user has a specific permission."""
    permission = body.get("permission", "")
    if not permission:
        raise HTTPException(status_code=400, detail="Permission is required")
    username = getattr(request.state, "username", "anonymous")
    role = getattr(request.state, "role", "user")
    pm = PermissionManager.get_instance()
    return {"permission": permission, "allowed": pm.has_permission(username, permission, role), "role": role}


@router.get("/effective")
async def get_effective_permissions(
    request: Request,
    username: str | None = None,
) -> dict:
    """Get full effective permissions for a user (CRUD matrix + expanded list).
    
    Non-admin users can only query their own permissions.
    Admin can query any user via the ?username= parameter.
    """
    caller_role = getattr(request.state, "role", "user")
    caller_username = getattr(request.state, "username", "anonymous")
    target = username or caller_username
    if target != caller_username and caller_role != "admin":
        raise HTTPException(status_code=403, detail="Cannot query other users' permissions")
    pm = PermissionManager.get_instance()
    return pm.get_user_effective_permissions(target, caller_role if target == caller_username else None)


# ── Admin-only endpoints ─────────────────────────────────────────────

@router.get("/config")
@require_permission("admin:admin")
async def get_permissions_config(request: Request) -> dict:
    """Get full permissions config (admin only)."""
    pm = PermissionManager.get_instance()
    return {"config": pm.get_config()}


@router.get("/roles")
@require_permission("admin:admin")
async def get_all_roles(request: Request) -> dict:
    """List all roles."""
    pm = PermissionManager.get_instance()
    return {"roles": pm.get_all_roles(), "current_role": getattr(request.state, "role", "user")}


@router.get("/role/{role}")
@require_permission("admin:admin")
async def get_role_config(role: str, request: Request) -> dict:
    """Get configuration for a specific role."""
    user_role = getattr(request.state, "role", "user")
    if role != user_role and user_role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view other roles' configuration")
    pm = PermissionManager.get_instance()
    return {"role": role, "config": pm.get_role_config(role)}


@router.put("/role/{role}")
@require_permission("admin:admin")
async def update_role_config(role: str, request: Request, body: dict) -> dict:
    """Update role configuration.
    
    Body:
      - modules: dict (CRUD matrix) — preferred
      - modules_list: list + permissions: list — legacy fallback
    """
    if role == "admin":
        raise HTTPException(status_code=400, detail="Cannot modify admin role")
    pm = PermissionManager.get_instance()
    
    modules_matrix = body.get("modules")
    if isinstance(modules_matrix, dict):
        success = pm.update_role_config(role, modules_matrix)
    else:
        modules_list = body.get("modules_list", body.get("modules", []))
        permissions_list = body.get("permissions_list", body.get("permissions", []))
        if not isinstance(modules_list, list):
            raise HTTPException(status_code=400, detail="modules must be a dict (CRUD matrix) or list (legacy)")
        success = pm.update_role_config_legacy(role, modules_list, permissions_list)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save role configuration")

    # Audit log
    try:
        from coapis.user_system.database import get_db
        db = get_db()
        admin_username = getattr(request.state, "username", "unknown")
        user = db.get_user_by_username(admin_username)
        if user:
            db.insert_audit_log(
                user_id=user["id"],
                username=admin_username,
                action="update_role",
                resource_type="role",
                resource_id=role,
                details={"modules": modules_matrix},
            )
    except Exception as _audit_err:
        import logging as _audit_log
        _audit_log.getLogger("permissions.audit").warning(f"Audit log failed: {_audit_err}")

    return {"success": True, "message": f"Role '{role}' updated"}


# ── User overrides ───────────────────────────────────────────────────

@router.get("/user/{username}")
@require_permission("admin:admin")
async def get_user_overrides(username: str, request: Request) -> dict:
    """Get user permission overrides."""
    pm = PermissionManager.get_instance()
    user_role = getattr(request.state, "role", "user")
    role = getattr(request.state, "role", "user")
    # For non-admin, only show own overrides
    if user_role != "admin":
        username = getattr(request.state, "username", "")
    return {
        "username": username,
        "overrides": pm.get_user_overrides(username),
    }


@router.put("/user/{username}")
@require_permission("admin:admin")
async def update_user_overrides(username: str, request: Request, body: dict) -> dict:
    """Set user permission overrides.
    
    Body: { "overrides": { "skills": {"create": true, "delete": false}, ... } }
    """
    if getattr(request.state, "role", "user") != "admin":
        username = getattr(request.state, "username", "")
    overrides = body.get("overrides", {})
    if not isinstance(overrides, dict):
        raise HTTPException(status_code=400, detail="overrides must be a dict")
    pm = PermissionManager.get_instance()
    success = pm.update_user_overrides(username, overrides)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save user overrides")

    # Audit log
    try:
        from coapis.user_system.database import get_db
        db = get_db()
        admin_username = getattr(request.state, "username", "unknown")
        user = db.get_user_by_username(admin_username)
        if user:
            db.insert_audit_log(
                user_id=user["id"],
                username=admin_username,
                action="update_user_overrides",
                resource_type="user_permission",
                resource_id=username,
                details={"overrides": overrides},
            )
    except Exception as _audit_err:
        import logging as _audit_log
        _audit_log.getLogger("permissions.audit").warning(f"Audit log failed: {_audit_err}")

    return {"success": True, "message": f"Overrides for '{username}' updated"}


@router.delete("/user/{username}")
@require_permission("admin:admin")
async def delete_user_overrides(username: str, request: Request) -> dict:
    """Clear all user permission overrides."""
    pm = PermissionManager.get_instance()
    pm.delete_user_overrides(username)

    # Audit log
    try:
        from coapis.user_system.database import get_db
        db = get_db()
        admin_username = getattr(request.state, "username", "unknown")
        user = db.get_user_by_username(admin_username)
        if user:
            db.insert_audit_log(
                user_id=user["id"],
                username=admin_username,
                action="delete_user_overrides",
                resource_type="user_permission",
                resource_id=username,
            )
    except Exception as _audit_err:
        import logging as _audit_log
        _audit_log.getLogger("permissions.audit").warning(f"Audit log failed: {_audit_err}")

    return {"success": True, "message": f"Overrides for '{username}' cleared"}


# ── Config management ────────────────────────────────────────────────

@router.post("/reload")
@require_permission("admin:admin")
async def reload_permissions(request: Request) -> dict:
    """Reload permissions config from file (admin only)."""
    if getattr(request.state, "role", "user") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can reload")
    pm = PermissionManager.get_instance()
    pm.reload()
    return {"success": True, "message": "Permissions config reloaded"}


@router.get("/audit")
@require_permission("admin:admin")
async def get_audit_logs(
    request: Request,
    username: str | None = None,
    role: str | None = None,
    result: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Get audit logs with filtering (admin only)."""
    from coapis.user_system.database import get_db
    db = get_db()
    where, params = [], []
    if username:
        where.append("al.username = ?")
        params.append(username)
    where_clause = " WHERE " + " AND ".join(where) if where else ""
    total = db.execute(
        f"SELECT COUNT(*) FROM audit_logs al{where_clause}", params
    ).fetchone()[0]
    rows = db.execute(
        f"""SELECT al.id, al.user_id, al.username, al.action, al.resource_type,
                   al.resource_id, al.details, al.ip_address, al.user_agent,
                   al.created_at
            FROM audit_logs al{where_clause}
            ORDER BY al.created_at DESC LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    logs = []
    for r in rows:
        details = {}
        try:
            details = json.loads(r["details"]) if r["details"] else {}
        except (json.JSONDecodeError, TypeError):
            pass
        logs.append({
            "id": r["id"],
            "user_id": r["user_id"],
            "username": r["username"],
            "action": r["action"],
            "resource_type": r["resource_type"],
            "resource_id": r["resource_id"],
            "details": details,
            "ip_address": r["ip_address"],
            "user_agent": r["user_agent"],
            "timestamp": r["created_at"],
        })
    return {"logs": logs, "total": total}
