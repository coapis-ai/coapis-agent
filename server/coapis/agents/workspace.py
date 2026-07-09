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
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

from ..constant import AGENTS_DIR, WORKSPACES_DIR

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
        self._config: Dict[str, Any] = {}
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
            from ..config.config import derive_workspace_dir
            user_workspace = _get_user_workspace_dir(username)
            if agent_id.startswith("user:"):
                # Default user agent: workspace = workspaces/{username}/
                self.workspace_dir = derive_workspace_dir(agent_id, username)
            else:
                # Sub-agent: workspace = workspaces/{username}/agents/{agent_id}/
                self.workspace_dir = _get_user_agents_dir(username) / agent_id
            self.data_dir = self.workspace_dir / "agents" / agent_id
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

        IMPORTANT: Uses RELATIVE paths for symlinks to ensure they work correctly
        across Docker volume mounts. Absolute paths would point to wrong locations
        when the host path differs from the container path.
        """
        files_link = self.workspace_dir / "files"
        user_files_dir = WORKSPACES_DIR / self.username / "files"

        # Create target directory if it doesn't exist
        user_files_dir.mkdir(parents=True, exist_ok=True)

        # Calculate RELATIVE path from files_link to user_files_dir
        # This ensures the symlink works correctly regardless of volume mount paths
        try:
            rel_target = os.path.relpath(user_files_dir, files_link.parent)
        except ValueError:
            # On Windows, relpath fails for different drives - fallback to absolute
            rel_target = str(user_files_dir)

        # Handle different states of the symlink
        if files_link.is_symlink():
            # Existing symlink - verify it points to the correct location
            current_target = files_link.resolve()
            expected_target = user_files_dir.resolve()
            if current_target != expected_target:
                logger.warning(
                    f"Workspace files symlink points to wrong location. "
                    f"Removing and recreating: {current_target} -> {expected_target}"
                )
                files_link.unlink()
                files_link.symlink_to(rel_target)
                logger.info(
                    f"Recreated files symlink for user {self.username}: "
                    f"{files_link} -> {rel_target} (relative)"
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
            # Create the symlink with RELATIVE path
            files_link.symlink_to(rel_target)
            logger.info(
                f"Created files symlink for user {self.username}: "
                f"{files_link} -> {rel_target} (relative)"
            )

    def set_manager(self, manager: Any) -> None:
        """Set the parent MultiAgentManager reference."""
        self._manager = manager

    def _ensure_identity_files(self) -> None:
        """Copy identity template files to workspace if missing.

        Sub-agents (non-user, non-global) get a slim set:
        only SOUL.md, PROFILE.md, AGENTS.md (from agent_level/ if available).
        User default agents and global agents get the full set.
        """
        try:
            from coapis.constant import TEMPLATES_DIR
            import shutil

            if not TEMPLATES_DIR.exists():
                logger.warning("TEMPLATES_DIR not found: %s", TEMPLATES_DIR)
                return

            # Determine if this is a sub-agent (not a user default or global agent)
            aid = self.agent_id
            is_sub_agent = (
                not aid.startswith("user:")
                and not aid.startswith("global_")
                and not self.is_global
            )

            if is_sub_agent:
                identity_files = ["AGENTS.md", "SOUL.md", "PROFILE.md", "MEMORY.md"]
                layer_dir = TEMPLATES_DIR / "agent_level"
            else:
                identity_files = [
                    "AGENTS.md", "SOUL.md", "PROFILE.md",
                    "MEMORY.md", "BOOTSTRAP.md", "HEARTBEAT.md",
                ]
                layer_dir = TEMPLATES_DIR / "user_level"

            copied = 0
            for fname in identity_files:
                dst = self.workspace_dir / fname
                if dst.exists():
                    continue
                # Layer-specific template first, then global fallback
                src = layer_dir / fname if layer_dir.exists() else TEMPLATES_DIR / fname
                if not src.exists():
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
            # Session messages are stored under workspace_dir/sessions/ by default.
            # For the default user agent (user:{username}), store sessions under
            # workspaces/{username}/sessions/ for backward compatibility.
            # For user sub-agents, store sessions under their own workspace
            # (workspaces/{username}/agents/{id}/sessions/) to keep messages isolated.
            try:
                from ..app.runner.session import SafeJSONSession
                if self.username and self.agent_id == f"user:{self.username}":
                    session_dir = str(_get_user_workspace_dir(self.username) / "sessions")
                elif self.username:
                    session_dir = str(self.workspace_dir / "sessions")
                else:
                    session_dir = str(self.workspace_dir / "sessions")
                r.session = SafeJSONSession(save_dir=session_dir)
            except Exception:
                pass
            r._health = True
            # Wire ChatManager for session persistence
            if self.chat_manager:
                r.set_chat_manager(self.chat_manager)
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

            # Global-inherited defaults (mcp/security/running/etc.)
            # These are NOT in agent.json or fallback — loaded from global config
            global_inherited = {}
            try:
                from ..config.config import AgentsRunningConfig, AgentsLLMRoutingConfig
                global_inherited = {
                    "mcp": getattr(root_config, "mcp", None),
                    "security": getattr(root_config, "security", None),
                    "acp": getattr(root_config, "acp", None),
                    "running": getattr(root_config.agents, "running", None) or AgentsRunningConfig(),
                    "llm_routing": getattr(root_config.agents, "llm_routing", None) or AgentsLLMRoutingConfig(),
                    "heartbeat": getattr(getattr(root_config.agents, "defaults", None), "heartbeat", None),
                    "channels": None,  # Do NOT inherit system-level channels
                }
            except Exception:
                pass

            try:
                default_config = build_fallback_agent_profile_config(self.agent_id, root_config, username=self.username).model_dump()
            except Exception:
                # Agent not in config.json - use minimal defaults
                default_config = {
                    "id": self.agent_id,
                    "name": self.agent_id,
                    "description": "",
                    "workspace_dir": ".",
                }

            try:
                file_config = load_agent_config(self.agent_id, workspace_dir=self.workspace_dir, username=self.username)
                # exclude_unset=True: only overlay fields explicitly set in agent.json,
                # don't let Pydantic defaults overwrite global-inherited values.
                file_config_dict = file_config.model_dump(exclude_unset=True) if hasattr(file_config, 'model_dump') else file_config
                config = {**global_inherited, **default_config, **file_config_dict, **raw_agent_config}
            except Exception:
                config = {**global_inherited, **default_config, **raw_agent_config}
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
            import os as _os
            if _os.environ.get("COAPIS_SKIP_PROVIDERS", "").strip() in ("1", "true", "yes"):
                logger.warning(f"No provider for agent {self.agent_id} (COAPIS_SKIP_PROVIDERS=1). "
                               "LLM features will be unavailable until a provider is configured.")
                core_config["model"] = core_config.get("model") or "placeholder"
                core_config["base_url"] = core_config.get("base_url") or "http://localhost:1"
                core_config["api_key"] = core_config.get("api_key") or "EMPTY"
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

                # Apply global tool config: deny disabled tools
                # Tool enabled/disabled is managed ONLY at global config.tools level,
                # not per-agent in agent.json.
                try:
                    from ..config import load_config as _load_global_config
                    global_cfg = _load_global_config()
                    if global_cfg.tools and global_cfg.tools.builtin_tools:
                        for tool_name, tool_cfg in global_cfg.tools.builtin_tools.items():
                            if not tool_cfg.enabled:
                                if tool_name not in registry._denied_tools:
                                    registry._denied_tools.append(tool_name)
                                    logger.info("Denied tool (disabled in global config): %s", tool_name)
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
        # MUST use workspace_dir / "chat" to align with multi_agent_manager
        # and service_factories. Using data_dir would point to a different
        # path for user:xxx agents, causing frontend/backend chats.json mismatch.
        def _create_chat_manager(ws):
            from ..app.runner.manager import ChatManager
            from ..app.runner.repo.json_repo import JsonChatRepository
            repo_dir = ws.workspace_dir / "chat"
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
                    Event, Message, TextContent, RunStatus, MessageType
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

                # ── Dream优化 + 轨迹清理 + B桶自动晋升 (新会话触发) ──
                if _is_new_chat and self.evolution_engine:
                    import time as _time

                    # 1. Dream优化：每24小时整理一次 MEMORY.md
                    try:
                        _dream_file = self.evolution_engine.data_dir / "evolution" / "last_dream.txt"
                        _last_dream = 0.0
                        if _dream_file.exists():
                            try:
                                _last_dream = float(_dream_file.read_text().strip())
                            except (ValueError, OSError):
                                pass
                        if _time.time() - _last_dream > 86400:
                            _dream_file.parent.mkdir(parents=True, exist_ok=True)
                            _dream_file.write_text(str(_time.time()))
                            asyncio.create_task(
                                self.evolution_engine._trigger_dream_optimization()
                            )
                            logger.info("[Dream] Triggered dream optimization (last=%.0fs ago)", _time.time() - _last_dream)
                    except Exception as dream_err:
                        logger.debug("[Dream] Trigger skipped: %s", dream_err)

                    # 2. 轨迹清理：删除30天前的旧轨迹文件
                    try:
                        _traj_dir = self.evolution_engine.data_dir / "evolution" / "trajectories"
                        if _traj_dir.exists():
                            _cutoff = _time.time() - 30 * 86400
                            _cleaned = 0
                            for _f in _traj_dir.glob("*.jsonl"):
                                if _f.stat().st_mtime < _cutoff:
                                    _f.unlink()
                                    _cleaned += 1
                            if _cleaned:
                                logger.info("[Evolution] Cleaned %d old trajectory files", _cleaned)
                    except Exception as cleanup_err:
                        logger.debug("[Trajectory] Cleanup skipped: %s", cleanup_err)

                    # 3. B桶自动晋升：扫描并晋升高置信度经验
                    try:
                        if hasattr(self, 'cross_agent_evolution') and self.cross_agent_evolution:
                            _result = self.cross_agent_evolution.auto_review_and_promote()
                            if _result.get("promoted") or _result.get("to_foundation"):
                                logger.info(
                                    "[Evolution] B-bucket auto-review: %d promoted, %d to foundation",
                                    _result.get("promoted", 0), _result.get("to_foundation", 0),
                                )
                    except Exception as review_err:
                        logger.debug("[Evolution] B-bucket review skipped: %s", review_err)

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

                # ── Core stream: delegate to runner.stream_query() ──
                # stream_query() calls query_handler() internally, then passes
                # (msg, last) tuples through adapt_agentscope_message_stream adapter
                # to produce proper Events (Message, TextContent, DataContent)
                # with correct lifecycle, delta tracking, and per-type msg_ids.
                async for event in self.runner.stream_query(request_obj):
                    yield event

                # Post-stream: evolution hooks + cleanup
                # NOTE: Persistence, display config, phase management, and
                # Event construction are all handled by runner.stream_query()
                # + adapt_agentscope_message_stream adapter.

                # ── Evolution: on_session_end ──
                if self.evolution_engine:
                    try:
                        await self.evolution_engine.on_session_end()
                    except Exception as evo_err:
                        logger.debug("Evolution on_session_end failed: %s", evo_err)

            return _stream(request)

        console_channel = ConsoleChannel(
            process=_process_handler,
            show_tool_details=True,
            filter_tool_messages=False,
            filter_thinking=False,
        )
        console_channel._workspace = self

        # Try to create additional channels from agent config
        from ..app.channels.manager import ChannelManager
        channels_list = [console_channel]

        _cfg = getattr(self, "_config", None) or self.config
        agent_channels = (
            _cfg.get("channels", {})
            if isinstance(_cfg, dict)
            else {}
        )
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
                        filter_thinking=channel_cfg.get("filter_thinking", False),
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
            filter_thinking=False,
        )
        console_channel._workspace = self
        channels_list = [console_channel]
        _cfg = getattr(self, "_config", None) or self.config
        agent_channels = (
            _cfg.get("channels", {})
            if isinstance(_cfg, dict)
            else {}
        )
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
                    filter_thinking=channel_cfg.get("filter_thinking", False),
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
