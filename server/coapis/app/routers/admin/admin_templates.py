# -*- coding: utf-8 -*-
"""
全局模板管理 API — 管理 system/templates/ 下的 SOUL.md, MEMORY.md, PROFILE.md

高频操作，通过 Admin 页面管理。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from ....constant import TEMPLATES_DIR, WORKING_DIR
from ...permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()

TEMPLATE_FILES = ["SOUL.md", "MEMORY.md", "PROFILE.md"]


@router.get("/admin/templates")
@require_permission("admin:admin")
async def list_templates(request: Request) -> Dict[str, Any]:
    """获取所有全局模板文件列表及内容"""

    result = {}
    for filename in TEMPLATE_FILES:
        file_path = TEMPLATES_DIR / filename
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8")
            result[filename] = {
                "exists": True,
                "size": len(content),
                "content": content,
            }
        else:
            result[filename] = {
                "exists": False,
                "size": 0,
                "content": "",
            }

    return {"templates": result, "templates_dir": str(TEMPLATES_DIR)}


@router.put("/admin/templates/{filename}")
@require_permission("admin:admin")
async def update_template(
    request: Request,
    filename: str,
    body: Dict[str, str],
) -> Dict[str, Any]:
    """更新指定全局模板文件内容"""

    if filename not in TEMPLATE_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的模板文件: {filename}。仅支持: {', '.join(TEMPLATE_FILES)}",
        )

    content = body.get("content", "")
    file_path = TEMPLATES_DIR / filename

    # 备份原文件
    if file_path.exists():
        backup_path = file_path.with_suffix(f".{file_path.suffix}.bak")
        try:
            file_path.rename(backup_path)
            logger.info(f"Backed up {filename} to {backup_path.name}")
        except Exception as e:
            logger.warning(f"Failed to backup {filename}: {e}")

    # 写入新内容
    file_path.write_text(content, encoding="utf-8")
    logger.info(f"Updated global template {filename} ({len(content)} bytes)")

    return {
        "success": True,
        "filename": filename,
        "size": len(content),
    }


@router.post("/admin/templates/{filename}/reset")
@require_permission("admin:admin")
async def reset_template(
    request: Request,
    filename: str,
) -> Dict[str, Any]:
    """重置指定全局模板文件为默认内容"""

    if filename not in TEMPLATE_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的模板文件: {filename}",
        )

    file_path = TEMPLATES_DIR / filename
    backup_path = file_path.with_suffix(f".{file_path.suffix}.bak")

    if backup_path.exists():
        backup_path.rename(file_path)
        logger.info(f"Reset {filename} from backup")
        return {"success": True, "filename": filename, "from": "backup"}

    # 无备份时写入默认内容
    defaults = {
        "SOUL.md": "# Soul\n\nI am the global base agent.\n",
        "MEMORY.md": "# Memory\n\nNo memories yet.\n",
        "PROFILE.md": "# Profile\n\nGlobal base agent profile.\n",
    }
    content = defaults.get(filename, "")
    file_path.write_text(content, encoding="utf-8")
    logger.info(f"Reset {filename} to default content")

    return {"success": True, "filename": filename, "from": "default"}


# ═══════════════════════════════════════════════════════════
# 模板同步到已有用户
# ═══════════════════════════════════════════════════════════

# All template files (including extended set)
ALL_TEMPLATE_FILES = ["SOUL.md", "MEMORY.md", "PROFILE.md", "AGENTS.md", "BOOTSTRAP.md", "HEARTBEAT.md"]


@router.post("/admin/templates/sync-to-users")
@require_permission("admin:admin")
async def sync_templates_to_users(
    request: Request,
    body: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """将全局模板同步到所有已有用户的智能体 workspace。

    Body params:
        strategy: "new_only" | "overwrite" — new_only 只复制新文件不覆盖已修改的，
                  overwrite 强制覆盖所有文件（会备份用户原文件）
        files: optional list of filenames to sync (default: all)
    """
    body = body or {}
    strategy = body.get("strategy", "new_only")
    files_to_sync = body.get("files") or ALL_TEMPLATE_FILES

    # Validate strategy
    if strategy not in ("new_only", "overwrite"):
        raise HTTPException(status_code=400, detail=f"不支持的策略: {strategy}")

    # Validate files
    for f in files_to_sync:
        if f not in ALL_TEMPLATE_FILES:
            raise HTTPException(status_code=400, detail=f"不支持的模板文件: {f}")

    from ....constant import WORKSPACES_DIR

    # Collect user workspace dirs
    user_dirs = []
    if WORKSPACES_DIR.exists():
        for entry in WORKSPACES_DIR.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                user_dirs.append(entry)

    # Also scan agents/ for user-owned agents (user:xxx agents)
    from ....constant import AGENTS_DIR
    agent_dirs = []
    if AGENTS_DIR.exists():
        for entry in AGENTS_DIR.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                agent_dirs.append(entry)

    synced_count = 0
    skipped_count = 0
    backup_count = 0
    errors: list[str] = []

    # Sync to workspaces/{username}/agents/{agent_id}/ structure
    for user_dir in user_dirs:
        agents_subdir = user_dir / "agents"
        if not agents_subdir.exists():
            continue
        for agent_dir in agents_subdir.iterdir():
            if not agent_dir.is_dir():
                continue
            for filename in files_to_sync:
                template_path = TEMPLATES_DIR / filename
                target_path = agent_dir / filename
                if not template_path.exists():
                    continue

                if strategy == "new_only" and target_path.exists():
                    skipped_count += 1
                    continue

                # Backup if overwriting existing file
                if strategy == "overwrite" and target_path.exists():
                    backup_dir = agent_dir / ".backups"
                    backup_dir.mkdir(exist_ok=True)
                    import shutil
                    backup_path = backup_dir / f"{filename}.{int(__import__('time').time())}.bak"
                    shutil.copy2(target_path, backup_path)
                    backup_count += 1

                import shutil
                shutil.copy2(template_path, target_path)
                synced_count += 1

    # Also sync to global agent workspaces (for consistency)
    for agent_dir in agent_dirs:
        agent_json = agent_dir / "agent.json"
        if not agent_json.exists():
            continue
        for filename in files_to_sync:
            template_path = TEMPLATES_DIR / filename
            target_path = agent_dir / filename
            if not template_path.exists():
                continue

            if strategy == "new_only" and target_path.exists():
                skipped_count += 1
                continue

            if strategy == "overwrite" and target_path.exists():
                backup_dir = agent_dir / ".backups"
                backup_dir.mkdir(exist_ok=True)
                import shutil
                backup_path = backup_dir / f"{filename}.{int(__import__('time').time())}.bak"
                shutil.copy2(target_path, backup_path)
                backup_count += 1

            import shutil
            shutil.copy2(template_path, target_path)
            synced_count += 1

    logger.info(
        f"Template sync complete: strategy={strategy}, synced={synced_count}, "
        f"skipped={skipped_count}, backups={backup_count}"
    )

    return {
        "success": True,
        "strategy": strategy,
        "synced": synced_count,
        "skipped": skipped_count,
        "backups": backup_count,
        "files": files_to_sync,
    }
