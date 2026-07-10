# -*- coding: utf-8 -*-
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

"""Service factory functions for workspace components.

Factory functions are used by Workspace._register_services() to create
and initialize service components. Extracted from local functions to
improve testability and code organization.
"""

from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .workspace import Workspace

logger = logging.getLogger(__name__)


async def create_mcp_service(ws: "Workspace", mcp):
    print("MCP_FACTORY_CALLED", flush=True)
    """Initialize MCP manager with merged global+user config and attach to runner.

    Merge logic:
    1. Load admin's MCP config as global pool
    2. Load user's own MCP config
    3. User keys override global keys with the same name
    4. Global-only keys are inherited unless user explicitly disabled them

    Args:
        ws: Workspace instance
        mcp: MCPClientManager instance
    """
    # pylint: disable=protected-access
    from ...config.config import MCPConfig, load_agent_config
    from ...config.utils import load_config

    logger.warning(f"[MCP_FACTORY] create_mcp_service called for {ws.agent_id}")

    # Build merged MCP config (global + user)
    merged_clients = {}

    # 1. Load global pool (admin's MCP)
    try:
        config = load_config()
        admin_agent_id = config.agents.active_agent or "user:admin"
        if admin_agent_id != ws.agent_id:
            admin_config = load_agent_config(admin_agent_id)
            if admin_config.mcp and admin_config.mcp.clients:
                merged_clients.update(
                    dict(admin_config.mcp.clients),
                )
                logger.warning(
                    "MCP: loaded %d global clients from %s",
                    len(admin_config.mcp.clients),
                    admin_agent_id,
                )
    except Exception as e:
        logger.debug(f"MCP: no global pool available: {e}")

    # 2. Overlay user's own MCP config
    if ws._config.mcp and ws._config.mcp.clients:
        merged_clients.update(dict(ws._config.mcp.clients))
        logger.warning(
            "MCP: overlaid %d user clients",
            len(ws._config.mcp.clients),
        )

    # 3. Filter out explicitly disabled keys
    active_clients = {
        k: v for k, v in merged_clients.items() if v.enabled
    }

    logger.warning(f"[MCP_FACTORY] active_clients: {list(active_clients.keys())}")

    if active_clients:
        merged_mcp = MCPConfig(clients=active_clients)
        try:
            await mcp.init_from_config(merged_mcp)
            logger.warning(
                "MCP: initialized %d clients for %s",
                len(active_clients),
                ws.agent_id,
            )
        except Exception as e:
            logger.warning(f"Failed to init MCP: {e}", exc_info=True)
    else:
        logger.warning(f"MCP: no active clients for {ws.agent_id}")

    ws._service_manager.services["runner"].set_mcp_manager(mcp)
    logger.warning(f"[MCP_FACTORY] set_mcp_manager done for {ws.agent_id}")
    # pylint: enable=protected-access


async def create_chat_service(ws: "Workspace", service):
    """Create and attach chat manager, or reuse existing one.

    Args:
        ws: Workspace instance
        service: Existing ChatManager if reused, None if creating new
    """
    # pylint: disable=protected-access
    from ..runner.manager import ChatManager
    from ..runner.repo.json_repo import JsonChatRepository

    if service is not None:
        # Reused ChatManager - just wire to new runner
        cm = service
        logger.info(f"Reusing ChatManager for {ws.agent_id}")
    else:
        # Create new ChatManager
        chats_dir = ws.workspace_dir / "chat"
        chats_dir.mkdir(parents=True, exist_ok=True)
        chats_path = str(chats_dir / "chats.json")
        chat_repo = JsonChatRepository(chats_path)
        cm = ChatManager(repo=chat_repo)
        ws._service_manager.services["chat_manager"] = cm
        logger.info(f"ChatManager created: {chats_path}")

    # Always wire to new runner
    ws._service_manager.services["runner"].set_chat_manager(cm)
    # pylint: enable=protected-access


async def create_channel_service(ws: "Workspace", _):
    """Create channel manager if configured.

    Args:
        ws: Workspace instance
        _: Unused service parameter

    Returns:
        ChannelManager instance or None if not configured
    """
    # pylint: disable=protected-access
    from ..channels.manager import ChannelManager
    from ..channels.utils import make_process_from_runner

    runner = ws._service_manager.services["runner"]

    def on_last_dispatch(channel, user_id, session_id):
        from ...config import update_last_dispatch
        update_last_dispatch(
            channel=channel,
            user_id=user_id,
            session_id=session_id,
            agent_id=ws.agent_id,
        )

    if not ws._config.channels:
        # No channels configured — create a minimal ChannelManager
        # with no active channels so that workspace.channel_manager
        # is never None.  The console channel (used by web UI) is
        # handled separately via the API router, not through
        # ChannelManager, so an empty manager is safe here.
        cm = ChannelManager(channels=[])
        ws._service_manager.services["channel_manager"] = cm
        cm.set_workspace(ws)
        runner.set_workspace(ws)
        return cm

    from ...config import Config

    temp_config = Config(channels=ws._config.channels)

    cm = ChannelManager.from_config(
        process=make_process_from_runner(runner),
        config=temp_config,
        on_last_dispatch=on_last_dispatch,
        workspace_dir=ws.workspace_dir,
    )
    ws._service_manager.services["channel_manager"] = cm

    # Inject workspace into ChannelManager and all channels
    cm.set_workspace(ws)

    # Inject workspace into runner for control command handlers
    runner.set_workspace(ws)

    return cm
    # pylint: enable=protected-access


async def create_agent_config_watcher(ws: "Workspace", _):
    """Create agent config watcher if channel/cron exists.

    Args:
        ws: Workspace instance
        _: Unused service parameter

    Returns:
        AgentConfigWatcher instance or None if not needed
    """
    # pylint: disable=protected-access
    channel_mgr = ws._service_manager.services.get("channel_manager")
    cron_mgr = ws._service_manager.services.get("cron_manager")

    if not (channel_mgr or cron_mgr):
        return None

    from ..agent_config_watcher import AgentConfigWatcher

    watcher = AgentConfigWatcher(
        agent_id=ws.agent_id,
        workspace_dir=ws.workspace_dir,
        channel_manager=channel_mgr,
        cron_manager=cron_mgr,
    )
    ws._service_manager.services["agent_config_watcher"] = watcher
    return watcher
    # pylint: enable=protected-access


async def create_mcp_config_watcher(ws: "Workspace", _):
    """Create MCP config watcher if MCP manager exists.

    Args:
        ws: Workspace instance
        _: Unused service parameter

    Returns:
        MCPConfigWatcher instance or None if not needed
    """
    # pylint: disable=protected-access
    mcp_mgr = ws._service_manager.services.get("mcp_manager")
    if not mcp_mgr:
        return None

    from ..mcp.watcher import MCPConfigWatcher
    from ...config.config import load_agent_config

    def mcp_config_loader():
        agent_config = load_agent_config(ws.agent_id)
        return agent_config.mcp

    watcher = MCPConfigWatcher(
        mcp_manager=mcp_mgr,
        config_loader=mcp_config_loader,
        config_path=ws.workspace_dir / "agent.json",
    )
    ws._service_manager.services["mcp_config_watcher"] = watcher
    return watcher
    # pylint: enable=protected-access
