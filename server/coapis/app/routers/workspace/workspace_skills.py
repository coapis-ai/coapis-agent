# -*- coding: utf-8 -*-
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

"""Workspace Skills router - user-level skill management.

每个用户可以安装、配置、卸载自己的技能。
"""
from __future__ import annotations

import logging
import json
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel

from ....constant import DATA_DIR
from ....app.user_store import get_user_skills_dir

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workspace/skills"])


# ── Pydantic models ─────────────────────────────────────────────────────

class SkillInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    installed: bool = False
    config: Dict[str, Any] = {}


class InstallSkillRequest(BaseModel):
    skill_id: str
    config: Dict[str, Any] = {}


class UpdateSkillConfigRequest(BaseModel):
    config: Dict[str, Any]


# ── Helper functions ─────────────────────────────────────────────────────

def _get_username(request: Request) -> str:
    """获取当前用户名."""
    username = getattr(request.state, "username", "anonymous")
    if username == "anonymous":
        raise HTTPException(status_code=401, detail="需要登录")
    return username


def _get_skill_pool() -> List[SkillInfo]:
    """从技能池获取可用技能列表."""
    from ....agents.skills_manager import SkillPoolService
    try:
        pool = SkillPoolService()
        skills = []
        for skill_id, skill_data in pool.list_available().items():
            skills.append(SkillInfo(
                id=skill_id,
                name=skill_data.get("name", skill_id),
                description=skill_data.get("description", ""),
                version=skill_data.get("version", "1.0.0"),
                installed=False,
            ))
        return skills
    except Exception:
        return []


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/workspace/skills")
async def list_my_skills(request: Request) -> Dict[str, Any]:
    """列出当前用户已安装的技能."""
    username = _get_username(request)
    skills_dir = get_user_skills_dir(username)
    
    installed_skills = []
    if skills_dir.exists():
        for skill_folder in skills_dir.iterdir():
            if skill_folder.is_dir():
                skill_file = skill_folder / "skill.json"
                if skill_file.exists():
                    with open(skill_file, "r") as f:
                        data = json.load(f)
                        installed_skills.append(SkillInfo(
                            id=data.get("id", skill_folder.name),
                            name=data.get("name", skill_folder.name),
                            description=data.get("description", ""),
                            version=data.get("version", "1.0.0"),
                            installed=True,
                            config=data.get("config", {}),
                        ))
    
    return {
        "username": username,
        "skills": [s.model_dump() for s in installed_skills],
        "total": len(installed_skills),
    }


@router.post("/workspace/skills/install")
async def install_skill(
    request: Request,
    payload: InstallSkillRequest = Body(...),
) -> Dict[str, Any]:
    """安装技能."""
    username = _get_username(request)
    
    # 从技能池获取技能信息
    pool_skills = _get_skill_pool()
    target = None
    for s in pool_skills:
        if s.id == payload.skill_id:
            target = s
            break
    
    if not target:
        raise HTTPException(status_code=404, detail=f"技能 {payload.skill_id} 不存在")
    
    skills_dir = get_user_skills_dir(username)
    skills_dir.mkdir(parents=True, exist_ok=True)
    
    skill_dir = skills_dir / payload.skill_id
    if skill_dir.exists():
        raise HTTPException(status_code=409, detail=f"技能 {payload.skill_id} 已安装")
    
    # 创建技能目录和配置文件
    skill_dir.mkdir(parents=True, exist_ok=True)
    
    skill_data = {
        "id": payload.skill_id,
        "name": target.name,
        "description": target.description,
        "version": target.version,
        "config": payload.config,
    }
    
    skill_file = skill_dir / "skill.json"
    with open(skill_file, "w") as f:
        json.dump(skill_data, f, indent=2, ensure_ascii=False)
    
    # Record audit log
    from ....user_system.database import UserSystemDB
    db = UserSystemDB()
    user = db.get_user_by_username(username)
    if user:
        db.insert_audit_log(
            user_id=user["id"],
            username=username,
            action="install_skill",
            resource_type="skill",
            resource_id=payload.skill_id,
        )
    
    return {
        "success": True,
        "skill": skill_data,
    }


@router.get("/workspace/skills/{skill_id}")
async def get_skill(
    request: Request,
    skill_id: str,
) -> Dict[str, Any]:
    """获取技能详情."""
    username = _get_username(request)
    skills_dir = get_user_skills_dir(username)
    
    skill_dir = skills_dir / skill_id
    skill_file = skill_dir / "skill.json"
    
    if not skill_file.exists():
        # 检查技能池
        pool_skills = _get_skill_pool()
        for s in pool_skills:
            if s.id == skill_id:
                return s.model_dump()
        
        raise HTTPException(status_code=404, detail=f"技能 {skill_id} 不存在")
    
    with open(skill_file, "r") as f:
        data = json.load(f)
    
    return data


@router.put("/workspace/skills/{skill_id}")
async def update_skill_config(
    request: Request,
    skill_id: str,
    payload: UpdateSkillConfigRequest = Body(...),
) -> Dict[str, Any]:
    """更新技能配置."""
    username = _get_username(request)
    skills_dir = get_user_skills_dir(username)
    
    skill_dir = skills_dir / skill_id
    skill_file = skill_dir / "skill.json"
    
    if not skill_file.exists():
        raise HTTPException(status_code=404, detail=f"技能 {skill_id} 未安装")
    
    with open(skill_file, "r") as f:
        data = json.load(f)
    
    data["config"] = payload.config
    
    with open(skill_file, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return {
        "success": True,
        "skill": data,
    }


@router.delete("/workspace/skills/{skill_id}")
async def uninstall_skill(
    request: Request,
    skill_id: str,
) -> Dict[str, Any]:
    """卸载技能."""
    username = _get_username(request)
    skills_dir = get_user_skills_dir(username)
    
    skill_dir = skills_dir / skill_id
    if not skill_dir.exists():
        raise HTTPException(status_code=404, detail=f"技能 {skill_id} 未安装")
    
    shutil.rmtree(skill_dir)
    
    # Record audit log
    from ....user_system.database import UserSystemDB
    db = UserSystemDB()
    user = db.get_user_by_username(username)
    if user:
        db.insert_audit_log(
            user_id=user["id"],
            username=username,
            action="uninstall_skill",
            resource_type="skill",
            resource_id=skill_id,
        )
    
    return {
        "success": True,
        "skill_id": skill_id,
    }


@router.get("/workspace/skills/pool")
async def get_skill_pool(request: Request) -> Dict[str, Any]:
    """获取技能池（可用技能列表）."""
    username = _get_username(request)
    
    pool_skills = _get_skill_pool()
    
    # 标记已安装的技能
    skills_dir = get_user_skills_dir(username)
    installed_ids = set()
    if skills_dir.exists():
        for skill_folder in skills_dir.iterdir():
            if skill_folder.is_dir():
                installed_ids.add(skill_folder.name)
    
    for s in pool_skills:
        s.installed = s.id in installed_ids
    
    return {
        "skills": [s.model_dump() for s in pool_skills],
        "total": len(pool_skills),
    }
