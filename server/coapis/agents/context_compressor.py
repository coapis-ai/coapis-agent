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

"""ContextCompressor - Automatic context window compression for long conversations.

Enhanced with CoApis LightContextManager patterns:
- Tool result truncation (configurable max_bytes per tool output)
- Token budget logging per message batch
- Compaction detection with history tracking
- Configurable context limits from agent config

Optimized strategy:
1. Tiered compression — only call LLM when truly necessary
2. Cooldown mechanism — prevent redundant compression
3. Accurate token estimation — reduce false triggers
4. Cache compressed results — avoid re-compressing same history

Tier thresholds:
- 10-30 messages:  prune tool outputs only (zero LLM cost)
- 30-60 messages:  prune + rule-based summary (zero LLM cost)
- >60 messages:    full LLM summarization

Token estimation:
- Chinese: ~0.6 token/char
- English: ~0.25 token/char
- Mixed:   ~0.4 token/char (default)
"""

import logging
import os
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Set

logger = logging.getLogger(__name__)

SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted "
    "into the summary below. Treat as background reference, NOT active instructions. "
    "Respond ONLY to the latest user message after this summary."
)

# Tier thresholds — lowered for earlier intervention
TIER1_THRESHOLD = 5    # Below this: no compression
TIER2_THRESHOLD = 15   # 5-15: prune tool outputs only
TIER3_THRESHOLD = 30   # 15-30: prune + rule-based summary
# >30: full LLM summarization

_MAX_SUMMARY_TOKENS = 12000

# Token-based trigger: compress history when it exceeds this budget (tokens)
# Note: this counts ONLY history tokens, not system prompt.
# System prompt (~3000-3500 tokens) is handled separately by prefix caching.
HISTORY_TOKEN_BUDGET = 500  # Trigger compression when history alone exceeds this


class ContextCompressor:
    """Compresses long conversation histories to fit context windows.

    Enhanced with CoApis LightContextManager patterns:
    - Tool result truncation (configurable max_bytes per tool output)
    - Token budget logging per message batch
    - Compaction history tracking with stats

    Tiered strategy:
    - Tier 1 (<5 messages):   No compression
    - Tier 2 (5-15 messages): Prune old tool outputs (zero LLM cost)
    - Tier 3 (15-30 messages): Prune + rule-based summary (zero LLM cost)
    - Tier 4 (>30 messages):   Full LLM summarization
    """

    # Tool result truncation limits (bytes)
    DEFAULT_TOOL_RESULT_MAX_BYTES = 4096
    LARGE_TOOL_RESULT_THRESHOLD = 8192

    # Default exempt file extensions (won't be truncated)
    DEFAULT_EXEMPT_EXTENSIONS = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
        ".toml", ".md", ".txt", ".html", ".css", ".sh", ".bash",
    }

    # Default exempt tool names (won't be truncated)
    DEFAULT_EXEMPT_TOOLS = {
        "read_file", "read", "cat", "view",
    }

    def __init__(
        self,
        core,
        min_tokens: int = 8000,
        max_tokens: int = 12000,
        tool_result_dir: str = None,
        exempt_extensions: Set[str] = None,
        exempt_tools: Set[str] = None,
        offload_retention_days: int = 7,
    ):
        self.core = core
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        # Cache: store last compressed result to avoid re-compression
        self._last_message_count = 0
        self._last_compressed = None
        # Compaction history tracking
        self._compaction_history: List[Dict] = []
        self._total_messages_compacted = 0
        self._total_tokens_saved = 0

        # Tool result offloading (borrowed from CoApis LightContextManager)
        self._tool_result_dir = Path(tool_result_dir) if tool_result_dir else None
        self._exempt_extensions = exempt_extensions or self.DEFAULT_EXEMPT_EXTENSIONS
        self._exempt_tools = (exempt_tools or self.DEFAULT_EXEMPT_TOOLS)
        self._offload_retention_days = offload_retention_days

    async def compress(self, messages: List[Dict], model: str) -> List[Dict]:
        """Compress messages using tiered strategy.

        Args:
            messages: Full message history
            model: Current model being used

        Returns:
            Compressed message list
        """
        msg_count = len(messages)

        # --- Quick check: if message count didn't grow much, return cached ---
        # But also check token budget — a single long response can blow past budget
        if self._last_compressed is not None and msg_count - self._last_message_count < 3:
            # Check if new messages alone exceeded token budget
            new_msgs = messages[self._last_message_count:]
            new_tokens = self._estimate_tokens(new_msgs)
            if new_tokens <= HISTORY_TOKEN_BUDGET:
                # Safe to reuse cached result + new messages
                return self._last_compressed + new_msgs
            else:
                logger.info(f"Cache bypass: new msgs ({len(new_msgs)}) have {new_tokens} tokens (budget={HISTORY_TOKEN_BUDGET})")
                # Fall through to full compression

        # --- Token-based trigger: compress even with few messages if tokens are high ---
        estimated_tokens = self._estimate_tokens(messages)
        # Trigger earlier: 3+ messages AND tokens > budget, OR 5+ messages regardless of tokens
        if (estimated_tokens > HISTORY_TOKEN_BUDGET and msg_count >= 3) or msg_count >= 5:
            # History is getting heavy — compress regardless of exact token count
            # Use rule-based summary (zero LLM cost) for short conversations
            if msg_count < TIER3_THRESHOLD:
                result = self._compress_rule_based(messages)
            else:
                result = await self._compress_llm(messages, model)
            self._cache_result(messages, result)
            compressed_tokens = self._estimate_tokens(result)
            saved = estimated_tokens - compressed_tokens
            logger.info(f"Token-triggered compression: {msg_count} msgs ({estimated_tokens} tokens) -> {len(result)} msgs ({compressed_tokens} tokens), saved={saved} tokens")
            return result

        # --- Tier 1: No compression needed ---
        if msg_count < TIER1_THRESHOLD:
            return messages

        # --- Tier 2: Prune tool outputs only (zero LLM cost) ---
        if msg_count < TIER2_THRESHOLD:
            result = self._prune_tool_outputs(messages)
            self._cache_result(messages, result)
            return result

        # --- Tier 3: Prune + rule-based summary (zero LLM cost) ---
        if TIER2_THRESHOLD <= msg_count <= TIER3_THRESHOLD:
            result = self._compress_rule_based(messages)
            self._cache_result(messages, result)
            logger.info(f"Tier 3 compression: {msg_count} -> {len(result)} messages (rule-based)")
            return result

        # --- Tier 4: Full LLM summarization (only when tokens are high) ---
        estimated_tokens = self._estimate_tokens(messages)
        context_limit = self._get_context_limit(model)

        if estimated_tokens < context_limit * 0.8:
            # Still within budget but message count is high — use rule-based summary
            # This handles the case where context window is large (128k) but message count is high
            result = self._compress_rule_based(messages)
            self._cache_result(messages, result)
            logger.info(f"Tier 4 fallback: {msg_count} msgs ({estimated_tokens} tokens) -> {len(result)} msgs (rule-based)")
            return result

        # Need full LLM compression — with retry + fallback
        logger.info(f"Tier 4 compression: {msg_count} messages ({estimated_tokens} tokens)")
        try:
            result = await self._compress_llm(messages, model, reserve_ratio=1.0)
        except Exception as e1:
            logger.warning(
                f"Tier 4 LLM compression failed (attempt 1): {e1}, "
                f"retrying with elevated reserve (1.5x)"
            )
            try:
                result = await self._compress_llm(
                    messages, model, reserve_ratio=1.5
                )
            except Exception as e2:
                logger.warning(
                    f"Tier 4 LLM compression failed (attempt 2): {e2}, "
                    f"retrying with 2x reserve"
                )
                try:
                    result = await self._compress_llm(
                        messages, model, reserve_ratio=2.0
                    )
                except Exception as e3:
                    logger.error(
                        f"Tier 4 LLM compression failed all 3 attempts: {e3}, "
                        f"falling back to rule-based compression"
                    )
                    result = self._compress_rule_based(messages)
        self._cache_result(messages, result)
        logger.info(f"Compressed to {len(result)} messages")
        return result

    def _cache_result(self, original: List[Dict], compressed: List[Dict]):
        """Cache the compressed result to avoid re-compression."""
        self._last_message_count = len(original)
        self._last_compressed = compressed

    def clear_cache(self):
        """Clear compression cache (call when session resets)."""
        self._last_message_count = 0
        self._last_compressed = None

    def _estimate_tokens(self, messages: List[Dict]) -> int:
        """More accurate token estimation using character-level heuristics.

        Chinese characters: ~0.6 token/char
        English words: ~0.25 token/char (including spaces)
        """
        total_tokens = 0
        for m in messages:
            content = str(m.get("content", ""))
            if not content:
                continue

            # Count Chinese vs non-Chinese characters
            chinese_chars = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', content))
            non_chinese_chars = len(content) - chinese_chars

            total_tokens += int(chinese_chars * 0.6) + int(non_chinese_chars * 0.25)

        return total_tokens

    def _get_context_limit(self, model: str) -> int:
        """Get context window size for model."""
        limits = {
            "qwen3.6-27b": 128_000,
            "qwen3-235b-a22b": 128_000,
            "qwen-max": 128_000,
            "qwen-plus": 128_000,
            "qwen-turbo": 128_000,
            "claude-sonnet-4-20250514": 200_000,
            "claude-opus-4-20250514": 200_000,
            "gpt-4o": 128_000,
            "gpt-4o-mini": 128_000,
        }
        return limits.get(model, 128_000)

    def _prune_tool_outputs(self, messages: List[Dict]) -> List[Dict]:
        """Replace old tool outputs with placeholder or truncate large ones.

        Enhanced: uses prune_tool_outputs_with_truncation for smarter pruning.
        """
        return self.prune_tool_outputs_with_truncation(messages, keep_recent=2)

    def _compress_rule_based(self, messages: List[Dict]) -> List[Dict]:
        """Rule-based compression without LLM call.

        Strategy:
        1. Keep head (first 2 messages — typically user + assistant)
        2. Keep tail (last 2 turns = 4 messages, or fewer for short convos)
        3. Replace middle with a concise rule-based summary
        4. Prune all tool outputs in middle

        For short conversations (5-6 msgs), keep head=2 and tail=2 to ensure
        there's always middle content to compress.
        """
        n = len(messages)
        if n <= 4:
            return messages  # Too short to compress

        head_count = 2  # Always keep first 2 (user + assistant)
        # Scale tail: 2 for short convos, up to 4 for longer ones
        tail_count = min(4, max(2, n - head_count - 1))

        middle = messages[head_count:-tail_count] if tail_count < n else []

        if not middle:
            return messages  # Safety fallback

        # Generate rule-based summary from middle
        summary = self._generate_rule_summary(middle)

        # Prune tool outputs in middle
        pruned_middle = self._prune_tool_outputs(middle)

        # Reconstruct — use "assistant" role for summary (NOT "system"!)
        # The outer stream_chat prepends the real system message, so having
        # a "system" role in the middle causes some LLM servers to reject with
        # "System message must be at the beginning."
        if summary:
            # Summary was generated and is worth it (>150 chars of middle content)
            compressed = (
                messages[:head_count] +
                [{"role": "assistant", "content": f"{SUMMARY_PREFIX}\n{summary}"}] +
                messages[-tail_count:]
            )
        else:
            # Middle was too short — just keep head + pruned middle + tail
            # (no summary insertion, but tool outputs are still pruned)
            compressed = (
                messages[:head_count] +
                pruned_middle +
                messages[-tail_count:]
            )

        return compressed

    def _generate_rule_summary(self, messages: List[Dict]) -> str:
        """Generate summary using rule-based extraction (no LLM call).

        Strategy: extract key topics and outcomes, NOT full text.
        The summary MUST be shorter than the original messages combined.

        Extracts:
        - User intents (from user messages) — condensed to topic keywords
        - Key outcomes (from assistant messages) — condensed to 1-line summary
        - Topic transitions
        """
        # Quick check: if middle is just 1 short message, don't bother summarizing
        # The summary itself adds overhead — only summarize if middle is substantial
        total_middle_chars = sum(len(str(m.get("content", ""))) for m in messages)
        if total_middle_chars < 150:
            # Too short to benefit from summarization — just return the middle as-is
            # The caller will inline these; no compression benefit but no harm either
            return ""  # Empty string signals caller to skip summary insertion

        user_topics = []
        assistant_outcomes = []

        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "user" and content and "[Tool output" not in content:
                # Extract topic keywords from user message (first ~15 chars)
                topic = self._extract_topic(content)
                if topic:
                    user_topics.append(topic)
            elif role == "assistant" and content and "[Tool output" not in content:
                # Extract outcome: first sentence or first ~50 chars
                outcome = self._extract_outcome(content)
                if outcome:
                    assistant_outcomes.append(outcome)

        # Build summary — keep it SHORT
        parts = []
        if user_topics:
            unique_topics = self._deduplicate_intents(user_topics)
            parts.append(f"Topics: {'; '.join(unique_topics[:4])}")

        if assistant_outcomes:
            unique_outcomes = self._deduplicate_intents(assistant_outcomes)
            if unique_outcomes:
                parts.append(f"Responses: {'; '.join(unique_outcomes[:3])}")

        return " ".join(parts) if parts else "[Earlier conversation summarized]"

    def _extract_topic(self, content: str) -> str:
        """Extract a short topic keyword from user message.

        Takes first ~15 chars as the topic indicator.
        """
        # Get first sentence or first ~15 chars
        first_sentence = content.split('.')[0].split('。')[0].split('!')[0].split('！')[0]
        return first_sentence.strip()[:15]

    def _extract_outcome(self, content: str) -> str:
        """Extract a short outcome summary from assistant response.

        Takes first sentence, truncated to ~50 chars.
        """
        # Get first sentence
        first_sentence = content.split('\n\n')[0]  # First paragraph
        first_sentence = first_sentence.split('.')[0].split('。')[0]
        return first_sentence.strip()[:50]

    def _deduplicate_intents(self, intents: List[str]) -> List[str]:
        """Remove similar intents based on keyword overlap."""
        if not intents:
            return []

        unique = [intents[0]]
        for intent in intents[1:]:
            # Simple check: if >50% words overlap with any existing, skip
            words = set(re.findall(r'[\w\u4e00-\u9fff]+', intent.lower()))
            is_duplicate = False
            for existing in unique:
                existing_words = set(re.findall(r'[\w\u4e00-\u9fff]+', existing.lower()))
                if words and existing_words:
                    overlap = len(words & existing_words) / min(len(words), len(existing_words))
                    if overlap > 0.5:
                        is_duplicate = True
                        break
            if not is_duplicate:
                unique.append(intent)

        return unique

    async def _compress_llm(
        self,
        messages: List[Dict],
        model: str,
        reserve_ratio: float = 1.0,
    ) -> List[Dict]:
        """Full LLM-based compression (Tier 4).

        Args:
            messages: Full message history
            model: Current model being used
            reserve_ratio: Multiplier for head/tail counts (>1.0 = keep more).
                On retry, caller can set 1.5 or 2.0 to retain more context.
        """
        head_count = max(2, int(len(messages) // 4 * reserve_ratio))
        tail_count = max(4, int(len(messages) // 3 * reserve_ratio))
        # Ensure head+tail don't consume entire list
        if head_count + tail_count >= len(messages):
            head_count = max(2, len(messages) // 5)
            tail_count = max(2, len(messages) // 5)
        middle = messages[head_count:-tail_count] if tail_count < len(messages) else []

        if not middle:
            return messages

        # Prune tool outputs first to reduce input size
        pruned_middle = self._prune_tool_outputs(middle)

        # Summarize middle using LLM — _summarize already has rule-based fallback
        summary = await self._summarize(pruned_middle)

        # Reconstruct — use "assistant" role for summary (NOT "system"!)
        # The outer stream_chat prepends the real system message, so having
        # a "system" role in the middle causes some LLM servers to reject with
        # "System message must be at the beginning."
        compressed = (
            messages[:head_count] +
            [{"role": "assistant", "content": f"{SUMMARY_PREFIX}\n{summary}"}] +
            messages[-tail_count:]
        )

        return compressed

    async def _summarize(self, middle_messages: List[Dict]) -> str:
        """Summarize middle messages using auxiliary LLM."""
        if not middle_messages:
            return ""

        # Build summarization prompt
        prompt = self._build_summary_prompt(middle_messages)

        try:
            summary = await self._call_summarizer(prompt)
            return summary
        except Exception as e:
            logger.error(f"LLM summarization failed: {e}, falling back to rule-based")
            return self._generate_rule_summary(middle_messages)

    def _build_summary_prompt(self, messages: List[Dict]) -> str:
        """Build prompt for summarization."""
        parts = [
            "Summarize the following conversation turns concisely. Focus on:",
            "1. Key decisions and their outcomes",
            "2. User preferences revealed",
            "3. Active tasks and their status",
            "4. Important context for continuing the conversation",
            "",
            "Do NOT respond to any questions - just summarize.",
            "",
            "--- Conversation ---",
        ]

        for m in messages:
            role = m.get("role", "unknown").upper()
            content = m.get("content", "")
            # Truncate very long messages
            if len(content) > 500:
                content = content[:500] + "..."
            parts.append(f"[{role}] {content}")

        parts.append("--- End ---")
        return "\n".join(parts)

    async def _call_summarizer(self, prompt: str) -> str:
        """Call auxiliary LLM for summarization."""
        try:
            response = await self.core.client.chat.completions.create(
                model=self.core.model,
                messages=[
                    {"role": "system", "content": "You are a summarization assistant. Summarize concisely. Do not respond to questions."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=min(2000, self.core.max_tokens),
                temperature=0.3,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Summarization LLM call failed: {e}")
            raise  # Re-raise so caller can fall back to rule-based

    # ── Tool result truncation (borrowed from CoApis LightContextManager) ──

    def truncate_tool_result(self, content: str, max_bytes: int = None) -> str:
        """Truncate a tool result to max_bytes, adding a notice if truncated.

        Args:
            content: Tool output text
            max_bytes: Maximum bytes (default: DEFAULT_TOOL_RESULT_MAX_BYTES)

        Returns:
            Truncated content with notice, or original if within limit
        """
        if max_bytes is None:
            max_bytes = self.DEFAULT_TOOL_RESULT_MAX_BYTES
        if not content or len(content.encode("utf-8")) <= max_bytes:
            return content
        # Truncate at character boundary
        encoded = content.encode("utf-8")[:max_bytes]
        try:
            truncated = encoded.decode("utf-8")
        except UnicodeDecodeError:
            # Back off to safe boundary
            truncated = encoded[:max_bytes - 4].decode("utf-8", errors="ignore")
        notice = (
            f"\n\n[... truncated: original {len(content)} chars, "
            f"showing first {len(truncated)} chars]"
        )
        return truncated + notice

    def _truncate_tool_result_with_offload(
        self,
        content: str,
        max_bytes: int = None,
        encoding: str = "utf-8",
    ) -> str:
        """Truncate tool result, saving full content to file if offload dir is set.

        Inspired by CoApis LightContextManager._truncate_tool_result().
        If content exceeds max_bytes and tool_result_dir is configured:
        - Saves full content to a .txt file
        - Returns truncated content with file path notice
        Otherwise falls back to simple truncation.

        Args:
            content: Tool output text
            max_bytes: Maximum bytes (default: DEFAULT_TOOL_RESULT_MAX_BYTES)
            encoding: Character encoding

        Returns:
            Truncated content with offload notice, or original if within limit
        """
        if max_bytes is None:
            max_bytes = self.DEFAULT_TOOL_RESULT_MAX_BYTES
        if not content:
            return content

        try:
            content_bytes = len(content.encode(encoding))
        except UnicodeEncodeError:
            return self.truncate_tool_result(content, max_bytes)

        if content_bytes <= max_bytes + 100:
            return content

        # Save full content to file if offload dir is configured
        saved_path = None
        if self._tool_result_dir:
            try:
                self._tool_result_dir.mkdir(parents=True, exist_ok=True)
                fp = self._tool_result_dir / f"{uuid.uuid4().hex}.txt"
                fp.write_text(content, encoding=encoding)
                saved_path = str(fp)
            except OSError as e:
                logger.warning("Failed to save tool result to file: %s", e)

        # Truncate
        truncated = self.truncate_tool_result(content, max_bytes)
        if saved_path:
            truncated += f"\n[Full output saved to: {saved_path}]"
        return truncated

    def _cleanup_expired_tool_result_files(self) -> int:
        """Clean up tool result files older than retention_days.

        Returns:
            Number of files successfully deleted.
        """
        if not self._tool_result_dir or not self._tool_result_dir.exists():
            return 0

        cutoff = datetime.now() - timedelta(days=self._offload_retention_days)
        deleted = failed = 0

        for fp in self._tool_result_dir.glob("*.txt"):
            try:
                stat = os.stat(fp)
                if sys.platform == "win32":
                    ts = stat.st_ctime
                else:
                    ts = getattr(stat, "st_birthtime", stat.st_mtime)
                if datetime.fromtimestamp(ts) < cutoff:
                    fp.unlink()
                    deleted += 1
            except FileNotFoundError:
                pass
            except Exception as e:
                failed += 1
                logger.warning("Failed to delete %s: %s", fp, e)

        if deleted or failed:
            logger.info(
                "Cleaned up %d expired tool result files (%d failed)",
                deleted, failed,
            )
        return deleted

    def _is_valid_summary(self, content: str) -> bool:
        """Check if the summary content is valid.

        Borrowed from CoApis LightContextManager._is_valid_summary().

        Args:
            content: The summary content to validate.

        Returns:
            True if valid, False otherwise.
        """
        if not content or not content.strip():
            return False
        # Must have some structure (## header or bullet points)
        if "##" not in content and "- " not in content:
            return False
        return True

    def prune_tool_outputs_with_truncation(
        self,
        messages: List[Dict],
        keep_recent: int = 2,
    ) -> List[Dict]:
        """Prune old tool outputs with smart truncation and exempt list support.

        Enhanced with CoApis patterns:
        - Exempt file extensions and tool names (won't be truncated)
        - File offloading for large results (saves to disk)
        - Recent tool outputs (last `keep_recent` tool messages): kept as-is
        - Older tool outputs > threshold: truncated to max_bytes
        - Older tool outputs <= threshold: replaced with placeholder

        Args:
            messages: Full message history
            keep_recent: Number of recent tool messages to keep intact

        Returns:
            Pruned message list
        """
        tool_count = 0
        tool_positions = []
        for i, m in enumerate(messages):
            if m.get("role") == "tool":
                tool_positions.append(i)
                tool_count += 1

        if tool_count <= keep_recent:
            return messages  # Nothing to prune

        # Detect exempt tool IDs (from tool_use blocks in preceding messages)
        exempt_tool_ids: Set[str] = set()
        for i, m in enumerate(messages):
            # Check for tool_use in content blocks (structured format)
            content = m.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_id = block.get("id", "")
                        tool_name = (block.get("name") or "").lower()
                        raw_input = (block.get("raw_input") or "").lower()
                        if tool_name in self._exempt_tools:
                            exempt_tool_ids.add(tool_id)
                        elif tool_name in ("read_file", "read"):
                            for ext in self._exempt_extensions:
                                if ext in raw_input:
                                    exempt_tool_ids.add(tool_id)
                                    break

        # Indices of tools to prune/truncate
        prune_indices = set(tool_positions[: tool_count - keep_recent])

        result = []
        for i, m in enumerate(messages):
            if i not in prune_indices:
                result.append(m)
                continue

            # Check if this tool result is exempt
            tool_id = m.get("tool_call_id", "") or m.get("id", "")
            if tool_id in exempt_tool_ids:
                result.append(m)
                continue

            content = str(m.get("content", ""))
            content_bytes = len(content.encode("utf-8"))
            if content_bytes > self.LARGE_TOOL_RESULT_THRESHOLD:
                # Large tool output → truncate with offloading
                result.append({
                    **m,
                    "content": self._truncate_tool_result_with_offload(content),
                })
            else:
                # Small tool output → placeholder
                result.append({**m, "content": "[Tool output cleared]"})
        return result

    # ── Compaction statistics ──

    def record_compaction(
        self,
        original_count: int,
        compressed_count: int,
        tokens_before: int,
        tokens_after: int,
        method: str,
    ) -> None:
        """Record a compaction event for statistics."""
        entry = {
            "original_count": original_count,
            "compressed_count": compressed_count,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_saved": tokens_before - tokens_after,
            "method": method,
            "timestamp": __import__("time").time(),
        }
        self._compaction_history.append(entry)
        # Keep only last 50 records
        if len(self._compaction_history) > 50:
            self._compaction_history = self._compaction_history[-50:]
        self._total_messages_compacted += original_count - compressed_count
        self._total_tokens_saved += max(0, tokens_before - tokens_after)

    def get_compaction_stats(self) -> Dict:
        """Return compaction statistics summary."""
        return {
            "total_compactions": len(self._compaction_history),
            "total_messages_compacted": self._total_messages_compacted,
            "total_tokens_saved": self._total_tokens_saved,
            "last_compaction": (
                self._compaction_history[-1] if self._compaction_history else None
            ),
            "cache_active": self._last_compressed is not None,
            "cached_message_count": self._last_message_count,
        }

    def log_token_budget(
        self,
        messages: List[Dict],
        label: str = "compress",
    ) -> int:
        """Log token budget breakdown per message role. Returns total tokens."""
        role_tokens: Dict[str, int] = {}
        for m in messages:
            role = m.get("role", "unknown")
            tokens = self._estimate_tokens([m])
            role_tokens[role] = role_tokens.get(role, 0) + tokens
        total = sum(role_tokens.values())
        parts = [f"{r}={t}" for r, t in sorted(role_tokens.items())]
        logger.info(
            "Token budget [%s]: total=%d (%s)",
            label,
            total,
            ", ".join(parts),
        )
        return total
