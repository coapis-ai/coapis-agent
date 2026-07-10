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

"""Admin audit router - global audit log viewing.

管理员可查看所有用户的审计日志。
"""
from __future__ import annotations

import logging
import json
import time
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ....user_system.database import UserSystemDB
from ...permissions import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin/audit"])


@router.get("/admin/audit")
@router.get("/admin/audit-logs")
@require_permission("admin:admin")
async def list_all_audit_logs(
    request: Request,
    username: Optional[str] = Query(None, description="筛选用户"),
    action: Optional[str] = Query(None, description="筛选操作类型"),
    resource_type: Optional[str] = Query(None, description="筛选资源类型"),
    start_time: Optional[float] = Query(None, description="开始时间戳"),
    end_time: Optional[float] = Query(None, description="结束时间戳"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """查询全局审计日志."""
    db = UserSystemDB()
    
    conditions = []
    params: List[Any] = []
    
    if username:
        conditions.append("username = ?")
        params.append(username)
    
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
    
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    
    # 总数
    total_row = db.execute(f"SELECT COUNT(*) as total FROM audit_logs {where}", params).fetchone()
    total = total_row["total"] if total_row else 0
    
    # 分页
    offset = (page - 1) * page_size
    rows = db.execute(
        f"SELECT * FROM audit_logs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
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
        
        logs.append({
            "id": row["id"],
            "user_id": row["user_id"],
            "username": row["username"],
            "action": row["action"],
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "details": details,
            "ip_address": row["ip_address"] if "ip_address" in row.keys() else "",
            "user_agent": row["user_agent"] if "user_agent" in row.keys() else "",
            "created_at": row["created_at"],
        })
    
    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/admin/audit/stats")
@require_permission("admin:admin")
async def get_global_audit_stats(request: Request) -> Dict[str, Any]:
    """获取全局审计统计."""
    db = UserSystemDB()
    
    # 总数
    total_row = db.execute("SELECT COUNT(*) as total FROM audit_logs").fetchone()
    total = total_row["total"] if total_row else 0
    
    # 按操作类型
    action_rows = db.execute(
        "SELECT action, COUNT(*) as count FROM audit_logs GROUP BY action ORDER BY count DESC"
    ).fetchall()
    by_action = {row["action"]: row["count"] for row in action_rows}
    
    # 按资源类型
    resource_rows = db.execute(
        "SELECT resource_type, COUNT(*) as count FROM audit_logs GROUP BY resource_type ORDER BY count DESC"
    ).fetchall()
    by_resource_type = {row["resource_type"]: row["count"] for row in resource_rows}
    
    # 按用户
    user_rows = db.execute(
        "SELECT username, COUNT(*) as count FROM audit_logs GROUP BY username ORDER BY count DESC LIMIT 10"
    ).fetchall()
    top_users = {row["username"]: row["count"] for row in user_rows}
    
    return {
        "total": total,
        "by_action": by_action,
        "by_resource_type": by_resource_type,
        "top_users": top_users,
    }


@router.get("/admin/audit/export")
@require_permission("admin:admin")
async def export_global_audit_logs(
    request: Request,
    start_time: Optional[float] = Query(None),
    end_time: Optional[float] = Query(None),
) -> Dict[str, Any]:
    """导出全局审计日志."""
    db = UserSystemDB()
    
    conditions = []
    params: List[Any] = []
    
    if start_time is not None:
        conditions.append("created_at >= ?")
        params.append(start_time)
    
    if end_time is not None:
        conditions.append("created_at <= ?")
        params.append(end_time)
    
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    
    rows = db.execute(f"SELECT * FROM audit_logs {where} ORDER BY created_at DESC", params).fetchall()
    
    logs = []
    for row in rows:
        details = row["details"] or "{}"
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except json.JSONDecodeError:
                details = {}
        
        logs.append({
            "username": row["username"],
            "action": row["action"],
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "details": details,
            "ip_address": row["ip_address"] if "ip_address" in row.keys() else "",
            "created_at": row["created_at"],
        })
    
    return {
        "logs": logs,
        "total": len(logs),
        "exported_at": time.time(),
    }
