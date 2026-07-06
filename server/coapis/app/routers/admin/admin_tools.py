# -*- coding: utf-8 -*-
"""
系统工具 API — 系统目录清理、健康诊断、外部智能体管理

低频操作，通过 CLI 工具或 Admin 页面管理。
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request

from ....constant import (
    AGENTS_DIR, SYSTEM_DIR, TEMPLATES_DIR, WORKING_DIR, WORKSPACES_DIR,
)
from ...permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 系统目录清理 ──────────────────────────────────────────────────────────

@router.get("/admin/tools/cleanup/scan")
@require_permission("admin:admin")
async def scan_cleanup(request: Request) -> Dict[str, Any]:
    """扫描 system/ 目录中的残留项"""
    KEEP_DIRS = {".secret", "templates"}
    KEEP_FILES = {
        "config.json", "users.json", "auth.json", "permissions.json",
        "providers.json", "evolution_config.json", "token_usage.json",
        "user_system.db", "user_system.db-shm", "user_system.db-wal"
    }

    stale_dirs = []
    unknown_files = []

    for item in SYSTEM_DIR.iterdir():
        if item.is_dir():
            if item.name not in KEEP_DIRS:
                size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                stale_dirs.append({
                    "name": item.name,
                    "path": str(item),
                    "size": size,
                    "size_kb": size // 1024,
                })
        elif item.is_file():
            if item.name not in KEEP_FILES:
                unknown_files.append({
                    "name": item.name,
                    "path": str(item),
                    "size": item.stat().st_size,
                })

    return {
        "stale_dirs": stale_dirs,
        "unknown_files": unknown_files,
        "total_stale_dirs": len(stale_dirs),
        "total_unknown_files": len(unknown_files),
    }


@router.post("/admin/tools/cleanup/execute")
@require_permission("admin:admin")
async def execute_cleanup(
    request: Request,
    body: Dict[str, Any] = {},
) -> Dict[str, Any]:
    """执行 system/ 目录清理"""
    remove_dirs = body.get("remove_dirs", [])
    removed = []

    for dir_name in remove_dirs:
        dir_path = SYSTEM_DIR / dir_name
        if dir_path.is_dir():
            # 安全保护：禁止删除关键目录
            if dir_name in {".secret", "templates"}:
                logger.warning(f"Refused to remove protected directory: {dir_name}")
                continue

            try:
                shutil.rmtree(dir_path)
                removed.append(dir_name)
                logger.info(f"Removed stale directory: {dir_name}")
            except Exception as e:
                logger.error(f"Failed to remove {dir_name}: {e}")

    return {
        "success": True,
        "removed": removed,
        "count": len(removed),
    }


# ── 系统健康诊断 ──────────────────────────────────────────────────────────

@router.get("/admin/tools/diagnose")
@require_permission("admin:admin")
async def system_diagnose(request: Request) -> Dict[str, Any]:
    """系统健康诊断"""
    issues = []
    checks = []

    # 1. 检查 system/ 目录污染
    stale_count = sum(
        1 for item in SYSTEM_DIR.iterdir()
        if item.is_dir() and item.name not in {".secret", "templates"}
    )
    if stale_count > 0:
        issues.append(f"system/ 目录存在 {stale_count} 个残留目录")
    checks.append({"name": "system_dir_clean", "ok": stale_count == 0, "detail": f"{stale_count} stale dirs"})

    # 2. 检查全局模板存在
    for filename in ["SOUL.md", "PROFILE.md"]:
        if not (TEMPLATES_DIR / filename).exists():
            issues.append(f"全局模板缺失: {filename}")
        checks.append({"name": f"template_{filename}", "ok": (TEMPLATES_DIR / filename).exists()})

    # 3. 检查全局智能体身份文件
    for agent_dir in AGENTS_DIR.iterdir():
        if agent_dir.is_dir():
            for filename in ["SOUL.md", "PROFILE.md"]:
                if not (agent_dir / filename).exists():
                    issues.append(f"全局智能体 {agent_dir.name} 缺失 {filename}")
            checks.append({
                "name": f"agent_{agent_dir.name}_identity",
                "ok": all((agent_dir / f).exists() for f in ["SOUL.md", "PROFILE.md"]),
            })

    # 4. 检查用户工作区完整性
    for workspace_dir in WORKSPACES_DIR.iterdir():
        if workspace_dir.is_dir():
            has_soul = (workspace_dir / "SOUL.md").exists()
            has_memory = (workspace_dir / "MEMORY.md").exists()
            has_profile = (workspace_dir / "PROFILE.md").exists()
            if not (has_soul and has_memory and has_profile):
                issues.append(f"用户 {workspace_dir.name} 工作区身份文件不完整")

    # 5. 检查 config.json 一致性
    config_path = SYSTEM_DIR / "config.json"
    if config_path.exists():
        # Scan agents/ directory instead of profiles
        from ....constant import AGENTS_DIR
        if AGENTS_DIR.exists():
            for item in AGENTS_DIR.iterdir():
                if not item.is_dir() or not (item / "agent.json").exists():
                    continue
                agent_id = item.name
                ws_dir = str(item)
                if WORKSPACES_DIR in Path(ws_dir).parents:
                    issues.append(f"全局智能体 {agent_id} 路径错误: {ws_dir}（应在 agents/ 下）")

    overall_ok = len(issues) == 0

    return {
        "overall": "healthy" if overall_ok else "issues_found",
        "issues": issues,
        "checks": checks,
        "timestamp": datetime.now().isoformat(),
    }


# ── 外部智能体管理 ────────────────────────────────────────────────────────

@router.get("/admin/tools/external-agents")
@require_permission("admin:admin")
async def list_external_agents(request: Request) -> Dict[str, Any]:
    """列出 config.json 中的外部智能体"""
    config_path = SYSTEM_DIR / "config.json"
    if not config_path.exists():
        return {"agents": []}

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    # Scan agents/ directory for external agents
    from ....constant import AGENTS_DIR
    external = []
    if AGENTS_DIR.exists():
        for item in sorted(AGENTS_DIR.iterdir()):
            if not item.is_dir() or not (item / "agent.json").exists():
                continue
            meta = json.loads((item / "agent.json").read_text(encoding="utf-8"))
            agent_id = meta.get("id", item.name)
            external.append({
                "id": agent_id,
                "name": meta.get("name", agent_id),
                "workspace_dir": str(item),
                "enabled": meta.get("enabled", True),
                "username": meta.get("owner", ""),
                "is_external": True,
            })
    return {"agents": external}


@router.post("/admin/tools/external-agents/{agent_id}/toggle")
@require_permission("admin:admin")
async def toggle_external_agent(
    request: Request,
    agent_id: str,
    body: Dict[str, bool] = {},
) -> Dict[str, Any]:
    """启用/禁用外部智能体"""
    config_path = SYSTEM_DIR / "config.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="config.json 不存在")

    enabled = body.get("enabled", True)

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    # Find agent in agents/ directory
    from ....constant import AGENTS_DIR
    agent_dir = AGENTS_DIR / agent_id
    agent_json = agent_dir / "agent.json"
    if not agent_json.exists():
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    meta = json.loads(agent_json.read_text(encoding="utf-8"))
    meta["enabled"] = enabled
    agent_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    logger.info(f"Toggled external agent {agent_id}: enabled={enabled}")

    return {"success": True, "agent_id": agent_id, "enabled": enabled}
