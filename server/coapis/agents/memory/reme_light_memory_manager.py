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

"""File-based memory manager with LLM-enhanced search.

Provides memory search (keyword + LLM rerank), context compaction
auto-extraction, and Dream-based memory consolidation — all without
requiring reme-ai or any vector database.
"""
import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from agentscope.message import Msg, TextBlock, ToolResultBlock, ToolUseBlock
from agentscope.tool import ToolResponse

from .base_memory_manager import BaseMemoryManager, memory_registry
from .prompts import (
    MEMORY_GUIDANCE_ZH,
    MEMORY_GUIDANCE_EN,
)
from ..model_factory import create_model_and_formatter
from ...config.config import load_agent_config
from ...config.context import (
    set_current_workspace_dir,
    set_current_recent_max_bytes,
)

logger = logging.getLogger(__name__)

# Maximum number of tokens from query splitting
MAX_QUERY_TOKENS = 50


@memory_registry.register("remelight")
class ReMeLightMemoryManager(BaseMemoryManager):
    """File-based memory manager with LLM-enhanced search.

    Provides:
    - memory_search: keyword matching + LLM semantic rerank
    - summarize: extract high-value info during context compaction
    - dream: consolidate daily notes into MEMORY.md
    - retrieve: auto-retrieve relevant memories for conversation context
    """

    def __init__(
        self,
        working_dir: str,
        agent_id: str,
        username: str | None = None,
    ):
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._workspace_dir = Path(working_dir)
        self._username = username

        # Derive user-level memory directory.
        # Rule: if username is known → WORKSPACES_DIR/{username}
        #        (constant, independent of workspace_dir)
        #        if no username → None (global agent, no user-level)
        if username:
            from ...constant import WORKSPACES_DIR
            self._user_workspace: Path | None = WORKSPACES_DIR / username
        else:
            self._user_workspace = None

        logger.info(
            "ReMeLightMemoryManager init: "
            "agent_id=%s, working_dir=%s, username=%s, "
            "user_workspace=%s (file-based mode)",
            agent_id, working_dir, username,
            self._user_workspace,
        )
        self.summary_toolkit = None

    # ------------------------------------------------------------------
    # BaseMemoryManager interface
    # ------------------------------------------------------------------

    async def start(self):
        """No-op. File-based memory has no lifecycle."""
        return None

    async def close(self) -> bool:
        """No-op. File-based memory has no lifecycle."""
        return True

    def get_memory_prompt(self, language: str = "zh") -> str:
        """Return the memory guidance prompt for the system prompt."""
        prompts = {"zh": MEMORY_GUIDANCE_ZH, "en": MEMORY_GUIDANCE_EN}
        return prompts.get(language, MEMORY_GUIDANCE_EN)

    def list_memory_tools(self):
        """Return memory tool functions to register with the agent toolkit."""
        return [self.memory_search]

    # ── File-based memory search ─────────────────────────────────────

    def _collect_memory_files(self) -> list[Path]:
        """Collect all searchable memory files: agent-level + user-level.

        Two-level search:
          Level 2 (agent): workspace_dir/MEMORY.md, workspace_dir/memory/*.md
          Level 1 (user):  user_workspace/MEMORY.md, user_workspace/memory/*.md

        For user default agents (user:xxx), workspace_dir == user_workspace,
        so only one level is searched (no duplication).
        For sub-agents, user_workspace is different → both levels searched.
        """
        ws = Path(self.working_dir)
        files: list[Path] = []

        # --- Level 2: Agent-level (always) ---
        agent_mem = ws / "MEMORY.md"
        if agent_mem.exists():
            files.append(agent_mem)
        agent_mem_dir = ws / "memory"
        if agent_mem_dir.is_dir():
            files.extend(sorted(agent_mem_dir.glob("*.md")))

        # --- Level 1: User-level (skip if same as workspace) ---
        uw = self._user_workspace
        if uw and uw != ws:
            user_mem = uw / "MEMORY.md"
            if user_mem.exists():
                files.append(user_mem)
            user_mem_dir = uw / "memory"
            if user_mem_dir.is_dir():
                files.extend(sorted(user_mem_dir.glob("*.md")))

        return files

    @staticmethod
    def _split_into_chunks(
        text: str,
        path: Path,
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> list[dict]:
        """Split text into overlapping chunks with location info."""
        lines = text.split("\n")
        chunks: list[dict] = []
        current_lines: list[str] = []
        current_len = 0
        start_line = 1

        for i, line in enumerate(lines, 1):
            current_lines.append(line)
            current_len += len(line) + 1
            if current_len >= chunk_size:
                chunks.append({
                    "text": "\n".join(current_lines),
                    "path": str(path),
                    "line": start_line,
                })
                keep = max(1, overlap // max(len(line), 1))
                current_lines = current_lines[-keep:]
                current_len = sum(len(l) + 1 for l in current_lines)
                start_line = i - keep + 1

        if current_lines:
            chunks.append({
                "text": "\n".join(current_lines),
                "path": str(path),
                "line": start_line,
            })
        return chunks

    @staticmethod
    def _keyword_score(query: str, text: str) -> float:
        """Simple keyword overlap scoring (0.0 ~ 1.0)."""
        query_tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', query.lower()))
        if not query_tokens:
            return 0.0
        text_lower = text.lower()
        matched = sum(1 for t in query_tokens if t in text_lower)
        return matched / len(query_tokens)

    async def _file_based_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> ToolResponse:
        """Search memory files using keyword matching + optional LLM rerank."""
        files = self._collect_memory_files()
        if not files:
            return ToolResponse(
                content=[TextBlock(
                    type="text",
                    text="No memory files found.",
                )],
            )

        # Phase 1: keyword matching to collect candidates
        candidates: list[dict] = []
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            for chunk in self._split_into_chunks(text, f):
                score = self._keyword_score(query, chunk["text"])
                if score >= min_score:
                    candidates.append({**chunk, "score": score})

        candidates.sort(key=lambda x: x["score"], reverse=True)
        top_candidates = candidates[:max_results * 3]

        if not top_candidates:
            return ToolResponse(
                content=[TextBlock(
                    type="text",
                    text=f"No relevant memory found for: {query}",
                )],
            )

        # Phase 2: LLM rerank (if enough candidates)
        if len(top_candidates) > max_results:
            try:
                reranked = await self._llm_rerank(query, top_candidates)
                if reranked:
                    top_candidates = reranked
            except Exception as e:
                logger.debug("LLM rerank skipped: %s", e)

        results = top_candidates[:max_results]
        output_lines = []
        for r in results:
            score_str = f"{r['score']:.2f}" if 'score' in r else "?"
            output_lines.append(
                f"[score={score_str}] {r['path']}:{r['line']}\n{r['text'][:300]}"
            )

        return ToolResponse(
            content=[TextBlock(
                type="text",
                text="\n\n---\n\n".join(output_lines),
            )],
        )

    async def _llm_rerank(
        self,
        query: str,
        candidates: list[dict],
    ) -> list[dict] | None:
        """Use LLM to rerank candidate chunks by relevance to query."""
        agent_config = load_agent_config(self.agent_id)
        chat_model, formatter = create_model_and_formatter(self.agent_id)

        numbered = []
        for i, c in enumerate(candidates):
            preview = c["text"][:200].replace("\n", " ")
            numbered.append(f"[{i}] {preview}")

        prompt = (
            f"Query: {query}\n\n"
            f"Candidates:\n" + "\n".join(numbered) + "\n\n"
            "Rank the candidates by relevance to the query. "
            "Return ONLY a JSON array of indices in descending relevance, "
            'e.g. [2, 0, 1]. Return at most 5 indices.'
        )

        msg = Msg(role="user", name="reranker", content=prompt)
        try:
            set_current_workspace_dir(Path(self.working_dir))
            response = await chat_model(msg, formatter=formatter)
            text = response.get_text_content() or ""

            match = re.search(r'\[[\d\s,]+\]', text)
            if match:
                indices = json.loads(match.group())
                reranked = [
                    candidates[i]
                    for i in indices
                    if 0 <= i < len(candidates)
                ]
                return reranked
        except Exception as e:
            logger.debug("LLM rerank failed: %s", e)
        return None

    # ── Public API ───────────────────────────────────────────────────

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> ToolResponse:
        """Search MEMORY.md and memory/*.md files semantically.

        Use this tool before answering questions about prior work,
        decisions, dates, people, preferences, or todos. Returns top
        relevant snippets with file paths and line numbers.

        Args:
            query: The semantic search query.
            max_results: Maximum number of results. Defaults to 5.
            min_score: Minimum similarity score. Defaults to 0.1.

        Returns:
            ToolResponse with search results.
        """
        logger.info("[MemorySearch] Searching for: %s", query[:50])
        return await self._file_based_search(
            query=query,
            max_results=max_results,
            min_score=min_score,
        )

    async def summarize(self, messages: list[Msg], **_kwargs) -> str:
        """Extract high-value info from compacted messages → MEMORY.md."""
        return await self._extract_and_save_memory(messages)

    async def _extract_and_save_memory(self, messages: list[Msg]) -> str:
        """Extract high-value info from messages → write to correct level.

        Two-level write routing:
          - User preferences / habits → user_workspace/MEMORY.md
          - Agent-specific knowledge → workspace_dir/MEMORY.md

        Uses LLM to classify and extract, then writes to the correct target.
        """
        try:
            conv_parts = []
            for msg in messages:
                role = msg.name or msg.role or "unknown"
                text = msg.get_text_content() or ""
                if text.strip():
                    conv_parts.append(f"[{role}]: {text[:500]}")

            if not conv_parts:
                return ""

            conv_text = "\n".join(conv_parts[-20:])

            agent_config = load_agent_config(self.agent_id)
            chat_model, formatter = create_model_and_formatter(self.agent_id)
            set_current_workspace_dir(Path(self.working_dir))

            # Ask LLM to classify extracted info into two categories
            has_user_ws = (
                self._user_workspace is not None
                and self._user_workspace != self._workspace_dir
            )

            if has_user_ws:
                extract_prompt = (
                    "从以下对话中提取值得长期记忆的信息，并按类型分类。\n\n"
                    "## 分类规则\n"
                    "- [USER] 用户明确的偏好、习惯、个人资料、项目上下文、工作方式\n"
                    "- [AGENT] 智能体专属知识、技能经验、领域专业知识、工具使用技巧\n"
                    "- [SKIP] 闲聊、一般性问答、临时性信息\n\n"
                    "## 输出格式\n"
                    "每条信息一行，格式：[类型] 内容\n"
                    "示例：\n"
                    "[USER] 用户喜欢用 pytest 而不是 unittest\n"
                    "[USER] 用户的项目代码在 /apps/ai/tool-dev/dev-coapis\n"
                    "[AGENT] 处理 Django ORM 时要注意 N+1 查询\n"
                    "[AGENT] 代码审查时先检查 imports 再检查逻辑\n"
                    "[SKIP] 无\n\n"
                    f"对话内容：\n{conv_text}"
                )
            else:
                # No user workspace distinction (default agent or global)
                # → all writes go to workspace_dir
                extract_prompt = (
                    "从以下对话中提取值得长期记忆的信息。只提取以下类型：\n"
                    "1. 用户明确的偏好或习惯\n"
                    "2. 重要的决策或结论\n"
                    "3. 关键的事实或数据\n"
                    "4. 用户纠正过的错误认知\n"
                    "5. 重要的待办事项或承诺\n\n"
                    "不要提取：闲聊、一般性问答、临时性信息。\n\n"
                    "如果有值得记忆的内容，输出简洁的要点列表（每条一行，以 - 开头）。\n"
                    "如果没有值得记忆的内容，输出：无\n\n"
                    f"对话内容：\n{conv_text}"
                )

            msg = Msg(role="user", name="memory_extractor", content=extract_prompt)
            response = await chat_model(msg, formatter=formatter)
            result_text = (response.get_text_content() or "").strip()

            if not result_text or result_text == "无" or "无" in result_text[:5]:
                logger.info("[MemoryExtract] Nothing worth saving")
                return ""

            now = datetime.now().strftime("%Y-%m-%d %H:%M")

            if has_user_ws:
                # Parse classified output → route to correct target
                user_items: list[str] = []
                agent_items: list[str] = []

                for line in result_text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("[USER]"):
                        user_items.append(line[6:].strip())
                    elif line.startswith("[AGENT]"):
                        agent_items.append(line[7:].strip())
                    elif line.startswith("[SKIP]"):
                        continue
                    else:
                        # Unclassified → treat as agent-level
                        agent_items.append(line)

                saved_any = False

                if user_items:
                    user_content = "\n".join(f"- {item}" for item in user_items)
                    user_path = self._user_workspace / "MEMORY.md"
                    self._append_memory_safe(
                        user_path, user_content, now, "用户记忆",
                    )
                    saved_any = True

                if agent_items:
                    agent_content = "\n".join(f"- {item}" for item in agent_items)
                    agent_path = self._workspace_dir / "MEMORY.md"
                    self._append_memory_safe(
                        agent_path, agent_content, now, "智能体记忆",
                    )
                    saved_any = True

                if saved_any:
                    logger.info(
                        "[MemoryExtract] Routed: %d user-level, %d agent-level items",
                        len(user_items), len(agent_items),
                    )
                return result_text
            else:
                # No user workspace → write to workspace_dir (backward compat)
                memory_path = self._workspace_dir / "MEMORY.md"
                entry = f"\n\n## 自动提取 ({now})\n{result_text}\n"

                existing = ""
                if memory_path.exists():
                    existing = memory_path.read_text(encoding="utf-8")

                if self._keyword_score(result_text[:100], existing) > 0.8:
                    logger.info("[MemoryExtract] Similar content already in MEMORY.md")
                    return result_text

                self._append_memory_safe(
                    memory_path, result_text, now, "记忆",
                )
                return result_text

        except Exception as e:
            logger.warning("[MemoryExtract] Failed: %s", e)
            return ""

    @staticmethod
    def _append_memory_safe(
        target: Path,
        content: str,
        timestamp: str,
        label: str,
    ) -> None:
        """Append memory to target file with dedup and file lock.

        Args:
            target: Target MEMORY.md path.
            content: Content to append.
            timestamp: Formatted timestamp string.
            label: Human-readable label for logging.
        """
        import fcntl

        if not content or not content.strip():
            return

        entry = f"\n\n## 自动提取 ({timestamp})\n{content}\n"

        target.parent.mkdir(parents=True, exist_ok=True)

        # Read existing content for dedup
        existing = ""
        if target.exists():
            existing = target.read_text(encoding="utf-8")

        # Check for duplicate (keyword overlap > 80%)
        query_tokens = set(
            re.findall(r'[\w\u4e00-\u9fff]+', content[:100].lower())
        )
        if query_tokens:
            text_lower = existing.lower()
            matched = sum(1 for t in query_tokens if t in text_lower)
            if matched / len(query_tokens) > 0.8:
                logger.info(
                    "[MemoryExtract] Similar content already in %s: %s",
                    label, target.name,
                )
                return

        # File lock + append (atomic for concurrent writes)
        lock_path = target.with_suffix(target.suffix + ".lock")
        lock_path.touch(exist_ok=True)
        try:
            with open(lock_path, "w") as lock_f:
                fcntl.flock(lock_f, fcntl.LOCK_EX)
                try:
                    with open(target, "a", encoding="utf-8") as f:
                        f.write(entry)
                finally:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
        except OSError:
            # Fallback: no locking (e.g. non-POSIX filesystem)
            with open(target, "a", encoding="utf-8") as f:
                f.write(entry)

        logger.info(
            "[MemoryExtract] Saved %d chars to %s: %s",
            len(content), label, target.name,
        )

    async def retrieve(
        self,
        messages: list[Msg] | Msg,
        agent_name: str = "",
        **_kwargs,
    ) -> dict | None:
        """Retrieve relevant memory and return updated kwargs dict.

        Returns:
            None: No relevant memory found.
            dict: {"msg": msgs + [assistant_msg, tool_result_msg]}
        """
        msgs: list[Msg] = (
            [messages] if isinstance(messages, Msg) else list(messages)
        )

        query_parts: list[str] = []
        total = 0
        for msg in reversed(msgs):
            remaining = 100 - total
            if remaining <= 0:
                break
            text = (msg.get_text_content() or "").strip()
            if not text:
                continue
            chunk = text[:remaining]
            query_parts.insert(0, chunk)
            total += len(chunk)

        query = " ".join(query_parts).strip()
        if not query:
            return None

        agent_config = load_agent_config(self.agent_id)
        reme_cfg = agent_config.running.reme_light_memory_config
        ms = reme_cfg.auto_memory_search_config
        max_results = ms.max_results
        min_score = ms.min_score

        try:
            result = await self.memory_search(
                query=query,
                max_results=max_results,
                min_score=min_score,
            )
            content_blocks = result.content

            text_content = "\n".join(
                b.get("text", "")
                for b in content_blocks
                if isinstance(b, dict) and b.get("text")
            )
            if not text_content:
                return None

            _id = uuid.uuid4().hex
            tool_use_input = {
                "query": query,
                "max_results": max_results,
                "min_score": min_score,
            }

            assistant_msg = Msg(
                name=agent_name,
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text="Searching memory for relevant context...",
                    ),
                    ToolUseBlock(
                        type="tool_use",
                        id=_id,
                        name="memory_search",
                        input=tool_use_input,
                        raw_input=json.dumps(
                            tool_use_input,
                            ensure_ascii=False,
                        ),
                    ),
                ],
            )

            tool_result_msg = Msg(
                name=agent_name,
                role="system",
                content=[
                    ToolResultBlock(
                        type="tool_result",
                        id=_id,
                        name="memory_search",
                        output=[TextBlock(type="text", text=text_content)],
                    ),
                ],
            )

            return {"msg": msgs + [assistant_msg, tool_result_msg]}

        except Exception as e:
            logger.exception("memory_search failed: %s", e)
            return None

    async def dream(self, **_kwargs) -> None:
        """Run one dream-based memory optimization pass.

        Two-level dream: for sub-agents, consolidates BOTH agent-level
        and user-level memory files. For default agents, only processes
        the single level (user workspace == agent workspace).
        """
        logger.info("[Dream] Starting memory optimization")

        agent_config = load_agent_config(self.agent_id)
        chat_model, formatter = create_model_and_formatter(self.agent_id)
        set_current_workspace_dir(Path(self.working_dir))

        language = getattr(agent_config, "language", "zh")
        has_user_ws = (
            self._user_workspace is not None
            and self._user_workspace != self._workspace_dir
        )

        if has_user_ws:
            # Sub-agent: dream both levels
            await self._dream_level(
                self._workspace_dir, chat_model, formatter,
                language, level_label="智能体级",
            )
            await self._dream_level(
                self._user_workspace, chat_model, formatter,
                language, level_label="用户级",
            )
        else:
            # Default agent or global: single level
            await self._dream_level(
                self._workspace_dir, chat_model, formatter,
                language, level_label="",
            )

    async def _dream_level(
        self,
        target_dir: Path,
        chat_model,
        formatter,
        language: str,
        level_label: str = "",
    ) -> None:
        """Run dream consolidation for a single memory level.

        Args:
            target_dir: The workspace directory containing MEMORY.md
                and memory/ subdirectory.
            chat_model: LLM model instance.
            formatter: LLM formatter instance.
            language: Language code ("zh" or "en").
            level_label: Label for logging (e.g. "智能体级", "用户级").
        """
        label = f"[{level_label}] " if level_label else ""
        logger.info("[Dream] %sProcessing: %s", label, target_dir)

        current_date = datetime.now().strftime("%Y-%m-%d")

        # Step 1: Collect recent memory files (today + last 3 days)
        memory_dir = target_dir / "memory"
        if not memory_dir.exists():
            logger.info("[Dream] %sNo memory/ directory, skipping", label)
            return

        recent_files = list(memory_dir.glob(f"{current_date}*.md"))
        for days_ago in range(1, 4):
            date_str = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            recent_files.extend(memory_dir.glob(f"{date_str}*.md"))

        if not recent_files:
            logger.info("[Dream] %sNo recent memory files found, skipping", label)
            return

        # Step 2: Read existing MEMORY.md
        memory_file = target_dir / "MEMORY.md"
        existing_memory = ""
        if memory_file.exists():
            existing_memory = memory_file.read_text(encoding="utf-8")

        # Step 3: Read daily notes
        daily_notes = []
        for fp in sorted(recent_files):
            try:
                content = fp.read_text(encoding="utf-8").strip()
                if content:
                    daily_notes.append(f"## {fp.name}\n{content}")
            except Exception as e:
                logger.warning("[Dream] %sFailed to read %s: %s", label, fp, e)

        if not daily_notes:
            logger.info("[Dream] %sAll recent memory files are empty, skipping", label)
            return

        daily_text = "\n\n".join(daily_notes)

        # Step 4: Backup MEMORY.md
        backup_path = target_dir.absolute() / "backup"
        backup_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if memory_file.exists():
            backup_file = backup_path / f"memory_backup_{timestamp}.md"
            try:
                shutil.copyfile(memory_file, backup_file)
                logger.info("[Dream] %sCreated MEMORY.md backup: %s", label, backup_file)
            except Exception as e:
                logger.warning("[Dream] %sBackup failed: %s", label, e)

        # Step 5: LLM consolidation
        if language == "zh":
            prompt = (
                "你是记忆整理专家。请将以下每日笔记与现有长期记忆合并，生成更新后的长期记忆。\n\n"
                "规则：\n"
                "1. 保留现有长期记忆中有价值的内容\n"
                "2. 从每日笔记中提取新的有价值信息（偏好、决策、事实、待办）\n"
                "3. 去重：合并重复信息，保留最新版本\n"
                "4. 删除过时或不再相关的内容\n"
                "5. 保持简洁，每条记忆不超过2行\n"
                "6. 按主题分类组织\n\n"
                f"现有长期记忆：\n{existing_memory[:3000]}\n\n"
                f"每日笔记：\n{daily_text[:5000]}\n\n"
                "请输出合并后的完整长期记忆内容（Markdown格式），不要加任何前言或说明："
            )
        else:
            prompt = (
                "You are a memory consolidation expert. Merge the daily notes "
                "below with the existing long-term memory.\n\n"
                "Rules:\n"
                "1. Preserve valuable content from existing memory\n"
                "2. Extract new valuable info from daily notes\n"
                "3. Deduplicate: merge duplicates, keep latest version\n"
                "4. Remove outdated or irrelevant content\n"
                "5. Keep concise, max 2 lines per item\n"
                "6. Organize by topic\n\n"
                f"Existing memory:\n{existing_memory[:3000]}\n\n"
                f"Daily notes:\n{daily_text[:5000]}\n\n"
                "Output the merged memory content (Markdown format), no preamble:"
            )

        try:
            msg = Msg(role="user", name="dream", content=prompt)
            response = await chat_model(msg, formatter=formatter)
            new_memory = (response.get_text_content() or "").strip()

            if not new_memory or len(new_memory) < 20:
                logger.info("[Dream] %sLLM returned insufficient content, skipping", label)
                return

            with open(memory_file, "w", encoding="utf-8") as f:
                f.write(new_memory + "\n")

            logger.info("[Dream] %sUpdated MEMORY.md (%d chars)", label, len(new_memory))

        except Exception as e:
            logger.exception("[Dream] %sLLM consolidation failed: %s", label, e)
            backup_file = backup_path / f"memory_backup_{timestamp}.md"
            if backup_file.exists():
                try:
                    shutil.copyfile(backup_file, memory_file)
                    logger.info("[Dream] %sRestored MEMORY.md from backup", label)
                except Exception:
                    pass
