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
def _audit_row(row: dict) -> dict:
    """仓储行 -> 原响应结构（details 为 JSON 串时解析成 dict，失败给 {}）。

    2026-11: 审计读侧从裸 SQL 迁到仓储缝后，router 只做形状转换，不再碰 SQL。
    """
    details = row.get("details") or "{}"
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except json.JSONDecodeError:
            details = {}
    return {
        "id": row.get("id"),
        "user_id": row.get("user_id"),
        "username": row.get("username"),
        "action": row.get("action"),
        "resource_type": row.get("resource_type"),
        "resource_id": row.get("resource_id"),
        "details": details,
        "ip_address": row.get("ip_address") or "",
        "user_agent": row.get("user_agent") or "",
        "created_at": row.get("created_at"),
    }



@router.get("/admin/audit")
@router.get("/admin/audit-logs")
@require_permission("audit:read")
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
    
    # 2026-11 修复：原本直调 db.execute() 跑裸 SQL，而委托式 UserSystemDB 从没
    # 有 execute 方法，接口必 500（两版皆坏；社区版注释里也承认这类端点"全部
    # 损坏"）。改走仓储缝 list_audit_logs —— created_at 的时间语义两版不同
    # （社区 REAL epoch / 企业 TIMESTAMPTZ），换算留在仓储，router 不碰 SQL。
    rows, total = db.list_audit_logs(
        limit=page_size,
        offset=(page - 1) * page_size,
        username=username,
        action=action,
        resource_type=resource_type,
        start_time=start_time,
        end_time=end_time,
    )

    return {
        "logs": [_audit_row(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/admin/audit/stats")
@require_permission("admin:admin")
async def get_global_audit_stats(request: Request) -> Dict[str, Any]:
    """获取全局审计统计."""
    db = UserSystemDB()
    
    # 2026-11: 聚合改走仓储缝 audit_stats；返回键名与原来逐项一致
    # （total / by_action / by_resource_type / top_users 取前 10），
    # 排序与 SQL 方言差异由各仓储自行实现。
    stats = db.audit_stats()
    return {
        "total": stats.get("total", 0),
        "by_action": stats.get("by_action", {}),
        "by_resource_type": stats.get("by_resource_type", {}),
        "top_users": stats.get("top_users", {}),
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
    
    # 2026-11: 导出同样走仓储缝；上限 10000 条，与原先隐式全量取的量级一致。
    rows, _total = db.list_audit_logs(
        limit=10000,
        offset=0,
        start_time=start_time,
        end_time=end_time,
    )

    logs = []
    for row in rows:
        details = row.get("details") or "{}"
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except json.JSONDecodeError:
                details = {}

        logs.append({
            "username": row.get("username"),
            "action": row.get("action"),
            "resource_type": row.get("resource_type"),
            "resource_id": row.get("resource_id"),
            "details": details,
            "ip_address": row.get("ip_address") or "",
            "created_at": row.get("created_at"),
        })
    
    return {
        "logs": logs,
        "total": len(logs),
        "exported_at": time.time(),
    }
