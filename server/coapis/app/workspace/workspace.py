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

"""Workspace: Encapsulates a complete independent agent runtime.

Each Workspace represents a standalone agent workspace with its own:
- Runner (request processing)
- ChannelManager (communication channels)
- BaseMemoryManager (conversation memory)
- MCPClientManager (MCP tool clients)
- CronManager (scheduled tasks)

All existing single-agent components are reused without modification.
"""
import logging
from pathlib import Path
from typing import Optional

from coapis.config.timezone import normalize_tz
from coapis.config.utils import load_config

from .service_manager import ServiceDescriptor, ServiceManager
from .service_factories import (
    create_mcp_service,
    create_chat_service,
    create_channel_service,
    create_agent_config_watcher,
    create_mcp_config_watcher,
)
from ..runner import AgentRunner
from ..runner.task_tracker import TaskTracker
from ..mcp import MCPClientManager
from ..crons.manager import CronManager
from ..crons.repo.json_repo import JsonJobRepository
from ...evolution.evolution_engine import EvolutionEngine, EvolutionConfig
from ...config.config import load_agent_config
from ...constant import WORKSPACES_DIR, SYSTEM_DIR

logger = logging.getLogger(__name__)


class Workspace:
    """Single agent workspace with complete runtime components.

    Each Workspace is an independent agent instance with its own:
    - Runner: Processes agent requests
    - ChannelManager: Manages communication channels
    - BaseMemoryManager: Manages conversation memory
    - MCPClientManager: Manages MCP tool clients
    - CronManager: Manages scheduled tasks

    All components use existing single-agent code without modification.
    """

    def __init__(self, agent_id: str, workspace_dir: str,
                 username: str | None = None, is_global: bool = False,
                 owner_role: str | None = None):
        """Initialize agent instance.

        Args:
            agent_id: Unique agent identifier
            workspace_dir: Path to agent's workspace directory
            username: Owner username (for user-scoped workspaces)
            is_global: True if this is a global (system) workspace
            owner_role: Explicit permission role for this workspace owner
                        (e.g. 'admin', 'user'). If None, resolved at runtime
                        from user_store via self.username.
        """
        self.agent_id = agent_id
        self.workspace_dir = Path(workspace_dir).expanduser()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.username = username
        self.is_global = is_global
        self._owner_role = owner_role  # Permission role (admin/user)

    @property
    def resolved_role(self) -> str:
        """Resolve the owner's permission role.

        Priority: explicit owner_role → user_store lookup via username → 'user'
        """
        if self._owner_role:
            return self._owner_role
        if self.username:
            try:
                from ..user_store import get_user
                user_info = get_user(self.username)
                if user_info:
                    return user_info.get("role", "user")
            except Exception:
                pass
        return "user"
        self._ensure_identity_files()

        # Link user's "My Space" files into workspace so agent tools can access them
        # User files are stored at workspaces/{username}/files/ but agent workspace
        # is at workspaces/{username}/agents/{agent_id}/ — they're in different subdirs.
        # Create a symlink so the agent's read_file/write_file tools can find them.
        if username and not is_global:
            self._link_user_files()

        # Service manager (unified component management)
        self._service_manager = ServiceManager(self)

        # Non-service state
        self._config = None  # Loaded before start()
        self._started = False
        self._manager = None  # Reference to MultiAgentManager
        self._task_tracker = TaskTracker()
        self.evolution_engine: EvolutionEngine | None = None

        # Register all services
        self._register_services()

        logger.debug(
            f"Created Workspace: {agent_id} at {self.workspace_dir}",
        )

    def _link_user_files(self):
        """Create symlink from workspace/files -> workspaces/{username}/files/.

        This bridges the physical separation between:
        - Agent workspace: workspaces/{username}/agents/{agent_id}/
        - User files: workspaces/{username}/files/

        Without this symlink, agent tools (read_file, write_file, etc.)
        cannot access user files stored in "My Space".
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
            # A real directory or file exists at this path - this shouldn't happen
            # in a properly configured system, but handle it gracefully
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

    def _ensure_identity_files(self) -> None:
        """Copy identity template files to workspace if missing."""
        try:
            from ...constant import TEMPLATES_DIR
            import shutil

            if not TEMPLATES_DIR.exists():
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
                    "Copied %d identity files to %s",
                    copied, self.workspace_dir,
                )
        except Exception as e:
            logger.warning(
                "Failed to ensure identity files for %s: %s",
                self.workspace_dir, e,
                exc_info=True,
            )

    # Service access via properties (delegates to ServiceManager)
    @property
    def runner(self) -> Optional[AgentRunner]:
        """Get runner instance from ServiceManager."""
        return self._service_manager.services.get("runner")

    @property
    def memory_manager(self):
        """Get memory manager instance from ServiceManager."""
        return self._service_manager.services.get("memory_manager")

    @property
    def context_manager(self):
        """Get context manager instance from ServiceManager."""
        return self._service_manager.services.get("context_manager")

    @property
    def mcp_manager(self):
        """Get MCP manager instance from ServiceManager."""
        return self._service_manager.services.get("mcp_manager")

    @property
    def chat_manager(self):
        """Get chat manager instance from ServiceManager."""
        return self._service_manager.services.get("chat_manager")

    @property
    def channel_manager(self):
        """Get channel manager instance from ServiceManager."""
        return self._service_manager.services.get("channel_manager")

    @property
    def cron_manager(self):
        """Get cron manager instance from ServiceManager."""
        return self._service_manager.services.get("cron_manager")

    # Non-service state
    @property
    def task_tracker(self) -> TaskTracker:
        """Get task tracker for background chat and reconnect."""
        return self._task_tracker

    @property
    def config(self):
        """Get agent configuration."""
        self._config = load_agent_config(self.agent_id)
        return self._config

    def set_manager(self, manager) -> None:
        """Set reference to MultiAgentManager for /daemon restart.

        Args:
            manager: MultiAgentManager instance
        """
        self._manager = manager
        # Pass to runner for /daemon restart command
        if self.runner is not None:
            self.runner._manager = manager  # pylint: disable=protected-access

    def _register_services(  # pylint: disable=too-many-statements
        self,
    ) -> None:
        """Register all workspace services with ServiceManager.

        Uses declarative ServiceDescriptor configuration to replace
        hardcoded initialization logic.
        """
        # pylint: disable=protected-access
        from ...agents.memory.base_memory_manager import (
            get_memory_manager_backend,
        )
        from ...agents.context.base_context_manager import (
            get_context_manager_backend,
        )

        sm = self._service_manager

        # Priority 10: Runner
        sm.register(
            ServiceDescriptor(
                name="runner",
                service_class=AgentRunner,
                init_args=lambda ws: {
                    "agent_id": ws.agent_id,
                    "workspace_dir": ws.workspace_dir,
                    "task_tracker": ws._task_tracker,
                },
                stop_method="stop",
                priority=10,
                concurrent_init=False,
            ),
        )

        # Priority 20: Core services (concurrent)
        sm.register(
            ServiceDescriptor(
                name="memory_manager",
                service_class=lambda ws: get_memory_manager_backend(
                    ws._config.running.memory_manager_backend,
                ),
                init_args=lambda ws: {
                    "working_dir": str(ws.workspace_dir),
                    "agent_id": ws.agent_id,
                },
                post_init=lambda ws, mm: setattr(
                    ws._service_manager.services["runner"],
                    "memory_manager",
                    mm,
                ),
                start_method="start",
                stop_method="close",
                reusable=True,
                priority=20,
                concurrent_init=True,
            ),
        )

        sm.register(
            ServiceDescriptor(
                name="context_manager",
                service_class=lambda ws: get_context_manager_backend(
                    ws._config.running.context_manager_backend,
                ),
                init_args=lambda ws: {
                    "working_dir": str(ws.workspace_dir),
                    "agent_id": ws.agent_id,
                },
                post_init=lambda ws, cm: setattr(
                    ws._service_manager.services["runner"],
                    "context_manager",
                    cm,
                ),
                start_method="start",
                stop_method="close",
                reusable=True,
                priority=20,
                concurrent_init=True,
            ),
        )

        sm.register(
            ServiceDescriptor(
                name="mcp_manager",
                service_class=MCPClientManager,
                post_init=create_mcp_service,
                stop_method="close_all",
                priority=20,
                concurrent_init=True,
            ),
        )

        sm.register(
            ServiceDescriptor(
                name="chat_manager",
                service_class=None,
                post_init=create_chat_service,
                reusable=True,
                priority=20,
                concurrent_init=True,
            ),
        )

        # Priority 25: Runner start
        sm.register(
            ServiceDescriptor(
                name="runner_start",
                service_class=None,
                post_init=lambda ws, _: ws._service_manager.services[
                    "runner"
                ].start(),
                priority=25,
                concurrent_init=False,
            ),
        )

        # Priority 30: Channel manager
        sm.register(
            ServiceDescriptor(
                name="channel_manager",
                service_class=None,
                post_init=create_channel_service,
                start_method="start_all",
                stop_method="stop_all",
                priority=30,
                concurrent_init=False,
            ),
        )

        # Priority 40: Cron manager
        sm.register(
            ServiceDescriptor(
                name="cron_manager",
                service_class=CronManager,
                init_args=lambda ws: {  # pylint: disable=protected-access
                    "repo": JsonJobRepository(
                        str(ws.workspace_dir / "jobs.json"),
                    ),
                    "runner": ws._service_manager.services["runner"],
                    "channel_manager": ws._service_manager.services.get(
                        "channel_manager",
                    ),
                    "timezone": normalize_tz(
                        load_config().user_timezone or "UTC",
                    )
                    or "UTC",
                    "agent_id": ws.agent_id,
                },
                start_method="start",
                stop_method="stop",
                priority=40,
                concurrent_init=False,
            ),
        )

        # Priority 50: Agent Config Watcher (conditional)
        sm.register(
            ServiceDescriptor(
                name="agent_config_watcher",
                service_class=None,
                post_init=create_agent_config_watcher,
                start_method="start",
                stop_method="stop",
                priority=50,
                concurrent_init=False,
            ),
        )

        # Priority 51: MCP Config Watcher (conditional)
        sm.register(
            ServiceDescriptor(
                name="mcp_config_watcher",
                service_class=None,
                post_init=create_mcp_config_watcher,
                start_method="start",
                stop_method="stop",
                priority=51,
                concurrent_init=False,
            ),
        )

    async def set_reusable_components(self, components: dict) -> None:
        """Set components to reuse from previous instance.

        Must be called BEFORE start(). Allows reusing components that support
        hot-reload without recreating them. If a service has a reload_func,
        it will be called during this process.

        Args:
            components: Dict mapping component name to instance.
                Supported keys:
                - 'memory_manager': BaseMemoryManager instance
                - 'context_manager': BaseContextManager instance
                - 'chat_manager': ChatManager instance

        Example:
            new_ws = Workspace("default", workspace_dir)
            await new_ws.set_reusable_components({
                'memory_manager': old_ws.memory_manager,
                'chat_manager': old_ws.chat_manager,
            })
            await new_ws.start()
        """
        if self._started:
            logger.warning(
                f"Cannot set reusable components for already started "
                f"workspace: {self.agent_id}",
            )
            return

        # Delegate to ServiceManager
        for name, component in components.items():
            await self._service_manager.set_reusable(name, component)

    def _init_evolution_engine(self) -> None:
        """Initialize EvolutionEngine for this workspace.
        
        Creates user-scoped evolution engine with proper data directories.
        """
        try:
            from ...constant import SYSTEM_DIR
            
            # Load evolution config from system config
            config = load_config()
            evo_config_data = getattr(config, "evolution", {}) or {}
            evo_config = EvolutionConfig.from_dict(evo_config_data)
            
            # v0.5.1: Evolution data centralized in SYSTEM_DIR/evolution/ for user agents.
            # Global agents keep evolution in agents/{agent_id}/evolution/.
            from ...constant import SYSTEM_EVOLUTION_DIR
            if self.username and not self.is_global:
                evo_dir = SYSTEM_EVOLUTION_DIR
                memory_workspace = self.workspace_dir
            else:
                evo_dir = self.workspace_dir / "evolution"
                memory_workspace = self.workspace_dir
            
            evo_dir.mkdir(parents=True, exist_ok=True)
            
            # Create the engine (agent_id is set via on_session_start)
            self.evolution_engine = EvolutionEngine(
                data_dir=str(evo_dir),
                workspace_dir=str(memory_workspace),
                config=evo_config,
            )

            # Initialize CrossAgentEvolution (AB bucket + AI review)
            try:
                from ...evolution.cross_agent_evolution import (
                    CrossAgentEvolution,
                    CrossAgentEvolutionConfig,
                )
                cross_config = CrossAgentEvolutionConfig(
                    enabled=evo_config.enabled,
                )
                self.cross_agent_evolution = CrossAgentEvolution(
                    data_dir=str(evo_dir),
                    config=cross_config,
                )
                # Start background periodic review task
                self.cross_agent_evolution.start_periodic_review()
                logger.info(
                    "CrossAgentEvolution initialized for %s",
                    self.agent_id,
                )
            except Exception as ce:
                logger.warning(
                    "CrossAgentEvolution init failed (non-fatal): %s",
                    ce,
                )
                self.cross_agent_evolution = None

            # Initialize KnowledgeFlow (layer promotion)
            try:
                from ...evolution.knowledge_flow import (
                    KnowledgeFlow,
                    FlowConfig,
                )
                from ...foundation.foundation_manager import FoundationManager
                foundation_dir = WORKSPACES_DIR / "foundation"
                if not foundation_dir.exists():
                    foundation_dir = evo_dir.parent / "foundation"
                foundation_mgr = None
                if foundation_dir.exists():
                    foundation_mgr = FoundationManager(foundation_dir)
                self.knowledge_flow = KnowledgeFlow(
                    data_dir=str(evo_dir),
                    foundation_manager=foundation_mgr,
                    config=FlowConfig(),
                )
                logger.info(
                    "KnowledgeFlow initialized for %s",
                    self.agent_id,
                )
            except Exception as ke:
                logger.warning(
                    "KnowledgeFlow init failed (non-fatal): %s",
                    ke,
                )
                self.knowledge_flow = None

            # Link to runner if available
            runner = self.runner
            if runner is not None:
                runner.set_workspace(self)

            logger.info(
                f"EvolutionEngine initialized for {self.agent_id} "
                f"(dir={evo_dir}, enabled={evo_config.enabled})"
            )
        except Exception as e:
            logger.warning(
                f"Failed to initialize EvolutionEngine for {self.agent_id}: {e}",
                exc_info=True,
            )
            self.evolution_engine = None

    async def start(self):
        """Start workspace and initialize all components."""
        if self._started:
            logger.debug(f"Workspace already started: {self.agent_id}")
            # Still ensure files symlink exists (for cached workspace reuse)
            if self.username and not self.is_global:
                self._link_user_files()
            return

        logger.info(f"Starting workspace: {self.agent_id}")

        # Ensure files symlink exists before starting services
        if self.username and not self.is_global:
            self._link_user_files()

        from ...agents.skills_manager import (
            ensure_skill_pool_initialized,
        )

        try:
            ensure_skill_pool_initialized()
        except Exception as e:
            logger.warning(
                f"Skill pool initialization failed (non-fatal): {e}",
            )

        try:
            # 1. Load agent configuration
            self._config = load_agent_config(self.agent_id)
            logger.debug(f"Loaded config for agent: {self.agent_id}")

            # 1.5. Initialize EvolutionEngine
            self._init_evolution_engine()

            # 2. Start all services via ServiceManager
            await self._service_manager.start_all()

            self._started = True
            logger.info(f"Workspace started successfully: {self.agent_id}")

        except Exception as e:
            logger.error(
                f"Failed to start agent instance {self.agent_id}: {e}",
            )
            # Clean up partially started components
            await self.stop()
            raise

    async def stop(self, final: bool = True):
        """Stop agent instance and clean up all resources.

        Args:
            final: If True (default), stop ALL services including reusable.
                   If False, skip reusable services (for reload scenario).
        """
        if not self._started:
            logger.debug(f"Workspace not started: {self.agent_id}")
            return

        logger.info(
            f"Stopping agent instance: {self.agent_id} (final={final})",
        )

        # Stop all services via ServiceManager (handles reuse automatically)
        await self._service_manager.stop_all(final=final)

        self._started = False
        logger.info(f"Workspace stopped: {self.agent_id}")

    def __repr__(self) -> str:
        """String representation of workspace."""
        status = "started" if self._started else "stopped"
        return (
            f"Workspace(id={self.agent_id}, "
            f"workspace={self.workspace_dir}, "
            f"status={status})"
        )
