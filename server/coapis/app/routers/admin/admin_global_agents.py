# -*- coding: utf-8 -*-
"""
全局智能体管理 API — 管理 /agents/ 目录下的全局智能体

高频操作，通过 Admin 页面管理。
支持：身份文件编辑、技能管理、配置管理
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request

from ....constant import AGENTS_DIR, SKILLS_DIR, TEMPLATES_DIR, WORKING_DIR
from ...permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/admin/global-agents")
@require_permission("admin:admin")
async def list_global_agents(request: Request) -> Dict[str, Any]:
    """获取所有全局智能体列表及状态"""
    agents = []
    if not AGENTS_DIR.exists():
        return {"agents": [], "agents_dir": str(AGENTS_DIR)}

    for agent_dir in AGENTS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue

        agent_id = agent_dir.name
        # 跳过用户智能体（user: 前缀），它们不应出现在全局列表中
        if agent_id.startswith("user:"):
            continue
        agent_info = {
            "id": agent_id,
            "path": str(agent_dir),
            "has_agent_json": (agent_dir / "agent.json").exists(),
            "has_soul": (agent_dir / "SOUL.md").exists(),
            "has_profile": (agent_dir / "PROFILE.md").exists(),
            "has_skills": (agent_dir / "skills").exists(),
        }

        # 读取 agent.json 获取详细信息
        agent_json_path = agent_dir / "agent.json"
        if agent_json_path.exists():
            try:
                with open(agent_json_path, encoding="utf-8") as f:
                    agent_config = json.load(f)
                agent_info["name"] = agent_config.get("name", agent_id)
                agent_info["description"] = agent_config.get("description", "")
                agent_info["enabled"] = agent_config.get("enabled", True)
                agent_info["role"] = agent_config.get("role", "template")
                agent_info["priority"] = agent_config.get("priority", 100)
            except Exception as e:
                logger.warning(f"Failed to read agent.json for {agent_id}: {e}")
                agent_info["name"] = agent_id
                agent_info["error"] = str(e)

        agents.append(agent_info)

    return {"agents": agents, "agents_dir": str(AGENTS_DIR)}


@router.get("/admin/global-agents/{agent_id}")
@require_permission("admin:admin")
async def get_global_agent(request: Request, agent_id: str) -> Dict[str, Any]:
    """获取指定全局智能体的详细信息"""
    agent_dir = AGENTS_DIR / agent_id
    if not agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"全局智能体不存在: {agent_id}")

    result = {"id": agent_id, "path": str(agent_dir)}

    # 读取 agent.json
    agent_json_path = agent_dir / "agent.json"
    if agent_json_path.exists():
        with open(agent_json_path, encoding="utf-8") as f:
            result["agent_json"] = json.load(f)

    # 读取身份文件
    for filename in ["SOUL.md", "PROFILE.md", "AGENTS.md", "BOOTSTRAP.md", "HEARTBEAT.md"]:
        file_path = agent_dir / filename
        if file_path.exists():
            result[filename.lower().replace(".md", "")] = file_path.read_text(encoding="utf-8")

    # 读取 agent.json 中的实际 enabled 状态
    agent_json_path = agent_dir / "agent.json"
    if agent_json_path.exists():
        with open(agent_json_path, encoding="utf-8") as f:
            agent_config = json.load(f)
        result["enabled"] = agent_config.get("enabled", True)
    else:
        result["enabled"] = True

    return result


@router.put("/admin/global-agents/{agent_id}")
@require_permission("admin:admin")
async def update_global_agent(
    request: Request,
    agent_id: str,
    body: Dict[str, Any],
) -> Dict[str, Any]:
    """更新指定全局智能体的配置"""
    agent_dir = AGENTS_DIR / agent_id
    if not agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"全局智能体不存在: {agent_id}")

    # 更新 agent.json
    if "agent_json" in body:
        agent_json_path = agent_dir / "agent.json"
        if agent_json_path.exists():
            with open(agent_json_path, encoding="utf-8") as f:
                current = json.load(f)
            current.update(body["agent_json"])
            with open(agent_json_path, "w", encoding="utf-8") as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
            logger.info(f"Updated agent.json for {agent_id}")

    # 更新身份文件
    for key, filename in [("soul", "SOUL.md"), ("profile", "PROFILE.md"), ("agents", "AGENTS.md"), ("bootstrap", "BOOTSTRAP.md"), ("heartbeat", "HEARTBEAT.md")]:
        if key in body:
            file_path = agent_dir / filename
            file_path.write_text(body[key], encoding="utf-8")
            logger.info(f"Updated {filename} for {agent_id}")

    return {"success": True, "agent_id": agent_id}


@router.post("/admin/global-agents/{agent_id}/init-identity")
@require_permission("admin:admin")
async def init_global_agent_identity(
    request: Request,
    agent_id: str,
) -> Dict[str, Any]:
    """为全局智能体初始化身份文件（从全局模板继承）"""
    agent_dir = AGENTS_DIR / agent_id
    if not agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"全局智能体不存在: {agent_id}")

    created = []
    for filename in ["SOUL.md", "PROFILE.md"]:
        file_path = agent_dir / filename
        template_path = TEMPLATES_DIR / filename

        if not file_path.exists() and template_path.exists():
            content = template_path.read_text(encoding="utf-8")
            file_path.write_text(content, encoding="utf-8")
            created.append(filename)
            logger.info(f"Created {filename} for {agent_id} from global template")

    return {"success": True, "agent_id": agent_id, "created": created}


@router.get("/admin/global-agents/{agent_id}/skills")
@require_permission("admin:admin")
async def list_global_agent_skills(request: Request, agent_id: str) -> Dict[str, Any]:
    """获取全局智能体的已安装技能列表"""
    agent_dir = AGENTS_DIR / agent_id
    if not agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"全局智能体不存在: {agent_id}")

    skills = []
    skill_json_path = agent_dir / "skill.json"
    if skill_json_path.exists():
        try:
            with open(skill_json_path, encoding="utf-8") as f:
                skill_data = json.load(f)
            
            skills_data = skill_data.get("skills", {})
            for skill_name, skill_info in skills_data.items():
                skills.append({
                    "name": skill_name,
                    "enabled": skill_info.get("enabled", True),
                    "source": skill_info.get("source", "unknown"),
                    "description": skill_info.get("metadata", {}).get("description", ""),
                    "version": skill_info.get("metadata", {}).get("version_text", ""),
                    "has_skill_md": (agent_dir / "skills" / skill_name / "SKILL.md").exists(),
                })
        except Exception as e:
            logger.warning(f"Failed to read skill.json for {agent_id}: {e}")

    return {"skills": skills, "agent_id": agent_id}


@router.post("/admin/global-agents/{agent_id}/skills/install")
@require_permission("admin:admin")
async def install_skill_to_global_agent(
    request: Request,
    agent_id: str,
) -> Dict[str, Any]:
    """安装技能到全局智能体（从全局技能池复制）"""
    username = getattr(request.state, "username", None)

    body: Dict[str, Any] = await request.json()
    skill_name = body.get("skill_name")
    if not skill_name:
        raise HTTPException(status_code=400, detail="缺少 skill_name")

    agent_dir = AGENTS_DIR / agent_id
    if not agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"全局智能体不存在: {agent_id}")

    # 源技能路径（全局技能池）
    source_skill = SKILLS_DIR / skill_name
    if not source_skill.exists():
        raise HTTPException(status_code=404, detail=f"技能池中不存在技能: {skill_name}")

    # 目标技能路径
    target_skill = agent_dir / "skills" / skill_name
    if target_skill.exists():
        raise HTTPException(status_code=409, detail=f"技能已存在: {skill_name}")

    # 复制技能目录
    shutil.copytree(source_skill, target_skill)
    logger.info(f"Installed skill '{skill_name}' to global agent '{agent_id}'")

    # 更新 skill.json
    skill_json_path = agent_dir / "skill.json"
    skill_data = {}
    if skill_json_path.exists():
        try:
            with open(skill_json_path, encoding="utf-8") as f:
                skill_data = json.load(f)
        except Exception:
            skill_data = {"schema_version": "workspace-skill-manifest.v1", "version": 0, "skills": {}}

    # 读取源技能的 SKILL.md 获取元数据
    skill_md = source_skill / "SKILL.md"
    description = ""
    if skill_md.exists():
        first_line = skill_md.read_text(encoding="utf-8").strip().split("\n")[0]
        description = first_line.lstrip("# ").strip() or ""

    skill_data["skills"][skill_name] = {
        "enabled": True,
        "channels": ["all"],
        "source": "builtin",
        "config": {},
        "metadata": {
            "name": skill_name,
            "description": description,
            "version_text": "1.0",
            "commit_text": "",
            "source": "builtin",
            "protected": False,
        },
        "requirements": {
            "require_bins": [],
            "require_envs": [],
        },
    }

    with open(skill_json_path, "w", encoding="utf-8") as f:
        json.dump(skill_data, f, ensure_ascii=False, indent=2)

    return {"success": True, "agent_id": agent_id, "skill_name": skill_name}


@router.post("/admin/global-agents/{agent_id}/skills/uninstall")
@require_permission("admin:admin")
async def uninstall_skill_from_global_agent(
    request: Request,
    agent_id: str,
) -> Dict[str, Any]:
    """从全局智能体卸载技能"""
    body: Dict[str, Any] = await request.json()
    skill_name = body.get("skill_name")
    if not skill_name:
        raise HTTPException(status_code=400, detail="缺少 skill_name")

    agent_dir = AGENTS_DIR / agent_id
    if not agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"全局智能体不存在: {agent_id}")

    target_skill = agent_dir / "skills" / skill_name
    if not target_skill.exists():
        raise HTTPException(status_code=404, detail=f"技能不存在: {skill_name}")

    # 删除技能目录
    shutil.rmtree(target_skill)
    logger.info(f"Uninstalled skill '{skill_name}' from global agent '{agent_id}'")

    # 更新 skill.json
    skill_json_path = agent_dir / "skill.json"
    if skill_json_path.exists():
        try:
            with open(skill_json_path, encoding="utf-8") as f:
                skill_data = json.load(f)
            skill_data["skills"].pop(skill_name, None)
            with open(skill_json_path, "w", encoding="utf-8") as f:
                json.dump(skill_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to update skill.json for {agent_id}: {e}")

    return {"success": True, "agent_id": agent_id, "skill_name": skill_name}


@router.put("/admin/global-agents/{agent_id}/skills/{skill_name}/toggle")
@require_permission("admin:admin")
async def toggle_global_agent_skill(
    request: Request,
    agent_id: str,
    skill_name: str,
) -> Dict[str, Any]:
    """切换全局智能体技能的启用/禁用状态"""
    body: Dict[str, Any] = await request.json()
    enabled = body.get("enabled")
    if enabled is None:
        raise HTTPException(status_code=400, detail="缺少 enabled 字段")

    agent_dir = AGENTS_DIR / agent_id
    if not agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"全局智能体不存在: {agent_id}")

    skill_json_path = agent_dir / "skill.json"
    if not skill_json_path.exists():
        raise HTTPException(status_code=404, detail=f"skill.json 不存在")

    try:
        with open(skill_json_path, encoding="utf-8") as f:
            skill_data = json.load(f)
        
        if skill_name not in skill_data.get("skills", {}):
            raise HTTPException(status_code=404, detail=f"技能不存在: {skill_name}")
        
        skill_data["skills"][skill_name]["enabled"] = enabled
        with open(skill_json_path, "w", encoding="utf-8") as f:
            json.dump(skill_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Toggled skill '{skill_name}' to {'enabled' if enabled else 'disabled'} for agent '{agent_id}'")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新技能状态失败: {e}")

    return {"success": True, "agent_id": agent_id, "skill_name": skill_name, "enabled": enabled}


@router.get("/admin/skills/pool")
@require_permission("admin:admin")
async def list_skills_pool(request: Request) -> Dict[str, Any]:
    """获取全局技能池中的可用技能列表"""
    skills = []
    if not SKILLS_DIR.exists():
        return {"skills": [], "skills_dir": str(SKILLS_DIR)}

    for skill_dir in SKILLS_DIR.iterdir():
        if not skill_dir.is_dir():
            continue

        skill_name = skill_dir.name
        if skill_name.startswith('.'):
            continue

        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        skills.append(skill_name)

    skills.sort()
    return {"skills": skills, "skills_dir": str(SKILLS_DIR)}


# ═══════════════════════════════════════════════════════════
# CRUD: Create / Delete / Toggle
# ═══════════════════════════════════════════════════════════

# Protected agent IDs that cannot be deleted or toggled
_PROTECTED_AGENTS: frozenset[str] = frozenset({"global_default", "global_qa_agent"})


@router.post("/admin/global-agents")
@require_permission("admin:admin")
async def create_global_agent(
    request: Request,
    body: Dict[str, Any],
) -> Dict[str, Any]:
    """创建新的全局智能体。

    body 字段:
      - id:        智能体 ID（必填，用作目录名）
      - name:      显示名称（默认同 id）
      - description: 描述（可选）
      - role:      角色 — template / service / hybrid（默认 template）
      - priority:  优先级，数字越小越优先（默认 100）
    """
    import re, uuid as _uuid

    agent_id = body.get("id", "").strip()
    if not agent_id:
        agent_id = f"global_{_uuid.uuid4().hex[:6]}"

    # 安全校验：ID 必须为 ASCII（字母、数字、短横线、下划线、冒号、点）
    if not re.match(r'^[a-zA-Z0-9_:.\-]+$', agent_id):
        raise HTTPException(
            status_code=400,
            detail=f"Agent ID must be ASCII-only (letters, digits, _ - : .), got: {agent_id!r}",
        )
    if agent_id.startswith("user:"):
        raise HTTPException(status_code=400, detail="id 不能以 user: 开头")

    agent_dir = AGENTS_DIR / agent_id
    if agent_dir.exists():
        raise HTTPException(status_code=409, detail=f"全局智能体已存在: {agent_id}")

    # 创建目录
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "data").mkdir(exist_ok=True)
    (agent_dir / "skills").mkdir(exist_ok=True)

    # 构建 agent.json
    agent_config: Dict[str, Any] = {
        "id": agent_id,
        "name": body.get("name", agent_id),
        "description": body.get("description", ""),
        "enabled": True,
        "workspace_dir": str(agent_dir),
        "role": body.get("role", "template"),
        "priority": body.get("priority", 100),
    }
    agent_json_path = agent_dir / "agent.json"
    with open(agent_json_path, "w", encoding="utf-8") as f:
        json.dump(agent_config, f, ensure_ascii=False, indent=2)
    logger.info(f"Created global agent '{agent_id}' ({agent_config['role']})")

    # 从全局模板继承身份文件
    inherited: list[str] = []
    for filename in ["SOUL.md", "PROFILE.md"]:
        template_path = TEMPLATES_DIR / filename
        if template_path.exists():
            dest = agent_dir / filename
            if not dest.exists():
                shutil.copy2(template_path, dest)
                inherited.append(filename)

    # 注册到 config.json（username=None 表示全局）
    from ....config.utils import load_config, save_config
    from ....config.config import AgentProfileRef

    config = load_config()
    if agent_id not in config.agents.profiles:
        config.agents.profiles[agent_id] = AgentProfileRef(
            id=agent_id,
            workspace_dir=str(agent_dir),
        )
        save_config(config)

    return {
        "success": True,
        "agent_id": agent_id,
        "role": agent_config["role"],
        "inherited_files": inherited,
    }


@router.delete("/admin/global-agents/{agent_id}")
@require_permission("admin:admin")
async def delete_global_agent(
    request: Request,
    agent_id: str,
    body: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """删除全局智能体。

    受保护的智能体（global_default、global_qa_agent）不可删除。
    删除前会备份到 system/backups/global_agents/ 目录。
    """
    if agent_id in _PROTECTED_AGENTS:
        raise HTTPException(status_code=400, detail=f"受保护的全局智能体不可删除: {agent_id}")

    agent_dir = AGENTS_DIR / agent_id
    if not agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"全局智能体不存在: {agent_id}")

    # 备份
    from ....constant import SYSTEM_DIR
    backup_dir = SYSTEM_DIR / "backups" / "global_agents"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_dest = backup_dir / f"{agent_id}"
    if backup_dest.exists():
        shutil.rmtree(backup_dest)
    shutil.copytree(agent_dir, backup_dest)
    logger.info(f"Backed up global agent '{agent_id}' to {backup_dest}")

    # 删除目录
    shutil.rmtree(agent_dir)

    # 从 config.json 移除
    from ....config.utils import load_config, save_config
    config = load_config()
    if agent_id in config.agents.profiles:
        del config.agents.profiles[agent_id]
        save_config(config)

    # 尝试从 MultiAgentManager 注销
    try:
        manager = getattr(request.app.state, "multi_agent_manager", None)
        if manager:
            await manager.destroy_agent(agent_id)
    except Exception as e:
        logger.warning(f"Failed to unregister agent from MultiAgentManager: {e}")

    logger.info(f"Deleted global agent '{agent_id}' (backup at {backup_dest})")
    return {"success": True, "agent_id": agent_id, "backup_path": str(backup_dest)}


@router.post("/admin/global-agents/{agent_id}/toggle")
@require_permission("admin:admin")
async def toggle_global_agent(
    request: Request,
    agent_id: str,
    body: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """切换全局智能体的启用/禁用状态。

    不需要传 body，默认切换当前状态；也可传 {"enabled": true/false} 指定目标状态。
    """
    if agent_id in _PROTECTED_AGENTS:
        raise HTTPException(status_code=400, detail=f"受保护的全局智能体不可禁用: {agent_id}")

    agent_dir = AGENTS_DIR / agent_id
    if not agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"全局智能体不存在: {agent_id}")

    agent_json_path = agent_dir / "agent.json"
    if not agent_json_path.exists():
        raise HTTPException(status_code=404, detail=f"agent.json 不存在: {agent_id}")

    with open(agent_json_path, encoding="utf-8") as f:
        config_data = json.load(f)

    current = config_data.get("enabled", True)
    body = body or {}
    new_state = body.get("enabled", not current)
    config_data["enabled"] = bool(new_state)

    with open(agent_json_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)

    logger.info(f"Toggled global agent '{agent_id}': {current} -> {new_state}")
    return {
        "success": True,
        "agent_id": agent_id,
        "enabled": bool(new_state),
    }
