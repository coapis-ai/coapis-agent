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

"""Agent workspace - isolated environment for each agent.

Each workspace has its own:
- Agent core (prompt builder, LLM client)
- Memory system
- Context compressor
- Growth system
- Skill manager
- Tool registry
- Data directory

Supports:
- Global workspaces (system-level, shared by all users)
- User workspaces (user-level, isolated per user)
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from ..constant import AGENTS_DIR, DATA_DIR, SKILLS_DIR, WORKSPACES_DIR

logger = logging.getLogger(__name__)

# Mapping of internal tool names to user-friendly Chinese status labels
_TOOL_FRIENDLY_NAMES: Dict[str, str] = {
    "web_search": "搜索网页",
    "web_extract": "提取网页内容",
    "execute_shell_command": "执行命令",
    "browser_use": "浏览器操作",
    "read_file": "读取文件",
    "write_file": "写入文件",
    "edit_file": "编辑文件",
    "grep_search": "搜索文件内容",
    "glob_search": "查找文件",
    "list_directory": "浏览目录",
    "memory_search": "搜索记忆",
    "list_agents": "查询智能体",
    "chat_with_agent": "与其他智能体通信",
    "get_current_time": "获取时间",
}


def _get_user_workspace_dir(username: str) -> Path:
    """Get user's workspace directory (unified user data path).
    
    Returns: workspaces/{username}/
    """
    return WORKSPACES_DIR / username


def _get_user_agents_dir(username: str) -> Path:
    """Get user's agents directory."""
    return _get_user_workspace_dir(username) / "agents"


def _get_user_skills_dir(username: str) -> Path:
    """Get user's skills directory."""
    return _get_user_workspace_dir(username) / "skills"

from .core import AgentCore
from .memory_manager import MemoryManager
from .context_compressor import ContextCompressor
from .growth import GrowthSystem
from ..skills.manager import SkillManager
from ..tools.registry import ToolRegistry, ToolInfo
from ..foundation import FoundationManager
from ..evolution import EvolutionEngine


class ChatContext:
    """Chat context for a single conversation session."""

    def __init__(self, chat_id: str, username: str = None):
        self.chat_id = chat_id
        self.username = username
        self.messages: List[Dict[str, Any]] = []
        self.created_at = 0.0

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})

    def get_messages(self) -> List[Dict[str, Any]]:
        """Get all messages in this chat context."""
        return self.messages

    def clear_messages(self):
        """Clear all messages (used by /clear command)."""
        self.messages = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "username": self.username,
            "messages": self.messages,
            "created_at": self.created_at,
        }


class Workspace:
    """Isolated workspace for a single agent with user support."""

    def __init__(self, agent_id: str, username: str = None, is_global: bool = True, workspace_dir: Path = None, role: str = None):
        self.agent_id = agent_id
        self.username = username
        self.is_global = is_global
        self.role = role
        self.status = "stopped"
        self.config: Optional[Dict[str, Any]] = None
        # Last streaming reasoning/response for persistence
        self.last_full_reasoning: list[str] = []
        self.last_full_response: list[str] = []

        # Determine directories based on scope
        if workspace_dir:
            # Explicit workspace_dir provided (e.g. from config)
            self.workspace_dir = workspace_dir
            if username and not is_global:
                # User agents: store runtime data inside workspace, not in system/
                self.data_dir = workspace_dir
                self.skills_dir = self.data_dir / "skills"
            else:
                # Global agents: runtime data in agents/{id}/data/, never in system/
                self.data_dir = AGENTS_DIR / agent_id / "data"
                self.skills_dir = AGENTS_DIR / agent_id / "skills"
        elif username and not is_global:
            # User-level workspace (unified under workspaces/{username}/)
            user_workspace = _get_user_workspace_dir(username)
            self.data_dir = user_workspace / "agents" / agent_id
            self.workspace_dir = _get_user_agents_dir(username) / agent_id
            self.skills_dir = _get_user_skills_dir(username) / agent_id
        else:
            # Global workspace: runtime data in agents/{id}/data/, never in system/
            self.data_dir = AGENTS_DIR / agent_id / "data"
            self.workspace_dir = AGENTS_DIR / agent_id
            self.skills_dir = AGENTS_DIR / agent_id / "skills"

        for d in [self.data_dir, self.workspace_dir, self.skills_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Copy identity template files if missing
        self._ensure_identity_files()

        # Link user's "My Space" files into workspace for user-level agents
        # User files are at workspaces/{username}/files/ but workspace is elsewhere.
        # Create symlink so agent tools (read_file, write_file, etc.) can access them.
        if username and not is_global:
            self._link_user_files()

        # Components (initialized on start)
        self.core: Optional[AgentCore] = None
        self.foundation_manager: Optional[FoundationManager] = None
        self.evolution_engine: Optional[EvolutionEngine] = None
        self.memory: Optional[MemoryManager] = None
        self.compressor: Optional[ContextCompressor] = None
        self.growth: Optional[GrowthSystem] = None
        self.skills: Optional[SkillManager] = None
        self.tools: Optional[ToolRegistry] = None

        # CoApis-compatible runner components
        self.task_tracker: Optional[Any] = None
        self.chat_manager: Optional[Any] = None
        self.channel_manager: Optional[Any] = None

        # Chat state
        self._active_chats: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._manager = None
        self._runner = None  # Lazily created AgentRunner
        self._config_watcher = None  # AgentConfigWatcher (started in start())

    def _link_user_files(self):
        """Create symlink from workspace/files -> workspaces/{username}/files/.

        User files are now stored at workspaces/{username}/files/ (unified path).
        Create symlink so agent tools (read_file, write_file, etc.) can access them.
        """
        files_link = self.workspace_dir / "files"
        user_files_dir = WORKSPACES_DIR / self.username / "files"

        # Normalize: strip trailing slash to avoid symlink target mismatch
        user_files_dir = Path(str(user_files_dir).rstrip("/"))

        # Create target directory if it doesn't exist
        user_files_dir.mkdir(parents=True, exist_ok=True)

        # Handle different states of the symlink
        if files_link.is_symlink():
            # Existing symlink - verify it points to the correct location
            target = files_link.resolve()
            if target != user_files_dir.resolve():
                logger.warning(
                    f"Workspace files symlink points to wrong location. "
                    f"Removing and recreating: {target} -> {user_files_dir}"
                )
                files_link.unlink()
                files_link.symlink_to(user_files_dir)
                logger.info(
                    f"Recreated files symlink for user {self.username}: "
                    f"{files_link} -> {user_files_dir}"
                )
            # else: symlink is correct, no action needed
        elif files_link.exists():
            # A real directory or file exists at this path - handle gracefully
            logger.warning(
                f"Cannot create files symlink for user {self.username}: "
                f"{files_link} already exists as a real path. "
                f"Please remove it manually."
            )
        else:
            # Create the symlink
            files_link.symlink_to(user_files_dir)
            logger.info(
                f"Created files symlink for user {self.username}: "
                f"{files_link} -> {user_files_dir}"
            )

    def set_manager(self, manager: Any) -> None:
        """Set the parent MultiAgentManager reference."""
        self._manager = manager

    def _ensure_identity_files(self) -> None:
        """Copy identity template files to workspace if missing.

        Ensures every agent workspace has AGENTS.md, SOUL.md, PROFILE.md,
        MEMORY.md, BOOTSTRAP.md, HEARTBEAT.md — copied from system/templates/.
        """
        try:
            from coapis.constant import TEMPLATES_DIR
            import shutil

            if not TEMPLATES_DIR.exists():
                logger.warning("TEMPLATES_DIR not found: %s", TEMPLATES_DIR)
                return

            identity_files = [
                "AGENTS.md", "SOUL.md", "PROFILE.md",
                "MEMORY.md", "BOOTSTRAP.md", "HEARTBEAT.md",
            ]
            copied = 0
            for fname in identity_files:
                dst = self.workspace_dir / fname
                if dst.exists():
                    continue
                src = TEMPLATES_DIR / fname
                if src.exists():
                    shutil.copy2(src, dst)
                    copied += 1
            if copied:
                logger.info(
                    "Copied %d identity files to %s", copied, self.workspace_dir,
                )
        except Exception as e:
            logger.warning(
                "Failed to ensure identity files for %s: %s",
                self.workspace_dir, e, exc_info=True,
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert workspace to dictionary representation for API responses."""
        return {
            "id": self.agent_id,
            "name": getattr(self, "name", self.agent_id),
            "description": getattr(self, "description", ""),
            "workspace_dir": str(self.workspace_dir),
            "data_dir": str(self.data_dir),
            "skills_dir": str(self.skills_dir),
            "status": self.status,
            "is_global": self.is_global,
            "username": self.username,
            "enabled": True,
            "active_model": None,  # Would need to read from core if available
        }

    @property
    def runner(self):
        """Get or create AgentRunner for this workspace.

        Lazily creates an AgentRunner instance that wraps the workspace's
        AgentCore, enabling compatibility with DynamicMultiAgentRunner.
        """
        if not hasattr(self, "_runner") or self._runner is None:
            from ..app.runner.runner import AgentRunner
            r = AgentRunner(
                agent_id=self.agent_id,
                workspace_dir=self.workspace_dir,
                task_tracker=self.task_tracker,
            )
            # Set workspace reference so evolution engine hooks work
            r.set_workspace(self)
            # Initialize context_manager and memory_manager for command dispatch
            try:
                from .context.light_context_manager import LightContextManager
                from .memory_manager import MemoryManager
                r.context_manager = LightContextManager(
                    working_dir=str(self.workspace_dir),
                    agent_id=self.agent_id or "default",
                )
                r.memory_manager = MemoryManager(workspace_dir=self.workspace_dir)
                # Set agent_id for command handler's config loading
                r.memory_manager.agent_id = self.agent_id or "default"
            except Exception as _cm_err:
                logger.warning("Failed to init context/memory manager for runner: %s", _cm_err)
            # Manually initialize session (sync) and mark as healthy.
            # Session messages are stored under workspaces/{username}/sessions/
            # to ensure user-level isolation. Falls back to workspace_dir/sessions/
            # for global agents without a username.
            try:
                from ..app.runner.session import SafeJSONSession
                if self.username:
                    session_dir = str(_get_user_workspace_dir(self.username) / "sessions")
                else:
                    session_dir = str(self.workspace_dir / "sessions")
                r.session = SafeJSONSession(save_dir=session_dir)
            except Exception:
                pass
            r._health = True
            # Wire MCP manager if initialized
            if hasattr(self, '_mcp_manager') and self._mcp_manager:
                r.set_mcp_manager(self._mcp_manager)
            self._runner = r
        return self._runner

    async def _init_mcp_manager(self):
        """Initialize MCP client manager with merged global+user config.

        Merges admin's MCP config (global pool) with user's own config.
        User keys override global keys with the same name.
        """
        try:
            from ..app.mcp.manager import MCPClientManager
            from ..config.config import MCPConfig, load_agent_config
            from ..config.utils import load_config

            self._mcp_manager = MCPClientManager()

            # Build merged MCP config (global + user)
            merged_clients = {}

            # 1. Load global pool (admin's MCP)
            try:
                config = load_config()
                admin_agent_id = config.agents.active_agent or "user:admin"
                if admin_agent_id != self.agent_id:
                    admin_config = load_agent_config(admin_agent_id)
                    if admin_config.mcp and admin_config.mcp.clients:
                        merged_clients.update(dict(admin_config.mcp.clients))
                        logger.info(
                            "MCP: loaded %d global clients from %s",
                            len(admin_config.mcp.clients),
                            admin_agent_id,
                        )
            except Exception as e:
                logger.debug(f"MCP: no global pool available: {e}")

            # 2. Overlay user's own MCP config
            agent_config = load_agent_config(self.agent_id, workspace_dir=self.workspace_dir)
            if agent_config.mcp and agent_config.mcp.clients:
                merged_clients.update(dict(agent_config.mcp.clients))
                logger.info(
                    "MCP: overlaid %d user clients",
                    len(agent_config.mcp.clients),
                )

            # 3. Filter out explicitly disabled keys
            active_clients = {k: v for k, v in merged_clients.items() if v.enabled}

            if active_clients:
                merged_mcp = MCPConfig(clients=active_clients)
                await asyncio.wait_for(
                    self._mcp_manager.init_from_config(merged_mcp),
                    timeout=30,
                )
                clients = await self._mcp_manager.get_clients()
                logger.info(
                    "MCP: initialized %d clients for %s",
                    len(clients),
                    self.agent_id,
                )
            else:
                logger.debug(f"MCP: no active clients for {self.agent_id}")

        except asyncio.TimeoutError:
            logger.warning("MCP manager init timed out after 30s, skipping")
        except Exception as e:
            logger.warning(f"Failed to init MCP manager: {e}", exc_info=True)

        # Register MCP tools into ToolRegistry (mcp__ prefix to avoid conflicts)
        try:
            if self._mcp_manager:
                clients = await self._mcp_manager.get_clients()
                if clients:
                    count = await self.tools.register_mcp_tools(clients)
                    if count:
                        logger.info(
                            "MCP: registered %d tools into ToolRegistry for %s",
                            count, self.agent_id,
                        )
        except Exception as e:
            logger.warning(f"MCP tool registration to ToolRegistry failed: {e}")

    async def start(self):
        """Initialize all workspace components."""
        # Always ensure identity files exist (handles cached workspace reuse)
        self._ensure_identity_files()

        scope = "user" if (self.username and not self.is_global) else "global"
        logger.info(f"Initializing {scope} workspace for agent: {self.agent_id}" +
                    (f" (user: {self.username})" if self.username else ""))

        # Load config: prefer externally-provided config, then try file-based loading
        from ..config import load_agent_config, load_config
        from ..config.config import build_fallback_agent_profile_config

        # Load raw agent.json directly to get provider field (bypasses Pydantic validation)
        raw_agent_config = {}
        agent_json_path = self.workspace_dir / "agent.json"
        if agent_json_path.exists():
            try:
                import json as _json
                with open(agent_json_path) as _f:
                    raw_agent_config = _json.load(_f)
                logger.info(f"Loaded raw agent.json for provider config: {self.agent_id}")
            except Exception as e:
                logger.warning(f"Failed to load raw agent.json: {e}")

        # Build config based on source
        if self.config:
            # Dynamic agent creation: use externally-provided config directly
            # Merge with raw agent.json (preserves 'provider' field)
            config = {**self.config, **raw_agent_config}
            logger.info(f"Using externally-provided config for agent: {self.agent_id}")
        else:
            # File-based agent: load from config.json + agent.json
            root_config = load_config()
            try:
                default_config = build_fallback_agent_profile_config(self.agent_id, root_config).model_dump()
            except Exception:
                # Agent not in config.json - use minimal defaults
                default_config = {
                    "id": self.agent_id,
                    "name": self.agent_id,
                    "description": "",
                    "workspace_dir": str(self.workspace_dir),
                }

            try:
                file_config = load_agent_config(self.agent_id, workspace_dir=self.workspace_dir)
                file_config_dict = file_config.model_dump() if hasattr(file_config, 'model_dump') else file_config
                config = {**default_config, **file_config_dict, **raw_agent_config}
            except Exception:
                # Agent not in config.json - use defaults + raw agent.json
                config = {**default_config, **raw_agent_config}
            logger.info(f"Loaded config for agent: {self.agent_id}")

        # Store config for later use (channel creation, etc.)
        self._config = config

        # Extract model/provider config for AgentCore
        # ALL LLM connections MUST go through ProviderManager - no hardcoded fallbacks
        core_config = {}
        active_model = config.get("active_model")
        provider = config.get("provider", {})

        # Resolve provider_id from active_model or provider field
        provider_id = None
        if isinstance(active_model, dict) and active_model.get("provider_id"):
            provider_id = active_model.get("provider_id")
        elif isinstance(provider, str) and provider:
            provider_id = provider

        # Fallback: read system-level active_model.json if no provider_id found
        # This is the standard way to configure a default provider for all agents
        if not provider_id:
            try:
                from ..config.utils import SYSTEM_DIR
                active_model_file = SYSTEM_DIR / ".secret" / "providers" / "active_model.json"
                if active_model_file.exists():
                    import json as _json
                    with open(active_model_file) as _f:
                        sys_active = _json.load(_f)
                    if sys_active.get("provider_id"):
                        provider_id = sys_active.get("provider_id")
                        logger.info(f"Loaded system-level provider_id: {provider_id}")
                    if sys_active.get("model") and not core_config.get("model"):
                        core_config["model"] = sys_active.get("model")
            except Exception as e:
                logger.warning(f"Failed to load system active_model.json: {e}")

        # Resolve model name (if not already set)
        if not core_config.get("model"):
            if isinstance(active_model, dict) and active_model.get("model"):
                core_config["model"] = active_model.get("model")
            elif config.get("model"):
                core_config["model"] = config.get("model")

        # ALWAYS use ProviderManager for base_url and api_key resolution
        if provider_id:
            try:
                from coapis.providers.provider_manager import ProviderManager
                pm = ProviderManager.get_instance()
                prov = pm.get_provider(provider_id)
                if prov and prov.base_url:
                    core_config["base_url"] = prov.base_url
                    core_config["api_key"] = prov.api_key or "EMPTY"
                    logger.info(f"Resolved provider '{provider_id}' from ProviderManager: base_url={prov.base_url}")
                else:
                    # v0.8.2: ProviderManager returned empty base_url (known bug
                    # with custom provider file overwrite). Fallback to agent.json
                    # provider config.
                    agent_provider = config.get("provider", {})
                    if isinstance(agent_provider, dict) and agent_provider.get("api_base"):
                        core_config["base_url"] = agent_provider["api_base"]
                        core_config["api_key"] = agent_provider.get("api_key", "EMPTY")
                        core_config["model"] = agent_provider.get("model") or core_config.get("model")
                        logger.info(f"Fallback to agent.json provider config: base_url={core_config['base_url']}")
                    elif prov:
                        raise ValueError(f"Provider '{provider_id}' has empty base_url. "
                                       f"Configure provider.api_base in agent.json or fix ProviderManager.")
                    else:
                        raise ValueError(f"Provider '{provider_id}' not found in ProviderManager. "
                                       f"Please configure it in Settings > Providers.")
            except ImportError as e:
                raise RuntimeError(f"Failed to import ProviderManager: {e}") from e
            except Exception as e:
                raise RuntimeError(f"Failed to resolve provider '{provider_id}': {e}") from e
        else:
            raise ValueError("No provider configured for agent. "
                           f"Please set 'active_model.provider_id' or 'provider' in agent.json, "
                           f"or create system-level active_model.json")

        # Merge core_config into config
        config = {**config, **core_config}

        # Initialize FoundationManager (hierarchical memory)
        # Use global foundation directory for all agents
        foundation_dir = Path(__file__).parent.parent / "foundation"
        self.foundation_manager = FoundationManager(foundation_dir=foundation_dir)
        logger.info(f"FoundationManager initialized for agent: {self.agent_id}")

        # Initialize KnowledgeFlow (knowledge propagation across layers)
        from ..evolution import KnowledgeFlow, FlowConfig
        self.knowledge_flow = KnowledgeFlow(
            foundation_manager=self.foundation_manager,
            data_dir=self.data_dir,
            config=FlowConfig(
                auto_promote_enabled=False,
                require_review=True,
            ),
        )

        # Initialize BackendReview (async background review)
        from ..evolution import BackendReview, ReviewSchedule
        self.backend_review = BackendReview(
            evolution_engine=None,  # Will be set after EvolutionEngine is created
            foundation_manager=self.foundation_manager,
            data_dir=self.data_dir,
            schedule=ReviewSchedule(
                memory_review_interval=3600,
                skill_review_interval=7200,
                experience_review_interval=1800,
                knowledge_flow_interval=5400,
                enabled=True,
            ),
        )

        # Initialize EvolutionEngine (self-improvement)
        # v0.5.1: Evolution data centralized in SYSTEM_DIR/evolution/ for all user agents.
        # Global agents keep evolution in agents/{agent_id}/evolution/.
        from ..constant import SYSTEM_EVOLUTION_DIR
        if self.username and not self.is_global:
            # User agents: shared evolution in system/evolution/
            evolution_data_dir = SYSTEM_EVOLUTION_DIR
            workspace_dir = self.workspace_dir
        else:
            # Global agents: per-agent evolution
            evolution_data_dir = self.workspace_dir / "evolution"
            workspace_dir = self.workspace_dir
        
        self.evolution_engine = EvolutionEngine(
            data_dir=evolution_data_dir,
            foundation_manager=self.foundation_manager,
            workspace_dir=workspace_dir,
            enabled=True,
            memory_nudge_interval=10,
            skill_nudge_interval=8,
            agent_core=None,  # Will be set after AgentCore is created
            knowledge_flow=self.knowledge_flow,
            backend_review=self.backend_review,
        )
        # Set evolution_engine reference in backend_review
        self.backend_review.evolution_engine = self.evolution_engine

        logger.info(f"EvolutionEngine initialized for agent: {self.agent_id}")

        # Initialize CrossAgentEvolution (cross-agent knowledge aggregation)
        # Uses global singleton — all agents share the same AB buckets
        if self.is_global:
            from ..evolution.cross_agent_evolution import init_global_cross_agent_evolution

            self.cross_agent_evolution = init_global_cross_agent_evolution(
                model=None,  # Will be set after AgentCore is created
                foundation_manager=self.foundation_manager,
            )

            # Link to EvolutionEngine
            self.evolution_engine.cross_agent_evolution = self.cross_agent_evolution

            logger.info(f"CrossAgentEvolution (global) linked for agent: {self.agent_id}")
        else:
            # User agents: link to global singleton for experience reporting
            from ..evolution.cross_agent_evolution import get_global_cross_agent_evolution
            self.cross_agent_evolution = get_global_cross_agent_evolution()
            if self.cross_agent_evolution:
                self.evolution_engine.cross_agent_evolution = self.cross_agent_evolution
                logger.info(f"CrossAgentEvolution (global singleton) linked for user agent: {self.agent_id}")

        # ── ServiceManager: 声明式服务生命周期管理 ──────────────────────
        from .service_manager import ServiceManager, ServiceDescriptor

        self._service_mgr = ServiceManager(self)

        # AgentCore (priority=10, 无依赖)
        self._service_mgr.register(ServiceDescriptor(
            name="core",
            factory=lambda ws, _cfg=config: (
                setattr(ws, "core",
                        AgentCore(
                            config=_cfg,
                            foundation_manager=ws.foundation_manager,
                            evolution_engine=ws.evolution_engine,
                        ))
                or setattr(ws.evolution_engine, "agent_core", ws.core)
                or (setattr(ws.cross_agent_evolution, "model", ws.core.client)
                    if ws.cross_agent_evolution else None)
                or ws.core
            ),
            priority=10,
            attr_name="core",
        ))

        # MemoryManager (priority=20)
        self._service_mgr.register(ServiceDescriptor(
            name="memory",
            factory=lambda ws: MemoryManager(workspace_dir=ws.workspace_dir),
            priority=20,
            attr_name="memory",
        ))

        # ContextCompressor (priority=20, 依赖 core)
        self._service_mgr.register(ServiceDescriptor(
            name="compressor",
            factory=lambda ws: ContextCompressor(core=ws.core),
            priority=20,
            dependencies=["core"],
            attr_name="compressor",
        ))

        # SkillManager (priority=30)
        self._service_mgr.register(ServiceDescriptor(
            name="skills",
            factory=lambda ws: SkillManager(ws.skills_dir),
            priority=30,
            attr_name="skills",
        ))

        # GrowthSystem (priority=40, 依赖 memory + skills)
        self._service_mgr.register(ServiceDescriptor(
            name="growth",
            factory=lambda ws: GrowthSystem(
                workspace_dir=ws.workspace_dir,
                memory=ws.memory,
                skills=ws.skills,
            ),
            priority=40,
            dependencies=["memory", "skills"],
            attr_name="growth",
        ))

        # ToolRegistry (priority=20) — bridge from agents/tools plugin registry
        def _create_tool_registry(ws):
            registry = ToolRegistry()
            try:
                from ..agents.tools._auto_register import register_all_builtin_tools
                from ..agents.tools.registry import get_registered_tools
                register_all_builtin_tools()
                plugin_tools = get_registered_tools()
                logger.info(
                    "Bridging %d plugin tools into ToolRegistry",
                    len(plugin_tools),
                )
                import inspect as _inspect
                for name, reg in plugin_tools.items():
                    # Build OpenAI-compatible parameter schema from function signature
                    params = {}
                    required = []
                    try:
                        sig = _inspect.signature(reg.func)
                        hints = {}
                        try:
                            hints = _inspect.get_annotations(reg.func)
                        except Exception:
                            pass
                        for pname, param in sig.parameters.items():
                            ptype = hints.get(pname, str)
                            type_str = (
                                "integer" if ptype in (int,)
                                else "number" if ptype in (float,)
                                else "boolean" if ptype in (bool,)
                                else "string"
                            )
                            param_schema: Dict[str, Any] = {
                                "type": type_str,
                                "description": pname,
                            }
                            params[pname] = param_schema
                            if param.default is _inspect.Parameter.empty:
                                required.append(pname)
                    except Exception:
                        pass
                    parameters_schema = (
                        {"type": "object", "properties": params, "required": required}
                        if params
                        else {"type": "object", "properties": {}}
                    )
                    registry._tools[name] = ToolInfo(
                        name=name,
                        description=reg.description or name,
                        func=reg.func,
                        parameters=parameters_schema,
                    )

                # Apply agent config: deny disabled tools
                try:
                    agent_config = getattr(ws, '_config', None)
                    if agent_config and 'tools' in agent_config:
                        builtin_tools = agent_config['tools'].get('builtin_tools', {})
                        for tool_name, tool_cfg in builtin_tools.items():
                            if isinstance(tool_cfg, dict) and tool_cfg.get('enabled') is False:
                                if tool_name not in registry._denied_tools:
                                    registry._denied_tools.append(tool_name)
                                    logger.info("Denied tool (disabled in config): %s", tool_name)
                except Exception as e:
                    logger.debug("Failed to apply tool deny list: %s", e)

            except Exception as e:
                logger.warning("Failed to bridge plugin tools: %s", e)
            return registry

        self._service_mgr.register(ServiceDescriptor(
            name="tools",
            factory=_create_tool_registry,
            priority=20,
            attr_name="tools",
        ))

        # TaskTracker (priority=50)
        from ..app.runner.task_tracker import TaskTracker
        self._service_mgr.register(ServiceDescriptor(
            name="task_tracker",
            factory=lambda ws: TaskTracker(),
            priority=50,
            attr_name="task_tracker",
        ))

        # ChatManager (priority=50)
        def _create_chat_manager(ws):
            from ..app.runner.manager import ChatManager
            from ..app.runner.repo.json_repo import JsonChatRepository
            repo_dir = ws.data_dir / "chats"
            repo_dir.mkdir(parents=True, exist_ok=True)
            chat_repo = JsonChatRepository(str(repo_dir / "chats.json"))
            return ChatManager(repo=chat_repo)

        self._service_mgr.register(ServiceDescriptor(
            name="chat_manager",
            factory=_create_chat_manager,
            priority=50,
            attr_name="chat_manager",
        ))

        # 启动所有已注册服务
        await self._service_mgr.start_all()

        # ── MCP Client Manager: 热加载 MCP 工具 ──────────────────────
        await self._init_mcp_manager()

        # ── TriggerTracker: 确保技能触发追踪单例已初始化 ──
        try:
            from .utils.trigger_tracker import get_trigger_tracker
            get_trigger_tracker()
        except Exception as e:
            logger.debug("TriggerTracker init skipped: %s", e)

        # 注册 workspace CronManager 到全局 CronManagerRegistry
        if self.username and not self.is_global:
            try:
                from ..app.crons.registry import get_registry
                registry = get_registry()
                cron_mgr = self._service_mgr.get("cron_manager")
                if registry and cron_mgr:
                    registry.register_manager(self.username, cron_mgr)
                    logger.info(f"Registered workspace CronManager for {self.username} into global registry")
            except Exception as e:
                logger.warning(f"Failed to register CronManager in registry: {e}")

        # ChannelManager + ConsoleChannel: SSE event streaming pipeline
        from ..app.channels.console import ConsoleChannel
        from ..app.channels.manager import ChannelManager

        def _process_handler(request):
            """ProcessHandler: accepts AgentRequest, streams Event objects.
            This is the bridge between the channel system and AgentCore.
            
            Yields proper Event/Message/TextContent objects matching
            @agentscope-ai/chat frontend expectations (CoApis native format).
            """
            async def _stream(request_obj):
                # Import Event classes
                from agentscope_runtime.engine.schemas.agent_schemas import (
                    Event, Message, TextContent, DataContent, RunStatus, MessageType
                )
                import uuid as uuid_mod

                # Extract message text from AgentRequest
                input_msgs = getattr(request_obj, "input", [])
                session_id = getattr(request_obj, "session_id", "")
                if not session_id:
                    session_id = str(uuid_mod.uuid4())[:8]
                user_id = getattr(request_obj, "user_id", "")

                user_texts = []
                for msg in input_msgs:
                    role = getattr(msg, "role", None)
                    if role == "user" or str(role) == "user":
                        content = getattr(msg, "content", "")
                        if isinstance(content, str):
                            user_texts.append(content)
                        elif isinstance(content, list):
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    user_texts.append(item.get("text", ""))
                                elif hasattr(item, "type") and str(getattr(item, "type", "")) == "text":
                                    user_texts.append(getattr(item, "text", ""))

                user_message = "\n".join(user_texts).strip()
                if not user_message:
                    user_message = " "

                # Build chat key with user isolation
                chat_key = f"{self.username}:{session_id}" if self.username else session_id

                # Check if this is a new chat BEFORE creating context
                _is_new_chat = chat_key not in self._active_chats

                # Get or create chat context
                context = await self._get_chat_context(chat_key)

                # Reset foundation memory for new sessions
                if _is_new_chat and self.foundation_manager:
                    self.foundation_manager.reset_injection_state()

                # ── Evolution: on_session_start for new chats ──
                if _is_new_chat and self.evolution_engine:
                    try:
                        self.evolution_engine.on_session_start(
                            session_id=session_id,
                            agent_id=self.agent_id or "unknown",
                            user_id=self.username or "unknown",
                        )
                    except Exception as evo_err:
                        logger.debug("Evolution on_session_start failed: %s", evo_err)

                # ── Evolution: on_turn_start ──
                if self.evolution_engine:
                    try:
                        self.evolution_engine.on_turn_start(user_message)
                    except Exception as evo_err:
                        logger.debug("Evolution on_turn_start failed: %s", evo_err)

                # ── Command routing: delegate to runner's command system ──
                # This handles /new, /compact, /history, /plan, /approve,
                # /stop, /status, /version, /daemon, etc.
                # /clear and /reset are handled locally below (need context cleanup).
                _cmd_query = user_message.strip()
                _clearable_commands = ("/clear", "/reset", "清空上下文")
                if _cmd_query.lower() not in _clearable_commands:
                    try:
                        from ..app.runner.command_dispatch import (
                            _is_command,
                            run_command_path,
                        )
                        from agentscope.message import Msg as _CmdMsg
                        logger.info(
                            "[CMD-DEBUG] _cmd_query=%r, _is_command=%s",
                            _cmd_query,
                            _is_command(_cmd_query),
                        )
                        if _is_command(_cmd_query):
                            _msg_id_cmd = str(uuid_mod.uuid4())
                            _resp_id_cmd = str(uuid_mod.uuid4())
                            # ── Yield Message(InProgress) to register stream_type ──
                            yield Message(
                                object="message",
                                id=_msg_id_cmd,
                                role="assistant",
                                type=MessageType.MESSAGE,
                                status=RunStatus.InProgress,
                                content=[TextContent(type="text", text="")],
                            )
                            # Build minimal Msg list for run_command_path
                            _cmd_msgs = [
                                _CmdMsg(name="user", role="user", content=_cmd_query),
                            ]
                            _cmd_runner = self.runner
                            _cmd_full_text = ""
                            async for _cmd_msg, _cmd_last in run_command_path(
                                request_obj, _cmd_msgs, _cmd_runner
                            ):
                                # Extract text from Msg
                                _cmd_text = ""
                                _cmd_content = getattr(_cmd_msg, "content", "")
                                if isinstance(_cmd_content, str):
                                    _cmd_text = _cmd_content
                                elif isinstance(_cmd_content, list):
                                    for _blk in _cmd_content:
                                        if hasattr(_blk, "text"):
                                            _cmd_text += getattr(_blk, "text", "")
                                        elif isinstance(_blk, dict) and _blk.get("type") == "text":
                                            _cmd_text += _blk.get("text", "")
                                _cmd_full_text += _cmd_text
                            # Yield full command output as delta text
                            if _cmd_full_text:
                                yield TextContent(
                                    object="content",
                                    msg_id=_msg_id_cmd,
                                    type="text",
                                    delta=True,
                                    status=RunStatus.InProgress,
                                    text=_cmd_full_text,
                                )
                            # Yield Message(Completed) to trigger on_streaming_end
                            yield Message(
                                object="message",
                                id=_msg_id_cmd,
                                role="assistant",
                                type=MessageType.MESSAGE,
                                status=RunStatus.Completed,
                                content=[],
                            )
                            yield Event(
                                object="response",
                                id=_resp_id_cmd,
                                status=RunStatus.Completed,
                                created_at=int(__import__('time').time() * 1000),
                            )
                            return
                    except Exception as _cmd_err:
                        logger.warning(
                            "Command routing failed, falling through to LLM: %s",
                            _cmd_err,
                        )

                # ── Handle /clear command: reset chat context ──
                if user_message.strip().lower() in ("/clear", "/reset", "清空上下文"):
                    context.clear_messages()
                    if self.foundation_manager:
                        self.foundation_manager.reset_injection_state()
                    # Yield Message(InProgress) to register stream_type
                    _clear_msg_id = str(uuid_mod.uuid4())
                    yield Message(
                        object="message",
                        id=_clear_msg_id,
                        role="assistant",
                        type=MessageType.MESSAGE,
                        status=RunStatus.InProgress,
                        content=[TextContent(type="text", text="")],
                    )
                    # Yield confirmation as delta text
                    confirm_text = "✅ 聊天上下文已清空。"
                    yield TextContent(
                        object="content",
                        msg_id=_clear_msg_id,
                        type="text",
                        delta=True,
                        text=confirm_text,
                    )
                    # Persist empty state to session
                    try:
                        session_obj = runner.session if runner else None
                        if session_obj:
                            await session_obj.update_session_state(
                                session_id=chat_key,
                                key="agent.memory",
                                value={},
                                user_id=self.username or user_id or "anonymous",
                            )
                    except Exception:
                        pass
                    yield Message(
                        object="message",
                        id=_clear_msg_id,
                        role="assistant",
                        type=MessageType.MESSAGE,
                        status=RunStatus.Completed,
                        content=[],
                    )
                    yield Event(
                        object="response",
                        id=response_id,
                        status=RunStatus.Completed,
                        created_at=int(__import__('time').time() * 1000),
                    )
                    return

                # Add user message to context BEFORE streaming
                context.add_message("user", user_message)

                # Generate unique IDs for this response
                response_id = str(uuid_mod.uuid4())
                msg_id = str(uuid_mod.uuid4())

                # Yield response created event
                yield Event(
                    object="response",
                    id=response_id,
                    status=RunStatus.Created,
                    created_at=int(__import__('time').time() * 1000),
                )

                # Yield message start event
                yield Message(
                    object="message",
                    id=msg_id,
                    role="assistant",
                    type=MessageType.MESSAGE,
                    content=[],
                )

                # Initialize streaming: yield a delta=False TextContent to signal
                # stream start. Without this, channel dispatchers that rely on
                # msg_id_to_stream_type mapping (e.g. WeChat Work) will silently
                # drop all subsequent delta=True events.
                yield TextContent(
                    object="content",
                    msg_id=msg_id,
                    type="text",
                    delta=False,
                    text="",
                )

                # Stream through AgentCore and yield proper events
                # AgentCore now yields (text_chunk, is_reasoning) tuples
                full_response = []
                full_reasoning = []
                _raw_blocks = []  # Collect raw ResponseBlock objects for session persistence
                _evo_tool_calls = []  # Collect tool call info for evolution engine
                _search_card_html = ""  # Search prefetch card HTML (empty if not used)
                _search_card_inserted_count = 0  # Track if search card has been inserted

                # ── Determine display strategy from user prefs + channel config ──
                _channel_name = getattr(request_obj, "channel", "") or ""

                # Read user preferences (ChatDisplayConfig)
                _chat_display = None
                try:
                    from ..user_system.database import UserSystemDB
                    _db = UserSystemDB()
                    # v0.8.2: Always resolve via self.username first.
                    # self._user_id may be a platform-specific ID (e.g. DingTalk
                    # staff_id) which is NOT the internal user ID stored in prefs.
                    _resolved_uid = None
                    if self.username:
                        _u = _db.get_user_by_username(self.username)
                        if _u:
                            _resolved_uid = _u.get("id")
                    # Fallback: try raw _user_id only if username resolution failed
                    if not _resolved_uid:
                        _resolved_uid = getattr(self, "_user_id", None)
                    if _resolved_uid:
                        _prefs = _db.get_preferences(_resolved_uid)
                        if _prefs and "chat_display" in _prefs:
                            from ..user_system.models import ChatDisplayConfig
                            _chat_display = ChatDisplayConfig(**_prefs["chat_display"])
                except Exception:
                    pass  # Graceful fallback to defaults

                # Read channel config (filter_tool_messages, filter_thinking)
                _ch_cfg = None
                try:
                    _agent_channels = self._config.get("channels", {}) if isinstance(self._config, dict) else {}
                    _ch_cfg = _agent_channels.get(_channel_name) if _channel_name else None
                except Exception:
                    pass

                # Merge: user preferences > channel config > defaults
                # Default: show everything (thinking + tool details)
                # Users complained about "stuck" feeling when messages are filtered
                # ── show_tool_details ──
                if _chat_display:
                    if _chat_display.displayMode == "simple":
                        _show_tool = False
                    elif _chat_display.hideToolCall:
                        _show_tool = False
                    else:
                        _show_tool = True
                elif _ch_cfg and _ch_cfg.get("filter_tool_messages"):
                    _show_tool = False
                else:
                    _show_tool = True

                # ── filter_thinking ──
                if _chat_display:
                    _filter_thinking = getattr(_chat_display, 'hideThinking', False) or getattr(_chat_display, 'hideThought', False)
                elif _ch_cfg and _ch_cfg.get("filter_thinking"):
                    _filter_thinking = True
                else:
                    _filter_thinking = False

                # ── display_mode (for channel-level block splitting) ──
                _display_mode = "simple"
                if _chat_display:
                    _display_mode = _chat_display.displayMode

                logger.debug(
                    "workspace display config: channel=%s show_tool=%s "
                    "filter_thinking=%s display_mode=%s",
                    _channel_name, _show_tool, _filter_thinking, _display_mode,
                )

                # ── Search intent pre-fetch (force web_search for search queries) ──
                # Load search config from JSON file (supports customization)
                _search_cfg_path = Path(__file__).parent / "search_config.json"
                _search_cfg = {}
                try:
                    import json as _json
                    with open(_search_cfg_path) as _sf:
                        _search_cfg = _json.load(_sf)
                except Exception:
                    pass
                _search_keywords = set(_search_cfg.get("search_keywords", [
                    '新闻', '热点', '热搜', '天气', '比分', '股票', '价格',
                    'news', 'weather', 'sports', 'score', 'price', 'stock',
                    '搜索', '查一下', '查查', '帮我查', '最新', '实时', '今天',
                    'latest', 'realtime', 'today', 'trending',
                ]))
                _search_max_results = _search_cfg.get("search_max_results", 10)
                _search_timeout = _search_cfg.get("search_timeout", 15.0)
                _search_backend = _search_cfg.get("search_backend", "auto")
                _is_search_query = any(kw in user_message.lower() for kw in _search_keywords)

                if _is_search_query and self.tools:
                    try:
                        search_tool = self.tools._tools.get('web_search')
                        if search_tool:
                            import asyncio as _aio
                            _search_result = await _aio.wait_for(
                                search_tool.func(query=user_message, max_results=_search_max_results, backend=_search_backend),
                                timeout=_search_timeout
                            )
                            if isinstance(_search_result, dict) and _search_result.get('results'):
                                _results_text = '\n\n'.join(
                                    f"[{i+1}] {r.get('title', '')}\n"
                                    f"    摘要: {r.get('snippet', '')}\n"
                                    f"    来源: {r.get('url', '')}"
                                    for i, r in enumerate(_search_result['results'])
                                )
                                # Keep user_message clean — pass search results
                                # via context so they reach the LLM but are NOT
                                # persisted in the user message session record.
                                _search_context = (
                                    f"[SEARCH_RESULTS] 以下是关于该话题的实时搜索结果（共{len(_search_result['results'])}条），"
                                    f"请基于以下搜索结果中的信息进行汇总回答。要求：\n"
                                    f"1. 按条理清晰地组织回答，使用分点或分段结构\n"
                                    f"2. 引用具体数据和事实，不要泛泛而谈\n"
                                    f"3. 如果涉及多条信息，分别列出\n"
                                    f"4. 用中文回答，语气专业但易读\n\n"
                                    f"{_results_text}\n[/SEARCH_RESULTS]"
                                )
                                context.add_message("system", _search_context)
                                logger.info(
                                    "Search pre-fetch: injected %d results for query: %s",
                                    len(_search_result['results']),
                                    user_message[:50]
                                )
                    except Exception as e:
                        logger.warning("Search pre-fetch failed: %s", e)

                # ── Initialize renderer from channel + user prefs ──
                from ..app.channels.renderer import RenderStyle, MessageRenderer
                _render_style = RenderStyle.from_channel(_channel_name, _ch_cfg or {})
                # Override with user chat_display preferences if available
                if _chat_display:
                    if hasattr(_chat_display, 'showToolDetails') and _chat_display.showToolDetails is not None:
                        _render_style.show_tool_details = _chat_display.showToolDetails
                    elif hasattr(_chat_display, 'hideToolCall'):
                        _render_style.show_tool_details = not _chat_display.hideToolCall
                    if hasattr(_chat_display, 'filterThinking') and _chat_display.filterThinking is not None:
                        _render_style.show_thinking = not _chat_display.filterThinking
                    elif hasattr(_chat_display, 'hideThought'):
                        _render_style.show_thinking = not _chat_display.hideThought
                _renderer = MessageRenderer(_render_style)

                logger.info(
                    "RenderStyle for %s: thinking=%s tool=%s emoji_only=%s",
                    _channel_name,
                    _render_style.show_thinking,
                    _render_style.show_tool_details,
                    not _render_style.show_tool_details,
                )

                # ── Progress feedback state ──
                _thinking_shown = False
                _tool_calls_seen = 0

                # ── Block-specific message IDs for @agentscope-ai/chat ──
                # Each block type (reasoning, plugin_call, message) needs its own
                # Message event with a unique msg_id for the frontend to render
                # as separate cards with collapse/expand functionality.
                _current_phase = None  # "reasoning" | "plugin_call" | "message"
                _phase_msg_id = None   # msg_id for the current phase's Message event

                async def _close_phase():
                    """Yield a Message completed event for the current phase."""
                    nonlocal _current_phase, _phase_msg_id
                    if _phase_msg_id is None:
                        return
                    if _current_phase == "reasoning":
                        _close_type = MessageType.REASONING
                    elif _current_phase == "plugin_call":
                        _close_type = MessageType.PLUGIN_CALL
                    else:
                        _close_type = MessageType.MESSAGE
                    yield Message(
                        object="message",
                        id=_phase_msg_id,
                        role="assistant",
                        type=_close_type,
                        status=RunStatus.Completed,
                    )
                    _current_phase = None
                    _phase_msg_id = None

                async def _open_phase(phase_type):
                    """Open a new phase, closing the previous one if needed."""
                    nonlocal _current_phase, _phase_msg_id
                    if _current_phase == phase_type and _phase_msg_id is not None:
                        return  # already open
                    # Close previous phase
                    if _phase_msg_id is not None:
                        async for ev in _close_phase():
                            yield ev
                    _current_phase = phase_type
                    _phase_msg_id = str(uuid_mod.uuid4())
                    # Determine message type
                    if phase_type == "reasoning":
                        msg_type = MessageType.REASONING
                    elif phase_type == "plugin_call":
                        msg_type = MessageType.PLUGIN_CALL
                    else:
                        msg_type = MessageType.MESSAGE
                    # Yield Message created event (status=InProgress so that
                    # the library's Reasoning component renders immediately)
                    yield Message(
                        object="message",
                        id=_phase_msg_id,
                        role="assistant",
                        type=msg_type,
                        status=RunStatus.InProgress,
                        content=[],
                    )

                # ── Pre-save user message to session (before stream) ──
                # Following qwenpaw strategy: user message is persisted BEFORE
                # stream processing begins, so it survives /stop interruption.
                # NOTE: The console router may have already persisted the user
                # message synchronously before starting the stream. In that
                # case, skip the pre-save to avoid duplicate messages.
                logger.info("[DEBUG] Starting pre-save, chat_key=%s", chat_key[:20])
                _pre_save_done = False
                try:
                    _session = self.runner.session if self.runner else None
                    if _session and user_message.strip():
                        from coapis.config.session_context import get_current_chat_id as _get_chat_id_pre
                        _pre_chat_id = (
                            getattr(request_obj, "chat_id", "")
                            or _get_chat_id_pre()
                            or chat_key
                        )
                        _pre_user = self.username or user_id or "anonymous"
                        # Load existing state
                        _pre_state = await _session.get_session_state_dict(
                            _pre_chat_id, _pre_user, allow_not_exist=True,
                        )
                        _pre_mem_state = (_pre_state or {}).get("agent", {}).get("memory", {})
                        from agentscope.memory import InMemoryMemory
                        from agentscope.message import Msg, TextBlock
                        _pre_mem = InMemoryMemory()
                        if _pre_mem_state:
                            _pre_mem.load_state_dict(_pre_mem_state, strict=False)
                        # Check if user message already persisted (by console router)
                        _existing_memories = await _pre_mem.get_memory(prepend_summary=False)
                        _already_saved = False
                        if _existing_memories:
                            _last = _existing_memories[-1]
                            if (getattr(_last, "role", "") == "user"
                                    and user_message.strip() in str(getattr(_last, "content", ""))):
                                _already_saved = True
                                logger.debug(
                                    "User message already persisted by console router, skipping pre-save: chat=%s",
                                    _pre_chat_id[:12],
                                )
                        if not _already_saved:
                            # Add user message
                            await _pre_mem.add(
                                Msg(name="user", content=[TextBlock(text=user_message)], role="user")
                            )
                            # Save back (only user message, assistant will be added later)
                            _pre_new_state = _pre_state.copy() if _pre_state else {}
                            if "agent" not in _pre_new_state:
                                _pre_new_state["agent"] = {}
                            _pre_new_state["agent"]["memory"] = _pre_mem.state_dict()
                            await _session.update_session_state(
                                _pre_chat_id, "agent.memory",
                                _pre_new_state["agent"]["memory"],
                                user_id=_pre_user,
                            )
                        _pre_save_done = True
                        logger.debug("Pre-saved user message to session, chat=%s", _pre_chat_id[:12])
                except Exception as e:
                    logger.warning("Pre-save user message failed: %s", e)

                # ── Stream via unified CoApisAgent (runner.query_handler) ──
                _stopped = False
                try:
                    from .stream_utils import msg_to_response_blocks
                    from agentscope.message import Msg as _StreamMsg
                    _stream_msgs = [_StreamMsg(name="user", content=user_message, role="user")]

                    async for _msg_obj, _is_last in self.runner.query_handler(
                        msgs=_stream_msgs,
                        request=request_obj,
                    ):
                        if not _msg_obj or not getattr(_msg_obj, "content", None):
                            continue
                        _blocks = msg_to_response_blocks(
                            _msg_obj,
                            show_tool=_show_tool,
                            filter_thinking=_filter_thinking,
                        )
                        for block in _blocks:
                            if not block.content:
                                continue

                            # Collect raw block for session persistence
                            _raw_blocks.append(block)

                            # ── Render block via renderer ──
                            if block.type == "thinking":
                                full_reasoning.append(block.content)
                                rendered = _renderer.render_thinking(block.content)
                                if rendered:
                                    async for ev in _open_phase("reasoning"):
                                        yield ev
                                    yield TextContent(
                                        object="content",
                                        msg_id=_phase_msg_id,
                                        type="text",
                                        delta=True,
                                        text=rendered,
                                        status=RunStatus.InProgress,
                                    )
                            elif block.type == "tool_call":
                                _tool_calls_seen += 1
                                if self.evolution_engine:
                                    try:
                                        _tc_meta = block.meta or {}
                                        _evo_tool_calls.append({
                                            "name": _tc_meta.get("tool_name", "unknown"),
                                            "args": _tc_meta.get("tool_args", {}),
                                            "call_id": _tc_meta.get("call_id", ""),
                                        })
                                    except Exception:
                                        pass
                                if _current_phase == "reasoning":
                                    async for ev in _close_phase():
                                        yield ev
                                rendered = _renderer.render_tool_call(block.content, block.meta)
                                if rendered:
                                    full_response.append(rendered)
                                    async for ev in _open_phase("plugin_call"):
                                        yield ev
                                    _tool_meta = block.meta or {}
                                    _tool_data = {
                                        "name": _tool_meta.get("tool_name", "unknown"),
                                        "call_id": _tool_meta.get("call_id", str(uuid_mod.uuid4())),
                                        "arguments": json.dumps(
                                            _tool_meta.get("tool_args", {}),
                                            ensure_ascii=False,
                                            default=str,
                                        ),
                                    }
                                    yield DataContent(
                                        object="content",
                                        msg_id=msg_id,
                                        type="data",
                                        delta=True,
                                        data=_tool_data,
                                        status=RunStatus.InProgress,
                                    )
                                    yield TextContent(
                                        object="content",
                                        msg_id=msg_id,
                                        type="text",
                                        delta=True,
                                        text=rendered,
                                        status=RunStatus.InProgress,
                                    )
                            elif block.type == "tool_output":
                                rendered = _renderer.render_tool_output(block.content, block.meta)
                                if rendered:
                                    async for ev in _close_phase():
                                        yield ev
                                    async for ev in _open_phase("tool_output"):
                                        yield ev
                                    full_response.append(rendered)
                                    _tool_out_meta = block.meta or {}
                                    yield DataContent(
                                        object="content",
                                        msg_id=msg_id,
                                        type="data",
                                        delta=True,
                                        data={
                                            "name": _tool_out_meta.get("tool_name", "unknown"),
                                            "call_id": _tool_out_meta.get("tool_call_id", ""),
                                            "output": block.content[:2000] if block.content else "",
                                        },
                                        status=RunStatus.InProgress,
                                    )
                                    yield TextContent(
                                        object="content",
                                        msg_id=msg_id,
                                        type="text",
                                        delta=True,
                                        text=rendered,
                                        status=RunStatus.InProgress,
                                    )
                            elif block.type == "text":
                                text_content = block.content
                                full_response.append(text_content)
                                if _search_card_html and _search_card_inserted_count < 1:
                                    _search_card_inserted_count += 1
                                    text_content = _search_card_html + "\n\n" + text_content
                                    _search_card_html = ""
                                if _current_phase:
                                    async for ev in _close_phase():
                                        yield ev
                                rendered = _renderer.render_text(text_content)
                                if rendered:
                                    full_response.append(rendered)
                                    yield TextContent(
                                        object="content",
                                        msg_id=msg_id,
                                        type="text",
                                        delta=True,
                                        text=rendered,
                                        status=RunStatus.InProgress,
                                    )
                            else:
                                pass

                except asyncio.CancelledError:
                    _stopped = True
                    logger.info("Stream cancelled by user (/stop)")

                # Build complete reply: reasoning + content (both parts must be preserved)
                assistant_reply = "".join(full_reasoning) + "".join(full_response)

                # ── Evolution: on_turn_end ──
                if self.evolution_engine:
                    try:
                        self.evolution_engine.on_turn_end(
                            assistant_message=assistant_reply,
                            tool_calls=_evo_tool_calls if _evo_tool_calls else None,
                        )
                    except Exception as evo_err:
                        logger.debug("Evolution on_turn_end failed: %s", evo_err)

                # ── Tool failure fallback for non-console channels ──
                if (
                    _tool_calls_seen > 0
                    and _channel_name != "console"
                ):
                    response_lower = assistant_reply.strip().lower()
                    _teaching_patterns = [
                        "你可以尝试", "建议你", "请尝试", "你可以通过",
                        "你可以使用", "建议使用", "可以试试", "你可以访问",
                        "你可以搜索", "请访问", "你可以打开", "你可以去",
                        "如何查", "怎么查", "怎么搜", "如何搜",
                    ]
                    is_teaching = any(p in response_lower for p in _teaching_patterns)
                    is_empty = len(assistant_reply.strip()) < 10
                    if is_teaching or is_empty:
                        fallback_msg = (
                            "\n\n⚠️ 抱歉，搜索/查询工具暂时不可用，无法获取实时信息。"
                            "请稍后再试，或换个方式提问。"
                        )
                        if fallback_msg not in assistant_reply:
                            assistant_reply += fallback_msg
                            yield TextContent(
                                object="content",
                                msg_id=msg_id,
                                type="text",
                                delta=True,
                                text=fallback_msg,
                                status=RunStatus.InProgress,
                            )
                if assistant_reply:
                    pass  # persistence handled by runner

                # Store for legacy access (runner handles persistence)
                self.last_full_reasoning = full_reasoning
                self.last_full_response = full_response

                # NOTE: Persistence is now handled by runner.query_handler()
                # via ChatManager. No workspace-level persistence needed.

                # ── Close any open phase ──
                async for ev in _close_phase():
                    yield ev

                # ── Evolution: on_session_end ──
                if self.evolution_engine:
                    try:
                        await self.evolution_engine.on_session_end()
                    except Exception as evo_err:
                        logger.debug("Evolution on_session_end failed: %s", evo_err)

                # Yield response completed event
                yield Event(
                    object="response",
                    id=response_id,
                    status=RunStatus.Completed,
                )

            return _stream(request)

        console_channel = ConsoleChannel(
            process=_process_handler,
            show_tool_details=True,
            filter_tool_messages=False,
            filter_thinking=True,  # Hide LLM reasoning from user-facing channels
        )
        console_channel._workspace = self

        # Try to create additional channels from agent config
        from ..app.channels.manager import ChannelManager
        channels_list = [console_channel]

        agent_channels = self._config.get("channels", {}) if isinstance(self._config, dict) else {}
        logger.info(f"Agent {self.agent_id} channels config: {list(agent_channels.keys()) if agent_channels else 'empty'}")
        if agent_channels:
            from ..app.channels.registry import get_channel_registry
            registry = get_channel_registry()

            # P1: Pre-flight bot_id conflict detection for wecom channel
            if "wecom" in agent_channels:
                wecom_cfg = agent_channels.get("wecom", {})
                if isinstance(wecom_cfg, dict) and wecom_cfg.get("enabled", False):
                    try:
                        from ..app.channels.wecom.channel import _WECOM_BOT_OWNER, _WECOM_INSTANCE_CACHE
                        this_bot_id = wecom_cfg.get("bot_id", "")
                        if this_bot_id and this_bot_id in _WECOM_BOT_OWNER:
                            existing_owner = _WECOM_BOT_OWNER[this_bot_id]
                            logger.warning(
                                "P1 STARTUP CHECK: bot_id=%s is already registered to another agent "
                                "(owner_process=%s, current_agent=%s). "
                                "Channel creation will be handled by from_config conflict detection.",
                                this_bot_id[:15],
                                existing_owner,
                                self.agent_id,
                            )
                        elif this_bot_id:
                            logger.info(
                                "P1 STARTUP CHECK: bot_id=%s is available for agent %s",
                                this_bot_id[:15],
                                self.agent_id,
                            )
                    except ImportError:
                        pass  # wecom module not available, skip check

            for channel_key, channel_cfg in agent_channels.items():
                if channel_key == "console" or not isinstance(channel_cfg, dict):
                    continue
                if not channel_cfg.get("enabled", False):
                    continue
                channel_cls = registry.get(channel_key)
                if not channel_cls or not hasattr(channel_cls, "from_config"):
                    continue
                try:
                    channel_config_obj = type("ChannelConfig", (), channel_cfg)()
                    ch = channel_cls.from_config(
                        process=_process_handler,
                        config=channel_config_obj,
                        show_tool_details=channel_cfg.get("show_tool_details", True),
                        filter_tool_messages=channel_cfg.get("filter_tool_messages", False),
                        filter_thinking=channel_cfg.get("filter_thinking", True),
                        workspace_dir=self.workspace_dir,
                    )
                    ch._workspace = self
                    channels_list.append(ch)
                    logger.info(f"Channel '{channel_key}' created for agent {self.agent_id}")
                except Exception as e:
                    logger.warning(f"Failed to create channel '{channel_key}': {e}")

        self.channel_manager = ChannelManager(channels_list)

        # Start channel manager consumer loops
        try:
            await self.channel_manager.start()
        except Exception as e:
            logger.warning(f"ChannelManager start failed (non-fatal): {e}")

        # TaskTracker and ChatManager are managed by ServiceManager above
        self.status = "running"
        logger.info(f"Workspace started: {self.agent_id}")

        # Start CronManager (heartbeat + scheduled tasks) in background
        try:
            from ..app.crons.manager import CronManager
            from ..app.crons.repo.json_repo import JsonJobRepository
            from ..config.timezone import normalize_tz
            crons_dir = self.workspace_dir / "crons"
            crons_dir.mkdir(parents=True, exist_ok=True)
            jobs_file = crons_dir / "jobs.json"
            if not jobs_file.exists():
                jobs_file.write_text('{"version": 1, "jobs": []}')
            cron_repo = JsonJobRepository(str(jobs_file))
            cfg = load_config()
            tz = normalize_tz(getattr(cfg, "user_timezone", None) or "UTC") or "UTC"
            self._cron_manager = CronManager(
                repo=cron_repo,
                runner=self.runner,
                channel_manager=self.channel_manager,
                timezone=tz,
                agent_id=self.agent_id,
            )
            await self._cron_manager.start()
            logger.info(f"CronManager started for agent {self.agent_id}")

            # 注册到全局 CronManagerRegistry
            if self.username and not self.is_global:
                try:
                    from ..app.crons.registry import get_registry
                    registry = get_registry()
                    if registry:
                        registry.register_manager(self.username, self._cron_manager)
                        logger.info(f"Registered workspace CronManager for {self.username} into global registry")
                except Exception as e:
                    logger.warning(f"Failed to register CronManager in registry: {e}")
        except Exception as e:
            logger.warning(f"CronManager start failed (non-fatal): {e}")
            self._cron_manager = None

        # Start AgentConfigWatcher (hot-reload on agent.json changes)
        try:
            from .agent_config_watcher import AgentConfigWatcher
            self._config_watcher = AgentConfigWatcher(
                agent_id=self.agent_id,
                workspace_dir=self.workspace_dir,
                workspace=self,
            )
            await self._config_watcher.start()
            logger.info(f"AgentConfigWatcher started for agent {self.agent_id}")
        except Exception as e:
            logger.warning(f"AgentConfigWatcher start failed (non-fatal): {e}")
            self._config_watcher = None

    async def stop(self):
        """Stop all workspace components."""
        if self.status != "running":
            return

        self.status = "stopped"

        # Stop config watcher first (if running)
        if self._config_watcher:
            try:
                await self._config_watcher.stop()
            except Exception as e:
                logger.warning(f"AgentConfigWatcher stop error: {e}")

        # Stop channel manager first (closes consumer loops)
        if self.channel_manager:
            try:
                await self.channel_manager.stop()
            except Exception as e:
                logger.warning(f"ChannelManager stop error: {e}")

        # Stop cron manager
        if getattr(self, "_cron_manager", None):
            try:
                await self._cron_manager.stop()
            except Exception as e:
                logger.warning(f"CronManager stop error: {e}")

        # Stop all services managed by ServiceManager (reverse priority order)
        if getattr(self, "_service_mgr", None):
            try:
                await self._service_mgr.stop_all()
            except Exception as e:
                logger.warning(f"ServiceManager stop_all error: {e}")

        logger.info(f"Workspace stopped: {self.agent_id}")

    async def chat(self, message: str, chat_id: str = "default",
                   username: str = None, **kwargs) -> str:
        """Process a chat message.

        Args:
            message: User message
            chat_id: Chat session ID
            username: Current user (for chat isolation)
            **kwargs: Additional parameters

        Returns:
            Agent response
        """
        if self.status != "running":
            raise RuntimeError(f"Agent {self.agent_id} is not running")

        if not self.core:
            raise RuntimeError(f"Agent {self.agent_id} core not initialized")

        # Build chat key with user isolation
        chat_key = f"{username}:{chat_id}" if username else chat_id

        # Get or create chat context
        is_new_chat = False
        if chat_key not in self._active_chats:
            is_new_chat = True
            self._active_chats[chat_key] = ChatContext(chat_id=chat_id, username=username)

        # Reset foundation memory for new chat session
        if is_new_chat and self.foundation_manager:
            self.foundation_manager.reset_injection_state()

        chat_context = self._active_chats[chat_key]
        chat_context.add_message("user", message)

        # Process through agent core (with foundation memory integration)
        response = await self.core.process(
            message=message,
            context=chat_context,
            memory=self.memory,
            compressor=self.compressor,
            skills=self.skills,
            tools=self.tools,
            **kwargs,
        )

        chat_context.add_message("assistant", response)

        return response

    @property
    def model(self) -> str:
        """Get the model name for this workspace."""
        if self.core:
            return self.core.model
        return "unknown"

    async def _get_chat_context(self, chat_id: str) -> 'ChatContext':
        """Get or create chat context for a chat session.
        
        This method is expected by the console router for SSE streaming.
        """
        chat_key = chat_id
        if chat_key not in self._active_chats:
            self._active_chats[chat_key] = ChatContext(chat_id=chat_id)
        return self._active_chats[chat_key]

    async def ensure_channel_manager(self) -> None:
        """Lazily initialize channel_manager if not yet created."""
        if self.channel_manager is not None:
            return
        # Create ConsoleChannel + additional channels from config
        from ..app.channels.console import ConsoleChannel
        from ..app.channels.manager import ChannelManager
        console_channel = ConsoleChannel(
            process=None,
            show_tool_details=True,
            filter_tool_messages=False,
            filter_thinking=True,
        )
        console_channel._workspace = self
        channels_list = [console_channel]
        agent_channels = self._config.get("channels", {}) if isinstance(self._config, dict) else {}
        for channel_key, channel_cfg in agent_channels.items():
            if channel_key == "console" or not isinstance(channel_cfg, dict):
                continue
            if not channel_cfg.get("enabled", False):
                continue
            from ..app.channels.registry import channel_registry as registry
            channel_cls = registry.get(channel_key)
            if not channel_cls or not hasattr(channel_cls, "from_config"):
                continue
            try:
                channel_config_obj = type("ChannelConfig", (), channel_cfg)()
                ch = channel_cls.from_config(
                    process=None,
                    config=channel_config_obj,
                    show_tool_details=channel_cfg.get("show_tool_details", True),
                    filter_tool_messages=channel_cfg.get("filter_tool_messages", False),
                    filter_thinking=channel_cfg.get("filter_thinking", True),
                    workspace_dir=self.workspace_dir,
                )
                ch._workspace = self
                channels_list.append(ch)
            except Exception:
                pass
        self.channel_manager = ChannelManager(channels_list)
        try:
            await self.channel_manager.start()
        except Exception:
            pass

    def get_info(self) -> Dict[str, Any]:
        """Get workspace information."""
        return {
            "agent_id": self.agent_id,
            "username": self.username,
            "is_global": self.is_global,
            "status": self.status,
            "model": self.model,
            "data_dir": str(self.data_dir),
            "workspace_dir": str(self.workspace_dir),
            "skills_dir": str(self.skills_dir),
            "active_chats": len(self._active_chats),
        }
