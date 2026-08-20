"""MCP Gateway — single entrypoint for discovering and calling MCP tools.

Design goals:
  - Minimal: reuse existing MCPClientManager / client transports.
  - Stable: do not change existing `register_mcp_tools` or `mcp__` naming.
  - Extensible: later this can back a single `mcp_gateway` toolkit tool.

Usage:
    gateway = MCPGateway(manager)
    tools = await gateway.list_gateway_tools()
    result = await gateway.call_tool("mcp:gitee.search_repos", {"query": "coapis"})
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPGateway:
    """Aggregate view over all connected MCP clients.

    Naming convention for gateway tools:
      mcp:{client_key}::{tool_name}

    Example:
      mcp:gitee::search_repos
      mcp:filesystem::read_file
    """

    def __init__(self, mcp_manager: Any) -> None:
        self._manager = mcp_manager

    async def list_gateway_tools(self) -> list[dict[str, Any]]:
        """Return all MCP tools across all enabled clients.

        Each item:
          - gateway_name: str  (mcp:{client_key}::{tool_name})
          - client_key: str
          - tool_name: str
          - description: str
          - input_schema: dict
          - enabled: bool
        """
        if self._manager is None:
            return []

        try:
            clients = await self._manager.get_clients()
        except Exception as exc:
            logger.debug("MCPGateway.list_gateway_tools: get_clients failed: %s", exc)
            return []

        tools: list[dict[str, Any]] = []
        for client in clients:
            client_key = getattr(client, "name", None) or getattr(client, "client_key", None)
            if not client_key:
                continue
            try:
                mcp_tools = await client.list_tools()
            except Exception as exc:
                logger.debug(
                    "MCPGateway.list_gateway_tools: client=%s list_tools failed: %s",
                    client_key,
                    exc,
                )
                continue

            for mcp_tool in mcp_tools:
                tool_name = mcp_tool.get("name", "")
                if not tool_name:
                    continue
                gateway_name = f"mcp:{client_key}::{tool_name}"
                tools.append({
                    "gateway_name": gateway_name,
                    "client_key": client_key,
                    "tool_name": tool_name,
                    "description": mcp_tool.get("description", "") or "",
                    "input_schema": mcp_tool.get("inputSchema", {}) or {},
                    "enabled": getattr(client, "enabled", True),
                })

        tools.sort(key=lambda x: (x["client_key"], x["tool_name"]))
        return tools

    async def call_tool(
        self, 
        gateway_name: str, 
        arguments: dict[str, Any],
        user_context_token: str | None = None,
    ) -> dict[str, Any]:
        """Call an MCP tool by gateway name.

        Args:
            gateway_name: "mcp:{client_key}::{tool_name}"
            arguments: tool arguments dict
            user_context_token: Internal context JWT token for external MCP server authentication

        Returns:
            {"result": str, "is_error": bool}
        """
        prefix = "mcp:"
        if not gateway_name.startswith(prefix) or "::" not in gateway_name:
            return {"result": f"Invalid gateway tool name: {gateway_name!r}", "is_error": True}

        body = gateway_name[len(prefix):]
        try:
            client_key, tool_name = body.split("::", 1)
        except ValueError:
            return {"result": f"Invalid gateway tool name format: {gateway_name!r}", "is_error": True}

        if not client_key or not tool_name:
            return {"result": f"Empty client_key or tool_name in: {gateway_name!r}", "is_error": True}

        if self._manager is None:
            return {"result": "MCP manager not initialized", "is_error": True}

        try:
            clients = await self._manager.get_clients()
        except Exception as exc:
            return {"result": f"Failed to get MCP clients: {exc}", "is_error": True}

        target = None
        for client in clients:
            c_key = getattr(client, "name", None) or getattr(client, "client_key", None)
            if c_key == client_key:
                target = client
                break

        if target is None:
            return {"result": f"MCP client '{client_key}' not found", "is_error": True}

        if not getattr(target, "enabled", True):
            return {"result": f"MCP client '{client_key}' is disabled", "is_error": True}

        # Set user context token on the target client if available
        if user_context_token and hasattr(target, 'set_user_context_token'):
            try:
                target.set_user_context_token(user_context_token)
            except Exception:
                pass  # Non-fatal if setting token fails
                
        try:
            result = await target.call_tool(tool_name, arguments)
        except Exception as exc:
            logger.exception("MCPGateway.call_tool failed: %s :: %s", gateway_name, exc)
            return {"result": f"Tool call failed: {exc}", "is_error": True}

        if hasattr(result, "content"):
            texts = []
            for blk in getattr(result, "content", []) or []:
                texts.append(getattr(blk, "text", None) or str(blk))
            return {
                "result": "\n".join(texts),
                "is_error": bool(getattr(result, "isError", False)),
            }

        return {"result": str(result), "is_error": False}
