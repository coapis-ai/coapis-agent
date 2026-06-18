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

"""跨 Agent 进化引擎 REST API 路由。"""
from __future__ import annotations

import logging
from ..permissions.decorators import require_permission
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Router 注册到主 router 时指定了 prefix="/api"，所以这里不要加 /api/ 前缀
# 子路由需要显式使用 /cross-agent 前缀
cross_agent_router = APIRouter(prefix="/cross-agent")


# =========================================================================
# Request Models
# =========================================================================

class ExperienceReportRequest(BaseModel):
    """经验上报请求。"""
    content: str = Field(..., description="经验原文")
    category: str = Field("general", description="分类")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="置信度")


class ReviewCycleRequest(BaseModel):
    """手动触发评审请求。"""
    pass


# =========================================================================
# 辅助函数
# =========================================================================

def _get_cross_agent_evolution(request: Request) -> Any:
    """从 app state 获取 CrossAgentEvolution 实例（全局单例）。
    
    NOTE: 统一使用 app.state.cross_agent_evolution，与 multi_layer_evolution.py 共享同一实例。
    旧版从 global_workspace.cross_agent_evolution 获取会导致数据不同步。
    """
    cae = getattr(request.app.state, "cross_agent_evolution", None)
    if cae is None:
        raise HTTPException(status_code=503, detail="跨 Agent 进化引擎未初始化")
    return cae


# =========================================================================
# API 端点
# =========================================================================

@cross_agent_router.get("/status")
@require_permission("admin:admin")
async def get_cross_agent_status(request: Request):
    """获取跨 Agent 进化引擎状态。"""
    cae = _get_cross_agent_evolution(request)
    return {
        "enabled": cae.config.enabled,
        "config": {
            "promotion_threshold": cae.config.promotion_threshold,
            "cold_start_threshold": cae.config.cold_start_threshold,
            "review_interval_minutes": cae.config.review_interval_minutes,
            "bucket_a_capacity": cae.config.bucket_a_capacity,
            "bucket_b_capacity": cae.config.bucket_b_capacity,
            "archive_ttl_days": cae.config.archive_ttl_days,
            "min_confidence": cae.config.min_confidence,
            "max_keywords": cae.config.max_keywords,
            "similarity_threshold": cae.config.similarity_threshold,
        },
        "buckets": cae.get_bucket_stats(),
    }


@cross_agent_router.get("/bucket-a")
@require_permission("admin:admin")
async def get_bucket_a(request: Request, status: str | None = None):
    """获取 A 桶（已纳入）经验列表。"""
    cae = _get_cross_agent_evolution(request)
    entries = cae.get_entries(bucket="A", status=status)
    return {
        "entries": [e.to_dict() for e in entries],
        "total": len(entries),
    }


@cross_agent_router.get("/bucket-b")
@require_permission("admin:admin")
async def get_bucket_b(request: Request, status: str | None = None):
    """获取 B 桶（待审核）经验列表。"""
    cae = _get_cross_agent_evolution(request)
    entries = cae.get_entries(bucket="B", status=status)
    return {
        "entries": [e.to_dict() for e in entries],
        "total": len(entries),
    }


@cross_agent_router.post("/report")
@require_permission("admin:admin")
async def report_experience(request: Request, body: ExperienceReportRequest):
    """上报经验到 B 桶。"""
    cae = _get_cross_agent_evolution(request)
    
    # 获取用户信息
    username = getattr(request.state, "username", "anonymous")
    
    entry = cae.report_experience(
        content=body.content,
        category=body.category,
        source_user=username,
        confidence=body.confidence,
    )
    
    return {
        "success": True,
        "entry": entry.to_dict(),
    }


@cross_agent_router.post("/review-cycle")
@require_permission("admin:admin")
async def trigger_review_cycle(request: Request):
    """手动触发一次评审周期。"""
    cae = _get_cross_agent_evolution(request)
    
    results = await cae.run_review_cycle()
    
    return {
        "success": True,
        "results": results,
        "total_reviewed": len(results),
        "promoted": sum(1 for r in results if r.get("promoted")),
    }


@cross_agent_router.get("/review-log")
@require_permission("admin:admin")
async def get_review_log(request: Request, limit: int = 50):
    """获取评审日志。"""
    cae = _get_cross_agent_evolution(request)
    
    # 返回最近的 N 条
    log = cae._review_log[-limit:]
    
    return {
        "log": log,
        "total": len(cae._review_log),
    }


@cross_agent_router.post("/cleanup-archives")
@require_permission("admin:admin")
async def cleanup_archives(request: Request):
    """清理过期归档。"""
    cae = _get_cross_agent_evolution(request)
    
    cleaned = cae.cleanup_expired_archives()
    
    return {
        "success": True,
        "cleaned": cleaned,
    }


@cross_agent_router.post("/enable")
@require_permission("admin:admin")
async def enable_cross_agent(request: Request):
    """启用跨 Agent 进化引擎。"""
    cae = _get_cross_agent_evolution(request)
    cae.config.enabled = True
    cae.start_periodic_review()
    
    return {"success": True, "enabled": True}


@cross_agent_router.post("/disable")
@require_permission("admin:admin")
async def disable_cross_agent(request: Request):
    """禁用跨 Agent 进化引擎。"""
    cae = _get_cross_agent_evolution(request)
    cae.config.enabled = False
    cae.stop_periodic_review()
    
    return {"success": True, "enabled": False}
