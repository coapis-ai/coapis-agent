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

"""ToolRegistry - Async tool registry with security sandboxing.

Inspired by external reference's model_tools.py + CoApis's tool system.
Tools are async-callable with structured metadata and security controls.
"""

import asyncio
import inspect
import logging
import functools
import os
from typing import Dict, List, Optional, Callable, Any, Awaitable
from dataclasses import dataclass, field

from .schema_gen import auto_generate_schema, merge_with_manual_schema

logger = logging.getLogger(__name__)

# ─── SandboxedExecutor integration ───
_sandboxed_executor = None


def _get_sandboxed_executor():
    """Lazy-load SandboxedExecutor to avoid circular imports."""
    global _sandboxed_executor
    if _sandboxed_executor is None:
        try:
            from ..security.sandboxed_executor import SandboxedExecutor
            _sandboxed_executor = SandboxedExecutor()
            logger.info("SandboxedExecutor loaded for tool whitelist checking")
        except Exception as e:
            logger.warning(f"Failed to load SandboxedExecutor: {e}")
    return _sandboxed_executor

# Tool groups — basic is always active; others activated by query keywords.
TOOL_GROUPS = {
    "basic": {
        "description": "基础文件和命令操作",
        "tools": {"read_file", "write_file", "edit_file", "execute_shell_command",
                   "grep_search", "glob_search", "get_current_time", "set_user_timezone"},
        "always_active": True,
    },
    "web": {
        "description": "网页搜索和浏览器自动化",
        "tools": {"web_search", "browser_use"},
        "keywords": {"search", "搜", "查", "新闻", "天气", "热点", "news", "weather",
                      "browser", "网页", "url", "http", "登录", "login", "navigate"},
    },
    "media": {
        "description": "图片、视频、文件传输",
        "tools": {"view_image", "view_video", "send_file_to_user", "desktop_screenshot"},
        "keywords": {"图片", "视频", "照片", "截屏", "screenshot", "image", "video",
                      "发送", "send", "desktop", "screen"},
    },
    "agent": {
        "description": "多智能体协作",
        "tools": {"list_agents", "chat_with_agent", "submit_to_agent",
                   "check_agent_task", "spawn_subagent"},
        "keywords": {"agent", "智能体", "代理", "delegate", "spawn", "协作",
                      "background", "task"},
    },
    "data": {
        "description": "数据分析和处理",
        "tools": {"data_store", "data_ops", "text_processor", "get_token_usage"},
        "keywords": {"数据", "data", "token", "usage", "统计"},
    },
}


@dataclass
class ToolInfo:
    """Tool metadata."""
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Any] = field(default_factory=dict)
    allowed: bool = True
    tags: List[str] = field(default_factory=list)

    @property
    def is_async(self) -> bool:
        return asyncio.iscoroutinefunction(self.func)


class ToolRegistry:
    """Async tool registry with security sandboxing.

    Features:
    - Async tool execution with timeout
    - Permission-based access control
    - Structured tool metadata for LLM prompts
    - Hot-reload support
    """

    def __init__(self):
        self._tools: Dict[str, ToolInfo] = {}
        self._allowed_tools: List[str] = []
        self._denied_tools: List[str] = []

    async def register(self, name: str, func: Callable, description: str = "",
                     parameters: Dict[str, Any] = None, tags: List[str] = None) -> ToolInfo:
        """Register a tool.

        If description or parameters are not provided, they are auto-generated
        from the function's docstring and type annotations.

        Args:
            name: Tool name
            func: Tool function (sync or async)
            description: Tool description (auto-generated from docstring if empty)
            parameters: Parameter schema (auto-generated from signature if None)
            tags: Tool tags for categorization

        Returns:
            ToolInfo metadata
        """
        # Auto-generate schema from function docstring + signature
        try:
            auto_schema = auto_generate_schema(func)
        except Exception as e:
            logger.debug(f"Auto schema generation failed for {name}: {e}")
            auto_schema = None

        # Merge: manual overrides take precedence
        final_description = description
        final_parameters = parameters

        if auto_schema:
            auto_func = auto_schema.get("function", {})
            if not final_description:
                final_description = auto_func.get("description", "")
            if final_parameters is None:
                final_parameters = auto_func.get("parameters", {})
            elif not final_parameters:
                final_parameters = auto_func.get("parameters", {})

        tool = ToolInfo(
            name=name,
            description=final_description or "",
            func=func,
            parameters=final_parameters or {},
            tags=tags or [],
        )
        self._tools[name] = tool
        logger.debug(f"Registered tool: {name}")
        return tool

    async def register_mcp_tools(self, mcp_clients: list) -> int:
        """Register MCP tools with mcp__ prefix to avoid conflicts with built-in tools.

        Each MCP tool is wrapped as a ToolInfo with an async closure that
        delegates to client.call_tool(). The mcp__ prefix convention is
        consistent with Cursor / Claude Desktop tool naming.

        Args:
            mcp_clients: List of MCP client instances (with list_tools/call_tool)

        Returns:
            Number of MCP tools registered
        """
        count = 0
        for client in mcp_clients:
            try:
                mcp_tools = await client.list_tools()
                for mcp_tool in mcp_tools:
                    prefixed = f"mcp__{mcp_tool.name}"

                    # Factory: capture client + tool name in closure
                    def _make_wrapper(_client, _tool_name):
                        async def _mcp_call(**kwargs):
                            result = await _client.call_tool(_tool_name, kwargs)
                            # Normalize CallToolResult → dict for ToolRegistry
                            if hasattr(result, "content"):
                                texts = []
                                for blk in result.content:
                                    texts.append(
                                        getattr(blk, "text", None) or str(blk)
                                    )
                                return {
                                    "result": "\n".join(texts),
                                    "is_error": getattr(result, "isError", False),
                                }
                            return str(result)
                        return _mcp_call

                    await self.register(
                        name=prefixed,
                        func=_make_wrapper(client, mcp_tool.name),
                        description=mcp_tool.description or f"MCP tool: {mcp_tool.name}",
                        parameters=getattr(mcp_tool, "inputSchema", None) or {},
                        tags=["mcp", client.name],
                    )
                    count += 1
                    logger.info(f"Registered MCP tool: {prefixed} (from {client.name})")
            except Exception as e:
                logger.warning(f"Failed to register MCP tools from {client.name}: {e}")
        return count

    async def discover(self):
        """Auto-discover tools from registered modules."""
        # Will be populated by register_builtin_tools and external tools
        pass

    def get_tool(self, name: str) -> Optional[ToolInfo]:
        """Get tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[ToolInfo]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_allowed_tools(self) -> List[ToolInfo]:
        """Get allowed tools (not in denied list)."""
        return [t for t in self._tools.values() if t.name not in self._denied_tools]

    @staticmethod
    def _coerce_args(kwargs: dict, parameters: dict) -> dict:
        """Coerce LLM string arguments to match parameter schema types.

        LLM function calling always sends string values in JSON.  This
        helper inspects the ``parameters`` schema (which may carry
        ``type`` hints extracted via ``inspect``) and converts each
        value to the correct Python type.
        """
        if not parameters:
            return kwargs

        props = parameters.get("properties", parameters)
        coerced = dict(kwargs)
        for key, val in coerced.items():
            if val is None or not isinstance(val, str):
                continue
            prop = props.get(key, {})
            # OpenAI-style schema has {"type": "integer"} etc.
            ptype = prop.get("type", "")
            if ptype in ("integer", "int"):
                try:
                    coerced[key] = int(val)
                except (ValueError, TypeError):
                    pass
            elif ptype in ("number", "float"):
                try:
                    coerced[key] = float(val)
                except (ValueError, TypeError):
                    pass
            elif ptype == "boolean":
                coerced[key] = val.lower() in ("true", "1", "yes")
        return coerced

    async def call(self, name: str, **kwargs) -> Any:
        """Call a tool with timeout and security checks.

        Security checks (in order):
        1. Tool existence check
        2. Deny-list check
        3. SandboxedExecutor whitelist check

        Args:
            name: Tool name
            **kwargs: Tool arguments

        Returns:
            Tool result

        Raises:
            ValueError: If tool not found or not allowed
            asyncio.TimeoutError: If tool execution times out
        """
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Tool not found: {name}")

        if name in self._denied_tools:
            raise ValueError(f"Tool denied: {name}")

        # SandboxedExecutor whitelist check
        executor = _get_sandboxed_executor()
        if executor:
            check = executor.check_tool_allowed(name)
            if not check["allowed"]:
                # Log to audit
                try:
                    from ..security.audit_logger import SecurityAuditLogger
                    username = os.environ.get("COAPIS_USER", "default")
                    audit = SecurityAuditLogger.get_instance()
                    audit.log_tool_denied(
                        user=username,
                        tool_name=name,
                        reason=check["reason"],
                    )
                except Exception:
                    pass
                raise ValueError(f"Tool not allowed: {name} — {check['reason']}")

        # Coerce string args to correct types per parameter schema
        kwargs = self._coerce_args(kwargs, tool.parameters)

        # Execute with timeout
        timeout = 30.0  # Default timeout
        try:
            if tool.is_async:
                return await asyncio.wait_for(tool.func(**kwargs), timeout=timeout)
            else:
                loop = asyncio.get_event_loop()
                return await asyncio.wait_for(
                    loop.run_in_executor(None, functools.partial(tool.func, **kwargs)),
                    timeout=timeout
                )
        except asyncio.TimeoutError:
            logger.error(f"Tool call timed out: {name}")
            raise

    def set_allowed(self, name: str, allowed: bool = True):
        """Set tool access control."""
        if name in self._tools:
            if allowed:
                self._denied_tools = [t for t in self._denied_tools if t != name]
            else:
                if name not in self._denied_tools:
                    self._denied_tools.append(name)

    def get_openai_tools(self, query: str = None, core_only: bool = False) -> List[Dict]:
        """Get tools in OpenAI format for LLM API calls.

        Args:
            query: User query for keyword-based tool matching
            core_only: If True, only return core tools

        Returns:
            List of tool dicts in OpenAI format
        """
        selected = self._select_tools(query, core_only)
        result = []
        for tool in selected:
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            })
        return result

    def _select_tools(self, query: str = None, core_only: bool = False) -> List['ToolInfo']:
        """Select tools using TOOL_GROUPS — basic always active, others by query keywords."""
        allowed = self.get_allowed_tools()
        allowed_names = {t.name for t in allowed}

        if core_only:
            basic = TOOL_GROUPS["basic"]["tools"]
            return [t for t in allowed if t.name in basic]

        if not query:
            # No query — activate all groups
            return list(allowed)

        query_lower = query.lower()
        matched_names = set()

        for group_name, group in TOOL_GROUPS.items():
            if group.get("always_active"):
                matched_names.update(group["tools"])
                continue
            keywords = group.get("keywords", set())
            if any(kw in query_lower for kw in keywords):
                matched_names.update(group["tools"])

        matched_names &= allowed_names  # Only keep registered tools

        # MCP tools are dynamic — always include them regardless of TOOL_GROUPS
        for t in allowed:
            if t.name.startswith("mcp__"):
                matched_names.add(t.name)

        if matched_names:
            selected = [t for t in allowed if t.name in matched_names]
            logger.info(f"Tool selection: {len(selected)} tools from {len(allowed)}")
            return selected

        # Fallback: return all
        return list(allowed)

    def get_prompt(self, query: str = None, core_only: bool = False) -> str:
        """Generate tools section for system prompt.

        Args:
            query: User query for keyword-based tool matching (optional)
            core_only: If True, only return core tools (5 essential ones)

        Returns:
            Tools section string for system prompt

        Strategy:
        - core_only=True: Return 5 core tools (read_file, write_file, edit_file,
          execute_shell_command, grep_search)
        - query provided: Match tools by keyword relevance to query
        - Neither: Return all allowed tools (backward compatible)
        """
        CORE_TOOLS = {"read_file", "write_file", "edit_file", "execute_shell_command", "grep_search"}

        # Keyword-to-tool mapping for query-based matching
        KEYWORD_TO_TOOL = {
            # File operations
            "file": ["read_file", "write_file", "edit_file"],
            "read": ["read_file"],
            "write": ["write_file"],
            "edit": ["edit_file"],
            "search": ["grep_search", "glob_search"],
            "find": ["grep_search", "glob_search"],
            "pattern": ["grep_search"],
            "glob": ["glob_search"],
            # Shell
            "shell": ["execute_shell_command"],
            "command": ["execute_shell_command"],
            "run": ["execute_shell_command"],
            "exec": ["execute_shell_command"],
            "terminal": ["execute_shell_command"],
            "bash": ["execute_shell_command"],
            "ls": ["execute_shell_command"],
            "cat": ["execute_shell_command"],
            "cd": ["execute_shell_command"],
            # Browser
            "browser": ["browser_use"],
            "web": ["browser_use"],
            "url": ["browser_use"],
            "http": ["browser_use"],
            "login": ["browser_use"],
            "screenshot": ["browser_use", "desktop_screenshot"],
            "click": ["browser_use"],
            "navigate": ["browser_use"],
            # Desktop/Screenshot
            "desktop": ["desktop_screenshot"],
            "screen": ["desktop_screenshot"],
            # Media
            "image": ["view_image"],
            "video": ["view_video"],
            "photo": ["view_image"],
            "picture": ["view_image"],
            # Send file
            "send": ["send_file_to_user"],
            "send file": ["send_file_to_user"],
            # Time
            "time": ["get_current_time"],
            "date": ["get_current_time"],
            "now": ["get_current_time"],
            "timezone": ["set_user_timezone"],
            # Token usage
            "token": ["get_token_usage"],
            "usage": ["get_token_usage"],
            # Agent management
            "agent": ["list_agents", "chat_with_agent"],
            "background": ["submit_to_agent"],
            "task": ["check_agent_task"],
            # Web search tools
            "search_web": ["web_search", "browser_use"],
            "news": ["web_search", "browser_use"],
            "weather": ["web_search", "browser_use"],
            "weather_info": ["web_search", "browser_use"],
            "price": ["web_search", "browser_use"],
            "stock": ["web_search", "browser_use"],
            "sports": ["web_search", "browser_use"],
            "score": ["web_search", "browser_use"],
            "result": ["web_search", "browser_use"],
            "today": ["web_search", "browser_use", "get_current_time"],
            "latest": ["web_search", "browser_use"],
            "realtime": ["web_search", "browser_use"],
            "hot": ["web_search", "browser_use"],
            "trending": ["web_search", "browser_use"],
            # Chinese keywords
            "搜索": ["web_search", "browser_use"],
            "查": ["web_search", "browser_use"],
            "新闻": ["web_search", "browser_use"],
            "天气": ["web_search", "browser_use"],
            "股票": ["web_search", "browser_use"],
            "体育": ["web_search", "browser_use"],
            "比分": ["web_search", "browser_use"],
            "价格": ["web_search", "browser_use"],
            "热点": ["web_search", "browser_use"],
            "热榜": ["web_search", "browser_use"],
            "热搜": ["web_search", "browser_use"],
            "今天": ["web_search", "browser_use", "get_current_time"],
            "最新": ["web_search", "browser_use"],
            "实时": ["web_search", "browser_use"],
            "网页": ["web_search", "browser_use"],
            "网站": ["browser_use"],
            "浏览": ["browser_use"],
            "打开": ["browser_use"],
            "截图": ["browser_use"],
        }

        allowed = self.get_allowed_tools()

        # Core-only mode: return only essential tools
        if core_only:
            selected = [t for t in allowed if t.name in CORE_TOOLS]
            if not selected:
                selected = list(allowed)  # Fallback if no core tools registered

        # Query-based matching: select relevant tools
        elif query:
            query_lower = query.lower()
            selected_names = set(CORE_TOOLS)  # Always include core tools

            for keyword, tool_names in KEYWORD_TO_TOOL.items():
                if keyword in query_lower:
                    selected_names.update(tool_names)

            selected = [t for t in allowed if t.name in selected_names]

        # Default: return all allowed tools (backward compatible)
        else:
            selected = allowed

        lines = ["Available Tools:"]
        for tool in selected:
            lines.append(f"- **{tool.name}**: {tool.description}")
            if tool.parameters:
                for param_name, param_schema in tool.parameters.items():
                    lines.append(f"  - `{param_name}`: {param_schema.get('description', '')}")
        return "\n".join(lines)
