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

"""Workspace Audit router - user-level audit log viewing.

每个用户可以查看自己的操作审计日志。
管理员可以查看所有用户的审计日志（通过 /admin/audit）。
"""
from __future__ import annotations

import logging
import json
import time
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ....user_system.database import UserSystemDB
from ....user_system.models import AuditLog, AuditLogList

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workspace/audit"])


# ── Helper functions ─────────────────────────────────────────────────────

def _get_username(request: Request) -> str:
    """获取当前用户名."""
    username = getattr(request.state, "username", "anonymous")
    if username == "anonymous":
        raise HTTPException(status_code=401, detail="需要登录")
    return username


def _format_timestamp(ts: Optional[float]) -> Optional[str]:
    """格式化时间戳为 ISO 字符串."""
    if ts is None:
        return None
    from datetime import datetime
    return datetime.fromtimestamp(ts).isoformat()


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/workspace/audit")
async def list_my_audit_logs(
    request: Request,
    action: Optional[str] = Query(None, description="筛选操作类型"),
    resource_type: Optional[str] = Query(None, description="筛选资源类型"),
    start_time: Optional[float] = Query(None, description="开始时间戳"),
    end_time: Optional[float] = Query(None, description="结束时间戳"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页数量"),
) -> Dict[str, Any]:
    """查询个人审计日志."""
    username = _get_username(request)
    db = UserSystemDB()
    
    user = db.get_user_by_username(username)
    if not user:
        return {"logs": [], "total": 0, "page": page, "page_size": page_size}
    
    user_id = user["id"]
    
    # 构建查询
    conditions = ["user_id = ?"]
    params: List[Any] = [user_id]
    
    if action:
        conditions.append("action = ?")
        params.append(action)
    
    if resource_type:
        conditions.append("resource_type = ?")
        params.append(resource_type)
    
    if start_time is not None:
        conditions.append("created_at >= ?")
        params.append(start_time)
    
    if end_time is not None:
        conditions.append("created_at <= ?")
        params.append(end_time)
    
    where_clause = " AND ".join(conditions)
    
    # 获取总数
    total_row = db.execute(
        f"SELECT COUNT(*) as total FROM audit_logs WHERE {where_clause}",
        params,
    ).fetchone()
    total = total_row["total"] if total_row else 0
    
    # 获取分页数据
    offset = (page - 1) * page_size
    rows = db.execute(
        f"SELECT id, user_id, username, action, resource_type, resource_id, "
        f"details, ip_address, user_agent, created_at "
        f"FROM audit_logs WHERE {where_clause} "
        f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()
    
    logs = []
    for row in rows:
        details = row["details"] or "{}"
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except json.JSONDecodeError:
                details = {}
        
        logs.append(AuditLog(
            id=row["id"],
            user_id=row["user_id"],
            username=row["username"],
            action=row["action"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            details=details,
            ip_address=row["ip_address"] or "",
            user_agent=row["user_agent"] or "",
            created_at=row["created_at"],
        ))
    
    return {
        "logs": [l.model_dump() for l in logs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/workspace/audit/export")
async def export_my_audit_logs(
    request: Request,
    start_time: Optional[float] = Query(None, description="开始时间戳"),
    end_time: Optional[float] = Query(None, description="结束时间戳"),
) -> Dict[str, Any]:
    """导出个人审计日志（返回 JSON 数据）."""
    username = _get_username(request)
    db = UserSystemDB()
    
    user = db.get_user_by_username(username)
    if not user:
        return {"logs": [], "exported_at": time.time()}
    
    user_id = user["id"]
    
    conditions = ["user_id = ?"]
    params: List[Any] = [user_id]
    
    if start_time is not None:
        conditions.append("created_at >= ?")
        params.append(start_time)
    
    if end_time is not None:
        conditions.append("created_at <= ?")
        params.append(end_time)
    
    where_clause = " AND ".join(conditions)
    
    rows = db.execute(
        f"SELECT id, user_id, username, action, resource_type, resource_id, "
        f"details, ip_address, user_agent, created_at "
        f"FROM audit_logs WHERE {where_clause} "
        f"ORDER BY created_at DESC",
        params,
    ).fetchall()
    
    logs = []
    for row in rows:
        details = row["details"] or "{}"
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except json.JSONDecodeError:
                details = {}
        
        logs.append({
            "id": row["id"],
            "username": row["username"],
            "action": row["action"],
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "details": details,
            "ip_address": row["ip_address"] or "",
            "user_agent": row["user_agent"] or "",
            "created_at": _format_timestamp(row["created_at"]),
        })
    
    return {
        "username": username,
        "logs": logs,
        "total": len(logs),
        "exported_at": _format_timestamp(time.time()),
    }


@router.get("/workspace/audit/stats")
async def get_my_audit_stats(request: Request) -> Dict[str, Any]:
    """获取个人审计统计."""
    username = _get_username(request)
    db = UserSystemDB()
    
    user = db.get_user_by_username(username)
    if not user:
        return {"total": 0, "by_action": {}, "by_resource_type": {}}
    
    user_id = user["id"]
    
    # 总数
    total_row = db.execute(
        "SELECT COUNT(*) as total FROM audit_logs WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    total = total_row["total"] if total_row else 0
    
    # 按操作类型统计
    action_rows = db.execute(
        "SELECT action, COUNT(*) as count FROM audit_logs "
        "WHERE user_id = ? GROUP BY action ORDER BY count DESC",
        (user_id,),
    ).fetchall()
    by_action = {row["action"]: row["count"] for row in action_rows}
    
    # 按资源类型统计
    resource_rows = db.execute(
        "SELECT resource_type, COUNT(*) as count FROM audit_logs "
        "WHERE user_id = ? GROUP BY resource_type ORDER BY count DESC",
        (user_id,),
    ).fetchall()
    by_resource_type = {row["resource_type"]: row["count"] for row in resource_rows}
    
    # 最近活动时间
    latest_row = db.execute(
        "SELECT MAX(created_at) as latest FROM audit_logs WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    
    return {
        "total": total,
        "by_action": by_action,
        "by_resource_type": by_resource_type,
        "latest_activity": _format_timestamp(latest_row["latest"]) if latest_row and latest_row["latest"] else None,
    }
