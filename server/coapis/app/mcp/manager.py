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

"""MCP client manager for hot-reloadable client lifecycle management.

This module provides centralized management of MCP clients with support
for runtime updates without restarting the application.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, TYPE_CHECKING

from .stateful_client import HttpStatefulClient, StdIOStatefulClient

if TYPE_CHECKING:
    from ...config.config import MCPClientConfig, MCPConfig

logger = logging.getLogger(__name__)


class MCPClientManager:
    """Manages MCP clients with hot-reload support.

    This manager handles the lifecycle of MCP clients, including:
    - Initial loading from config
    - Runtime replacement when config changes
    - Cleanup on shutdown

    Design pattern mirrors ChannelManager for consistency.
    """

    def __init__(self) -> None:
        """Initialize an empty MCP client manager."""
        self._clients: Dict[str, Any] = {}
        # {client_key: registry-key} for clients shared via
        # SharedHTTPClientRegistry (http/sse only)
        self._shared_keys: Dict[str, tuple] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _is_http_transport(transport: str | None) -> bool:
        """Whether the transport goes through the shared registry."""
        return (transport or "stdio") in ("streamable_http", "sse")

    @staticmethod
    def _http_share_key(client_config: "MCPClientConfig") -> tuple:
        """Sharing key for an http/sse client (after env expansion,
        matching what _build_client actually connects with)."""
        from .shared_client import SharedHTTPClientRegistry

        headers = client_config.headers
        if headers:
            headers = {
                k: os.path.expandvars(v) for k, v in headers.items()
            }
        return SharedHTTPClientRegistry.make_key(
            client_config.transport,
            client_config.url,
            headers or None,
        )

    async def _release_client(self, key: str, client: Any) -> None:
        """Release a client: drops the shared reference (if shared) and
        closes it only when the last workspace lets go."""
        registry_key = self._shared_keys.pop(key, None)
        if registry_key is not None:
            from .shared_client import SharedHTTPClientRegistry

            closed = await SharedHTTPClientRegistry.get_instance().release(
                registry_key,
                client,
            )
            if closed:
                logger.info(
                    f"Shared MCP connection released: '{client.name}'",
                )
            return
        try:
            await client.close()
        except Exception as e:
            logger.warning(f"Error closing MCP client '{key}': {e}")

    async def init_from_config(self, config: "MCPConfig") -> None:
        """Initialize clients from configuration.

        Args:
            config: MCP configuration containing client definitions
        """
        logger.debug("Initializing MCP clients from config")
        for key, client_config in config.clients.items():
            if not client_config.enabled:
                logger.debug(f"MCP client '{key}' is disabled, skipping")
                continue

            try:
                await self._add_client(key, client_config)
                logger.debug(f"MCP client '{key}' initialized successfully")
            except BaseException as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning(
                    f"Failed to initialize MCP client '{key}': {e}",
                    exc_info=True,
                )

    async def get_clients(self) -> List[Any]:
        """Get list of all active MCP clients.

        This method is called by the runner on each query to get
        the latest set of clients.

        Returns:
            List of connected MCP client instances
        """
        async with self._lock:
            # Only expose connected clients: "pending" clients (whose
            # lifecycle task is retrying in the background) will show
            # up here automatically once they connect.
            return [
                client
                for client in self._clients.values()
                if client is not None
                and getattr(client, "is_connected", False)
            ]

    async def get_client(self, key: str) -> Any | None:
        """Get a specific active MCP client by key.

        Args:
            key: Client identifier (from config)

        Returns:
            Connected MCP client instance, or None if not found
        """
        async with self._lock:
            return self._clients.get(key)

    async def replace_client(
        self,
        key: str,
        client_config: "MCPClientConfig",
        timeout: float = 5.0,
    ) -> None:
        """Replace or add a client with new configuration.

        Flow: connect new (outside lock) → swap + close old (inside lock).
        This ensures minimal lock holding time.

        Args:
            key: Client identifier (from config)
            client_config: New client configuration
            timeout: Connection timeout in seconds (default 5s)
        """
        # 1. Build + connect the new client outside the lock (may be
        #    slow). HTTP/SSE clients go through the shared registry so
        #    all workspaces reuse one real connection per URL.
        logger.debug(f"Connecting new MCP client: {key}")
        is_http = self._is_http_transport(client_config.transport)
        registry_key = None

        if is_http:
            from .shared_client import SharedHTTPClientRegistry

            registry_key = self._http_share_key(client_config)
            new_client = await SharedHTTPClientRegistry.get_instance().acquire_client(
                registry_key,
                lambda: self._build_client(client_config, key),
                connect_timeout=timeout,
            )
        else:
            new_client = self._build_client(client_config, key)
            try:
                # Add timeout to prevent indefinite blocking
                await asyncio.wait_for(
                    new_client.connect(), timeout=timeout,
                )
            except BaseException as e:
                # Keep the client pending: its lifecycle task keeps
                # retrying with backoff in the background.
                logger.warning(
                    f"MCP client '{key}' not connected ({e}); kept "
                    f"pending with background retries.",
                )

        # 2. Swap and release old client inside lock
        async with self._lock:
            old_client = self._clients.get(key)
            old_registry_key = self._shared_keys.pop(key, None)
            self._clients[key] = new_client
            if is_http:
                self._shared_keys[key] = registry_key
            same_instance = old_client is new_client

        if same_instance:
            # The shared client was already in place under this key
            # (e.g. only non-connection fields changed): undo the
            # extra reference taken by acquire() and keep it as is.
            if is_http:
                from .shared_client import SharedHTTPClientRegistry

                await SharedHTTPClientRegistry.get_instance().release(
                    registry_key,
                    new_client,
                )
            return

        if old_client is not None:
            logger.debug(f"Closing old MCP client: {key}")
            if old_registry_key is not None:
                from .shared_client import SharedHTTPClientRegistry

                closed = await SharedHTTPClientRegistry.get_instance().release(
                    old_registry_key,
                    old_client,
                )
                if closed:
                    logger.info(
                        f"Shared MCP connection released: "
                        f"'{old_client.name}'",
                    )
            else:
                try:
                    await old_client.close()
                except Exception as e:
                    logger.warning(
                        f"Error closing old MCP client '{key}': {e}",
                    )
        else:
            logger.debug(f"Added new MCP client: {key}")

    async def remove_client(self, key: str) -> None:
        """Remove and close a client.

        Args:
            key: Client identifier to remove
        """
        async with self._lock:
            old_client = self._clients.pop(key, None)

        if old_client is not None:
            logger.debug(f"Removing MCP client: {key}")
            await self._release_client(key, old_client)

    async def close_all(self) -> None:
        """Close all MCP clients.

        Called during application shutdown.
        """
        async with self._lock:
            clients_snapshot = list(self._clients.items())
            self._clients.clear()

        logger.debug("Closing all MCP clients")
        for key, client in clients_snapshot:
            if client is not None:
                await self._release_client(key, client)

    async def _add_client(
        self,
        key: str,
        client_config: "MCPClientConfig",
        timeout: float = 5.0,
    ) -> None:
        """Add a new client (used during initial setup).

        On connection failure the client is kept "pending" — its
        lifecycle task keeps retrying with backoff in the background,
        so it self-heals when the server becomes reachable.

        Args:
            key: Client identifier
            client_config: Client configuration
            timeout: Connection timeout in seconds (default 5s)
        """
        async with self._lock:
            if key in self._clients:
                return

        if self._is_http_transport(client_config.transport):
            from .shared_client import SharedHTTPClientRegistry

            registry_key = self._http_share_key(client_config)
            client = await SharedHTTPClientRegistry.get_instance().acquire_client(
                registry_key,
                lambda: self._build_client(client_config, key),
                connect_timeout=timeout,
            )
            async with self._lock:
                if key in self._clients:
                    # Added concurrently by another coroutine
                    await SharedHTTPClientRegistry.get_instance().release(
                        registry_key,
                        client,
                    )
                    return
                self._shared_keys[key] = registry_key
                self._clients[key] = client
            return

        client = self._build_client(client_config, key)
        try:
            await asyncio.wait_for(client.connect(), timeout=timeout)
        except BaseException as e:
            logger.warning(
                f"MCP client '{key}' not connected at startup ({e}); "
                f"kept pending with background retries.",
            )

        async with self._lock:
            if key in self._clients:
                # Added concurrently by another coroutine
                await client.close()
                return
            self._clients[key] = client

    @staticmethod
    async def _force_cleanup_client(client: Any) -> None:
        """Force-close a client whose ``connect()`` was interrupted.

        ``StatefulClientBase.close()`` refuses to run when
        ``is_connected`` is still ``False`` (which is the case when
        ``connect()`` times out or raises).  We bypass that guard by
        closing the ``AsyncExitStack`` directly — this triggers the
        ``stdio_client`` finally-block that sends SIGTERM/SIGKILL to
        the child process.

        The ``ClientSession`` is registered on the same stack via
        ``enter_async_context``, so ``stack.aclose()`` exits it in
        LIFO order — no separate session teardown is needed.
        """
        if client is None:
            return

        stack = getattr(client, "stack", None)
        if stack is None:
            return

        try:
            await stack.aclose()
        except Exception:
            logger.debug(
                "Error during force-cleanup of MCP client",
                exc_info=True,
            )
        finally:
            for attr, default in (
                ("stack", None),
                ("session", None),
                ("is_connected", False),
            ):
                try:
                    setattr(client, attr, default)
                except Exception:
                    pass

    @staticmethod
    def _build_client(client_config: "MCPClientConfig", client_key: str) -> Any:
        """Build MCP client instance by configured transport."""
        rebuild_info = {
            "name": client_config.name,
            "client_key": client_key,
            "transport": client_config.transport,
            "url": client_config.url,
            "headers": client_config.headers or None,
            "command": client_config.command,
            "args": list(client_config.args),
            "env": {**os.environ, **dict(client_config.env or {})},
            "cwd": client_config.cwd or None,
        }

        if client_config.transport == "stdio":
            client = StdIOStatefulClient(
                name=client_config.name,
                command=client_config.command,
                args=client_config.args,
                env={**os.environ, **(client_config.env or {})},
                cwd=client_config.cwd or None,
            )
            setattr(client, "_coapis_rebuild_info", rebuild_info)
            setattr(client, "client_key", client_key)
            return client

        headers = client_config.headers
        if headers:
            headers = {k: os.path.expandvars(v) for k, v in headers.items()}

        client = HttpStatefulClient(
            name=client_config.name,
            transport=client_config.transport,
            url=client_config.url,
            headers=headers or None,
        )
        setattr(client, "_coapis_rebuild_info", rebuild_info)
        setattr(client, "client_key", client_key)
        return client
