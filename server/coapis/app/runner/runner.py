# -*- coding: utf-8 -*-
# pylint: disable=unused-argument too-many-branches too-many-statements
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

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator, Coroutine

import frontmatter as fm
from agentscope.message import Msg, TextBlock
from agentscope_runtime.engine.runner import Runner
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
from agentscope_runtime.engine.schemas.exception import (
    AgentException,
    AppBaseException,
)
from dotenv import load_dotenv

from .command_dispatch import (
    _get_last_user_text,
    _is_command,
    run_command_path,
)
from .query_error_dump import write_query_error_dump
from .mission_dispatch import (
    maybe_handle_mission_command,
    detect_active_mission_phase,
)
from .session import SafeJSONSession
from .utils import build_env_context
from ..channels.schema import DEFAULT_CHANNEL
from ...agents.react_agent import CoApisAgent
from ...exceptions import convert_model_exception
from ...agents.utils.file_handling import (
    read_text_file_with_encoding_fallback,
)
from ...config.config import load_agent_config
from ...constant import WORKING_DIR

if TYPE_CHECKING:
    from ...agents.memory import BaseMemoryManager
    from ...agents.context import BaseContextManager

logger = logging.getLogger(__name__)




# ------------------------------------------------------------------
# Evolution Engine Helpers (used in query_handler)
# ------------------------------------------------------------------

def _evolution_collect_text(msg: Any, buf: list[str]) -> None:
    """Append text content from a message to a buffer list.
    
    Handles both AgentScope Msg objects and plain text.
    """
    try:
        text = getattr(msg, "get_text_content", None)
        if callable(text):
            t = text()
            if t:
                buf.append(t)
        else:
            # Fallback: try content attribute
            content = getattr(msg, "content", None)
            if isinstance(content, str) and content:
                buf.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, str):
                        buf.append(block)
                    elif hasattr(block, "type") and hasattr(block, "text"):
                        if getattr(block, "type") == "text":
                            buf.append(getattr(block, "text", ""))
    except Exception:
        # Never let evolution collection break the main flow
        pass


def _evolution_trigger_turn_end(
    engine: Any,
    assistant_message: str,
) -> None:
    """Safely trigger EvolutionEngine.on_turn_end.
    
    Wraps in try/except so evolution never blocks the main flow.
    Also injects trigger causality data from TriggerTracker.
    """
    try:
        if engine.enabled:
            # Collect trigger data from TriggerTracker
            trigger_events = []
            trigger_outcomes = []
            try:
                from coapis.agents.utils.trigger_tracker import get_trigger_tracker
                tracker = get_trigger_tracker()
                trigger_events = tracker.get_session_trigger_events()
                trigger_outcomes = tracker.get_session_trigger_outcomes()
            except Exception:
                pass

            engine.on_turn_end(
                assistant_message=assistant_message,
                tool_calls=[],
                tool_results=[],
                tokens_used=0,
                trigger_events=trigger_events or None,
                trigger_outcomes=trigger_outcomes or None,
            )
            logger.debug(
                "EvolutionEngine: turn_end recorded (%d chars, %d triggers, %d outcomes)",
                len(assistant_message), len(trigger_events), len(trigger_outcomes),
            )
    except Exception:
        logger.warning(
            "EvolutionEngine.on_turn_end failed",
            exc_info=True,
        )


# Imported from shared module — keep aliases for backward compatibility
from ...agents.stream_utils import (
    cancel_streaming_task as _cancel_streaming_agent_task,
    stream_agent_messages as _stream_printing_messages_interruptible,
)


class AgentRunner(Runner):
    def __init__(
        self,
        agent_id: str = "default",
        workspace_dir: Path | None = None,
        task_tracker: Any | None = None,
    ) -> None:
        super().__init__()
        self.framework_type = "agentscope"
        self.agent_id = agent_id  # Store agent_id for config loading
        self.workspace_dir = (
            workspace_dir  # Store workspace_dir for prompt building
        )
        self._chat_manager = None  # Store chat_manager reference
        self._mcp_manager = None  # MCP client manager for hot-reload
        self._workspace: Any = None  # Workspace instance for control commands
        self.memory_manager: BaseMemoryManager | None = None
        self.context_manager: BaseContextManager | None = None
        self._task_tracker = task_tracker  # Task tracker for background tasks

    def set_chat_manager(self, chat_manager):
        """Set chat manager for auto-registration.

        Args:
            chat_manager: ChatManager instance
        """
        self._chat_manager = chat_manager

    def set_mcp_manager(self, mcp_manager):
        """Set MCP client manager for hot-reload support.

        Args:
            mcp_manager: MCPClientManager instance
        """
        self._mcp_manager = mcp_manager

    def set_workspace(self, workspace):
        """Set workspace for control command handlers.

        Args:
            workspace: Workspace instance
        """
        self._workspace = workspace

    def _get_evolution_engine(self) -> Any | None:
        """Get evolution engine from Workspace if available.

        Returns:
            EvolutionEngine instance or None.
        """
        if self._workspace is None:
            return None
        engine = getattr(self._workspace, "evolution_engine", None)
        if engine is not None:
            return engine
        # Fallback: check ServiceManager services
        sm = getattr(self._workspace, "_service_manager", None)
        if sm is not None:
            return getattr(sm, "services", {}).get("evolution_engine")
        return None

    @staticmethod
    def _extract_summary_from_reasoning(reasoning_text: str, max_chars: int = 800) -> str:
        """Extract a user-visible summary from reasoning text.

        When the model puts all explanatory text in reasoning blocks
        and the message block is empty, this method extracts the last
        meaningful paragraph as a fallback summary.

        Args:
            reasoning_text: Full concatenated reasoning text
            max_chars: Maximum characters to extract

        Returns:
            Extracted summary text, or empty string if nothing useful
        """
        if not reasoning_text or not reasoning_text.strip():
            return ""

        text = reasoning_text.strip()

        # Split into paragraphs (double newline)
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        if not paragraphs:
            # Single paragraph — take last N chars
            return text[-max_chars:] if len(text) > max_chars else text

        # Take the last 1-3 paragraphs that fit within max_chars
        result_parts = []
        total_len = 0
        for p in reversed(paragraphs):
            if total_len + len(p) > max_chars and result_parts:
                break
            result_parts.append(p)
            total_len += len(p)

        result_parts.reverse()
        return "\n\n".join(result_parts)

    async def _persist_chat_messages(
        self,
        chat,
        session_id: str,
        user_id: str,
        channel: str,
        msgs: list,
        assistant_text: str,
        name: str = "New Chat",
        full_reasoning: list[str] | None = None,
        user_text_override: str = "",
        agent_messages: list | None = None,
    ) -> None:
        """Persist chat messages to session state.

        After the agent finishes processing, this method saves the
        complete conversation (including tool_call, tool_output,
        reasoning, assistant) to the AgentScope session state file
        at workspaces/{username}/sessions/{chat_id}.json.

        This ensures:
        1. Chat history survives page reload with full structure
        2. Each user has completely isolated chat storage
        3. Chat title auto-renames from first user message
        4. chats.json only stores metadata (no embedded messages)
        """
        # Get the MultiAgentManager via workspace back-reference
        manager = getattr(self._workspace, "_manager", None)
        if manager is None:
            logger.warning(
                "_persist_chat_messages: no MultiAgentManager on workspace %s, "
                "messages will NOT be persisted! workspace_type=%s, "
                "has_runner=%s",
                getattr(self._workspace, '__class__', '?').__name__,
                type(self._workspace).__name__,
                hasattr(self._workspace, 'runner'),
            )
            return

        # For channel messages (e.g. WeCom, DingTalk), user_id is the channel
        # sender's ID, not a system user ID. Resolve to workspace owner if needed.
        effective_user_id = user_id
        ws_username = getattr(self._workspace, 'username', None)
        if ws_username and user_id != ws_username:
            logger.info(
                "_persist_chat_messages: user_id=%s resolved to workspace owner=%s",
                user_id, ws_username,
            )
            effective_user_id = ws_username

        # Use workspace's own ChatManager (physical isolation)
        cm = self._chat_manager
        if cm is None:
            logger.warning("_persist_chat_messages: no ChatManager for user_id=%s, skip", user_id)
            return

        # Find the chat by UUID (chat.id)
        chat_id = getattr(chat, "id", None)
        user_chat = None
        if chat_id:
            user_chat = await cm.get_chat(chat_id)
        if user_chat is None:
            user_chat = await cm.get_or_create_chat(
                session_id, effective_user_id, channel,
                name=name, agent_id=self.agent_id,
            )

        # Extract user message text - prefer override (raw query) over msgs[-1]
        # because msgs contains agent internal messages (BOOTSTRAP, system prompts)
        # not the original user input.
        user_text = user_text_override.strip() if user_text_override else ""
        if not user_text and msgs:
            last_msg = msgs[-1]
            user_text = getattr(last_msg, "get_text_content", lambda: "")()
            if not user_text:
                user_text = str(getattr(last_msg, "content", ""))
        logger.info(
            "_persist_chat_messages: user_text_override=%r, final user_text=%r (len=%d), msgs_count=%d",
            user_text_override[:50] if user_text_override else "",
            user_text[:80], len(user_text), len(msgs) if msgs else 0,
        )

        # Auto-rename chat from first user message (if still "New Chat")
        current_name = getattr(user_chat, "name", "") or ""
        is_new_chat = not current_name or current_name in ("New Chat", "新聊天", "")
        if user_text and is_new_chat:
            first_line = user_text.strip().split("\n")[0].strip()
            quick_name = first_line[:30] + ("..." if len(first_line) > 30 else "")
            if quick_name:
                try:
                    from ..runner.models import ChatUpdate
                    await cm.patch_chat(user_chat.id, ChatUpdate(name=quick_name))
                    logger.debug(f"Quick-renamed chat to: {quick_name}")
                except Exception:
                    logger.debug("Failed to quick-rename chat", exc_info=True)
                try:
                    asyncio.create_task(
                        self._generate_llm_title(cm, user_chat.id, user_text, assistant_text),
                    )
                except Exception:
                    logger.debug("Failed to queue LLM title generation", exc_info=True)

        # ── Persist messages to session state (CoApis pattern) ──
        # Use chat_id (UUID) as session key for per-chat isolation.
        # session_id (e.g. "console:admin") is shared across all chats
        # and would cause messages to overwrite each other.
        # chat_id is unique per chat, stored at agents/{agent_id}/sessions/{chat_id}.json
        #
        # IMPORTANT: session file write is in its own try/except so that a
        # write failure (disk full, permission) does NOT prevent the chat
        # metadata (rename, etc.) from being committed above.
        try:
            session = self.session  # SafeJSONSession from Runner base
            if session is None:
                logger.warning("_persist_chat_messages: session is None, skip")
                return

            # Load existing session state using chat_id as key
            state = await session.get_session_state_dict(
                user_chat.id, user_id, allow_not_exist=True,
            )
            memory_state = (state or {}).get("agent", {}).get("memory", {})
            _existing_blocks = sum(
                len(msg.get("content", []))
                for batch in memory_state.get("content", [])
                if isinstance(batch, list) and batch
                for msg in [batch[0]]
                if isinstance(msg, dict)
            )
            logger.info(
                "_persist_chat_messages: loaded memory_state with %d batches, %d total blocks",
                len(memory_state.get("content", [])),
                _existing_blocks,
            )

            # ── Migration: session_id file → chat_id (UUID) file ──
            # When the session key format changed from session_id to chat_id
            # (UUID), old messages remain in the session_id file. Merge
            # them into the UUID file so Console can display full history.
            # Only merge when old file has more batches (one-time migration).
            # Note: old format used "{user}:{channel}:{ext_id}" as session_id,
            # new format uses "{channel}:{ext_id}". Try both.
            if session_id and session_id != user_chat.id:
                _candidates = [session_id]
                if effective_user_id and not session_id.startswith(effective_user_id + ":"):
                    _candidates.append(f"{effective_user_id}:{session_id}")
                old_memory = {}
                old_batches = []
                for _sid in _candidates:
                    old_state = await session.get_session_state_dict(
                        _sid, effective_user_id, allow_not_exist=True,
                    )
                    old_memory = (old_state or {}).get("agent", {}).get("memory", {})
                    old_batches = old_memory.get("content", [])
                    if old_batches:
                        break
                cur_batches = memory_state.get("content", [])
                if old_batches and len(old_batches) > len(cur_batches):
                    logger.info(
                        "_persist_chat_messages: merging %d old batches "
                        "(session_id=%s) into %d batches (chat_id=%s)",
                        len(old_batches), session_id,
                        len(cur_batches), user_chat.id,
                    )
                    # Prepend old batches before current ones
                    merged = list(old_batches) + [
                        b for b in cur_batches
                        if b not in old_batches
                    ]
                    merged_memory = dict(old_memory)
                    merged_memory["content"] = merged
                    await session.update_session_state(
                        session_id=user_chat.id,
                        key="agent.memory",
                        value=merged_memory,
                        user_id=effective_user_id,
                    )
                    memory_state = merged_memory

            # Use a FRESH InMemoryMemory to avoid cross-chat contamination.
            # self.memory_manager is shared across all chats and accumulates
            # messages from every request — using it would leak messages
            # between different users/chats.
            from agentscope.memory import InMemoryMemory
            isolated_mem = InMemoryMemory()
            if memory_state:
                isolated_mem.load_state_dict(memory_state, strict=False)
            logger.info(
                "_persist_chat_messages: isolated_mem loaded with %d messages",
                len(isolated_mem.content),
            )

            # ── Add new messages ──
            # If agent_messages is provided (from agent.memory), use it directly.
            # This preserves ALL message types: tool_call, tool_output, mcp_call,
            # mcp_call_output, reasoning, assistant — not just user + assistant.
            if agent_messages:
                # Dedup: skip if first new message is already the last in session
                _existing_count = len(isolated_mem.content)
                _skip_first = False
                if _existing_count > 0 and agent_messages:
                    _last_existing, _ = isolated_mem.content[-1]
                    _first_new = agent_messages[0]
                    # Check if they're the same user message
                    if (getattr(_last_existing, "role", "") == "user"
                            and getattr(_first_new, "role", "") == "user"):
                        _last_text = getattr(_last_existing, "get_text_content", lambda: "")()
                        _first_text = getattr(_first_new, "get_text_content", lambda: "")()
                        if _last_text.strip() == _first_text.strip():
                            _skip_first = True
                            logger.info("_persist_chat_messages: skipped duplicate user message")

                _msgs_to_add = agent_messages[1:] if _skip_first else agent_messages

                # Filter out ephemeral bootstrap guidance system messages
                # to prevent them from being persisted into session history.
                from ...agents.prompt import _BOOTSTRAP_GUIDANCE_TAG
                _before_filter = len(_msgs_to_add)
                _msgs_to_add = [
                    m for m in _msgs_to_add
                    if not (
                        getattr(m, "role", "") == "system"
                        and _BOOTSTRAP_GUIDANCE_TAG in (
                            (m.get_text_content() or "")
                            if hasattr(m, "get_text_content")
                            else str(getattr(m, "content", "") or "")
                        )
                    )
                ]
                _filtered = _before_filter - len(_msgs_to_add)
                if _filtered:
                    logger.info(
                        "_persist_chat_messages: filtered %d bootstrap "
                        "guidance system messages", _filtered,
                    )

                for msg in _msgs_to_add:
                    await isolated_mem.add(msg)
                logger.info(
                    "_persist_chat_messages: added %d agent messages (tool_call, "
                    "tool_output, reasoning, assistant, etc.)",
                    len(_msgs_to_add),
                )
            else:
                # Fallback: old logic for paths that don't pass agent_messages
                # (e.g. early-exit paths like /mission, /skill info)
                _last_user_text = ""
                if isolated_mem.content:
                    _last_msg, _ = isolated_mem.content[-1]
                    if getattr(_last_msg, "role", "") == "user":
                        _last_user_text = getattr(_last_msg, "get_text_content", lambda: "")()

                if user_text and user_text.strip() != _last_user_text.strip():
                    user_msg = Msg(name="user", content=[TextBlock(text=user_text)], role="user")
                    await isolated_mem.add(user_msg)
                    logger.info("_persist_chat_messages: added user message (%d chars)", len(user_text))
                elif user_text:
                    logger.info("_persist_chat_messages: skipped duplicate user message (%d chars)", len(user_text))

                # Save reasoning/thinking as a separate message with metadata marker
                reasoning_text = "".join(full_reasoning) if full_reasoning else ""
                if reasoning_text:
                    reasoning_msg = Msg(
                        name="assistant",
                        content=[TextBlock(text=reasoning_text)],
                        role="assistant",
                    )
                    reasoning_msg.metadata = {"type": "reasoning"}
                    await isolated_mem.add(reasoning_msg)
                if assistant_text:
                    assistant_msg = Msg(name="assistant", content=[TextBlock(text=assistant_text)], role="assistant")
                    await isolated_mem.add(assistant_msg)
                elif reasoning_text:
                    summary = self._extract_summary_from_reasoning(reasoning_text)
                    if summary:
                        assistant_msg = Msg(name="assistant", content=[TextBlock(text=summary)], role="assistant")
                        await isolated_mem.add(assistant_msg)

            logger.info(
                "_persist_chat_messages: isolated_mem now has %d messages before save",
                len(isolated_mem.content),
            )
            for idx, (m, marks) in enumerate(isolated_mem.content):
                blocks = getattr(m, "content", [])
                block_types = [getattr(b, "type", "?") for b in blocks] if isinstance(blocks, list) else []
                logger.info(
                    "  [%d] role=%s, blocks=%s, marks=%s",
                    idx, getattr(m, "role", "?"), block_types, marks,
                )

            # Save updated memory state back to session using chat_id as key
            await session.update_session_state(
                session_id=user_chat.id,
                key="agent.memory",
                value=isolated_mem.state_dict(),
                user_id=effective_user_id,
            )

            logger.info(
                f"_persist_chat_messages: saved to session chat={user_chat.id} "
                f"user={effective_user_id}, session_file={user_chat.id}.json"
            )
        except Exception:
            logger.warning(
                "Failed to persist messages to session state",
                exc_info=True,
            )

    async def _generate_llm_title(
        self,
        chat_manager,
        chat_id: str,
        user_text: str,
        assistant_text: str = "",
    ) -> None:
        """Generate a concise session title using LLM in background.

        Runs asynchronously after the quick-rename so the UI gets
        instant feedback, then upgrades to a polished title.
        """
        try:
            # Build a compact prompt
            snippet = user_text[:500]
            context = ""
            if assistant_text:
                context = f"\nAssistant replied: {assistant_text[:200]}"

            prompt = (
                f"Generate a concise title (max 20 chars) for this conversation.\n"
                f"User said: {snippet}{context}\n\n"
                f"Reply with ONLY the title, no quotes, no explanation."
            )

            # Use the agent's LLM client (lightweight call)
            ws = getattr(self, "_workspace", None)
            client = None
            if ws:
                core = getattr(ws, "core", None)
                if core and hasattr(core, "client"):
                    client = core.client
            if client is None:
                logger.debug("_generate_llm_title: no LLM client available, skip")
                return

            # Determine model name from core or fallback
            model_name = "qwen-turbo"
            if ws:
                core = getattr(ws, "core", None)
                if core and hasattr(core, "model"):
                    model_name = core.model

            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are a title generator. Reply with only the title."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=30,
                temperature=0.3,
            )
            title = (response.choices[0].message.content or "").strip().strip('"').strip("'")
            if not title or len(title) > 50:
                return

            # Update chat name
            from ..runner.models import ChatUpdate
            await chat_manager.patch_chat(chat_id, ChatUpdate(name=title))
            logger.info(f"LLM title generated for chat {chat_id}: {title}")
        except Exception:
            logger.debug("LLM title generation failed", exc_info=True)

    @staticmethod
    def _parse_skill_query(
        query: str,
    ) -> tuple[str, str] | None:
        """Parse ``/name [input]`` or ``/[name with spaces] [input]``.

        Bracket form ``/[...]`` handles spaces in skill names and
        bypasses built-in command priority.

        Returns ``(skill_name, user_input)`` or ``None``.
        """
        stripped = query.strip()
        if not stripped.startswith("/"):
            return None

        rest = stripped[1:]  # drop leading /

        # /[skill name] input — bracket form
        if rest.startswith("["):
            close = rest.find("]")
            if close < 0:
                return None
            name = rest[1:close].strip().lower()
            user_input = rest[close + 1 :].strip()
            return (name, user_input) if name else None

        # /name input — plain form
        parts = rest.split(None, 1)
        if not parts:
            return None
        name = parts[0].lower()
        user_input = parts[1] if len(parts) > 1 else ""
        return (name, user_input) if name else None

    @staticmethod
    def _maybe_inject_skill(
        query: str | None,
        msgs: list,
        skills: dict,
    ) -> Msg | None:
        """Handle ``/<skill_name> [input]`` or ``/[skill name] [input]``.

        *skills* is ``agent.toolkit.skills`` — already resolved for
        the current channel during agent init.  Hot-reload safe because
        the agent is recreated on every query.

        Returns a ``Msg`` to short-circuit (skill info), or ``None``
        to continue to the LLM with rewritten ``msgs``.
        """
        if not query or not query.startswith("/") or not msgs:
            return None

        parsed = AgentRunner._parse_skill_query(query)
        if not parsed:
            return None
        name, user_input = parsed

        # Lookup by folder name
        skill = next(
            (
                s
                for s in skills.values()
                if Path(s["dir"]).name.lower() == name
            ),
            None,
        )
        if not skill:
            return None

        skill_dir = Path(skill["dir"])
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None

        raw = read_text_file_with_encoding_fallback(skill_md)
        post = fm.loads(raw)
        display_name = post.get("name") or name

        # /<name> without input → return skill info.
        if not user_input:
            desc = post.get("description") or "No description."
            logger.info("Skill info: %s", name)
            return Msg(
                name="Friday",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"**{name}**\n\n"
                            f"- **command**: `/{name} <input>` to invoke\n"
                            f"- **name**: {display_name}\n"
                            f"- **description**: {desc}\n"
                            f"- **path**: `{skill_dir}`"
                        ),
                    ),
                ],
            )

        # /<name> <input> → rewrite user message with skill body.
        merged = (
            f"Use the [{display_name}] skill in "
            f"`{skill_dir}` to fulfill "
            f"user's task: {user_input}\n\n"
            f"{post.content}"
        )
        AgentRunner._rewrite_last_message_text(msgs, merged)
        logger.info("Skill invocation: %s", name)
        return None

    @staticmethod
    def _rewrite_last_message_text(
        msgs: list,
        new_text: str,
    ) -> None:
        """Rewrite the text content of the last message in-place."""
        if not msgs:
            return
        last = msgs[-1]
        content = getattr(last, "content", None)
        if isinstance(content, list):
            for i, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "text":
                    content[i] = TextBlock(
                        type="text",
                        text=new_text,
                    )
                    return
            content.insert(
                0,
                TextBlock(type="text", text=new_text),
            )
        elif isinstance(content, str):
            last.content = new_text

    async def stream_query(self, request, **kwargs):
        """Override base Runner.stream_query to set created_at on response events.

        The base class handles:
        1. Calling self.query_handler() to get (msg, last) tuples
        2. Passing through adapt_agentscope_message_stream adapter
           to convert (msg, last) → proper Event objects (Message, TextContent, DataContent)
        3. Yielding Events with correct lifecycle (InProgress/Completed)

        Workspace calls stream_query() instead of
        query_handler() directly, letting the framework adapter handle all Event
        construction — fixing tool_call rendering, delta duplication, and message
        structure issues.
        """
        from datetime import datetime, timezone

        created_at = int(datetime.now(timezone.utc).timestamp())
        async for event in super().stream_query(request, **kwargs):
            if getattr(event, "object", None) == "response":
                event.created_at = created_at
            yield event

    async def query_handler(
        self,
        msgs,
        request: AgentRequest = None,
        **kwargs,
    ):
        """
        Handle agent query.
        """
        logger.debug(
            f"AgentRunner.query_handler called: agent_id={self.agent_id}, "
            f"msgs={msgs}, request={request}",
        )
        query = _get_last_user_text(msgs)
        session_id = getattr(request, "session_id", "") or ""

        # --- Evolution Engine Hooks (Phase 1: Session + Turn Start) ---
        engine = self._get_evolution_engine()
        if engine and query and not _is_command(query):
            # Only start session once per new session
            if not engine._current_session_id:
                user_id = getattr(request, "user_id", "") or ""
                engine.on_session_start(
                    session_id=session_id,
                    agent_id=self.agent_id,
                    user_id=user_id,
                )
            # Record user message for every turn
            engine.on_turn_start(user_message=query)
        # ----------------------------------------------------------------

        # Check if query is a command (including /approval)
        logger.debug(f"Query: {query!r}, is_command: {_is_command(query)}")
        if query and _is_command(query):
            logger.info("Command path: %s", query.strip()[:50])
            async for msg, last in run_command_path(request, msgs, self):
                yield msg, last
            return

        logger.debug(
            f"AgentRunner.stream_query: request={request}, "
            f"agent_id={self.agent_id}",
        )

        # Set session context for concurrent safety (CoApis pattern)
        from ...config.session_context import (
            set_current_agent_id,
            set_current_session_id,
            set_current_root_session_id,
        )

        set_current_agent_id(self.agent_id)
        set_current_session_id(session_id)

        agent = None
        chat = None
        session_state_loaded = False
        # Initialize variables before try block so they're available in finally
        _evolution_full_response: list[str] = []
        _evolution_full_reasoning: list[str] = []
        _memory_snapshot_len = 0
        name = "New Chat"
        channel = DEFAULT_CHANNEL
        try:
            # Get session identity from request, with session_context fallback
            from ...config.session_context import (
                get_current_session_id,
                get_current_user_id,
                get_current_channel,
            )
            session_id = request.session_id or get_current_session_id() or ""
            user_id = request.user_id or get_current_user_id() or ""
            channel = getattr(request, "channel", None) or get_current_channel() or DEFAULT_CHANNEL

            logger.info(
                "Handle agent query:\n%s",
                json.dumps(
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                        "channel": channel,
                        "msgs_len": len(msgs) if msgs else 0,
                        "msgs_str": str(msgs)[:300] + "...",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )

            env_context = build_env_context(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                working_dir=(
                    str(self.workspace_dir)
                    if self.workspace_dir
                    else str(WORKING_DIR)
                ),
            )

            # Get MCP clients from manager (hot-reloadable)
            mcp_clients = []
            if self._mcp_manager is not None:
                mcp_clients = await self._mcp_manager.get_clients()
                logger.warning(f"[MCP_DEBUG] Got {len(mcp_clients)} clients from mcp_manager")
            else:
                logger.warning(f"[MCP_DEBUG] _mcp_manager is None!")

            # Load agent-specific configuration
            agent_config = load_agent_config(self.agent_id)

            # Override agent language with user's language preference
            # This ensures LLM outputs in the user's preferred language
            try:
                from ..routers.user.user_preferences import _load_preferences
                prefs = _load_preferences(user_id)
                user_lang = prefs.language or "zh"
                if hasattr(agent_config, "language"):
                    agent_config.language = user_lang
                logger.debug(
                    f"Runner: using user language '{user_lang}' for "
                    f"user_id={user_id}"
                )
            except Exception as e:
                logger.debug(
                    f"Runner: failed to get user language, "
                    f"using agent default: {e}"
                )

            logger.debug(f"Enabled MCP: {mcp_clients}")

            # Build base request context
            base_request_context = {
                "session_id": session_id,
                "user_id": user_id,
                "channel": channel,
                "agent_id": self.agent_id,
            }

            # ── 从 auth middleware 注入 role（用于记忆配额等多用户场景）──
            _role = getattr(getattr(request, "state", None), "role", None)

            # ── Fallback: 非HTTP渠道(WeCom等)通过 workspace owner 获取角色 ──
            # 链路: request.state.role → workspace.resolved_role → workspace.owner 的 user role → 默认 'user'
            if not _role and getattr(self, "_workspace", None):
                _ws = self._workspace
                _role = getattr(_ws, "resolved_role", None) or "user"
                logger.info(
                    "Runner: resolved role from workspace '%s': %s",
                    getattr(_ws, "agent_id", "?"),
                    _role,
                )

            if _role:
                base_request_context["role"] = _role
                # 同步写入 context 供下游 tool_guard / workspace_guard 使用
                try:
                    from ...config.session_context import set_current_user_role
                    set_current_user_role(_role)
                except Exception:
                    pass
                try:
                    from ...config.context import set_current_user_role as _set_ctx_role
                    _set_ctx_role(_role)
                except Exception:
                    pass

            # Extract root_session_id from request payload (agent chat)
            payload_root_session = getattr(request, "root_session_id", "")
            if payload_root_session and isinstance(payload_root_session, str):
                base_request_context["root_session_id"] = payload_root_session
                set_current_root_session_id(payload_root_session)
                root_preview = (
                    payload_root_session[:12]
                    if len(payload_root_session) >= 12
                    else payload_root_session
                )
                logger.debug(
                    "Runner: using root_session_id from payload: %s",
                    root_preview,
                )
            else:
                # Current session is the root
                base_request_context["root_session_id"] = session_id
                set_current_root_session_id(session_id)
                session_preview = (
                    session_id[:12] if len(session_id) >= 12 else session_id
                )
                logger.debug(
                    "Runner: current session is root: %s",
                    session_preview,
                )

            # Mission Mode: /mission
            _ws = self.workspace_dir or WORKING_DIR
            mission_info: dict | None = None

            mission_result = await maybe_handle_mission_command(
                query=query,
                msgs=msgs,
                workspace_dir=_ws,
                agent_id=self.agent_id,
                rewrite_fn=self._rewrite_last_message_text,
                session_id=session_id,
            )
            if isinstance(mission_result, Msg):
                yield mission_result, True
                return
            if isinstance(mission_result, dict):
                mission_info = mission_result

            # Active mission: auto-detect follow-up messages
            # (e.g., user confirms PRD without typing /mission again)
            if mission_info is None:
                mission_info = detect_active_mission_phase(
                    _ws,
                    session_id=session_id,
                )

            # Mission Mode: inject context reminder for active mission
            if mission_info is not None:
                # Inject context reminder for active mission
                loop_dir = mission_info.get("loop_dir", "")
                phase = mission_info.get("mission_phase", 1)
                if phase == 1:
                    refresher = (
                        f"[Mission active — dir: `{loop_dir}`]\n"
                        f"You are in Mission Phase 1 (PRD review). "
                        f"The user's message follows.\n"
                        f"If the user is confirming the PRD, update "
                        f"`{loop_dir}/loop_config.json` setting "
                        f"`current_phase` to `execution_confirmed`.\n"
                        f"If the user requests changes, modify "
                        f"prd.json.\n---\n"
                    )
                elif phase == 2:
                    refresher = (
                        f"[Mission active — dir: `{loop_dir}`]\n"
                        f"You are in Mission Phase 2 (execution). "
                        f"The user's follow-up message follows.\n"
                        f"Continue the worker → verifier pipeline. "
                        f"Check prd.json progress and dispatch workers "
                        f"for remaining stories.\n---\n"
                    )
                else:
                    refresher = f"[Mission active — dir: `{loop_dir}`]\n---\n"
                original = query or ""
                self._rewrite_last_message_text(
                    msgs,
                    refresher + original,
                )

            # --- Plan Mode ------------------------------------------
            plan_notebook = None
            plan_enabled = getattr(
                getattr(agent_config, "plan", None),
                "enabled",
                False,
            )
            if plan_enabled:
                try:
                    from agentscope.plan import (
                        PlanNotebook,
                        InMemoryPlanStorage,
                    )
                    from ...plan.hints import SimplePlanToHint, set_plan_gate

                    hint_gen = SimplePlanToHint()
                    plan_notebook = PlanNotebook(
                        plan_to_hint=hint_gen,
                        storage=InMemoryPlanStorage(),
                    )
                    hint_gen.bind_notebook(plan_notebook)

                    # Detect /plan <description> and set gate
                    if query and query.strip().lower().startswith("/plan "):
                        plan_desc = query.strip()[6:].strip()
                        if plan_desc:
                            set_plan_gate(plan_notebook, enabled=True)
                            self._rewrite_last_message_text(
                                msgs,
                                plan_desc,
                            )
                            logger.info(
                                "Plan mode: /plan gate set, desc=%s",
                                plan_desc[:60],
                            )

                    # Register SSE broadcast hook + state tracking
                    from ...plan.broadcast import broadcast_plan_update
                    from ...plan.schemas import plan_to_response

                    def _on_plan_change(  # pylint: disable=protected-access
                        nb,
                        plan,
                    ):
                        had_plan = getattr(nb, "_qp_had_plan", False)
                        prev_id = getattr(nb, "_qp_prev_plan_id", None)

                        if plan is not None:
                            cur_id = plan.id
                            if not had_plan or cur_id != prev_id:
                                nb._plan_just_mutated = True
                            nb._qp_prev_plan_id = cur_id
                        else:
                            if had_plan:
                                nb._plan_recently_finished = True
                            nb._qp_prev_plan_id = None
                        nb._qp_had_plan = plan is not None

                        payload = {
                            "type": "plan_update",
                            "plan": (
                                plan_to_response(plan).model_dump()
                                if plan is not None
                                else None
                            ),
                        }
                        broadcast_plan_update(
                            self.agent_id,
                            payload,
                            session_id=session_id,
                        )

                    plan_notebook.register_plan_change_hook(
                        "broadcast",
                        _on_plan_change,
                    )
                except Exception:
                    logger.warning(
                        "Failed to create PlanNotebook",
                        exc_info=True,
                    )
                    plan_notebook = None

            agent = CoApisAgent(
                agent_config=agent_config,
                env_context=env_context,
                mcp_clients=mcp_clients,
                memory_manager=self.memory_manager,
                context_manager=self.context_manager,
                request_context=base_request_context,
                workspace_dir=self.workspace_dir,
                task_tracker=self._task_tracker,
                plan_notebook=plan_notebook,
            )
            await agent.register_mcp_clients()
            mcp_tool_count = len([t for t in (agent.toolkit.tools or {}) if t.startswith("mcp_")]) if hasattr(agent, "toolkit") and agent.toolkit else 0
            logger.warning(
                f"[MCP_DEBUG] register_mcp_clients done: mcp_clients={len(mcp_clients)}, toolkit_mcp_tools={mcp_tool_count}, total_tools={len(agent.toolkit.tools) if hasattr(agent, 'toolkit') and agent.toolkit else 0}"
            )
            agent.set_console_output_enabled(enabled=False)

            logger.debug(
                f"Agent Query msgs {msgs}",
            )

            name = "New Chat"
            if len(msgs) > 0:
                content = msgs[0].get_text_content()
                if content:
                    name = msgs[0].get_text_content()[:10]
                else:
                    name = "Media Message"

            logger.debug(
                f"DEBUG chat_manager status: "
                f"_chat_manager={self._chat_manager}, "
                f"is_none={self._chat_manager is None}, "
                f"agent_id={self.agent_id}",
            )

            # Use the workspace's own ChatManager (physical isolation).
            # Each agent's ChatManager reads from its own workspace directory.
            effective_cm = self._chat_manager
            if effective_cm is not None:
                # Prefer chat_id from request (passed via channel_meta)
                # to match the exact chat. Contextvars don't propagate
                # to background tasks, so request.chat_id is more reliable.
                from ...config.session_context import get_current_chat_id
                ctx_chat_id = getattr(request, 'chat_id', None) or get_current_chat_id()
                if ctx_chat_id:
                    chat = await effective_cm.get_chat(ctx_chat_id)
                if chat is None:
                    chat = await effective_cm.get_or_create_chat(
                        session_id,
                        user_id,
                        channel,
                        name=name,
                        agent_id=self.agent_id,
                    )
                logger.debug(f"Runner: Got chat: {chat.id}")
            else:
                logger.warning(
                    f"ChatManager is None! Cannot auto-register chat for "
                    f"session_id={session_id}",
                )

            # Skill info (/<name> without input) is display-only
            if mission_info is None:
                skill_response = self._maybe_inject_skill(
                    query,
                    msgs,
                    agent.toolkit.skills,
                )
                if skill_response is not None:
                    yield skill_response, True
                    return

            # Ensure session file has a valid plan_notebook dict
            # to prevent TypeError/KeyError during load_state_dict
            # Use chat.id (UUID) as session key for per-chat isolation
            if chat is not None and plan_notebook is not None:
                try:
                    _states = await self.session.get_session_state_dict(
                        session_id=chat.id,
                        user_id=user_id,
                        allow_not_exist=True,
                    )
                    _agent_st = _states.get("agent", {})
                    _nb_val = _agent_st.get("plan_notebook")
                    if _agent_st and (
                        "plan_notebook" not in _agent_st
                        or not isinstance(_nb_val, dict)
                    ):
                        await self.session.update_session_state(
                            session_id=chat.id,
                            key="agent.plan_notebook",
                            value=plan_notebook.state_dict(),
                            user_id=user_id,
                            create_if_not_exist=False,
                        )
                except Exception:
                    logger.debug(
                        "Pre-populate plan_notebook skipped",
                        exc_info=True,
                    )

            if chat is not None:
                try:
                    await self.session.load_session_state(
                        session_id=chat.id,
                        user_id=user_id,
                        agent=agent,
                    )
                except KeyError as e:
                    logger.warning(
                        "load_session_state skipped (state schema mismatch): %s; "
                        "will save fresh state on completion to recover file",
                        e,
                    )
            session_state_loaded = True

            # Rebuild system prompt so it always reflects the latest
            # AGENTS.md / SOUL.md / PROFILE.md, not the stale one saved
            # in the session state.
            agent.rebuild_sys_prompt()

            # Snapshot memory length BEFORE processing so we can extract
            # only the NEW messages afterwards (includes tool_call, tool_output,
            # reasoning, assistant — not just user + assistant text).
            _memory_snapshot_len = len(agent.memory.content) if agent.memory else 0

            # --- Execution: Mission Mode (phased) or standard -----
            # Collect full assistant response for evolution engine & chat persistence

            if mission_info is not None:
                from ...agents.mission.mission_runner import (
                    run_mission_phase1,
                    run_mission_phase2,
                )

                phase = mission_info["mission_phase"]
                loop_dir = Path(mission_info["loop_dir"])
                max_iters = mission_info.get(
                    "max_iterations",
                    20,
                )

                if phase == 1:
                    async for msg, last in run_mission_phase1(
                        agent=agent,
                        msgs=msgs,
                        loop_dir=loop_dir,
                        max_iterations=max_iters,
                        agent_id=self.agent_id,
                    ):
                        _evolution_collect_text(msg, _evolution_full_response)
                        yield msg, last
                else:
                    async for msg, last in run_mission_phase2(
                        agent=agent,
                        msgs=msgs,
                        loop_dir=loop_dir,
                        max_iterations=max_iters,
                        agent_id=self.agent_id,
                    ):
                        _evolution_collect_text(msg, _evolution_full_response)
                        yield msg, last
            else:
                async for msg, last in _stream_printing_messages_interruptible(
                    agents=[agent],
                    coroutine_task=agent(msgs),
                ):
                    _evolution_collect_text(msg, _evolution_full_response)
                    yield msg, last

            # --- Bootstrap: Append guidance after streaming ends ---
            # If bootstrap is pending, read current attempt count from state
            # file, append the corresponding prompt, and increment counter.
            from ...agents.utils import has_pending_bootstrap
            from ...agents.hooks.bootstrap import get_bootstrap_prompt
            if self.workspace_dir and has_pending_bootstrap(self.workspace_dir):
                state_file = self.workspace_dir / ".bootstrap_state"
                state = {"attempts": 0}
                if state_file.exists():
                    try:
                        state = json.loads(state_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                prompts_sent = state.get("attempts", 0)
                max_att = state.get("max_attempts", 3)
                if prompts_sent < max_att:
                    next_attempt = prompts_sent + 1
                    bootstrap_text = get_bootstrap_prompt(
                        attempt=next_attempt,
                        language="zh",
                    )
                    _evolution_full_response.append(bootstrap_text)
                    # Increment counter for next time
                    state["attempts"] = next_attempt
                    state_file.write_text(
                        json.dumps(state, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    logger.info(
                        "Bootstrap prompt %d appended", next_attempt,
                    )
            # -------------------------------------------------------

            # --- Evolution Engine Hooks (Phase 2: Turn End) ---
            if engine:
                _evolution_trigger_turn_end(
                    engine,
                    assistant_message="".join(_evolution_full_response),
                )
            # -------------------------------------------------------

        except asyncio.CancelledError as exc:
            logger.info(f"query_handler: {session_id} cancelled!")

            # Cancel all pending approvals for this root session
            root_session_id = base_request_context.get(
                "root_session_id",
                session_id,
            )
            from ..approvals.service import get_approval_service

            approval_svc = get_approval_service()
            cancelled_count = (
                await approval_svc.cancel_all_pending_by_root_session(
                    root_session_id,
                )
            )
            if cancelled_count > 0:
                logger.info(
                    "Auto-denied %d pending approval(s) for root session %s",
                    cancelled_count,
                    root_session_id[:8]
                    if len(root_session_id) >= 8
                    else root_session_id,
                )

            # ── Persist partial assistant response before cancelling ──
            # When the task is cancelled (e.g. /stop), the stream may have
            # produced partial output in _evolution_full_response.  We must
            # write that into agent.memory so that save_session_state in
            # the finally block captures the full conversation context.
            if agent is not None and agent.memory:
                # Ensure user message is in memory even on ultra-early cancel
                # (before agent yields anything). This guarantees the user's
                # input survives regardless of cancellation timing.
                _has_user_msg = any(
                    getattr(m, "role", "") == "user"
                    for m, _ in agent.memory.content
                )
                if not _has_user_msg and query and query.strip():
                    try:
                        await agent.memory.add(
                            Msg(
                                name="user",
                                content=[TextBlock(text=query)],
                                role="user",
                            ),
                        )
                        logger.info(
                            "CancelledError: added missing user message "
                            "to memory (%d chars)",
                            len(query),
                        )
                    except Exception as mem_exc:
                        logger.warning(
                            "Failed to add user message on cancel: %s",
                            mem_exc,
                        )

                if _evolution_full_response:
                    partial_text = "".join(_evolution_full_response).strip()
                    if partial_text:
                        try:
                            await agent.memory.add(
                                Msg(
                                    name="assistant",
                                    content=[TextBlock(text=partial_text)],
                                    role="assistant",
                                ),
                            )
                            logger.info(
                                "CancelledError: persisted %d chars of "
                                "partial assistant response to memory",
                                len(partial_text),
                            )
                        except Exception as mem_exc:
                            logger.warning(
                                "Failed to persist partial assistant "
                                "response on cancel: %s",
                                mem_exc,
                            )

            if agent is not None:
                await agent.interrupt()
            raise AgentException("Task has been cancelled!") from exc
        except AppBaseException:
            raise
        except Exception as e:
            model_name = None
            if agent and hasattr(agent, "model"):
                model_name = getattr(agent.model, "model_name", None)

            converted = convert_model_exception(e, model_name)

            # Preserve all original error dump logic
            debug_dump_path = write_query_error_dump(
                request=request,
                exc=converted,
                locals_=locals(),
            )
            path_hint = (
                f"\n(Details:  {debug_dump_path})" if debug_dump_path else ""
            )
            logger.exception(f"Error in query handler: {converted}{path_hint}")
            if debug_dump_path:
                setattr(converted, "debug_dump_path", debug_dump_path)
                if hasattr(converted, "add_note"):
                    converted.add_note(
                        f"(Details:  {debug_dump_path})",
                    )
                suffix = f"\n(Details:  {debug_dump_path})"
                if hasattr(converted, "message") and isinstance(
                    converted.message,
                    str,
                ):
                    converted.message += suffix
                elif converted.args:
                    converted.args = (
                        f"{converted.args[0]}{suffix}",
                    ) + converted.args[1:]
            raise converted from e
        finally:
            # --- Flush memory manager on interrupt/cancel ---
            # Ensure any pending summary tasks are properly handled
            # when the session is interrupted (e.g., /stop, timeout, disconnect).
            if self.memory_manager is not None:
                try:
                    await self.memory_manager.close()
                    logger.debug("memory_manager.close() called in finally block")
                except Exception:
                    logger.warning("Failed to close memory_manager", exc_info=True)

            # --- Persist messages to user's ChatManager ---
            # MUST run BEFORE save_session_state to avoid duplication:
            # _persist_chat_messages loads session state and appends new messages,
            # then save_session_state overwrites agent.memory with the agent's
            # internal state. If save_session_state ran first, _persist_chat_messages
            # would load the agent's internal memory (which already has user+assistant)
            # and append them again.
            if chat is not None:
                try:
                    # Extract ALL new messages from agent.memory (includes
                    # tool_call, tool_output, reasoning, assistant — not just
                    # user + assistant text).  This is the key difference from
                    # the old approach that only saved 3 messages.
                    _new_msgs = []
                    if agent is not None and agent.memory:
                        _all_content = agent.memory.content
                        _new_msgs = [
                            msg for msg, _marks in _all_content[_memory_snapshot_len:]
                        ]
                        logger.info(
                            "Extracted %d new messages from agent.memory "
                            "(snapshot_len=%d, total=%d)",
                            len(_new_msgs), _memory_snapshot_len, len(_all_content),
                        )

                    # Shield from CancelledError so partial results are
                    # persisted even when the user clicks "Stop".
                    # Without shield(), CancelledError re-fires at the
                    # await inside _persist_chat_messages, interrupting
                    # the save and losing all chat content.
                    await asyncio.shield(self._persist_chat_messages(
                        chat=chat,
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                        msgs=msgs,
                        assistant_text="".join(_evolution_full_response),
                        name=name,
                        full_reasoning=getattr(self._workspace, 'last_full_reasoning', None),
                        user_text_override=query,
                        agent_messages=_new_msgs,
                    ))
                except asyncio.CancelledError:
                    logger.warning(
                        "Chat persistence was cancelled (user stopped), "
                        "data may be incomplete",
                    )
                except Exception:
                    logger.warning(
                        "Failed to persist chat messages",
                        exc_info=True,
                    )

            # NOTE: save_session_state removed.
            # _persist_chat_messages already saves the complete session state
            # (user message + assistant response + reasoning). Running
            # save_session_state after it would overwrite with agent's
            # internal memory, losing the curated message list.
            # ------------------------------------------------

            # --- Evolution: session end → experience extraction ---
            try:
                if engine is not None:
                    experiences = await engine.on_session_end()
                    if experiences:
                        logger.info(
                            "EvolutionEngine: extracted %d experiences "
                            "from session %s",
                            len(experiences), session_id,
                        )
                        # Flow to CrossAgentEvolution (AB buckets)
                        ws = self._workspace
                        cross_evo = getattr(ws, "cross_agent_evolution", None)
                        if cross_evo is not None:
                            for exp in experiences:
                                try:
                                    await cross_evo.report_experience(
                                        content=exp.content,
                                        category=exp.category,
                                        source_user=exp.source_user,
                                        agent_level="user",
                                        confidence=exp.confidence,
                                    )
                                except Exception:
                                    logger.debug(
                                        "CrossAgentEvolution submit failed",
                                        exc_info=True,
                                    )
                        # Flow to KnowledgeFlow (professional layer)
                        kflow = getattr(ws, "knowledge_flow", None)
                        if kflow is not None:
                            for exp in experiences:
                                try:
                                    await kflow.evaluate_and_flow(
                                        exp, self.agent_id, user_id,
                                    )
                                except Exception:
                                    logger.debug(
                                        "KnowledgeFlow evaluate failed",
                                        exc_info=True,
                                    )
            except Exception:
                logger.warning(
                    "EvolutionEngine.on_session_end failed",
                    exc_info=True,
                )
            # -------------------------------------------------------

    async def init_handler(self, *args, **kwargs):
        """
        Init handler.
        """
        # Load environment variables from .env file
        # env_path = Path(__file__).resolve().parents[4] / ".env"
        env_path = Path("./") / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug(f"Loaded environment variables from {env_path}")
        else:
            logger.debug(
                f".env file not found at {env_path}, "
                "using existing environment variables",
            )

        # Session dir will be overridden by Workspace.runner property.
        # Default: workspace_dir/sessions/ (for standalone runner usage).
        session_dir = str(
            (self.workspace_dir if self.workspace_dir else WORKING_DIR)
            / "sessions",
        )
        self.session = SafeJSONSession(save_dir=session_dir)

    async def shutdown_handler(self, *args, **kwargs):
        """
        Shutdown handler.
        """
