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

"""
P2-1 监控面板 API 端点

端点列表：
- GET  /api/monitor/health       - 健康状态汇总
- GET  /api/monitor/cpu          - CPU 指标
- GET  /api/monitor/memory       - 内存指标
- GET  /api/monitor/disk         - 磁盘指标
- GET  /api/monitor/network      - 网络指标
- GET  /api/monitor/process      - 进程指标
- GET  /api/monitor/snapshot     - 全量快照
- GET  /api/monitor/api-stats    - API 调用统计
- GET  /api/monitor/uptime       - 运行时间

权限：admin 角色可访问全部端点
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from ..permissions.decorators import require_role
from .collector import collector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitor", tags=["monitoring"])


@router.get("/health")
@require_role("admin")
async def get_health(request: Request) -> Dict[str, Any]:
    """健康状态汇总（快速检查）."""
    return collector.get_health_summary()


@router.get("/cpu")
@require_role("admin")
async def get_cpu_metrics(request: Request) -> Dict[str, Any]:
    """CPU 实时指标."""
    return collector.get_cpu_metrics()


@router.get("/memory")
@require_role("admin")
async def get_memory_metrics(request: Request) -> Dict[str, Any]:
    """内存实时指标."""
    return collector.get_memory_metrics()


@router.get("/disk")
@require_role("admin")
async def get_disk_metrics(request: Request) -> Dict[str, Any]:
    """磁盘使用与 IO 指标."""
    return collector.get_disk_metrics()


@router.get("/network")
@require_role("admin")
async def get_network_metrics(request: Request) -> Dict[str, Any]:
    """网络 IO 指标."""
    return collector.get_network_metrics()


@router.get("/process")
@require_role("admin")
async def get_process_metrics(request: Request) -> Dict[str, Any]:
    """当前进程指标."""
    return collector.get_process_metrics()


@router.get("/snapshot")
@require_role("admin")
async def get_full_snapshot(request: Request) -> Dict[str, Any]:
    """全量指标快照（一次性采集所有指标）."""
    return collector.get_full_snapshot()


@router.get("/api-stats")
@require_role("admin")
async def get_api_stats(request: Request) -> Dict[str, Any]:
    """API 调用统计."""
    return collector.get_api_stats()


@router.get("/uptime")
@require_role("admin")
async def get_uptime(request: Request) -> Dict[str, Any]:
    """服务运行时间."""
    return {"uptime_seconds": collector.get_uptime()}


# =========================================================================
# P5: 进化引擎 + 记忆系统 + 全局监控
# =========================================================================

@router.get("/evolution")
@require_role("admin")
async def get_evolution_monitor(request: Request) -> Dict[str, Any]:
    """进化引擎全局监控：跨 agent AB 桶容量、LLM 调用统计、采样统计。"""
    mgr = request.app.state.multi_agent_manager
    result = {
        "cross_agent_evolution": None,
        "per_agent": {},
        "prompt_cache": None,
    }

    # Global CrossAgentEvolution stats
    try:
        from coapis.evolution.cross_agent_evolution import get_global_cross_agent_evolution
        cae = get_global_cross_agent_evolution()
        if cae:
            result["cross_agent_evolution"] = {
                "bucket_a_count": cae.bucket_a_count,
                "bucket_b_count": cae.bucket_b_count,
                "foundation_count": cae.foundation_count,
                "pending_confirmations": len(cae.get_pending_confirmations()),
                "config": {
                    "enabled": cae.config.enabled,
                    "promotion_threshold": cae.config.promotion_threshold,
                    "min_confidence": cae.config.min_confidence,
                },
            }
    except Exception as e:
        result["cross_agent_evolution"] = {"error": str(e)}

    # Per-agent evolution engine stats
    for key, ws in list(mgr._workspaces.items()):
        try:
            engine = getattr(ws, "evolution_engine", None)
            if engine and engine.enabled:
                result["per_agent"][key] = {
                    "llm_stats": dict(engine._llm_stats),
                    "sampling_stats": dict(engine._sampling_stats),
                    "current_trajectory": len(engine._current_trajectory),
                    "pending_experiences": len(engine._pending_experiences),
                }
        except Exception:
            pass

    # PromptBuilder cache stats
    try:
        from coapis.agents.prompt import get_cache_stats
        result["prompt_cache"] = get_cache_stats()
    except Exception as e:
        result["prompt_cache"] = {"error": str(e)}

    return result


@router.get("/memory")
@require_role("admin")
async def get_memory_monitor(request: Request) -> Dict[str, Any]:
    """记忆系统监控：全局/用户 MEMORY.md 大小、容量状态、版本历史。"""
    from pathlib import Path
    from coapis.constant import AGENTS_DIR, WORKSPACES_DIR
    from coapis.evolution.memory_capacity import MemoryCapacityManager, estimate_tokens

    result = {"global_agents": {}, "user_agents": {}}

    # Global agents
    for agent_dir in [AGENTS_DIR / "global_default", AGENTS_DIR / "global_qa_agent"]:
        if agent_dir.is_dir():
            mem_file = agent_dir / "MEMORY.md"
            name = agent_dir.name
            mgr = MemoryCapacityManager(mem_file)
            result["global_agents"][name] = mgr.get_status()

    # User agents (scan workspaces)
    if WORKSPACES_DIR.exists():
        for user_dir in sorted(WORKSPACES_DIR.iterdir()):
            if not user_dir.is_dir():
                continue
            user_agents = user_dir / "agents"
            if not user_agents.exists():
                continue
            for agent_dir in user_agents.iterdir():
                if not agent_dir.is_dir():
                    continue
                mem_file = agent_dir / "MEMORY.md"
                if mem_file.exists():
                    content = mem_file.read_text(encoding="utf-8")
                    key = f"{user_dir.name}:{agent_dir.name}"
                    result["user_agents"][key] = {
                        "chars": len(content),
                        "tokens": estimate_tokens(content),
                        "max_tokens": 10000,
                    }

    # Dream drafts status
    for agent_dir in [AGENTS_DIR / "global_default", AGENTS_DIR / "global_qa_agent"]:
        draft_dir = agent_dir / ".dream_drafts"
        if draft_dir.exists():
            drafts = []
            for f in sorted(draft_dir.glob("draft_*.json")):
                import json as _json
                try:
                    drafts.append(_json.loads(f.read_text(encoding="utf-8")))
                except Exception:
                    pass
            result[f"dream_drafts_{agent_dir.name}"] = drafts

    return result
