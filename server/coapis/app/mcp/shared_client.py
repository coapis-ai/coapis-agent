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

"""App-level shared registry for HTTP/SSE MCP clients.

Multiple workspaces merge the same global-pool MCP config (e.g. the
admin user's "global" clients), which previously caused every workspace
to open its own connection to the same MCP server. Single-session
servers (e.g. FastMCP streamable_http) then kick each other out, so
most workspaces saw a permanently broken client.

This registry dedupes HTTP/SSE connections: one client instance per
(transport, url, headers) key, reference-counted so the connection is
only closed when the last workspace releases it.

Stdio clients are NOT shared (each subprocess is local and cheap);
only HTTP/SSE go through the registry.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class _SharedEntry:
    """One shared client instance plus its reference count."""

    __slots__ = ("client", "refcount", "ready")

    def __init__(self) -> None:
        self.client: Any | None = None  # None => creation in flight
        self.refcount: int = 0
        # Set once creation finishes (successfully or not).
        self.ready: asyncio.Event = asyncio.Event()


class SharedHTTPClientRegistry:
    """Process-wide registry that dedupes HTTP/SSE MCP connections."""

    _instance: "SharedHTTPClientRegistry | None" = None

    @classmethod
    def get_instance(cls) -> "SharedHTTPClientRegistry":
        if cls._instance is None:
            cls._instance = SharedHTTPClientRegistry()
        return cls._instance

    def __init__(self) -> None:
        self._entries: dict[tuple, _SharedEntry] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def make_key(
        transport: str,
        url: str,
        headers: dict[str, str] | None,
    ) -> tuple:
        """Build the sharing key from connection parameters."""
        norm_headers = tuple(
            sorted((str(k), str(v)) for k, v in (headers or {}).items())
        )
        return (transport, url, norm_headers)

    async def acquire_client(
        self,
        key: tuple,
        factory: Callable[[], Any],
        connect_timeout: float,
    ) -> Any:
        """Get (and reference) the shared client for ``key``.

        Creates the client via ``factory`` and connects it on first use.
        On connection failure the client is kept "pending" — its
        lifecycle task keeps retrying with backoff in the background
        (see stateful_client) — and is still returned so all
        workspaces share the same retrying instance.
        """
        creating = False
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _SharedEntry()
                entry.refcount = 1
                self._entries[key] = entry
                creating = True
            else:
                entry.refcount += 1
                if entry.client is not None:
                    return entry.client
                creating = False

        if not creating:
            # Another coroutine is creating the client; wait for it.
            await entry.ready.wait()
            return entry.client

        try:
            client = factory()
            try:
                await asyncio.wait_for(
                    client.connect(), timeout=connect_timeout,
                )
                logger.info(
                    f"Shared MCP client connected: '{client.name}' "
                    f"({key[0]} {key[1]})",
                )
            except BaseException as e:
                # Keep the client pending: background backoff retries
                # continue inside its lifecycle task.
                logger.warning(
                    f"Shared MCP client '{client.name}' ({key[0]} "
                    f"{key[1]}) not connected yet ({e}); keeping it "
                    f"pending with background retries.",
                )
        except BaseException:
            # factory() itself failed — release the entry so a later
            # call can retry from scratch.
            async with self._lock:
                self._entries.pop(key, None)
            raise

        entry.client = client
        entry.ready.set()
        return client

    async def release(self, key: tuple, client: Any) -> bool:
        """Release one reference; closes the client when the last
        workspace lets go. Returns True if the client was closed."""
        should_close = False
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.client is not client:
                return False
            entry.refcount -= 1
            if entry.refcount <= 0:
                del self._entries[key]
                should_close = True
        if should_close:
            try:
                await client.close()
            except Exception as e:
                logger.warning(
                    f"Error closing shared MCP client '{client.name}' "
                    f"({key[0]} {key[1]}): {e}",
                )
        return should_close

    async def close_all(self) -> None:
        """Close every shared client (app shutdown)."""
        async with self._lock:
            entries = list(self._entries.items())
            self._entries.clear()
        for key, entry in entries:
            if entry.client is not None:
                try:
                    await entry.client.close()
                except Exception as e:
                    logger.warning(
                        f"Error closing shared MCP client "
                        f"'{entry.client.name}' during shutdown: {e}",
                    )
