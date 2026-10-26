# -*- coding: utf-8 -*-
# pylint: disable=too-many-nested-blocks,too-many-branches
# pylint: disable=too-many-return-statements,too-many-statements
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

"""Context manager for agents with compaction support."""
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Set

from agentscope.message import Msg, TextBlock

from .agent_context import AgentContext
from .base_context_manager import BaseContextManager, context_registry
from .fixed_overhead import enforce_fixed_overhead
from .window_source import compute_keep_recent, resolve_for_model
from ..model_factory import create_model_and_formatter
from ..tools.utils import truncate_text_output, DEFAULT_MAX_BYTES
from ..utils import get_token_counter
from ...config.config import load_agent_config
from ...constant import TRUNCATION_NOTICE_MARKER

if TYPE_CHECKING:
    from ..react_agent import CoApisAgent

logger = logging.getLogger(__name__)


def _fmt_tokens(n: int) -> str:
    """Format token count as e.g. '82.3k' or '450'."""
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _normalize_output(output: Any) -> list[Any]:
    """工具结果 output 归一为块列表。

    agentscope 里 ``output`` 可能是裸字符串、单块、或块列表；
    治理地板要三种形态都吃得下，不能因结构差异抛异常。
    """
    if isinstance(output, list):
        return output
    if isinstance(output, str):
        return [{"type": "text", "text": output}]
    if isinstance(output, dict):
        return [output]
    return []


def _governance_floor_truncate(
    messages: list[Msg],
    limit: Any,
) -> int:
    """治理层兜底截断（治理地基 片1 · 接入现成截断函数）。

    工具结果裁剪（``tool_result_pruning_config.enabled``）关闭时，此前**没有任何
    截断**——超大工具结果原样进上下文，直接顶爆窗口。治理层给一条地板：
    即便裁剪关闭，超过预算的工具结果也按阶梯 L1（头尾保留）截断，并留下可见说明。

    刻意做成薄接线：只处理纯文本块，不复制裁剪器的落盘/元数据逻辑（那是
    ``_truncate_tool_result`` 的职责，裁剪开启时由它接管）。

    Args:
        messages: 本轮记忆中的消息（就地修改其中的工具结果块）。
        limit: 治理层台账里的工具结果限制。

    Returns:
        被截断的块数。治理层不可用时返回 0，绝不因治理层缺失而中断对话。
    """
    from ...governance import choose_tier, truncate_head_tail

    changed = 0
    for msg in messages:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            raw_output = block.get("output")
            items = _normalize_output(raw_output)
            for item in items:
                if not isinstance(item, dict) or item.get("type") != "text":
                    continue
                text = item.get("text") or ""
                plan = choose_tier(len(text), limit)
                if plan.is_full:
                    continue
                # 地板只做到 L1：更深的降级（分段/摘要/分治）需要工具语义，
                # 属于片4/片5 的职责，不在兜底路径里越权。
                kept = truncate_head_tail(text, limit.budget)
                if len(kept) >= len(text):
                    continue
                item["text"] = (
                    kept
                    + f"\n\n[治理层 {plan.tier.value}] {plan.note}"
                    + f"（原文 {len(text)} 字符，保留 {len(kept)}）"
                )
                changed += 1
            if isinstance(raw_output, str) and items:
                # 裸字符串形态：归一化出的块是临时对象，必须写回原字段
                block["output"] = items[0].get("text", raw_output)
    if changed:
        logger.info(
            "governance floor truncation applied: %d block(s), budget=%d, source=%s",
            changed,
            limit.budget,
            limit.source,
        )
    return changed


@context_registry.register("light")
def _walk_compression_tail(
    messages: list[Any],
    keep_recent: int | None,
) -> tuple[int, int]:
    """Replica of upstream's keep-tail loop, verbatim.

    ``ReActAgent._compress_memory_if_needed`` walks the messages from the
    newest backwards, accumulating ``tool_result`` ids and retiring a
    ``tool_use`` id once its result has been seen; a message closes a group
    when no tool call is left unmatched.  It breaks the moment the group
    count reaches ``keep_recent`` and compresses ``messages[:i]`` — so when
    that break lands on index 0 the list it would compress is **empty** and
    compression is skipped, no matter how many characters the prompt
    measures.  Walking past the whole list without breaking compresses
    everything.

    Returns ``(prefix_upstream_would_compress, groups_closed_so_far)``.
    With ``keep_recent=None`` the walk never breaks, so the second number is
    the total group count of the list.
    """
    msgs = list(messages or [])
    n_keep = 0
    pending: set[str] = set()
    for i in range(len(msgs) - 1, -1, -1):
        msg = msgs[i]
        getter = getattr(msg, "get_content_blocks", None)
        if getter is not None:
            try:
                for block in getter("tool_result"):
                    block_id = block.get("id")
                    if block_id:
                        pending.add(block_id)
                for block in getter("tool_use"):
                    block_id = block.get("id")
                    if block_id in pending:
                        pending.discard(block_id)
            except Exception:  # malformed row: it still occupies a group
                logger.debug("Group counting skipped a malformed message")
        if not pending:
            n_keep += 1
        if keep_recent is not None and n_keep >= keep_recent:
            return i, n_keep
    return len(msgs), n_keep


def count_message_groups(messages: list[Any]) -> int:
    """How many *groups* upstream's compactor sees in this message list."""
    return _walk_compression_tail(messages, None)[1]


def compressible_prefix_count(messages: list[Any], keep_recent: int) -> int:
    """How many messages upstream would compress at this ``keep_recent``.

    ``0`` is the cliff: the session is over the trigger, there is plenty to
    summarize, and upstream compresses nothing.
    """
    return _walk_compression_tail(messages, keep_recent)[0]


#: Logged once per process: the reme summarizer is configured, the agent has a
#: memory manager, and that manager has no summarize entry point.
_SUMMARIZE_GAP_LOGGED = False


def hand_to_long_term_memory(
    memory_manager: Any,
    messages: list[Any],
    reason: str,
) -> bool:
    """Feed compacted/exchanged messages to the long-term memory pipeline.

    The summarize entry point belongs to ``BaseMemoryManager`` (the reme
    family).  The community agent runs with the file-based ``MemoryManager``,
    which has no such method, so the call used to raise ``AttributeError`` on
    **every** compaction — a WARNING per event, and the durable-memory
    linkage silently doing nothing (dev, 2026-10-17:
    ``'MemoryManager' object has no attribute 'add_summarize_task'``).

    Returns whether the messages were accepted.  A missing entry point is a
    configuration fact, not an exception, so it is reported once.
    """
    global _SUMMARIZE_GAP_LOGGED

    add_task = getattr(memory_manager, "add_summarize_task", None)
    if not callable(add_task):
        if not _SUMMARIZE_GAP_LOGGED:
            _SUMMARIZE_GAP_LOGGED = True
            logger.info(
                "Long-term memory linkage skipped: %s has no summarize entry "
                "point (reme_light_memory_config.summarize_when_compact is on "
                "but the agent runs the file-based MemoryManager).  Further "
                "%s events will not be logged.",
                type(memory_manager).__name__,
                reason,
            )
        return False

    try:
        add_task(messages=messages)
    except Exception as exc:  # never fail a reply for a memory side task
        logger.warning("Long-term memory linkage failed: %s", exc)
        return False
    return True


class LightContextManager(BaseContextManager):
    """Context manager for the community edition.

    Compaction itself lives upstream (agentscope's
    ``ReActAgent._compress_memory_if_needed``); this manager owns the
    hygiene around it.

    Responsibilities:
    - Tool-result pruning via _prune_tool_result()
    - Sizing the tail upstream keeps (pre_reasoning → keep_recent)
    - Archiving + purging what upstream compressed (post_reasoning)
    - Manual ``/compact`` on the same upstream contract (compact_context)
    - Agent context retrieval via get_agent_context()
    """

    def __init__(self, working_dir: str, agent_id: str):
        """Initialize context manager.

        Args:
            working_dir: Working directory for context storage.
            agent_id: Agent ID for config loading.
        """
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        logger.info(
            f"LightContextManager init: "
            f"agent_id={agent_id}, working_dir={working_dir}",
        )

    # ------------------------------------------------------------------
    # BaseContextManager interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the context manager lifecycle."""

    async def close(self) -> bool:
        """Close context manager and cleanup expired tool result files."""
        logger.info(f"LightContextManager closing: agent_id={self.agent_id}")
        self._cleanup_expired_tool_result_files()
        logger.info(f"LightContextManager closed: agent_id={self.agent_id}")
        return True

    def _cleanup_expired_tool_result_files(self) -> int:
        """Clean up tool result files older than retention_days.

        Returns:
            Number of files successfully deleted.
        """
        agent_config = load_agent_config(self.agent_id)
        lcc = agent_config.running.light_context_config
        trc = lcc.tool_result_pruning_config
        tool_result_dir = Path(self.working_dir) / trc.tool_results_cache
        retention_days = trc.offload_retention_days

        if not tool_result_dir.exists():
            return 0

        cutoff = datetime.now() - timedelta(days=retention_days)
        deleted = failed = 0

        for fp in tool_result_dir.glob("*.txt"):
            try:
                stat = os.stat(fp)
                if sys.platform == "win32":
                    ts = stat.st_ctime  # creation time on Windows
                else:
                    ts = getattr(
                        stat,
                        "st_birthtime",
                        stat.st_mtime,
                    )  # macOS/BSD; Linux fallback to mtime
                if datetime.fromtimestamp(ts) < cutoff:
                    fp.unlink()
                    deleted += 1
            except FileNotFoundError:
                pass  # deleted by another process between glob and stat/unlink
            except Exception as e:
                failed += 1
                logger.warning("Failed to delete %s: %s", fp, e)

        if deleted or failed:
            logger.info(
                "Cleaned up %d expired tool result files (%d failed)",
                deleted,
                failed,
            )
        return deleted

    def _truncate_tool_result(
        self,
        content: str,
        max_bytes: int,
        encoding: str = "utf-8",
    ) -> str:
        """Truncate tool result content, saving full content to file if needed.

        Args:
            content: The content to truncate.
            max_bytes: Maximum bytes allowed.
            encoding: Character encoding.

        Returns:
            Truncated content with notice if truncated,
            or original if under limit.
        """
        if not content:
            return content

        # Already truncated content - retruncate with new limit
        if TRUNCATION_NOTICE_MARKER in content:
            return truncate_text_output(
                content,
                max_bytes=max_bytes,
                encoding=encoding,
            )

        # Check if content fits within limit (with small slack)
        try:
            content_bytes = len(content.encode(encoding))
        except UnicodeEncodeError as e:
            logger.warning("Failed to encode content: %s", e)
            return content

        if content_bytes <= max_bytes + 100:
            return content

        # Save full content to file
        agent_config = load_agent_config(self.agent_id)
        lcc = agent_config.running.light_context_config
        trc = lcc.tool_result_pruning_config
        tool_result_dir = Path(self.working_dir) / trc.tool_results_cache

        try:
            tool_result_dir.mkdir(parents=True, exist_ok=True)
            fp = tool_result_dir / f"{uuid.uuid4().hex}.txt"
            fp.write_text(content, encoding=encoding)
            saved_path = str(fp)
        except OSError as e:
            logger.exception(f"Failed to save tool result to file: {e}")
            # Fallback: truncate without saving
            return truncate_text_output(
                content,
                max_bytes=max_bytes,
                encoding=encoding,
            )

        # Truncate and include file path in notice
        return truncate_text_output(
            content,
            start_line=1,
            total_lines=content.count("\n") + 1,
            max_bytes=max_bytes,
            file_path=saved_path,
            encoding=encoding,
        )

    def _prune_output(
        self,
        output: str | list[dict],
        max_bytes: int,
        encoding: str = "utf-8",
    ) -> str | list[dict]:
        """Prune output by truncating to max_bytes.

        Args:
            output: The output to prune (str or list[dict]).
            max_bytes: Maximum bytes allowed.
            encoding: Character encoding.

        Returns:
            Pruned output.
        """
        if isinstance(output, str):
            return self._truncate_tool_result(output, max_bytes, encoding)
        if isinstance(output, list):
            for block in output:
                if isinstance(block, dict) and block.get("type") == "text":
                    block["text"] = self._truncate_tool_result(
                        block.get("text", ""),
                        max_bytes,
                        encoding,
                    )
        return output

    async def _governance_floor_pass(
        self,
        agent: "CoApisAgent",
        messages: list[Msg],
    ) -> int:
        """治理层地板：读取台账预算，对超限文本块做 L1 截断。

        治理层不可用时返回 0 并放行——治理层缺失绝不能中断对话。
        """
        try:
            from ...governance import LimitKind, ledger_for_agent

            cfg = load_agent_config(agent.agent_id)
            ledger = ledger_for_agent(
                running_config=cfg.running,
                context_config=getattr(cfg.running, "context_compact", None),
                pruning_config=getattr(cfg.running, "tool_result_pruning_config", None),
            )
            limit = ledger.limit(LimitKind.TOOL_RESULT_BYTES)
        except Exception:  # 治理层缺失/配置缺失 → 放行
            return 0
        changed = _governance_floor_truncate(messages, limit)
        if changed:
            ledger.record(LimitKind.TOOL_RESULT_BYTES, changed)
        return changed

    async def _prune_tool_result(
        self,
        messages: list[Msg],
        recent_n: int = 1,
        old_max_bytes: int = 3000,
        recent_max_bytes: int = DEFAULT_MAX_BYTES,
        **_kwargs,
    ) -> list[Msg]:
        """Process all messages, truncating large tool results.

        Args:
            messages: List of messages to process.
            recent_n: Number of recent messages to treat with recent_max_bytes.
            old_max_bytes: Maximum bytes for older tool results.
            recent_max_bytes: Maximum bytes for recent tool results.
            retention_days: Days to retain offloaded files
                (unused here, set in init).

        Returns:
            Processed messages list.
        """
        if not messages:
            return messages

        # Count recent tool_result messages from the end
        recent_count = 0
        for msg in reversed(messages):
            if not isinstance(msg.content, list) or not any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in msg.content
            ):
                break
            recent_count += 1
        split_index = max(0, len(messages) - max(recent_count, recent_n))

        # Detect tool_use IDs for exempt file extensions and tool names
        exempt_tool_ids: Set[str] = set()
        try:
            # Load exempt lists from config
            agent_config = load_agent_config(self.agent_id)
            lcc = agent_config.running.light_context_config
            trc = lcc.tool_result_pruning_config
            exempt_extensions = set(
                ext.lower() for ext in trc.exempt_file_extensions
            )
            exempt_tools = set(name.lower() for name in trc.exempt_tool_names)

            for msg in messages:
                if not isinstance(msg.content, list):
                    continue

                for block in msg.content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_use"
                    ):
                        tool_id = block.get("id", "")
                        if not tool_id:
                            continue

                        tool_name = block.get("name", "").lower()
                        raw_input = (block.get("raw_input") or "").lower()

                        # Check if tool name is in exempt list
                        if tool_name in exempt_tools:
                            exempt_tool_ids.add(tool_id)
                            continue

                        # Check if file extension is in exempt list
                        # for read_file
                        if tool_name == "read_file":
                            for ext in exempt_extensions:
                                if ext in raw_input:
                                    exempt_tool_ids.add(tool_id)
                                    break
        except Exception as e:
            logger.warning("Failed to detect exempt tool ids: %s", e)

        # Prune tool_result blocks
        for idx, msg in enumerate(messages):
            if not isinstance(msg.content, list):
                continue
            is_recent = idx >= split_index
            max_bytes = recent_max_bytes if is_recent else old_max_bytes

            for block in msg.content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                ):
                    tool_id = block.get("id", "")
                    output = block.get("output")
                    if not output:
                        continue

                    # Use recent_max_bytes for exempt tool results
                    effective_max_bytes = (
                        recent_max_bytes
                        if tool_id in exempt_tool_ids
                        else max_bytes
                    )
                    block["output"] = self._prune_output(
                        output,
                        effective_max_bytes,
                    )

        return messages

    # ------------------------------------------------------------------
    # Manual compaction (/compact): the same engine as the automatic path
    # ------------------------------------------------------------------

    async def compact_context(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        extra_instruction: str = "",
    ) -> dict:
        """Compact messages with the upstream compression contract.

        Coapis has exactly one compaction engine: agentscope's
        ``ReActAgent._compress_memory_if_needed``.  A manual ``/compact``
        cannot call it, because the command path builds a ``CommandHandler``
        without an agent instance — so instead of shipping a second
        summarizer, this reuses the *same* config object: the same
        ``compression_prompt``, the same ``summary_template``, the same
        ``summary_schema``, the same token accounting.  A manual summary and
        an automatic one are therefore interchangeable, and compacting a
        session either way produces the same kind of memory.

        The previous implementation built its own prompt, its own 6-section
        template, its own validity checks and a throwaway ``ReActAgent`` to
        run it through — a second compactor with a second definition of a
        good summary, ~265 lines of it.  Removed.

        Args:
            messages: Messages to compact.
            previous_summary: Earlier summary to fold into the new one.
            extra_instruction: Optional user instruction for the summary.

        Returns:
            Dict with keys: success, reason, history_compact,
            before_tokens, after_tokens.
        """
        empty: dict = {
            "success": False,
            "reason": "",
            "history_compact": "",
            "before_tokens": 0,
            "after_tokens": 0,
        }
        if not messages:
            empty["reason"] = "empty messages"
            return empty

        try:
            from agentscope.agent import ReActAgent
            from agentscope.token import CharTokenCounter
        except ImportError as e:
            empty["reason"] = f"agentscope compression unavailable: {e}"
            return empty

        # trigger_threshold=1 / keep_recent=1: a manual request compacts
        # everything it was handed, whatever the automatic budget says.
        compression_config = ReActAgent.CompressionConfig(
            enable=True,
            agent_token_counter=CharTokenCounter(),
            trigger_threshold=1,
            keep_recent=1,
        )

        compression_prompt = compression_config.compression_prompt
        if extra_instruction:
            compression_prompt = f"{compression_prompt}\n\n{extra_instruction}"

        history = list(messages)
        if previous_summary:
            history.insert(0, Msg("user", previous_summary, "user"))

        model, formatter = create_model_and_formatter(self.agent_id)

        prompt = await formatter.format(
            [
                Msg(
                    "system",
                    "You compress conversation history. Produce only the "
                    "structured summary the user message asks for; never "
                    "continue the dialogue.",
                    "system",
                ),
                *history,
                Msg("user", compression_prompt, "user"),
            ],
        )

        token_counter = compression_config.agent_token_counter
        before_tokens = await token_counter.count(prompt)

        try:
            res = await model(
                prompt,
                structured_model=compression_config.summary_schema,
            )
            last_chunk = res
            if getattr(model, "stream", False):
                last_chunk = None
                async for chunk in res:
                    last_chunk = chunk
        except Exception as e:
            logger.exception("Manual compaction model call failed: %s", e)
            empty["reason"] = f"model call failed: {e}"
            empty["before_tokens"] = before_tokens
            return empty

        if last_chunk is None or not getattr(last_chunk, "metadata", None):
            logger.error("Manual compaction produced no structured summary.")
            empty["reason"] = "no structured summary generated"
            empty["before_tokens"] = before_tokens
            return empty

        try:
            history_compact = compression_config.summary_template.format(
                **last_chunk.metadata,
            )
        except (KeyError, ValueError) as e:
            logger.exception("Summary template formatting failed: %s", e)
            empty["reason"] = f"summary template failed: {e}"
            empty["before_tokens"] = before_tokens
            return empty

        after_tokens = await token_counter.count(
            await formatter.format([Msg("user", history_compact, "user")]),
        )

        logger.info(
            "Manual compaction: %d message(s), %d -> %d counter tokens "
            "(model %s).",
            len(messages),
            before_tokens,
            after_tokens,
            getattr(model, "model_name", "?"),
        )
        return {
            "success": True,
            "reason": "",
            "history_compact": history_compact,
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
        }

    # ------------------------------------------------------------------
    # Agent lifecycle hook methods
    # ------------------------------------------------------------------

    @staticmethod
    async def _print_status_message(agent: "CoApisAgent", text: str) -> None:
        msg = Msg(
            name=agent.name,
            role="assistant",
            content=[TextBlock(type="text", text=text)],
        )
        await agent.print(msg)

    async def pre_reply(
        self,
        agent: "CoApisAgent",
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Augment ``msg`` with retrieved memory results before reply.

        When ``auto_memory_search_config.enabled`` is enabled, calls
        ``memory_manager.retrieve()`` which returns a dict with updated
        messages. Commands are skipped because ``reply()`` returns early
        before the ReAct loop runs.
        """
        msg = kwargs.get("msg")
        if msg is None:
            return None

        last_msg = msg[-1] if isinstance(msg, list) else msg
        query = (
            last_msg.get_text_content() if isinstance(last_msg, Msg) else None
        )

        # Commands are handled before the ReAct loop — skip memory search.
        command_handler = agent.command_handler
        if command_handler is not None and command_handler.is_command(query):
            return None

        agent_config = load_agent_config(self.agent_id)
        rlmc = agent_config.running.reme_light_memory_config
        ms = rlmc.auto_memory_search_config

        if not ms.enabled:
            return None

        memory_manager = agent.memory_manager
        if memory_manager is None:
            return None

        try:
            result = await memory_manager.retrieve(msg, agent_name=agent.name)
        except BaseException as e:
            logger.warning(
                "memory_manager.retrieve failed, skipping e=%s",
                e,
            )
            return None

        if result is None:
            return None

        return {**kwargs, **result}

    async def pre_reasoning(
        self,
        agent: "CoApisAgent",
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Size the tail that upstream keeps, before upstream decides.

        Compaction itself is agentscope's job:
        ``ReActAgent._compress_memory_if_needed`` runs at the top of every
        reasoning iteration, measures the *formatted* prompt with
        ``CharTokenCounter`` and summarizes everything older than
        ``keep_recent`` message groups.  This hook does not summarize
        anything any more — the old in-hook compactor (token estimate,
        threshold check, "🔄 context compaction started", the LLM call, the
        ✅/❌ report) is gone, because a second compactor inside a hook is
        how the two compressors used to fight each other.

        What remains is cheap and mechanical: re-derive ``keep_recent`` from
        the live token budget, so the tail upstream keeps is sized by tokens
        rather than by a constant baked into the config.
        """
        compression_config = getattr(agent, "compression_config", None)
        memory = getattr(agent, "memory", None)
        if (
            compression_config is None
            or not compression_config.enable
            or memory is None
        ):
            return None

        agent_config = load_agent_config(self.agent_id)
        running = agent_config.running
        ccc = running.light_context_config.context_compact_config

        # Half of the compression budget stays raw: the newest exchanges are
        # the ones whose exact wording matters (tool output, file paths,
        # numbers the next step will reuse).  The window itself comes from
        # the model's own report (window_source), not from max_input_length.
        window = resolve_for_model(
            agent.model,
            running,
            chars_per_token=ccc.formatted_chars_per_token,
        )

        # Fixed-overhead guard (B0/D8): the ratio is a constraint with an
        # action, not a reading.  Runs at step 1 only — shedding mid-task
        # would take tools away from a run in progress, and a group the
        # model still needs is one reset_equipped_tools call away from
        # coming back.
        try:
            max_fixed_ratio = float(
                getattr(ccc, "fixed_overhead_max_ratio", 0.0) or 0.0,
            )
            if max_fixed_ratio > 0 and getattr(agent, "cur_iter", 0) == 0:
                enforce_fixed_overhead(
                    agent,
                    window.to_chars(window.effective_tokens),
                    max_ratio=max_fixed_ratio,
                    min_history_share=float(
                        getattr(ccc, "min_history_share", 0.30) or 0.30,
                    ),
                )
        except Exception:
            # The guard is an optimisation, never a reason to lose the turn:
            # a config-shape or measurement failure must not propagate into
            # pre_reasoning, where an exception kills the reply.
            logger.warning(
                "fixed-overhead guard failed; continuing without it",
                exc_info=True,
            )

        budget_tokens = int(
            window.effective_tokens * ccc.compact_threshold_ratio * 0.5,
        )
        keep_recent = await self._compute_keep_recent(
            memory,
            budget_tokens=budget_tokens,
            chars_per_token=window.chars_per_token,
            keep_recent_min=ccc.keep_recent_min,
            keep_recent_max=ccc.keep_recent_max,
        )
        keep_recent = await self._compressibility_floor(
            agent,
            memory,
            keep_recent,
            ccc,
        )
        if keep_recent != compression_config.keep_recent:
            logger.debug(
                "keep_recent adjusted %d -> %d for the current token budget.",
                compression_config.keep_recent,
                keep_recent,
            )
            compression_config.keep_recent = keep_recent
        return None

    @staticmethod
    async def _compressibility_floor(
        agent: "CoApisAgent",
        memory: Any,
        keep_recent: int,
        ccc: Any,
    ) -> int:
        """Make sure there is something upstream is allowed to compress.

        Upstream's keep-tail loop breaks the moment the group count reaches
        ``keep_recent`` and compresses the prefix before that point.  When
        the session holds **exactly** ``keep_recent`` groups the break lands
        on index 0, the prefix is empty, and ``if not to_compressed_msgs:
        return`` skips compression entirely — no matter how many characters
        the prompt measures.  A session whose group count happens to equal
        the budget-derived ``keep_recent`` therefore never compresses, and
        the gate refuses the next call: "compaction is enabled" is not a
        fact, it is a function of ``keep_recent`` versus the group count.
        The cliff is real and narrow, and it is exactly the shape of the dev
        incident (3 groups, 88,000-char tool result, 0 compactions).

        So when the gate has already measured a prompt over the trigger and
        upstream would compress zero messages, ``keep_recent`` drops by one
        and the prefix becomes compressible.  This is the one place that
        deliberately bypasses ``keep_recent_min``: that floor bounds the tail
        the *budget* can pay for, not whether the session is compressible at
        all.  It fires only on the measured-over-trigger path; every other
        path is untouched.
        """
        snapshot = getattr(
            getattr(agent, "context_guard", None),
            "last_snapshot",
            None,
        )
        if snapshot is None or snapshot.total_chars <= snapshot.trigger_chars:
            return keep_recent
        try:
            from agentscope.agent._react_agent import _MemoryMark

            uncompressed = await memory.get_memory(
                prepend_summary=False,
                exclude_mark=_MemoryMark.COMPRESSED,
            )
        except Exception:
            return keep_recent
        prefix = compressible_prefix_count(uncompressed, keep_recent)
        if prefix > 0 or len(uncompressed) <= 1:
            return keep_recent
        groups = count_message_groups(uncompressed)
        logger.warning(
            "keep_recent %d -> %d: %d message group(s) measured over the "
            "compression trigger (%d > %d chars) and upstream would compress "
            "zero messages at keep_recent == groups (keep_recent_min=%d "
            "bypassed for compressibility).",
            keep_recent,
            keep_recent - 1,
            groups,
            snapshot.total_chars,
            snapshot.trigger_chars,
            ccc.keep_recent_min,
        )
        return max(0, keep_recent - 1)

    @staticmethod
    async def _compute_keep_recent(
        memory: "AgentContext",
        budget_tokens: int,
        chars_per_token: float,
        keep_recent_min: int,
        keep_recent_max: int,
    ) -> int:
        """Delegate to :func:`window_source.compute_keep_recent`.

        Kept as a method for existing callers and tests; the rule itself
        lives in one place so every budget consumer sizes tails the same way.
        """
        return await compute_keep_recent(
            memory,
            budget_tokens=budget_tokens,
            chars_per_token=chars_per_token,
            keep_recent_min=keep_recent_min,
            keep_recent_max=keep_recent_max,
        )

    async def post_reasoning(
        self,
        agent: "CoApisAgent",
        kwargs: dict[str, Any],
        output: Any,
    ) -> Msg | None:
        """Archive what upstream compressed, then purge it from memory.

        Upstream summarizes the old prefix and marks it ``COMPRESSED``, but
        never removes it.  Every later prompt re-formats that dead weight, the
        persisted session state grows forever, and the token-usage cache keeps
        paying for messages that no longer matter.  This hook closes the loop:

        1. full transcript appended to ``dialog/*.jsonl`` — nothing is lost;
        2. messages removed from working memory;
        3. archived messages handed to the long-term memory manager, so a
           compaction event is also what produces durable memories.

        Runs after every reasoning step and costs a single scan when nothing
        was compressed.
        """
        memory = getattr(agent, "memory", None)
        if memory is None or not hasattr(memory, "archive_compressed_and_purge"):
            return None

        try:
            archived = await memory.archive_compressed_and_purge()
        except Exception as e:
            logger.warning("Could not archive compressed messages: %s", e)
            return None

        if not archived:
            return None

        agent_config = load_agent_config(self.agent_id)
        memory_manager = getattr(agent, "memory_manager", None)
        rlmc = getattr(agent_config.running, "reme_light_memory_config", None)
        if rlmc is not None and rlmc.summarize_when_compact:
            if memory_manager is not None:
                hand_to_long_term_memory(memory_manager, archived, "compaction")
            else:
                logger.debug(
                    "Compacted %d message(s) but the agent has no memory "
                    "manager; skipping reme summarization.",
                    len(archived),
                )

        summary = memory.get_compressed_summary() or ""
        try:
            await self._print_status_message(
                agent,
                f"🗜️ **Context compacted**\n\n"
                f"- {len(archived)} message(s) archived to dialog and dropped "
                f"from the working context\n"
                f"- rolling summary is now {len(summary)} characters",
            )
        except Exception:
            # Status lines are UX sugar; compaction must not depend on them.
            logger.debug("Could not show the compaction status line.", exc_info=True)
        return None

    async def _last_tool_result(self, agent: "CoApisAgent", tool_call: Any) -> Any:
        """Find the tool_result block matching *tool_call* in memory's tail.

        `_acting` appends the result message in its ``finally`` block and
        returns None for ordinary tools, so the tail of memory is the only
        place the raw output exists.  Scan a few messages, match by call id,
        fall back to the newest tool_result block.
        """
        try:
            call_id = ""
            call_name = ""
            if isinstance(tool_call, dict):
                call_id = str(tool_call.get("id", ""))
                call_name = str(tool_call.get("name", ""))
            else:
                call_id = str(getattr(tool_call, "id", "") or "")
                call_name = str(getattr(tool_call, "name", "") or "")
            messages = await agent.memory.get_memory(prepend_summary=False)
            newest = None
            for msg in reversed(messages[-6:]):
                for block in msg.get_content_blocks("tool_result"):
                    if block.get("type") != "tool_result":
                        continue
                    if newest is None:
                        newest = block
                    if call_id and block.get("id") == call_id:
                        return block
                    if call_name and block.get("name") == call_name:
                        return block
            return newest
        except Exception:
            logger.debug("Could not locate tool result in memory.", exc_info=True)
            return None

    async def post_acting(
        self,
        agent: "CoApisAgent",
        kwargs: dict[str, Any],
        output: Any,
    ) -> Msg | None:
        """Truncate oversized tool-call results after each acting step."""
        # 会话资源采集（B1）：把这一步读到的网页 / 写到工作区的文件登记进
        # 台账 + 本轮上下文。放在裁剪之前 —— 裁剪会把大输出 offload 掉，采集
        # 读的是原始文本。纯代码解析、零 LLM、自吞异常，坏了不影响消息链路。
        #
        # 注意：agentscope 的 `_acting` 只在 generate_response 时返回 dict，
        # 普通工具调用的结果只写进 memory，钩子拿到的 output 是 None。所以
        # 结果要从 memory 尾部的 tool_result 块里取，否则采集恒为空。
        try:
            from .reference_collector import collect_from_tool_call
            from ...config.context import get_current_username

            tool_call = kwargs.get("tool_call")
            result = output
            if result is None and tool_call is not None:
                result = await self._last_tool_result(agent, tool_call)
            if result is not None:
                collect_from_tool_call(
                    tool_call,
                    result,
                    username=get_current_username() or self.agent_id,
                )
        except Exception:
            logger.debug("resource collection hook skipped", exc_info=True)

        try:
            agent_config = load_agent_config(self.agent_id)
            lcc = agent_config.running.light_context_config
            trc = lcc.tool_result_pruning_config
            if not trc.enabled:
                return None

            memory = agent.memory
            messages = await memory.get_memory(prepend_summary=False)

            # 治理层地板（治理地基 片1）：裁剪器只处理 tool_result 块，
            # 工具直接返回的超大 text 块此前无人截断；由地板兜住。
            await self._governance_floor_pass(agent, messages)

            await self._prune_tool_result(
                messages=messages,
                recent_n=trc.pruning_recent_n,
                old_max_bytes=trc.pruning_old_msg_max_bytes,
                recent_max_bytes=trc.pruning_recent_msg_max_bytes,
                retention_days=trc.offload_retention_days,
            )
        except Exception as e:
            logger.exception(
                "Failed to prune tool results in post_acting hook: %s",
                e,
                exc_info=True,
            )

        return None

    async def post_reply(
        self,
        agent: "CoApisAgent",
        kwargs: dict[str, Any],
        output: Any,
    ) -> Msg | None:
        """Auto memory periodically based on user query count.

        When ``auto_memory_interval`` is set (e.g., 2), this hook counts user
        messages in the memory and triggers auto memory every N queries.
        """
        # 会话引用闸门（D2-A）：搜索结果里的链接只有被正文真正引用才算引用。
        # 必须放在最前面 —— 下面 memory_manager 为空会提前 return。
        try:
            from .reference_collector import _iter_text_chunks, finalize_web_references

            body = "\n".join(_iter_text_chunks(output))
            if body:
                finalize_web_references(body)
        except Exception:
            logger.debug("web reference gate skipped", exc_info=True)

        try:
            memory_manager = agent.memory_manager
            if memory_manager is None:
                return None

            agent_config = load_agent_config(self.agent_id)
            rlmc = agent_config.running.reme_light_memory_config
            auto_memory_interval = rlmc.auto_memory_interval

            if auto_memory_interval is None or auto_memory_interval <= 0:
                return None

            memory = agent.memory
            # memory.content is list[tuple[Msg, marks]]
            # Find indices of user messages to locate recent interval
            user_msg_indices = [
                i
                for i, (msg, _) in enumerate(memory.content)
                if msg.role == "user"
            ]

            if (
                len(user_msg_indices) >= auto_memory_interval
                and len(user_msg_indices) % auto_memory_interval == 0
            ):
                # Get messages from the start of recent interval
                start_index = user_msg_indices[-auto_memory_interval]
                recent_messages = [
                    msg for msg, _ in memory.content[start_index:]
                ]
                if recent_messages:
                    hand_to_long_term_memory(
                        memory_manager,
                        recent_messages,
                        "auto-memory interval",
                    )
        except Exception as e:
            logger.warning("post_reply hook failed: %s", e)

        return None

    def get_agent_context(self, **_kwargs) -> AgentContext:
        """Retrieve the agent context object with token counting support."""
        agent_config = load_agent_config(self.agent_id)
        dialog_path = os.path.join(
            self.working_dir,
            agent_config.running.light_context_config.dialog_path,
        )
        return AgentContext(
            token_counter=get_token_counter(agent_config),
            dialog_path=dialog_path,
        )
