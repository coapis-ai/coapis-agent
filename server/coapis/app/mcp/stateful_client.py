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

"""MCP stateful clients with proper cross-task lifecycle management.

This module provides drop-in replacements for AgentScope's MCP clients
that solve the CPU leak issue caused by cross-task context manager exits.

The issue occurs when using AgentScope's StatefulClientBase in uvicorn/FastAPI:
- connect() enters AsyncExitStack in task A (e.g., startup event)
- close() exits AsyncExitStack in task B (e.g., reload background task)
- anyio.CancelScope requires enter/exit in the same task
- Error is silently ignored, leaving MCP processes and streams uncleaned

Our solution: Run the entire context manager lifecycle in a single dedicated
background task, using event-based signaling for reload/stop operations.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Literal

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from agentscope.mcp import StatefulClientBase

logger = logging.getLogger(__name__)

# Connection retry policy (shared by stdio/http clients).
# Before the cap: exponential backoff (2,4,8,16,30s). After the cap: a
# fixed low-frequency interval keeps the client alive so it self-heals
# when the server comes back, without hammering a downed server.
_MAX_RETRIES = 5
_BACKOFF_CAP = 30.0
_IDLE_RETRY_INTERVAL = 60.0


def _next_retry_delay(retry_count: int) -> float:
    """Backoff delay (seconds) for the given 1-based retry count."""
    if retry_count <= _MAX_RETRIES:
        return min(2.0 ** retry_count, _BACKOFF_CAP)
    return _IDLE_RETRY_INTERVAL


class StdIOStatefulClient(StatefulClientBase):
    """StdIO MCP client with proper cross-task lifecycle management.

    Drop-in replacement for agentscope.mcp.StdIOStatefulClient that solves
    the CPU leak issue by running the entire context manager lifecycle in
    a single dedicated background task.

    Key improvements:
    - Context manager enter/exit happens in the same asyncio task
    - Uses event-based signaling for reload/stop operations
    - Properly cleans up MCP subprocess and stdio streams
    - No CPU leak on reload
    - No zombie processes

    API-compatible with agentscope.mcp.StdIOStatefulClient for drop-in
    replacement.
    """

    def __init__(
        self,
        name: Any,
        command: Any,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        encoding: str = "utf-8",
        encoding_error_handler: Literal[
            "strict",
            "ignore",
            "replace",
        ] = "strict",
        **kwargs,
    ) -> None:
        """Initialize the StdIO MCP client.

        Args:
            name: Client identifier (unique across MCP servers)
            command: The executable to run to start the server
            args: Command line arguments to pass to the executable
            env: The environment to use when spawning the process
            cwd: The working directory to use when spawning the process
            encoding: The text encoding used when sending/receiving messages
            encoding_error_handler: The text encoding error handler

        Raises:
            TypeError: If name or command is not a string
        """
        if not isinstance(name, str):
            raise TypeError(f"name must be str, got {type(name).__name__}")
        if not isinstance(command, str):
            raise TypeError(
                f"command must be str, got {type(command).__name__}",
            )

        self.name = name
        self.server_params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env,
            cwd=cwd,
            encoding=encoding,
            encoding_error_handler=encoding_error_handler,
        )

        # Lifecycle management
        self._lifecycle_task: asyncio.Task | None = None
        self._reload_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        self._stop_event = asyncio.Event()

        # Session state
        self.session: ClientSession | None = None
        self.is_connected = False

        # Tool cache
        self._cached_tools = None

        self.timeout = kwargs.get("timeout")
        
        # User context token for MCP gateway authentication
        self._user_context_token: str | None = None

        # Connection retry bookkeeping (see _run_lifecycle)
        self._retry_count: int = 0

    async def _run_lifecycle(self) -> None:
        """Run MCP client lifecycle in a dedicated task.

        This ensures __aenter__ and __aexit__ are called in the same task,
        avoiding the cross-task cancel scope error.
        """
        from mcp.client.stdio import stdio_client

        while not self._stop_event.is_set():
            try:
                logger.debug(f"Connecting MCP client: {self.name}")

                # Enter context manager in THIS task
                async with AsyncExitStack() as stack:
                    context = await stack.enter_async_context(
                        stdio_client(self.server_params),
                    )
                    read_stream, write_stream = context[0], context[1]

                    # Initialize session
                    self.session = ClientSession(read_stream, write_stream)
                    await stack.enter_async_context(self.session)
                    await self.session.initialize()

                    # Mark as connected and signal ready
                    self.is_connected = True
                    self._ready_event.set()
                    logger.info(f"MCP client connected: {self.name}")
                    if self._retry_count:
                        logger.info(
                            f"MCP client '{self.name}' connected after "
                            f"{self._retry_count} failed attempt(s).",
                        )
                        self._retry_count = 0

                    # Wait for reload or stop signal
                    while (
                        not self._reload_event.is_set()
                        and not self._stop_event.is_set()
                    ):
                        await asyncio.sleep(0.1)

                    # Clear state before exiting context
                    self.session = None
                    self.is_connected = False
                    self._cached_tools = None

                    if self._reload_event.is_set():
                        logger.info(f"Reloading MCP client: {self.name}")
                        self._reload_event.clear()
                        self._ready_event.clear()
                        # Context manager will exit here, then loop restarts
                    else:
                        logger.info(f"Stopping MCP client: {self.name}")
                        # Context manager will exit here, then loop exits

                # Context manager exits cleanly in THIS task

            except Exception as e:
                self._retry_count += 1
                if self._retry_count == 1:
                    logger.error(
                        f"Error in MCP client lifecycle for {self.name}: {e}",
                        exc_info=True,
                    )
                self.session = None
                self.is_connected = False
                self._cached_tools = None
                self._ready_event.clear()
                delay = _next_retry_delay(self._retry_count)
                if self._retry_count == _MAX_RETRIES + 1:
                    logger.warning(
                        f"MCP client '{self.name}' exceeded max retries "
                        f"({_MAX_RETRIES}); retrying every {delay:.0f}s "
                        f"until connected or removed.",
                    )
                elif self._retry_count <= _MAX_RETRIES:
                    logger.warning(
                        f"MCP client '{self.name}' connect failed "
                        f"({self._retry_count}/{_MAX_RETRIES}), "
                        f"retrying in {delay:.0f}s: {e}",
                    )
                else:
                    logger.debug(
                        f"MCP client '{self.name}' idle retry "
                        f"(#{self._retry_count}) failed: {e}",
                    )
                # Sleep, but wake up immediately on stop/reload
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=delay,
                    )
                except asyncio.TimeoutError:
                    pass  # delay elapsed -> loop retries

        logger.info(f"MCP client lifecycle task exited: {self.name}")

    async def connect(self, timeout: float = 30.0) -> None:
        """Connect to MCP server.

        Args:
            timeout: Connection timeout in seconds (default 30s)

        Raises:
            RuntimeError: If already connected
            asyncio.TimeoutError: If connection times out
        """
        if self.is_connected:
            raise RuntimeError(
                f"MCP client '{self.name}' is already connected. "
                f"Call close() before connecting again.",
            )

        # Start lifecycle task
        self._stop_event.clear()
        self._lifecycle_task = asyncio.create_task(self._run_lifecycle())

        # Wait for initial connection
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Keep the lifecycle task alive: it retries with backoff in
            # the background (see _run_lifecycle). The caller can hold
            # this client as "pending" — it will self-heal when the
            # server becomes reachable.
            logger.warning(
                f"Timeout waiting for MCP client '{self.name}' to connect; "
                f"keeping it pending with background retries.",
            )
            raise

    async def close(self, ignore_errors: bool = True) -> None:
        """Close MCP client and clean up resources.

        Args:
            ignore_errors: Whether to ignore errors during cleanup

        Raises:
            RuntimeError: If not connected (unless ignore_errors=True)
        """
        # Even when not connected, the lifecycle task may still be
        # running (background retries after a failed connect) — always
        # stop it in that case.
        if not self.is_connected and self._lifecycle_task is None:
            if not ignore_errors:
                raise RuntimeError(
                    f"MCP client '{self.name}' is not connected. "
                    f"Call connect() before closing.",
                )
            return

        try:
            # Signal stop and wait for lifecycle task to finish
            self._stop_event.set()
            if self._lifecycle_task:
                await asyncio.wait_for(self._lifecycle_task, timeout=10)
                self._lifecycle_task = None
        except asyncio.TimeoutError:
            # stop_event was set; the task will exit shortly.
            self._lifecycle_task = None
            logger.warning(
                f"Timed out waiting for MCP client '{self.name}' "
                f"lifecycle to stop",
            )
        except Exception as e:
            if not ignore_errors:
                raise
            logger.warning(
                f"Error closing MCP client '{self.name}': {e}",
            )

    async def reload(self, timeout: float = 30.0) -> None:
        """Reload the MCP client (reconnect).

        Args:
            timeout: Connection timeout in seconds (default 30s)

        Raises:
            RuntimeError: If not connected
            asyncio.TimeoutError: If reload times out
        """
        if not self.is_connected:
            raise RuntimeError(
                f"MCP client '{self.name}' is not connected. "
                f"Call connect() first.",
            )

        logger.info(f"Triggering reload for MCP client: {self.name}")
        self._reload_event.set()

        # Wait for new connection
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            logger.info(f"Reload completed for MCP client: {self.name}")
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout waiting for MCP client '{self.name}' to reload",
            )
            raise

    async def list_tools(self):
        """Get all available tools from the server.

        Returns:
            List of available MCP tools

        Raises:
            RuntimeError: If not connected
        """
        self._validate_connection()

        try:
            res = await self.session.list_tools()
        except Exception as e:
            exc_str = str(e).lower()
            # Check if it's a pydantic validation error due to extra fields like metadata.action_templates
            if "extra" in exc_str or "forbidden" in exc_str or "invalid field" in exc_str or "extraneous" in exc_str or "validation error" in exc_str:
                logger.warning(f"MCP client '{self.name}' list_tools encountered Pydantic validation error: {e}. Attempting relaxed parsing.")
                
                # Fallback: attempt to get tools via manual JSON-RPC call with relaxed parsing
                try:
                    import mcp.types as types
                    
                    # Send raw tools/list request and parse as dict to avoid Pydantic strict validation
                    result = await self.session.send_request(
                        types.MethodCall(method="tools/list", params={}, id=None),
                        dict,
                    )
                    
                    # Extract tools from result
                    tools_data = result.get("result", {}).get("tools", [])
                    loose_tools = []
                    for tool_data in tools_data:
                        if not isinstance(tool_data, dict):
                            continue
                        # Create a simple dict-based tool object with required attributes, preserving metadata (including action_templates)
                        loose_tool = {
                            "name": tool_data.get("name"),
                            "description": tool_data.get("description"),
                            "inputSchema": tool_data.get("inputSchema", {})
                        }
                        # Preserve metadata if present (e.g., action_templates)
                        if "metadata" in tool_data:
                            loose_tool["metadata"] = tool_data.get("metadata")
                        
                        loose_tools.append(loose_tool)
                    
                    # Cache and return the loosely parsed tools
                    self._cached_tools = loose_tools
                    logger.info(f"MCP client '{self.name}' successfully parsed {len(loose_tools)} tools with relaxed validation.")
                    return loose_tools
                    
                except Exception as fallback_err:
                    logger.error(f"MCP client '{self.name}' list_tools relaxed parsing failed: {fallback_err}")
                    raise e
            else:
                raise

        # Cache the tools for later use
        self._cached_tools = res.tools
        return res.tools

    async def call_tool(self, name: str, arguments: dict | None = None):
        """Call a tool on the MCP server.

        Args:
            name: Tool name
            arguments: Tool arguments (optional)

        Returns:
            Tool call result

        Raises:
            RuntimeError: If not connected
        """
        self._validate_connection()

        return await self.session.call_tool(name, arguments or {})

    def _validate_connection(self) -> None:
        """Validate the connection to the MCP server.

        Raises:
            RuntimeError: If not connected or session not initialized
        """
        if not self.is_connected:
            raise RuntimeError(
                f"MCP client '{self.name}' is not connected. "
                f"Call connect() first.",
            )

        if not self.session:
            raise RuntimeError(
                f"MCP client '{self.name}' session is not initialized. "
                f"Call connect() first.",
            )


class HttpStatefulClient(StatefulClientBase):
    """HTTP/SSE MCP client with proper cross-task lifecycle management.

    Drop-in replacement for agentscope.mcp.HttpStatefulClient that solves
    the CPU leak issue by running the entire context manager lifecycle in
    a single dedicated background task.

    Supports both streamable HTTP and SSE transports.
    """

    def __init__(
        self,
        name: Any,
        transport: Any,
        url: Any,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
        sse_read_timeout: float = 60 * 5,
        **client_kwargs: Any,
    ) -> None:
        """Initialize the HTTP MCP client.

        Args:
            name: Client identifier (unique across MCP servers)
            transport: The transport type ("streamable_http" or "sse")
            url: The URL to the MCP server
            headers: Additional headers to include in the HTTP request
            timeout: The timeout for the HTTP request in seconds
            sse_read_timeout: The timeout for reading SSE in seconds
            **client_kwargs: Additional keyword arguments for the client

        Raises:
            TypeError: If name, transport, or url is not a string
            ValueError: If transport is not "streamable_http" or "sse"
        """
        if not isinstance(name, str):
            raise TypeError(f"name must be str, got {type(name).__name__}")
        if not isinstance(transport, str):
            raise TypeError(
                f"transport must be str, got {type(transport).__name__}",
            )
        if transport not in ["streamable_http", "sse"]:
            raise ValueError(
                f"transport must be 'streamable_http' or 'sse', "
                f"got {transport!r}",
            )
        if not isinstance(url, str):
            raise TypeError(f"url must be str, got {type(url).__name__}")

        self.name = name
        self.transport = transport
        self.url = url
        self.headers = headers
        self.timeout = timeout
        self.sse_read_timeout = sse_read_timeout
        self.client_kwargs = client_kwargs

        # Lifecycle management
        self._lifecycle_task: asyncio.Task | None = None
        self._reload_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        self._stop_event = asyncio.Event()

        # Session state
        self.session: ClientSession | None = None
        self.is_connected = False

        # Tool cache
        self._cached_tools = None
        
        # User context token for MCP gateway authentication
        self._user_context_token: str | None = None

        # Connection retry bookkeeping (see _run_lifecycle)
        self._retry_count: int = 0

    def set_user_context_token(self, token: str | None) -> None:
        """Set the user context token for this client.
        
        This token is used when making HTTP requests to external MCP servers
        through the gateway for multi-tenant authentication and authorization.
        """
        self._user_context_token = token

    async def _run_lifecycle(self) -> None:
        """Run MCP client lifecycle in a dedicated task."""
        while not self._stop_event.is_set():
            try:
                logger.debug(f"Connecting MCP client: {self.name}")

                # Enter context manager in THIS task
                async with AsyncExitStack() as stack:
                    # Select client based on transport
                    if self.transport == "streamable_http":
                        # Create httpx.AsyncClient with headers and timeout
                        timeout_seconds = (
                            self.timeout.total_seconds()
                            if isinstance(self.timeout, timedelta)
                            else self.timeout
                        )
                        sse_read_timeout_seconds = (
                            self.sse_read_timeout.total_seconds()
                            if isinstance(self.sse_read_timeout, timedelta)
                            else self.sse_read_timeout
                        )

                        # Configure httpx client with MCP-recommended timeouts
                        http_client = httpx.AsyncClient(
                            headers=self.headers or {},
                            timeout=httpx.Timeout(
                                connect=timeout_seconds,
                                read=sse_read_timeout_seconds,
                                write=timeout_seconds,
                                pool=timeout_seconds,
                            ),
                            **self.client_kwargs,
                        )

                        # Add http_client to exit stack for proper cleanup
                        await stack.enter_async_context(http_client)

                        context = await stack.enter_async_context(
                            streamable_http_client(
                                url=self.url,
                                http_client=http_client,
                            ),
                        )
                    else:
                        context = await stack.enter_async_context(
                            sse_client(
                                url=self.url,
                                headers=self.headers,
                                timeout=self.timeout,
                                sse_read_timeout=self.sse_read_timeout,
                                **self.client_kwargs,
                            ),
                        )

                    read_stream, write_stream = context[0], context[1]

                    # Initialize session
                    self.session = ClientSession(read_stream, write_stream)
                    await stack.enter_async_context(self.session)
                    await self.session.initialize()

                    # Mark as connected and signal ready
                    self.is_connected = True
                    self._ready_event.set()
                    logger.info(f"MCP client connected: {self.name}")
                    if self._retry_count:
                        logger.info(
                            f"MCP client '{self.name}' connected after "
                            f"{self._retry_count} failed attempt(s).",
                        )
                        self._retry_count = 0

                    # Wait for reload or stop signal
                    while (
                        not self._reload_event.is_set()
                        and not self._stop_event.is_set()
                    ):
                        await asyncio.sleep(0.1)

                    # Clear state before exiting context
                    self.session = None
                    self.is_connected = False
                    self._cached_tools = None

                    if self._reload_event.is_set():
                        logger.info(f"Reloading MCP client: {self.name}")
                        self._reload_event.clear()
                        self._ready_event.clear()
                    else:
                        logger.info(f"Stopping MCP client: {self.name}")

                # Context manager exits cleanly in THIS task

            except Exception as e:
                self._retry_count += 1
                if self._retry_count == 1:
                    logger.error(
                        f"Error in MCP client lifecycle for {self.name}: {e}",
                        exc_info=True,
                    )
                self.session = None
                self.is_connected = False
                self._cached_tools = None
                self._ready_event.clear()
                delay = _next_retry_delay(self._retry_count)
                if self._retry_count == _MAX_RETRIES + 1:
                    logger.warning(
                        f"MCP client '{self.name}' exceeded max retries "
                        f"({_MAX_RETRIES}); retrying every {delay:.0f}s "
                        f"until connected or removed.",
                    )
                elif self._retry_count <= _MAX_RETRIES:
                    logger.warning(
                        f"MCP client '{self.name}' connect failed "
                        f"({self._retry_count}/{_MAX_RETRIES}), "
                        f"retrying in {delay:.0f}s: {e}",
                    )
                else:
                    logger.debug(
                        f"MCP client '{self.name}' idle retry "
                        f"(#{self._retry_count}) failed: {e}",
                    )
                # Sleep, but wake up immediately on stop/reload
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=delay,
                    )
                except asyncio.TimeoutError:
                    pass  # delay elapsed -> loop retries

        logger.info(f"MCP client lifecycle task exited: {self.name}")

    async def connect(self, timeout: float = 30.0) -> None:
        """Connect to MCP server.

        Args:
            timeout: Connection timeout in seconds

        Raises:
            RuntimeError: If already connected
            asyncio.TimeoutError: If connection times out
        """
        if self.is_connected:
            raise RuntimeError(
                f"MCP client '{self.name}' is already connected. "
                f"Call close() before connecting again.",
            )

        self._stop_event.clear()
        self._lifecycle_task = asyncio.create_task(self._run_lifecycle())

        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Keep the lifecycle task alive: it retries with backoff in
            # the background (see _run_lifecycle). The caller can hold
            # this client as "pending" — it will self-heal when the
            # server becomes reachable.
            logger.warning(
                f"Timeout waiting for MCP client '{self.name}' to connect; "
                f"keeping it pending with background retries.",
            )
            raise

    async def close(self, ignore_errors: bool = True) -> None:
        """Close MCP client and clean up resources.

        Args:
            ignore_errors: Whether to ignore errors during cleanup

        Raises:
            RuntimeError: If not connected (unless ignore_errors=True)
        """
        # Even when not connected, the lifecycle task may still be
        # running (background retries after a failed connect) — always
        # stop it in that case.
        if not self.is_connected and self._lifecycle_task is None:
            if not ignore_errors:
                raise RuntimeError(
                    f"MCP client '{self.name}' is not connected. "
                    f"Call connect() before closing.",
                )
            return

        try:
            self._stop_event.set()
            if self._lifecycle_task:
                await asyncio.wait_for(self._lifecycle_task, timeout=10)
                self._lifecycle_task = None
        except asyncio.TimeoutError:
            # stop_event was set; the task will exit shortly.
            self._lifecycle_task = None
            logger.warning(
                f"Timed out waiting for MCP client '{self.name}' "
                f"lifecycle to stop",
            )
        except Exception as e:
            if not ignore_errors:
                raise
            logger.warning(
                f"Error closing MCP client '{self.name}': {e}",
            )

    async def list_tools(self):
        """Get all available tools from the server.

        Returns:
            List of available MCP tools

        Raises:
            RuntimeError: If not connected
        """
        self._validate_connection()

        try:
            res = await self.session.list_tools()
        except Exception as e:
            exc_str = str(e).lower()
            # Check if it's a pydantic validation error due to extra fields like metadata.action_templates
            if "extra" in exc_str or "forbidden" in exc_str or "invalid field" in exc_str or "extraneous" in exc_str or "validation error" in exc_str:
                logger.warning(f"MCP client '{self.name}' list_tools encountered Pydantic validation error: {e}. Attempting relaxed parsing.")
                
                # Fallback: attempt to get tools via manual JSON-RPC call with relaxed parsing
                try:
                    import mcp.types as types
                    
                    # Send raw tools/list request and parse as dict to avoid Pydantic strict validation
                    result = await self.session.send_request(
                        types.MethodCall(method="tools/list", params={}, id=None),
                        dict,
                    )
                    
                    # Extract tools from result
                    tools_data = result.get("result", {}).get("tools", [])
                    loose_tools = []
                    for tool_data in tools_data:
                        if not isinstance(tool_data, dict):
                            continue
                        # Create a simple dict-based tool object with required attributes, preserving metadata (including action_templates)
                        loose_tool = {
                            "name": tool_data.get("name"),
                            "description": tool_data.get("description"),
                            "inputSchema": tool_data.get("inputSchema", {})
                        }
                        # Preserve metadata if present (e.g., action_templates)
                        if "metadata" in tool_data:
                            loose_tool["metadata"] = tool_data.get("metadata")
                        
                        loose_tools.append(loose_tool)
                    
                    # Cache and return the loosely parsed tools
                    self._cached_tools = loose_tools
                    logger.info(f"MCP client '{self.name}' successfully parsed {len(loose_tools)} tools with relaxed validation.")
                    return loose_tools
                    
                except Exception as fallback_err:
                    logger.error(f"MCP client '{self.name}' list_tools relaxed parsing failed: {fallback_err}")
                    raise e
            else:
                raise

        # Cache the tools for later use
        self._cached_tools = res.tools
        return res.tools

    async def call_tool(self, name: str, arguments: dict | None = None):
        """Call a tool on the MCP server.

        Args:
            name: Tool name
            arguments: Tool arguments (optional)

        Returns:
            Tool call result

        Raises:
            RuntimeError: If not connected
        """
        self._validate_connection()

        return await self.session.call_tool(name, arguments or {})

    def _validate_connection(self) -> None:
        """Validate the connection to the MCP server.

        Raises:
            RuntimeError: If not connected or session not initialized
        """
        if not self.is_connected:
            raise RuntimeError(
                f"MCP client '{self.name}' is not connected. "
                f"Call connect() first.",
            )

        if not self.session:
            raise RuntimeError(
                f"MCP client '{self.name}' session is not initialized. "
                f"Call connect() first.",
            )
