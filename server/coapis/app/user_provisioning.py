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

"""User provisioning - initializes a new user's complete workspace.

When a new user registers, this module ensures they get:
1. A dedicated workspace directory (workspaces/{username}/)
2. A default agent with agent.json config
3. Essential JSON files (jobs.json, skill.json)
4. Registration in config.json agents.profiles
5. User data directories (workspaces/{username}/agents, skills, workflows, chat, files, files/media)
6. Base template files (SOUL.md, MEMORY.md, PROFILE.md)

This creates an "independent user space" equivalent to the default agent's setup.
⚠️ CRITICAL: All user data MUST be in workspaces/{username}/. Never use data/{username}/.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from ..agents.templates import (
    DEFAULT_AGENT_TEMPLATE,
    build_agent_template,
)
from ..config.config import (
    AgentProfileConfig,
    UserProfileConfig,
    save_agent_config,
    save_user_config,
)
from ..config.utils import load_config, save_config
from ..constant import WORKING_DIR, WORKSPACES_DIR

logger = logging.getLogger(__name__)

# Default workspace JSON files
_WORKSPACE_JSON_DEFAULTS: list[tuple[str, dict]] = [
    # jobs.json 已移至 crons/jobs.json，由 CronManager 自动创建
    ("skill.json", {"version": 0, "schema_version": "workspace-skill-manifest.v1", "skills": {}}),
]


def init_user_workspace(username: str, display_name: Optional[str] = None, request: Any = None, language: str = "zh") -> str:
    """Initialize a complete workspace for a new user.

    Creates:
    1. Workspace directory: workspaces/{username}/
    2. User-level config.json (user identity and preferences)
    3. Agent config: workspaces/{username}/agent.json (based on DEFAULT_AGENT_TEMPLATE)
    4. Essential JSON files: jobs.json, skill.json
    5. User data directories: memory, agents, skills, chat, files, crons, backups
    6. Base template files: SOUL.md, PROFILE.md, AGENTS.md (copied from system templates)
    7. Registers agent in MultiAgentManager (if request provided) — critical for runtime visibility

    ⚠️ CRITICAL: All user data MUST be in workspaces/{username}/. Never use data/{username}/.
    ⚠️ CRITICAL: User workspace must be fully isolated — no shared chat history, no shared files.

    Args:
        username: The username to provision
        display_name: Optional display name for the agent
        request: Optional FastAPI Request for runtime registration with MultiAgentManager

    Returns:
        The agent_id for the user's default agent (e.g., "agent:20")
    """
    # Get user info for generating ASCII-safe agent_id
    from .user_system.service import get_user_by_username
    user = get_user_by_username(username)
    
    # Generate ASCII-safe internal agent_id
    internal_agent_id = f"agent:{user.id}" if user else f"agent:{username}"
    
    # Keep semantic ID for backward compatibility
    semantic_agent_id = f"user:{username}"
    agent_name = display_name or f"Default（{username}）"

    # 1. Create workspace directory (unified path: workspaces/{username}/)
    workspace_dir = WORKSPACES_DIR / username
    workspace_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Created workspace directory for {username}: {workspace_dir}")

    # 1b. Create user-level config.json (user identity and preferences)
    from datetime import datetime, timezone
    user_cfg = UserProfileConfig(
        username=username,
        display_name=display_name or "",
        default_agent_id=f"user:{username}",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    save_user_config(username, user_cfg)
    logger.info(f"Created config.json for {username}")

    # 2. Create essential JSON files (empty — no shared data!)
    _create_workspace_json_files(workspace_dir, username)

    # 3. Build and save agent config
    _create_agent_config(username, internal_agent_id, semantic_agent_id, agent_name, workspace_dir)

    # 3b. Register default agent in user's config.json agents registry
    from coapis.config.config import add_agent_to_registry
    add_agent_to_registry(
        username=username,
        agent_id=internal_agent_id,  # Use internal_agent_id for registry
        name=agent_name,
        description="默认智能体",
        workspace_dir="",
        is_default=True,
    )

    # 4. Create ALL user data directories (isolated per user)
    # v0.5.1: Simplified structure — no evolution/ directory.
    # Evolution data is centralized in system/evolution/.
    for subdir in ["memory", "agents", "skills", "chat", "files", "files/media", "crons", "backups"]:
        dir_path = workspace_dir / subdir
        dir_path.mkdir(parents=True, exist_ok=True)

    # 4b. Create MEMORY.md for user's default agent (language-aware)
    memory_md = workspace_dir / "MEMORY.md"
    if not memory_md.exists():
        from ..system.data_loader import load_memory_init
        memory_content = load_memory_init(language=language, username=username)
        memory_md.write_text(memory_content, encoding="utf-8")
    logger.info(f"User data directories created for {username}")

    # 5. Copy user-level templates (SOUL.md, PROFILE.md, AGENTS.md, etc.)
    _copy_base_templates(workspace_dir, username, level="user", language=language)

    # 6. Register agent in MultiAgentManager (if request provided) — critical for runtime visibility
    if request is not None:
        _register_with_multi_agent_manager(request, internal_agent_id, username, workspace_dir)

    logger.info(f"User workspace initialized for {username} (agent: {internal_agent_id})")
    return internal_agent_id


def _register_with_multi_agent_manager(request: Any, agent_id: str, username: str, workspace_dir: Path) -> None:
    """Register a newly created user agent with the running MultiAgentManager.

    This ensures the agent is visible in list_agents immediately after user creation,
    without requiring a server restart.

    Args:
        request: FastAPI Request object
        agent_id: Agent ID (e.g., "user:admin")
        username: Owner username
        workspace_dir: Workspace directory path
    """
    import asyncio

    # Get MultiAgentManager from app.state
    manager = None
    try:
        app = getattr(request, "app", None)
        if app is None:
            # Try from request.scope
            app = request.scope.get("app")
        if app is not None:
            manager = getattr(getattr(app, "state", None), "multi_agent_manager", None)
    except Exception as e:
        logger.warning(f"Failed to get MultiAgentManager from request: {e}")

    if manager is None:
        logger.warning(f"Cannot register agent {agent_id} with MultiAgentManager: not initialized")
        return

    # Load agent config from disk
    from ..config.config import load_agent_config
    try:
        agent_config = load_agent_config(agent_id)
        config_dict = agent_config.model_dump() if hasattr(agent_config, "model_dump") else agent_config.dict()
    except Exception as e:
        logger.error(f"Failed to load agent config for {agent_id}: {e}")
        return

    # Register with MultiAgentManager (async — schedule for next event loop iteration)
    async def _do_register():
        try:
            await manager.create_agent(
                agent_id=agent_id,
                config=config_dict,
                username=username,
                is_global=False,  # User agent — not shared
            )
            logger.info(f"Registered agent {agent_id} with MultiAgentManager (user: {username})")

            # ✅ 创建用户后立即启动智能体（如果有启用的外部渠道）
            # 只检查外部渠道（wecom, discord, telegram 等），不包括 console（被动渠道）
            external_channels = ["wecom", "discord", "telegram", "dingtalk", "feishu", "qq", "mattermost", "matrix", "xiaoyi", "weixin", "onebot"]
            channels = config_dict.get("channels", {})
            has_enabled_channels = any(
                ch_name in external_channels and ch_cfg.get("enabled", False)
                for ch_name, ch_cfg in channels.items()
                if isinstance(ch_cfg, dict)
            )

            if has_enabled_channels:
                logger.info(f"Starting agent {agent_id} (has enabled channels)")
                try:
                    await manager.get_agent(agent_id, username=username)
                    logger.info(f"✓ Agent {agent_id} started successfully")
                except Exception as e:
                    logger.error(f"✗ Failed to start agent {agent_id}: {e}")
        except Exception as e:
            logger.error(f"Failed to register agent {agent_id} with MultiAgentManager: {e}")

    # Schedule async registration — don't block user creation
    asyncio.ensure_future(_do_register())


def _create_workspace_json_files(workspace_dir: Path, username: str) -> None:
    """Create essential JSON files in user's workspace."""
    for filename, default in _WORKSPACE_JSON_DEFAULTS:
        filepath = workspace_dir / filename
        if not filepath.exists():
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
            logger.debug(f"Created {filename} for user {username}")


def _create_agent_config(
    username: str,
    internal_agent_id: str,
    semantic_agent_id: str,
    agent_name: str,
    workspace_dir: Path,
) -> None:
    """Create agent.json for user's default agent.
    
    Args:
        username: Username (may contain non-ASCII)
        internal_agent_id: ASCII-safe internal ID (e.g., "agent:20")
        semantic_agent_id: Semantic ID for display (e.g., "user:张三")
        agent_name: Display name
        workspace_dir: Workspace directory path
    """
    config = load_config()
    fallback_language = config.agents.language or "zh"

    template_result = build_agent_template(
        DEFAULT_AGENT_TEMPLATE,
        name=agent_name,
        agent_id=internal_agent_id,
        semantic_agent_id=semantic_agent_id,
        workspace_dir=workspace_dir,
        fallback_language=fallback_language,
        description=f"Default agent for user {username}",
    )

    # Set owner field — critical for ownership-based permission checks
    template_result.agent_config.owner = username

    # Save agent.json (pass workspace_dir for dynamic agent support)
    save_agent_config(internal_agent_id, template_result.agent_config, workspace_dir=workspace_dir)
    logger.info(f"Created agent.json for {username} (agent_id: {internal_agent_id}, owner: {username})")


def ensure_user_workspace_exists(username: str) -> bool:
    """Check and initialize user workspace if it doesn't exist.

    Args:
        username: The username to check

    Returns:
        True if workspace was created, False if it already existed
    """
    workspace_dir = Path(f"{WORKING_DIR}/workspaces/{username}")
    agent_json = workspace_dir / "agent.json"

    if agent_json.exists():
        logger.debug(f"User workspace already exists for {username}")
        return False

    logger.info(f"Initializing missing workspace for existing user {username}")
    init_user_workspace(username)
    return True


def _copy_base_templates(workspace_dir: Path, username: str, level: str = "user", language: str = "zh") -> None:
    """Copy template files to workspace from the appropriate layer.

    Template resolution order (language-aware):
    1. data/packs/{lang}/templates/{level}/{filename} — language + layer specific
    2. data/packs/zh/templates/{level}/{filename} — Chinese fallback
    3. data/packs/base/... — base fallback
    4. Inline fallback — minimal default

    Args:
        workspace_dir: Target workspace directory
        username: Username (for logging)
        level: Template layer — "user" for default agent, "agent" for sub-agent
        language: Language code (e.g., "zh", "en")
    """
    from ..system.data_loader import load_pack_template

    # Files to copy for each level
    if level == "agent":
        files_to_copy = ("SOUL.md", "PROFILE.md", "AGENTS.md", "MEMORY.md")
    else:
        files_to_copy = ("SOUL.md", "PROFILE.md", "AGENTS.md", "MEMORY.md", "BOOTSTRAP.md", "HEARTBEAT.md")

    # Inline fallback templates (last resort)
    _FALLBACK_TEMPLATES = {
        "SOUL.md": "# Agent Soul\n\n## Core Principles\n\n**Help genuinely.** Just help.\n",
        "PROFILE.md": "## Identity\n\n- **Name:** \n- **Role:** AI Assistant\n",
        "AGENTS.md": "# AGENTS.md\n\n## Security\n\n- Never leak private data.\n",
        "MEMORY.md": f"# {username}'s Memory\n\n> Auto-created during initialization.\n",
    }

    for filename in files_to_copy:
        file_path = workspace_dir / filename
        if file_path.exists():
            logger.debug(f"{filename} already exists for {username}")
            continue

        # Load from data packs (language-aware, with fallback chain)
        content = load_pack_template(filename, level=level, language=language)
        if content:
            source = f"data_pack({language})"
        else:
            content = _FALLBACK_TEMPLATES.get(filename, f"# {filename}\n")
            source = "inline fallback"
            logger.warning(f"Template {filename} not found in data packs, using fallback")

        # Replace {username} placeholder in MEMORY.md
        if filename == "MEMORY.md" and "{username}" in content:
            content = content.replace("{username}", username)

        file_path.write_text(content, encoding="utf-8")
        logger.info(f"Created {filename} for {username} (from {source})")


def get_user_workspace_dir(username: str) -> Path:
    """Get user's workspace directory.

    Args:
        username: The username

    Returns:
        Path to user's workspace directory
    """
    return WORKSPACES_DIR / username


def get_user_agent_id(username: str) -> str:
    """Get user's default agent ID.

    Args:
        username: The username

    Returns:
        Agent ID (e.g., "user:admin")
    """
    return f"user:{username}"
