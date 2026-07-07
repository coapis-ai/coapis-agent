# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
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

"""MultiAgentManager - Manages multiple agent workspaces with user isolation.

Supports:
- Global agents (system-level, shared by all users)
- User agents (user-level, isolated per user)
- Dynamic agent creation/destruction
- Agent lifecycle management
- Chat routing to agents
- Workspace isolation
- Auto-recovery from persisted data on restart

Directory structure:
~/.coapis/
├── agents/              ← Global agents (system-level)
├── data/{username}/     ← User isolated storage
│   ├── agents/          ← User custom agents
│   ├── skills/          ← User custom skills
│   ├── workflows/       ← User custom workflows
│   └── chats/           ← User chat history
"""

import asyncio
import json
import time

from agentscope_runtime.engine.schemas.exception import ConfigurationException
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

from ..agents.workspace import Workspace
from ..config import load_config
from ..constant import AGENTS_DIR, WORKSPACES_DIR
from ..app.user_store import get_user_agents_dir, get_user_workspace_dir

logger = logging.getLogger(__name__)


class MultiAgentManager:
    """Manages multiple agent workspaces with user isolation."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._workspaces: Dict[str, Workspace] = {}  # agent_id -> Workspace
        self._user_agents: Dict[str, List[str]] = {}  # username -> [agent_ids]
        self._lock = asyncio.Lock()
        self._pending_starts: Dict[str, asyncio.Event] = {}  # agent_id -> Event
        self._user_chat_managers: Dict[str, Any] = {}  # username -> ChatManager
    @property
    def agents(self) -> Dict[str, Workspace]:
        """Alias for _workspaces for compatibility."""
        return self._workspaces

    def get_user_chat_manager(self, username: str):
        """Get or create a per-user ChatManager with isolated storage.

        Each user gets their own ChatManager backed by
        workspaces/{username}/chat/chats.json, ensuring complete
        chat isolation between users.

        Args:
            username: The authenticated username

        Returns:
            ChatManager instance for this user
        """
        if username in self._user_chat_managers:
            return self._user_chat_managers[username]

        from .runner.manager import ChatManager
        from .runner.repo.json_repo import JsonChatRepository

        chats_dir = WORKSPACES_DIR / username / "chat"
        chats_dir.mkdir(parents=True, exist_ok=True)
        chats_path = chats_dir / "chats.json"
        chat_repo = JsonChatRepository(chats_path)
        cm = ChatManager(repo=chat_repo)
        self._user_chat_managers[username] = cm
        logger.info(f"Created user ChatManager: {chats_path}")
        return cm

    def get_all_user_chat_managers(self) -> Dict[str, Any]:
        """Get all existing user ChatManagers (for admin aggregation).

        Scans workspaces/ directory for users with chat/chats.json
        and returns a dict of username -> ChatManager.

        Returns:
            Dict mapping username to ChatManager instances
        """
        result = {}
        if WORKSPACES_DIR.exists():
            for user_dir in WORKSPACES_DIR.iterdir():
                if user_dir.is_dir() and not user_dir.name.startswith("."):
                    username = user_dir.name
                    result[username] = self.get_user_chat_manager(username)
        return result

    async def create_agent(
        self,
        agent_id: str,
        config: Dict[str, Any] = None,
        username: str = None,
        is_global: bool = True,
    ) -> Workspace:
        """Create a new agent workspace (lightweight registration only).

        Registers the workspace in memory and user registry but does NOT
        start runtime services (MCP, channels, cron). Those are started
        lazily on first use via get_agent().

        Uses composite cache key "{username}:{agent_id}" for user isolation.

        Args:
            agent_id: Unique agent identifier
            config: Agent configuration
            username: Owner username (None for global agents)
            is_global: If True, agent is shared by all users

        Returns:
            Workspace instance (not yet started)
        """
        # Composite key for user isolation
        cache_key = f"{username}:{agent_id}" if username else f"global:{agent_id}"

        async with self._lock:
            if cache_key in self._workspaces:
                logger.warning(f"Agent already exists: {cache_key}")
                return self._workspaces[cache_key]

            # Determine workspace_dir from config (fix: was missing, causing parameter misalignment)
            workspace_dir = None
            if config and isinstance(config, dict):
                workspace_dir = config.get("workspace_dir")

            # Determine workspace type
            workspace = Workspace(
                agent_id=agent_id,
                username=username,
                is_global=is_global,
                workspace_dir=Path(workspace_dir) if workspace_dir else None,
            )
            if config:
                workspace.config = config

            # Set back-reference to MultiAgentManager so runner can
            # access per-user ChatManagers for message persistence
            workspace._manager = self

            # Register workspace BEFORE start() so it appears in list_agents
            # even if start() fails (e.g. no provider configured).
            # This ensures the agent dropdown is always populated.
            self._workspaces[cache_key] = workspace
            if username and not is_global:
                if username not in self._user_agents:
                    self._user_agents[username] = []
                if agent_id not in self._user_agents[username]:
                    self._user_agents[username].append(agent_id)

            # NOTE: Do NOT call workspace.start() here.
            # Runtime services (MCP, channels, cron) are started lazily
            # on first use via get_agent(). This keeps create_agent fast (<1s).
            scope = "user" if (username and not is_global) else "global"
            logger.info(f"Created {scope} agent: {cache_key}" + (f" (user: {username})" if username else ""))
            return workspace

    async def destroy_agent(self, agent_id: str, username: str = None) -> bool:
        """Stop and destroy an agent workspace.

        Args:
            agent_id: Agent identifier
            username: Owner username (None for global agents)

        Returns:
            True if destroyed successfully
        """
        cache_key = f"{username}:{agent_id}" if username else f"global:{agent_id}"

        async with self._lock:
            if cache_key not in self._workspaces:
                # Fallback: try old key format for backward compatibility
                if agent_id in self._workspaces:
                    cache_key = agent_id
                else:
                    return False

            workspace = self._workspaces[cache_key]
            # Skip stop() if workspace was never started (lazy-init optimization)
            if getattr(workspace, "status", "stopped") == "running":
                await workspace.stop()
            del self._workspaces[cache_key]

            # Clean up from user tracking
            for uname, agent_ids in self._user_agents.items():
                if agent_id in agent_ids:
                    agent_ids.remove(agent_id)
                    if not agent_ids:
                        del self._user_agents[uname]
                    break

            # Clean up persisted agent directory
            if workspace.username:
                agent_dir = get_user_agents_dir(workspace.username) / agent_id
            else:
                agent_dir = AGENTS_DIR / agent_id

            if agent_dir.exists():
                import shutil
                shutil.rmtree(agent_dir)
                logger.info(f"Cleaned up agent directory: {agent_dir}")

            logger.info(f"Destroyed agent: {agent_id}")
            return True

    def get_workspace(self, agent_id: str, username: str = None) -> Optional[Workspace]:
        """Get workspace by agent ID (supports user isolation).
        
        Tries user-specific key first, then falls back to global key.
        This ensures global agents (like 'default') are accessible to all users.
        """
        # Try user-specific key first
        if username:
            cache_key = f"{username}:{agent_id}"
            ws = self._workspaces.get(cache_key)
            if ws:
                return ws
            # Fallback to global key for global agents
            cache_key = f"global:{agent_id}"
            ws = self._workspaces.get(cache_key)
            if ws:
                return ws
        
        # No username: try global key only
        cache_key = f"global:{agent_id}"
        return self._workspaces.get(cache_key)

    async def invalidate_workspaces_by_provider(self, provider_id: str) -> int:
        """Remove cached workspaces that reference a deleted provider.

        When a provider is deleted via the API, any workspace that was
        initialized with that provider becomes stale (cached config points
        to a non-existent provider). This method scans all cached workspaces
        and evicts those whose config references the deleted provider,
        forcing them to be re-initialized with a valid provider on next access.

        Checks TWO sources:
        1. agent.json (source of truth for what the user wants)
        2. Workspace's cached config (what was actually used at init time)

        This catches both cases:
        - User hasn't changed config yet → agent.json still references deleted provider
        - User changed agent.json but workspace cache is stale → cached config still uses deleted provider

        Returns:
            Number of workspaces evicted from cache.
        """
        evicted = []
        for cache_key, workspace in self._workspaces.items():
            should_evict = False

            # Check 1: workspace's cached config (what was actually initialized with)
            cached_config = getattr(workspace, '_config', {})
            if isinstance(cached_config, dict):
                cached_am = cached_config.get("active_model", {})
                cached_provider = None
                if isinstance(cached_am, dict):
                    cached_provider = cached_am.get("provider_id")
                if not cached_provider:
                    cached_provider = cached_config.get("provider")
                if cached_provider == provider_id:
                    should_evict = True

            # Check 2: agent.json (source of truth for user intent)
            if not should_evict:
                try:
                    agent_json_path = workspace.workspace_dir / "agent.json"
                    if agent_json_path.exists():
                        import json as _json
                        with open(agent_json_path) as f:
                            agent_cfg = _json.load(f)
                        active_model = agent_cfg.get("active_model", {})
                        referenced_provider = None
                        if isinstance(active_model, dict):
                            referenced_provider = active_model.get("provider_id")
                        if not referenced_provider:
                            referenced_provider = agent_cfg.get("provider")
                        if referenced_provider == provider_id:
                            should_evict = True
                except Exception as e:
                    logger.warning(f"Failed to check agent.json for workspace {cache_key}: {e}")

            if should_evict:
                evicted.append(cache_key)

        # Evict stale workspaces under lock
        if evicted:
            async with self._lock:
                for key in evicted:
                    ws = self._workspaces.pop(key, None)
                    if ws:
                        # Reset cached LLM client to force re-creation
                        if hasattr(ws, 'core') and ws.core:
                            ws.core._client = None
                        logger.info(f"Evicted stale workspace {key} (provider '{provider_id}' deleted)")

        return len(evicted)

    def get_user_agents(self, username: str) -> List[Dict[str, Any]]:
        """Get all agents for a specific user (global + user-specific)."""
        result = []

        # Add global agents (key starts with "global:")
        for cache_key, workspace in self._workspaces.items():
            if cache_key.startswith("global:") and workspace.is_global:
                result.append(workspace.to_dict())
            # Add user-specific agents (key starts with "{username}:")
            elif cache_key.startswith(f"{username}:") and workspace.username == username:
                result.append(workspace.to_dict())

        # Also add from _user_agents tracking
        for agent_id in self._user_agents.get(username, []):
            cache_key = f"{username}:{agent_id}"
            workspace = self._workspaces.get(cache_key)
            if workspace and workspace.to_dict() not in result:
                result.append(workspace.to_dict())

        return result

    def get_workspace_for_user(self, username: str) -> Optional[Workspace]:
        """Get the primary workspace for a user.

        Returns the user's default agent workspace, which has the CronManager,
        ChannelManager, MemoryManager, etc.

        Returns None if no workspace found for this user.
        """
        # Try {username}:default first (the default agent)
        cache_key = f"{username}:default"
        ws = self._workspaces.get(cache_key)
        if ws:
            return ws

        # Try any workspace owned by this user
        for key, workspace in self._workspaces.items():
            if workspace.username == username and not workspace.is_global:
                return workspace

        return None

    def get_all_agents(self) -> List[Dict[str, Any]]:
        """Get all agents (admin view)."""
        return [ws.to_dict() for ws in self._workspaces.values()]

    def list_agents(self) -> List[Dict[str, Any]]:
        """List all managed agents."""
        return [
            {
                "id": agent_id,
                "status": workspace.status,
                "model": workspace.model,
                "scope": "user" if workspace.username else "global",
                "username": workspace.username,
            }
            for agent_id, workspace in self._workspaces.items()
        ]

    async def chat(
        self,
        agent_id: str,
        message: str,
        chat_id: str = "default",
        username: str = None,
        **kwargs,
    ) -> str:
        """Send message to an agent (supports user isolation).

        Args:
            agent_id: Target agent
            message: User message
            chat_id: Chat session ID
            username: Current user (for chat isolation)
            **kwargs: Additional parameters

        Returns:
            Agent response
        """
        cache_key = f"{username}:{agent_id}" if username else f"global:{agent_id}"
        workspace = self._workspaces.get(cache_key)
        if not workspace:
            # Fallback: try old key format
            workspace = self._workspaces.get(agent_id)
        if not workspace:
            raise ValueError(f"Agent not found: {agent_id}")

        if workspace.status != "running":
            raise RuntimeError(f"Agent {agent_id} is not running")

        return await workspace.chat(message, chat_id, username=username, **kwargs)

    async def start_all(self):
        """Start all registered agents."""
        for agent_id, workspace in self._workspaces.items():
            if workspace.status != "running":
                await workspace.start()

    async def stop_all(self):
        """Stop all registered agents."""
        for agent_id, workspace in list(self._workspaces.items()):
            if workspace.status == "running":
                await workspace.stop()

    async def load_default_agents(self):
        """Discover agents from filesystem and register them (no startup).

        Only scans disk and creates lightweight Workspace objects in
        _workspaces. Runtime services (MCP, channels, cron) are NOT started
        here — they start lazily on first use via get_agent().

        Discovery order:
        1. Global agents: AGENTS_DIR/*/agent.json
        2. User default agents: WORKSPACES_DIR/*/agent.json
        3. User sub-agents: WORKSPACES_DIR/*/agents/*/agent.json
        """
        from ..config.config import load_user_config, derive_workspace_dir

        seen_cache_keys: set[str] = set()

        # ── 1. Global agents (AGENTS_DIR) ──
        if AGENTS_DIR.exists():
            for agent_dir in AGENTS_DIR.iterdir():
                if not agent_dir.is_dir():
                    continue
                agent_json = agent_dir / "agent.json"
                if not agent_json.exists():
                    continue
                agent_id = agent_dir.name
                cache_key = f"global:{agent_id}"
                if cache_key in self._workspaces:
                    seen_cache_keys.add(cache_key)
                    continue
                logger.info(f"Loading global agent: {agent_id}")
                await self.create_agent(agent_id, is_global=True)
                seen_cache_keys.add(cache_key)

        # ── 2. User default agents (WORKSPACES_DIR/*) ──
        if WORKSPACES_DIR.exists():
            for user_dir in WORKSPACES_DIR.iterdir():
                if not user_dir.is_dir() or user_dir.name.startswith("."):
                    continue
                username = user_dir.name
                agent_json = user_dir / "agent.json"
                if not agent_json.exists():
                    continue
                # Read agent_id from agent.json (fallback to convention)
                try:
                    with open(agent_json, encoding="utf-8") as f:
                        meta = json.load(f)
                    agent_id = meta.get("id", f"user:{username}")
                except Exception:
                    agent_id = f"user:{username}"
                cache_key = f"{username}:{agent_id}"
                if cache_key in self._workspaces:
                    seen_cache_keys.add(cache_key)
                    continue
                logger.info(f"Loading user default agent: {agent_id} (user: {username})")
                await self.create_agent(
                    agent_id,
                    username=username,
                    is_global=False,
                )
                seen_cache_keys.add(cache_key)

                # ── 3. User sub-agents (WORKSPACES_DIR/*/agents/*) ──
                user_agents_dir = user_dir / "agents"
                if user_agents_dir.exists():
                    for agent_dir in user_agents_dir.iterdir():
                        if not agent_dir.is_dir():
                            continue
                        sub_agent_json = agent_dir / "agent.json"
                        if not sub_agent_json.exists():
                            continue
                        sub_agent_id = agent_dir.name
                        sub_cache_key = f"{username}:{sub_agent_id}"
                        if sub_cache_key in self._workspaces:
                            seen_cache_keys.add(sub_cache_key)
                            continue
                        logger.info(f"Loading user agent: {sub_agent_id} (user: {username})")
                        await self.create_agent(
                            sub_agent_id,
                            username=username,
                            is_global=False,
                        )
                        seen_cache_keys.add(sub_cache_key)

        logger.info(
            f"Agent discovery complete: {len(self._workspaces)} agents loaded "
            f"({sum(1 for k in self._workspaces if k.startswith('global:'))} global, "
            f"{sum(1 for k in self._workspaces if not k.startswith('global:'))} user)"
        )

    async def get_agent(self, agent_id: str, username: str = None) -> Workspace:
        """Get agent workspace by ID (lazy loading with dedup).

        If workspace doesn't exist in memory, it will be created and started.
        Multiple concurrent callers for the same agent_id are coordinated:
        the first caller creates the workspace while others wait.

        The lock is only held briefly for dict checks/mutations, not during
        the slow workspace startup, allowing parallel agent initialization.

        Supports user isolation: each user gets independent workspace instances
        keyed by "{username}:{agent_id}" composite key.

        IMPORTANT: Global agents (is_global=True) are shared across all users.
        When a user requests a global agent, we return the global workspace
        directly without creating a user-specific copy.

        Args:
            agent_id: Agent ID to retrieve
            username: Owner username (None for global agents)

        Returns:
            Workspace: The requested workspace instance

        Raises:
            ConfigurationException: If agent ID not found in configuration
        """
        # Composite key for user isolation: "{username}:{agent_id}" or "global:{agent_id}"
        cache_key = f"{username}:{agent_id}" if username else f"global:{agent_id}"

        # ── Strict ownership check via disk (no profiles dependency) ──
        from ..config.config import derive_workspace_dir, load_user_config
        workspace_dir = derive_workspace_dir(agent_id, username)
        agent_json_path = workspace_dir / "agent.json"
        if not agent_json_path.exists():
            raise ConfigurationException(
                config_key="agent",
                message=f"Agent '{agent_id}' not found (no agent.json at {workspace_dir}).",
            )
        # Read owner from agent.json
        try:
            with open(agent_json_path, encoding="utf-8") as f:
                agent_meta = json.load(f)
            profile_owner = agent_meta.get("owner", "") or ""
            if not profile_owner and agent_meta.get("username"):
                profile_owner = agent_meta["username"]
        except Exception as _exc:
            profile_owner = ""
        # Infer owner from agent_id for user agents (user:X → owner is X)
        if not profile_owner and agent_id.startswith("user:"):
            profile_owner = agent_id.split(":", 1)[1]
        # Reject if: user trying to access global agent, or accessing someone else's agent
        # Allow: system-level access (username=None) to global agents
        if profile_owner and username and profile_owner != username:
            # User trying to access another user's agent
            raise ConfigurationException(
                config_key="agent",
                message=(
                    f"Access denied: agent '{agent_id}' belongs to "
                    f"'{profile_owner}', not '{username}'"
                ),
            )
        if not profile_owner and username:
            # User trying to access a global agent — reject
            raise ConfigurationException(
                config_key="agent",
                message=(
                    f"Access denied: agent '{agent_id}' is a global agent, "
                    f"not accessible by user '{username}'"
                ),
            )

        # Fast path: already loaded (no lock)
        if cache_key in self.agents:
            ws = self.agents[cache_key]
            # Lazy-start: workspace registered by create_agent() but not yet started
            if getattr(ws, "status", "running") != "running":
                logger.info(f"Lazy-starting workspace: {cache_key}")
                try:
                    await ws.start()
                    ws.set_manager(self)
                except Exception as e:
                    logger.error(f"Lazy-start failed for {cache_key}: {e}")
            return ws

        should_start = False
        event = None
        agent_ref = None

        async with self._lock:
            # Re-check under lock
            if cache_key in self.agents:
                logger.debug(f"Returning cached agent: {cache_key}")
                return self.agents[cache_key]

            if cache_key in self._pending_starts:
                # Another task is already starting this agent; wait for it
                event = self._pending_starts[cache_key]
            else:
                # We are the first caller — claim startup
                event = asyncio.Event()
                self._pending_starts[cache_key] = event
                should_start = True

        if not should_start:
            # Wait for the in-progress startup to finish
            await event.wait()
            if cache_key in self.agents:
                logger.debug(f"Returning cached agent: {cache_key}")
                return self.agents[cache_key]
            raise ConfigurationException(
                config_key="agent",
                message=f"Agent '{agent_id}' failed to initialize",
            )

        # We are the starter — create outside the lock for parallelism
        t0 = time.perf_counter()
        logger.debug(f"Creating new workspace: {cache_key}")
        # Derive workspace_dir at runtime instead of reading from config
        from ..config.config import derive_workspace_dir
        workspace_dir = derive_workspace_dir(agent_id, username)

        # Determine workspace scope
        # If no username, create global agent; otherwise create user-specific agent
        is_global = (username is None)
        instance = Workspace(
            agent_id=agent_id,
            workspace_dir=workspace_dir,
            username=username,
            is_global=is_global,
            role=getattr(agent_ref, 'role', None),
        )

        # Register BEFORE start() so it appears in list_agents
        # even if start() fails (e.g. no provider configured)
        async with self._lock:
            self.agents[cache_key] = instance

        try:
            await instance.start()
            instance.set_manager(self)

            elapsed = time.perf_counter() - t0
            scope = "user" if username else "global"
            logger.debug(
                f"{scope.capitalize()} workspace created: {cache_key} "
                f"({elapsed:.3f}s)",
            )
            return instance
        except Exception as e:
            # Workspace registered but not started — still visible in dropdown
            logger.error(f"Failed to start workspace {cache_key}: {e}")
            return instance
        finally:
            # Always clean up pending state and signal waiters
            # This handles cancellation (CancelledError) and all other cases
            async with self._lock:
                self._pending_starts.pop(cache_key, None)
            event.set()


    @staticmethod
    def _infer_username_from_workspace_dir(workspace_dir: str) -> Optional[str]:
        """Infer owner username from workspace_dir path.

        User-level agents follow pattern: workspaces/{username}/agents/{agent_id}
        User workspaces follow pattern: workspaces/{username}
        Global agents follow pattern: AGENTS_DIR/{agent_id}

        Returns username if this is a user-level agent, None if global.
        """
        if not workspace_dir:
            return None
        try:
            ws_path = Path(workspace_dir)
            # Check if workspace_dir is under WORKSPACES_DIR (e.g. /apps/ai/coapis/workspaces/testuser/agents/my-agent)
            if WORKSPACES_DIR in ws_path.parents:
                # Get the relative path from WORKSPACES_DIR
                rel = ws_path.relative_to(WORKSPACES_DIR)
                parts = rel.parts
                if len(parts) >= 3 and parts[1] == "agents":
                    # Pattern: {username}/agents/{agent_id}
                    return parts[0]
                elif len(parts) == 1:
                    # Pattern: {username} (direct user workspace)
                    # Distinguish from global agents: user dirs have subdirs like chat/, agents/
                    user_dir = WORKSPACES_DIR / parts[0]
                    if user_dir.is_dir():
                        subdirs = {d.name for d in user_dir.iterdir() if d.is_dir()}
                        # User workspaces have chat/ or agents/ subdirs;
                        # global agents in workspaces/ don't have these
                        if subdirs & {"chat", "agents", "skills", "backups"}:
                            return parts[0]
        except (ValueError, IndexError):
            pass
        return None

    async def start_all_configured_agents(self) -> dict[str, bool]:
        """Start all enabled agents defined in configuration concurrently.

        Only agents with enabled=True will be started.
        Disabled agents are skipped to save resources.

        Agents are started truly in parallel: get_agent() only holds the
        manager lock briefly for dict checks, releasing it during the slow
        workspace initialization.

        Returns:
            dict[str, bool]: Mapping of agent_id to success status
        """
        config = load_config()

        # Discover enabled agents from disk (no profiles dependency)
        agent_ids = []
        for cache_key, ws in self._workspaces.items():
            agent_ids.append(ws.agent_id)

        if not agent_ids:
            logger.warning("No agents discovered on disk")
            return {}

        total_agents = len(agent_ids)
        logger.debug(f"Starting {len(agent_ids)} discovered agent(s)")

        async def start_single_agent(agent_id: str) -> tuple[str, bool]:
            """Start a single agent with error handling."""
            try:
                # Infer username from cache key
                cache_key_match = None
                for ck in self._workspaces:
                    if self._workspaces[ck].agent_id == agent_id:
                        cache_key_match = ck
                        break
                username = None
                if cache_key_match and ":" in cache_key_match:
                    prefix = cache_key_match.split(":", 1)[0]
                    if prefix != "global":
                        username = prefix

                logger.debug(f"Starting agent: {agent_id}" + (f" (user: {username})" if username else ""))
                ws = await self.get_agent(agent_id, username=username)
                started = getattr(ws, 'runner', None) is not None
                if started:
                    logger.debug(f"Agent started successfully: {agent_id}")
                else:
                    logger.warning(f"Agent registered but not started: {agent_id} (no provider?)")
                return (agent_id, started)
            except Exception as e:
                logger.error(
                    f"Failed to start agent {agent_id}: {e}. "
                    f"Continuing with other agents...",
                )
                return (agent_id, False)

        # Truly parallel: get_agent releases lock during workspace startup
        results = await asyncio.gather(
            *[start_single_agent(agent_id) for agent_id in agent_ids],
            return_exceptions=False,
        )

        # Build result mapping
        result_map = dict(results)
        success_count = sum(1 for success in result_map.values() if success)
        logger.info(
            f"Agent startup complete: {success_count}/{len(agent_ids)} "
            f"agents started successfully, {disabled_count} disabled",
        )

        return result_map

    def __repr__(self) -> str:
        """String representation of manager."""
        loaded = list(self.agents.keys())
        return f"MultiAgentManager(loaded_agents={loaded})"
