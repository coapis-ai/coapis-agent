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

"""AgentCore - The brain of each agent.

Orchestrates LLM calls, tool execution, and response generation.
Inspired by external reference's run_agent.py loop.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


@dataclass
class ResponseBlock:
    """Structured output block from stream_chat.

    Attributes:
        type: Block type — one of "text", "thinking", "tool_call", "tool_output", "newline"
        content: The text content of this block
        meta: Optional metadata (tool_name, tool_args, etc.)
    """
    type: str          # "text" | "thinking" | "tool_call" | "tool_output" | "newline"
    content: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


def _safe_import(module_name: str) -> bool:
    """Return True if module can be imported, False otherwise."""
    import importlib
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


# ── Tool → Skill fallback mapping ──────────────────────────────────
# When a tool fails, the LLM is hinted to read the related SKILL.md
# for an alternative approach (e.g. using an external library).
# Format: tool_name → (skill_name, brief_reason)
TOOL_SKILL_FALLBACKS: Dict[str, tuple] = {
    "browser_use": ("browser_use", "内置浏览器工具不可用，可使用外部 browser-use 库"),
    "web_search": ("web_search", "搜索工具暂时出错，请检查参数后重试"),
    "desktop_screenshot": ("desktop_screenshot", "截图工具不可用"),
    "send_file_to_user": ("file_reader", "文件发送不可用"),
    "himalaya": ("himalaya", "邮件工具不可用"),
    "execute_shell_command": ("guidance", "命令执行不可用"),
}


class AgentCore:
    """Core agent loop - processes messages through LLM with tool calling.

    Features:
    - Automatic tool calling loop until completion
    - Configurable model parameters
    - Error handling and recovery
    - Message history management
    - Support for multiple model providers
    - Hierarchical memory integration (FoundationManager)
    - Tiered context compression (zero LLM cost for short conversations)
    """

    def __init__(
        self,
        config: Dict[str, Any],
        foundation_manager: Any = None,
        evolution_engine: Any = None,
    ):
        self.config = config
        self.model = config.get("model", "claude-sonnet-4-20250514")
        self.base_url = config.get("base_url", "https://api.anthropic.com")
        # Important: preserve None as None - don't default to empty string
        # Empty string "" causes OpenAI client to fail; None tells it to skip auth header
        self.api_key = config.get("api_key")
        if self.api_key is None and "api_key" not in config:
            self.api_key = ""  # Only default to "" if key wasn't in config at all
        self.temperature = config.get("temperature", 0.7)
        self.max_tokens = config.get("max_tokens", 4096)
        self.max_tool_calls = config.get("max_tool_calls", 20)
        self.top_p = config.get("top_p", 0.95)

        # System prompt components
        self.system_prompt = config.get("system_prompt", "")
        self.identity = config.get("identity", "coapis Agent")

        # Hierarchical memory integration
        self.foundation_manager = foundation_manager

        # Evolution engine integration (self-improvement)
        self.evolution_engine = evolution_engine

        # Security: cross-platform sandbox for tool execution
        self._tool_sandbox = None
        self._import_sandbox = None
        self._ast_sandbox = None
        self._resource_limiter = None
        self._process_isolator = None
        try:
            from ..security.tool_sandbox import ToolSandbox
            from ..security.ast_sandbox import ASTSandbox
            from ..security.resource_limiter import ResourceLimiter
            from ..security.process_isolator import ProcessIsolator
            workspace_dir = config.get("workspace_dir", "")
            username = config.get("username", "")
            if workspace_dir and username:
                self._tool_sandbox = ToolSandbox(username, workspace_dir)
                self._ast_sandbox = ASTSandbox()
                self._resource_limiter = ResourceLimiter()
                self._process_isolator = ProcessIsolator(workspace_dir)
                logger.info("Cross-platform sandbox initialized for user %s", username)
        except Exception as e:
            logger.debug(f"Sandbox init skipped: {e}")

        # LLM client (lazy init)
        self._client: Optional[AsyncOpenAI] = None

        # Session state for foundation memory injection
        self._session_initialized = False

        # Context compressor — always instantiated, triggers based on token/message thresholds
        from .context_compressor import ContextCompressor
        self.compressor = ContextCompressor(self, min_tokens=8000, max_tokens=12000)

    @property
    def client(self) -> AsyncOpenAI:
        """Get or create LLM client."""
        if self._client is None:
            # OpenAI SDK requires a non-empty api_key string.
            # For local LLM (no auth), use "EMPTY" - vLLM and similar servers
            # reject "none" (403 Forbidden) but accept "EMPTY".
            # Never pass None or "" to the client - it will reject the request.
            api_key = self.api_key
            if not api_key:
                api_key = "EMPTY"  # Placeholder for local LLM (vLLM-compatible)
            self._client = AsyncOpenAI(
                base_url=self.base_url,
                api_key=api_key,
            )
        return self._client

    async def process(
        self,
        messages: List[Dict],
        skills: Any = None,
        memory: Any = None,
        is_initial: bool = True,
        query: str = "",
        tools: Any = None,
    ) -> Dict[str, Any]:
        """Process messages through LLM with tool calling loop.

        Args:
            messages: Message history
            skills: SkillManager instance
            memory: MemoryManager instance
            is_initial: Whether this is the first message in session
            query: Current user query (for foundation memory retrieval)
            tools: ToolRegistry instance for on-demand tool selection

        Returns:
            Response dict with content and tool_calls
        """
        system = self._build_system_prompt(skills, memory, is_initial, query)

        # Compress history if needed
        messages = await self.compressor.compress(messages, self.model)

        # Get on-demand tools (core tools + query-relevant tools)
        openai_tools = None
        if tools:
            openai_tools = tools.get_openai_tools(query=query, core_only=not is_initial)

        result = await self._call_llm(system, messages, tools=openai_tools)
        content = result.get("content", "")
        tool_calls = result.get("tool_calls")

        # Execute tools if requested
        if tool_calls:
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                tool_args = json.loads(tc["function"].get("arguments", "{}"))
                try:
                    # Sandbox: validate tool name and arguments
                    if self._tool_sandbox:
                        if tool_name in ("read_file", "write_file", "edit_file"):
                            path = tool_args.get("file_path", "")
                            if path:
                                result = self._tool_sandbox.check_path(path)
                                if not result.allowed:
                                    raise PermissionError(f"Path: {result.reason}")
                        if tool_name == "execute_shell_command":
                            cmd = tool_args.get("command", "")
                            if cmd:
                                result = self._tool_sandbox.check_command(cmd)
                                if not result.allowed:
                                    raise PermissionError(f"Command: {result.reason}")

                    # Prefer ToolRegistry (has registered tool functions)
                    if tools:
                        tool_result = await tools.call(tool_name, **tool_args)
                    elif skills:
                        tool_result = await skills.execute_tool(tool_name, tool_args)
                    else:
                        tool_result = f"No tool executor available for {tool_name}"
                except PermissionError as e:
                    tool_result = f"⛔ Security: {e}"
                    logger.warning(f"Tool {tool_name} blocked by sandbox: {e}")
                except Exception as e:
                    tool_result = f"Tool error: {e}"
                    logger.warning(f"Tool {tool_name} failed: {e}")
                # Use json.dumps to ensure proper JSON format (double quotes)
                # str() produces Python-style single quotes which break LLM JSON parsing
                try:
                    if isinstance(tool_result, dict):
                        tool_result_str = json.dumps(tool_result, ensure_ascii=False, default=str)
                    else:
                        # Handle ToolResponse dataclass (agentscope.tool.ToolResponse)
                        # Extract content blocks and serialize as proper JSON
                        from agentscope.tool import ToolResponse
                        if isinstance(tool_result, ToolResponse):
                            blocks = []
                            for block in tool_result.content:
                                if hasattr(block, "model_dump"):
                                    blocks.append(block.model_dump())
                                elif hasattr(block, "dict"):
                                    blocks.append(block.dict())
                                else:
                                    blocks.append({"type": "text", "text": str(block)})
                            tool_result_str = json.dumps(blocks, ensure_ascii=False, default=str)
                        else:
                            tool_result_str = json.dumps(tool_result, ensure_ascii=False, default=str)
                except Exception:
                    tool_result_str = str(tool_result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tool_name,
                    "content": tool_result_str,
                })
            # Recursive call with tool results
            result = await self._call_llm(system, messages, tools=openai_tools)
            content = result.get("content", "")

        # Evolution: record trajectory
        if self.evolution_engine:
            self.evolution_engine.on_turn_end(
                assistant_message=content,
                tool_calls=tool_calls,
            )

        return {"content": content, "tool_calls": tool_calls}

    async def stream_chat(
        self,
        message: str = None,
        context: Any = None,
        memory: Any = None,
        skills: Any = None,
        compressor: Any = None,
        is_initial: bool = True,
        tools: Any = None,
        show_tool_details: bool = True,
    ):
        """Stream chat response — matches console.py calling convention.

        Args:
            message: Current user message text
            context: ChatContext instance (has .get_messages() and .add_message())
            memory: MemoryManager instance
            skills: SkillManager instance
            compressor: ContextCompressor instance (prefer over self.compressor)
            is_initial: Whether this is the first message in session
            tools: ToolRegistry instance for on-demand tool selection
            show_tool_details: If True, yield 🔧 tool markers into output text.
                If False, suppress them — tool call noise stays internal.

        Yields:
            Text chunks (strings) — consumed by console.py SSE formatter
        """
        # Get message history from context
        messages = context.get_messages() if context else []

        # Build system prompt
        query = message or ""
        system = self._build_system_prompt(skills, memory, is_initial, query)

        # Compress history if needed (use passed compressor or self.compressor)
        active_compressor = compressor or self.compressor
        messages = await active_compressor.compress(messages, self.model)

        # Get on-demand tools (core tools + query-relevant tools)
        openai_tools = None
        if tools:
            openai_tools = tools.get_openai_tools(query=query, core_only=not is_initial)

        # Build request params
        request_params = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "stream": True,
        }
        # Add tools if provided (on-demand tool selection)
        if openai_tools:
            request_params["tools"] = openai_tools

        # Tool-calling loop: keep calling LLM until no more tool calls
        try:
            for _tool_round in range(self.max_tool_calls):
                # Debug: dump messages for JSON issue diagnosis
                _msgs_for_log = [{"role": m.get("role"), "content": str(m.get("content", ""))[:200]} for m in request_params["messages"]]
                logger.info(f"LLM request: model={request_params.get('model')} msgs={len(request_params['messages'])} tools={len(request_params.get('tools') or [])}")
                for _i, _m in enumerate(_msgs_for_log):
                    logger.info(f"  msg[{_i}] role={_m['role']} content_preview={_m['content'][:150]}")
                stream = await self.client.chat.completions.create(**request_params)

                full_content = []
                full_reasoning = []
                tool_calls_data = []
                finish_reason = None

                async for chunk in stream:
                    # Guard against empty choices (some providers send keepalive/no-op chunks)
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    finish_reason = getattr(chunk.choices[0], "finish_reason", None)
                    content = getattr(delta, "content", None) or ""
                    reasoning_content = getattr(delta, "reasoning_content", None) or ""
                    if not reasoning_content:
                        reasoning_content = getattr(delta, "reasoning", None) or ""

                    # Accumulate tool call chunks (streaming format)
                    if hasattr(delta, "tool_calls") and delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            while len(tool_calls_data) <= idx:
                                tool_calls_data.append({"id": "", "function": {"name": "", "arguments": ""}})
                            tc = tool_calls_data[idx]
                            if tc_delta.id:
                                tc["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tc["function"]["name"] = tc_delta.function.name
                                if tc_delta.function.arguments:
                                    tc["function"]["arguments"] += tc_delta.function.arguments

                    if reasoning_content:
                        full_reasoning.append(reasoning_content)
                        yield ResponseBlock(type="thinking", content=reasoning_content)
                    elif content:
                        full_content.append(content)
                        yield ResponseBlock(type="text", content=content)

                # If no tool calls, we're done
                if not tool_calls_data or not any(tc["function"]["name"] for tc in tool_calls_data):
                    break

                # Execute tool calls and build next round messages
                assistant_tool_msg = {
                    "role": "assistant",
                    "tool_calls": [
                        {"id": tc["id"], "type": "function", "function": tc["function"]}
                        for tc in tool_calls_data if tc["function"]["name"]
                    ],
                }
                messages.append(assistant_tool_msg)
                request_params["messages"] = [{"role": "system", "content": system}, *messages]

                for tc in tool_calls_data:
                    if not tc["function"]["name"]:
                        continue
                    tool_name = tc["function"]["name"]
                    try:
                        tool_args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                    except json.JSONDecodeError:
                        tool_args = {}

                    try:
                        logger.info(f"Tool {tool_name} called with args: {json.dumps(tool_args, ensure_ascii=False)[:500]}")
                        if tools:
                            tool_result = await tools.call(tool_name, **tool_args)
                        elif skills:
                            tool_result = await skills.execute_tool(tool_name, tool_args)
                        else:
                            tool_result = f"No tool executor available for {tool_name}"
                        logger.info(f"Tool {tool_name} result (first 300): {str(tool_result)[:300]}")
                    except Exception as e:
                        tool_result = f"Tool error: {e}"
                        logger.warning(f"Tool {tool_name} failed: {e}")
                        # Skill fallback hint: guide LLM to read SKILL.md
                        fallback = TOOL_SKILL_FALLBACKS.get(tool_name)
                        if fallback:
                            skill_name, reason = fallback
                            tool_result += (
                                f"\n\n💡 提示：{reason}。"
                                f"请读取 {skill_name} 技能的 SKILL.md 文件获取详细说明和替代方案。"
                            )

                    # Always yield tool_call so the renderer can decide
                    # how to display (full details, smart summary, or hide)
                    yield ResponseBlock(
                        type="tool_call",
                        content=f"\n\n🔧 [{tool_name}]\n",
                        meta={"tool_name": tool_name, "tool_args": tool_args},
                    )

                    # Use json.dumps to ensure proper JSON format (double quotes)
                    try:
                        if isinstance(tool_result, dict):
                            tool_result_str = json.dumps(tool_result, ensure_ascii=False, default=str)[:8000]
                        else:
                            from agentscope.tool import ToolResponse
                            if isinstance(tool_result, ToolResponse):
                                blocks = []
                                for block in tool_result.content:
                                    if hasattr(block, "model_dump"):
                                        blocks.append(block.model_dump())
                                    elif hasattr(block, "dict"):
                                        blocks.append(block.dict())
                                    else:
                                        blocks.append({"type": "text", "text": str(block)})
                                tool_result_str = json.dumps(blocks, ensure_ascii=False, default=str)[:8000]
                            else:
                                tool_result_str = json.dumps(tool_result, ensure_ascii=False, default=str)[:8000]
                    except Exception:
                        tool_result_str = str(tool_result)[:8000]
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": tool_name,
                        "content": tool_result_str,
                    })
                    request_params["messages"] = [{"role": "system", "content": system}, *messages]

        except Exception as e:
            logger.error(f"stream_chat LLM call failed: {e}", exc_info=True)
            yield ResponseBlock(type="text", content=f"\n\n❌ 抱歉，LLM 调用失败：{e}\n")

        # Evolution: record trajectory (combine both reasoning and content)
        if self.evolution_engine:
            self.evolution_engine.on_turn_end(
                assistant_message="".join(full_content),
            )

    def reset_session(self):
        """Reset session state for new conversation."""
        self._session_initialized = False
        self._cached_system_prompt = None
        self._last_memory_context = None
        # Clear compressor cache and tool usage hint cache
        self.compressor.clear_cache()
        # Force rebuild system prompt on next request
        self._cached_system_prompt = None
        if self.foundation_manager:
            self.foundation_manager.reset_injection_state()

    async def _call_llm(self, system: str, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> Dict:
        """Call LLM and parse response (supports tool calling)."""
        try:
            # Build request params
            request_params = {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, *messages],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "top_p": self.top_p,
            }
            # Add tools if provided (on-demand tool selection)
            if tools:
                request_params["tools"] = tools

            response = await self.client.chat.completions.create(**request_params)

            msg = response.choices[0].message
            # Qwen3 reasoning-parser writes to msg.reasoning instead of msg.content
            content = msg.content or ""
            reasoning = getattr(msg, "reasoning", None) or ""
            # Merge: use reasoning as fallback when content is empty
            merged_content = content if content else reasoning
            result = {"content": merged_content}

            # Parse tool calls
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_calls = []
                for tc in msg.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    })
                result["tool_calls"] = tool_calls

            return result

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return {"content": f"Error: {e}"}

    # ── Tool availability detection (cached once per process) ──

    _tool_availability_cache: str | None = None

    def _get_tool_availability_hint(self) -> str:
        """Check which tools work at runtime and return a prompt section.

        Results are cached because tool deps don't change within a process.
        """
        if self._tool_availability_cache is not None:
            return self._tool_availability_cache

        import importlib, os

        # (tool_name, description, check_callable, how_to_enable)
        checks = [
            (
                "web_search",
                "网页搜索",
                lambda: bool(os.environ.get("TAVILY_API_KEY") or os.environ.get("EXA_API_KEY")),
                "在 docker-compose.yml 中设置 TAVILY_API_KEY（免费 100次/月，注册 https://tavily.com）",
            ),
            (
                "browser_use",
                "浏览器自动化（打开网页、截图、填表等）",
                lambda: _safe_import("browser_use") and _safe_import("playwright"),
                "在 Dockerfile 中添加: pip install browser-use && playwright install chromium",
            ),
            (
                "http_client",
                "HTTP 请求（抓取网页、调用 API）",
                lambda: _safe_import("requests"),
                "已可用（requests 已安装）",
            ),
        ]

        available = []
        unavailable = []
        partial = []

        for name, desc, check, how in checks:
            try:
                ok = check()
            except Exception:
                ok = False
            if ok:
                available.append(f"  ✅ {name}: {desc}")
            else:
                # http_client is "partial" — works but limited for JS pages
                if name == "http_client":
                    partial.append(f"  ⚠️ {name}: {desc}（对 JS 动态渲染页面有限）")
                else:
                    unavailable.append(f"  ❌ {name}: {desc}\n     启用方法: {how}")

        lines = ["\n[TOOL AVAILABILITY]\n以下工具当前可用性状态（如不可用请直接告知用户，不要尝试调用）："]
        lines.extend(available)
        lines.extend(partial)
        if unavailable:
            lines.extend(unavailable)
            lines.append("\n注意：当用户请求依赖不可用工具的功能时，请：")
            lines.append("1. 告知用户该功能当前不可用及原因")
            lines.append("2. 提供替代方案（如有）")
            lines.append("3. 说明如何启用该功能")

        result = "\n".join(lines)
        self._tool_availability_cache = result
        return result

    def _build_system_prompt(
        self,
        skills: Any,
        memory: Any,
        is_initial: bool,
        query: str,
    ) -> str:
        """Build system prompt with hierarchical memory integration.

        优化策略:
        1. 首次请求注入完整 system prompt，后续请求复用缓存（仅替换动态部分）
        2. Skills index 按需精简 — 首次注入完整列表，后续仅保留已使用的技能
        3. Foundation memory 首次注入后缓存，后续不重复注入

        Args:
            skills: SkillManager instance
            memory: MemoryManager instance
            is_initial: Whether this is the initial message in session
            query: Current user query (for foundation memory retrieval)

        Returns:
            Complete system prompt
        """
        # Performance: reuse cached system prompt if available
        if hasattr(self, '_cached_system_prompt') and self._cached_system_prompt and not is_initial:
            # For non-initial requests, reuse the cached base prompt
            # Only rebuild if memory context changed significantly
            if memory:
                memory_context = memory.get_context()
                if memory_context and memory_context != getattr(self, '_last_memory_context', ''):
                    # Memory changed, rebuild
                    self._last_memory_context = memory_context
                    return self._build_full_system_prompt(skills, memory, is_initial, query)
            return self._cached_system_prompt

        # Build full system prompt (first request or memory changed)
        result = self._build_full_system_prompt(skills, memory, is_initial, query)

        # Cache for subsequent requests (only the static parts)
        if is_initial:
            self._cached_system_prompt = result
        return result

    def _load_workspace_md_files(self) -> str:
        """Load AGENTS.md, SOUL.md, PROFILE.md from workspace directory."""
        from pathlib import Path
        import json as _json

        # Get workspace_dir from agent.json
        workspace_dir = None
        try:
            agent_id = self.config.get("agent_id", self.config.get("id", ""))
            logger.info("Workspace MD loader: agent_id=%s, config_keys=%s", agent_id, list(self.config.keys())[:15])
            # Try common workspace paths
            possible_paths = [
                Path(f"/apps/ai/eaterclaw/workspaces/{agent_id.split(':')[-1]}"),
                Path(f"/apps/ai/eaterclaw/workspaces/global_default"),
                Path(f"/apps/ai/coapis/workspaces/{agent_id.split(':')[-1]}"),
                Path(f"/apps/ai/coapis/workspaces/global_default"),
            ]
            for p in possible_paths:
                if (p / "agent.json").exists():
                    with open(p / "agent.json") as f:
                        cfg = _json.load(f)
                    workspace_dir = Path(cfg.get("workspace_dir", str(p)))
                    break
        except Exception as e:
            logger.debug("Failed to get workspace_dir: %s", e)

        if not workspace_dir:
            logger.warning("Workspace MD loader: no workspace_dir found for agent_id=%s", agent_id)
            return ""

        # Load enabled files from system_prompt_files config
        enabled_files = self.config.get("system_prompt_files", ["AGENTS.md", "SOUL.md", "PROFILE.md"])
        logger.info("Workspace MD loader: enabled_files=%s, workspace_dir=%s", enabled_files, workspace_dir)
        parts = []
        for filename in enabled_files:
            file_path = workspace_dir / filename
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8").strip()
                    if content:
                        parts.append(f"\n# {filename}\n\n{content}")
                except Exception as e:
                    logger.debug("Failed to read %s: %s", file_path, e)

        return "\n".join(parts)

    def _build_full_system_prompt(
        self,
        skills: Any,
        memory: Any,
        is_initial: bool,
        query: str,
    ) -> str:
        """Build the complete system prompt from all sources."""
        parts = []

        # Workspace markdown files (AGENTS.md, SOUL.md, PROFILE.md)
        try:
            md_content = self._load_workspace_md_files()
            logger.info("Workspace MD content length: %d", len(md_content) if md_content else 0)
            if md_content:
                parts.append(md_content)
                logger.info("After adding MD content, parts count: %d", len(parts))
        except Exception as e:
            logger.warning("Failed to load workspace markdown files: %s", e)

        # Base identity
        if self.system_prompt:
            parts.append(self.system_prompt)
            logger.info("After adding system_prompt, parts count: %d", len(parts))

        # Foundation memory injection (only on initial request)
        if self.foundation_manager and is_initial:
            context = self.foundation_manager.build_context(is_initial=True, query=query)
            if context:
                parts.append(f"\n[FOUNDATION MEMORY]\n{context}")

        # Skills index — on-demand loading based on query
        if skills:
            # Use query-based matching for initial requests, compact for subsequent
            if is_initial and query:
                skill_index = skills.get_index_prompt(compact=False, query=query)
            else:
                skill_index = skills.get_index_prompt(compact=not is_initial)
            if skill_index:
                parts.append(f"\n[AVAILABLE SKILLS]\n{skill_index}")

        # Inject dynamic built-in skills section from PromptBuilder
        try:
            from .prompt import PromptBuilder
            from pathlib import Path
            pb = PromptBuilder(
                working_dir=Path("."),
                enabled_files=[],
                heartbeat_enabled=False,
                language="zh",
                memory_manager=None,
                include_skills=True,
            )
            discovered = pb._discover_skills()
            if discovered:
                skills_section = pb._build_skills_section(discovered)
                if skills_section:
                    parts.append(f"\n{skills_section}")
        except Exception as e:
            logger.debug("Failed to inject built-in skills section: %s", e)

        # Tool usage instructions — tell the LLM it has function calling tools
        # and should actively use them rather than just answering.
        tool_usage_hint = (
            "\n[TOOL USAGE]\n"
            "你拥有完整的工具集来执行实际操作。当用户的请求涉及以下任何场景时，"
            "你**必须**通过 function call 调用对应工具，而不是仅用文字描述：\n"
            "- 搜索/查找文件内容 -> 使用 grep_search 或 glob_search\n"
            "- 读取文件 -> 使用 read_file\n"
            "- 写入/创建文件 -> 使用 write_file\n"
            "- 编辑文件 -> 使用 edit_file\n"
            "- 执行命令/运行脚本 -> 使用 execute_shell_command\n"
            "- 搜索网页/获取信息 -> 使用 browser_use 或 web_search\n"
            "- 发送文件给用户 -> 使用 send_file_to_user\n"
            "- 查看图片/视频 -> 使用 view_image 或 view_video\n"
            "- 截屏 -> 使用 desktop_screenshot\n"
            "- 查询时间 -> 使用 get_current_time\n"
            "- 代理间通信 -> 使用 chat_with_agent 或 list_agents\n\n"
            "规则：\n"
            "1. 不要说'我会搜索...'，直接调用工具。\n"
            "2. 不要说'这个文件包含...'，直接用 read_file 读取。\n"
            "3. 不要说'我来帮你写个文件'，直接用 write_file 写入。\n"
            "4. 工具执行失败时，分析错误并尝试修复，不要放弃。\n"
            "5. 复杂任务可以连续调用多个工具，工具结果会自动返回给你。\n"
        )
        parts.append(tool_usage_hint)

        # Tool availability — tell the LLM which tools actually work right now.
        # This prevents wasting tokens on tools that will fail at runtime.
        tool_availability = self._get_tool_availability_hint()
        if tool_availability:
            parts.append(tool_availability)

        # Memory context
        if memory:
            memory_context = memory.get_context()
            if memory_context:
                parts.append(f"\n[MEMORY]\n{memory_context}")

        result = "\n".join(parts) if parts else self.system_prompt or ""
        logger.info("Final system prompt length: %d, parts count: %d", len(result), len(parts))
        return result
