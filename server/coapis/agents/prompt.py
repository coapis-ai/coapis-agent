# -*- coding: utf-8 -*-
# flake8: noqa: E501
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

"""System prompt building utilities.

This module provides utilities for building system prompts from
markdown configuration files in the working directory.
"""
import logging
import re
from pathlib import Path

from agentscope_runtime.engine.schemas.exception import (
    ConfigurationException,
)

from .memory.base_memory_manager import BaseMemoryManager
from .utils.file_handling import read_text_file_with_encoding_fallback

logger = logging.getLogger(__name__)

# Default fallback prompt
DEFAULT_SYS_PROMPT = """
You are a helpful assistant.
"""

# Backward compatibility alias
SYS_PROMPT = DEFAULT_SYS_PROMPT

# ── PromptBuilder mtime cache ──
# Key: (str(working_dir), frozenset(enabled_files), heartbeat_enabled)
# Value: (prompt_str, {filename: mtime})
_prompt_cache: dict[tuple, tuple[str, dict[str, float]]] = {}

# ── Cache statistics ──
_cache_stats: dict[str, int] = {"hits": 0, "misses": 0, "total": 0}


def get_cache_stats() -> dict:
    """Get PromptBuilder cache hit/miss statistics."""
    total = _cache_stats["total"]
    return {
        **_cache_stats,
        "hit_rate": round(_cache_stats["hits"] / total, 3) if total > 0 else 0.0,
        "cache_size": len(_prompt_cache),
    }


def _get_file_mtimes(working_dir: Path, filenames: list[str]) -> dict[str, float]:
    """Get mtimes for all files. O(1) stat calls per file."""
    mtimes = {}
    for f in filenames:
        fp = working_dir / f
        try:
            mtimes[f] = fp.stat().st_mtime
        except OSError:
            mtimes[f] = 0.0
    return mtimes


def _cache_key(
    working_dir: Path,
    enabled_files: list[str],
    heartbeat_enabled: bool,
) -> tuple:
    return (str(working_dir), tuple(sorted(enabled_files)), heartbeat_enabled)


class PromptConfig:
    """Configuration for system prompt building."""

    # Default files to load when no config is provided
    # All files are optional - if they don't exist, they'll be skipped
    DEFAULT_FILES = [
        "AGENTS.md",
        "SOUL.md",
        "PROFILE.md",
    ]


class PromptBuilder:
    """Builder for constructing system prompts from markdown files."""

    # Regex pattern to match heartbeat section markers
    HEARTBEAT_PATTERN = re.compile(
        r"<!-- heartbeat:start -->.*?<!-- heartbeat:end -->",
        re.DOTALL,
    )

    # Regex pattern to match memory section markers
    MEMORY_PATTERN = re.compile(
        r"<!-- memory:start -->.*?<!-- memory:end -->",
        re.DOTALL,
    )

    def __init__(
        self,
        working_dir: Path,
        enabled_files: list[str] | None = None,
        heartbeat_enabled: bool = False,
        language: str = "zh",
        memory_manager: BaseMemoryManager | None = None,
    ):
        """Initialize prompt builder.

        Args:
            working_dir: Directory containing markdown configuration files
            enabled_files: List of filenames to load (if None, uses default order)
            heartbeat_enabled: Whether heartbeat is enabled, affects AGENTS.md content
            language: Language code used to select the memory prompt.
            memory_manager: Memory manager instance for generating memory prompts.
        """
        self.working_dir = working_dir
        self.enabled_files = enabled_files
        self.heartbeat_enabled = heartbeat_enabled
        self.language = language
        self.memory_manager = memory_manager
        self.prompt_parts = []
        self.loaded_count = 0

    def _load_file(self, filename: str) -> None:
        """Load a single markdown file.

        All files are optional - if they don't exist or can't be read,
        they will be silently skipped.

        Args:
            filename: Name of the file to load
        """
        file_path = self.working_dir / filename

        if not file_path.exists():
            logger.debug("File %s not found, skipping", filename)
            return

        try:
            content = read_text_file_with_encoding_fallback(file_path).strip()

            # Remove YAML frontmatter if present
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    content = parts[2].strip()

            # Filter heartbeat / memory sections from AGENTS.md based on config
            if filename == "AGENTS.md":
                try:
                    content = self._process_heartbeat_section(content)
                except Exception as e:
                    logger.warning(
                        f"Failed to process heartbeat with {e}",
                    )
                try:
                    content = self._process_memory_section(content)
                except Exception as e:
                    logger.warning(
                        f"Failed to process memory section with {e}",
                    )

            if content:
                if self.prompt_parts:  # Add separator if not first section
                    self.prompt_parts.append("")
                # Add section header with filename
                self.prompt_parts.append(f"# {filename}")
                self.prompt_parts.append("")
                self.prompt_parts.append(content)
                self.loaded_count += 1
                logger.debug("Loaded %s", filename)
            else:
                logger.debug("Skipped empty file: %s", filename)

        except Exception as e:
            logger.warning(
                "Failed to read file %s: %s, skipping",
                filename,
                e,
            )

    def _process_heartbeat_section(self, content: str) -> str:
        """Process heartbeat section in AGENTS.md content.

        - If heartbeat markers not found: keep content unchanged (backward compatibility)
        - If heartbeat is enabled: keep the content but remove the markers
        - If heartbeat is disabled: remove the entire section

        Args:
            content: Original AGENTS.md content

        Returns:
            Processed content
        """
        # Check if markers exist
        if "<!-- heartbeat:start -->" not in content:
            return content

        if self.heartbeat_enabled:
            # Keep content, just remove the markers
            content = content.replace("<!-- heartbeat:start -->", "")
            content = content.replace("<!-- heartbeat:end -->", "")
            return content.strip()
        else:
            # Remove the entire heartbeat section
            filtered = self.HEARTBEAT_PATTERN.sub("", content)
            return filtered.strip()

    def _process_memory_section(self, content: str) -> str:
        """Process memory section in AGENTS.md content.

        - If memory markers are found: remove the entire section.
        - Always append the canonical memory prompt at the end.

        Args:
            content: Original AGENTS.md content

        Returns:
            Processed content with memory prompt appended.
        """
        # Remove existing memory section if markers exist
        if "<!-- memory:start -->" in content:
            content = self.MEMORY_PATTERN.sub("", content).strip()

        # Get memory prompt from manager or fallback
        if self.memory_manager:
            memory_section = self.memory_manager.get_memory_prompt(
                self.language,
            )
        else:
            memory_section = ""

        return (
            (content + "\n\n" + memory_section).strip()
            if content
            else memory_section
        )

    def build(self) -> str:
        """Build the system prompt from markdown files.

        All files are optional. If no files can be loaded, returns the default prompt.

        Returns:
            Constructed system prompt string
        """
        # Determine which files to load
        files_to_load = (
            PromptConfig.DEFAULT_FILES
            if self.enabled_files is None
            else self.enabled_files
        )

        # Load all files (all are optional)
        for filename in files_to_load:
            self._load_file(filename)

        # Build language instruction — strengthened to reduce mixed-language output
        if self.language == "zh":
            lang_instruction = (
                "\n\n# 语言设置\n\n"
                "你必须使用中文回复用户。所有思考过程、分析、回答内容均须使用中文，"
                "禁止在回复中夹杂英文（专有名词和技术术语除外）。"
            )
        elif self.language == "en":
            lang_instruction = (
                "\n\n# Language Settings\n\n"
                "You MUST respond to the user in English. "
                "All reasoning, analysis, and responses must be in English."
            )
        else:
            lang_instruction = (
                f"\n\n# Language Settings\n\n"
                f"Please respond to the user in {self.language}."
            )

        if not self.prompt_parts:
            logger.warning("No content loaded from working directory")
            return DEFAULT_SYS_PROMPT + lang_instruction

        # Join all parts with double newlines
        final_prompt = "\n\n".join(self.prompt_parts)

        # Append explicit language instruction for LLM output
        final_prompt += lang_instruction

        logger.debug(
            "System prompt built from %d file(s), total length: %d chars",
            self.loaded_count,
            len(final_prompt),
        )

        return final_prompt


class SectionMerger:
    """Merge markdown content by ## sections with priority-based override.

    Usage:
        merger = SectionMerger()
        merger.add_layer("global", global_content, priority=0)
        merger.add_layer("user", user_content, priority=1)
        merger.add_layer("agent", agent_content, priority=2)
        result = merger.merge()
    """

    def __init__(self) -> None:
        self._layers: list[tuple[str, str, int]] = []

    def add_layer(self, name: str, content: str, priority: int) -> None:
        if content and content.strip():
            self._layers.append((name, content.strip(), priority))

    @staticmethod
    def _parse_sections(content: str) -> list[tuple[str, str]]:
        """Split markdown into (header, body) pairs by ## headers.

        Returns list of (section_name, full_section_text) tuples.
        A preamble (text before first ##) is stored as "(preamble)".
        """
        import re
        sections: list[tuple[str, str]] = []
        # Split on lines starting with ##
        parts = re.split(r'^(## .+)$', content, flags=re.MULTILINE)
        # parts[0] = preamble, then alternating header/body
        preamble = parts[0].strip()
        if preamble:
            sections.append(("(preamble)", preamble))
        for i in range(1, len(parts), 2):
            header = parts[i].strip()
            body = parts[i + 1].strip() if i + 1 < len(parts) else ""
            name = header.lstrip("#").strip()
            sections.append((name, f"{header}\n\n{body}"))
        return sections

    def merge(self) -> str:
        """Merge all layers, higher priority overrides same-name sections."""
        if not self._layers:
            return ""

        # Collect all section names across layers, preserving first-seen order
        section_order: list[str] = []
        # name → list of (priority, content) sorted desc by priority
        section_candidates: dict[str, list[tuple[int, str]]] = {}

        for _name, content, priority in self._layers:
            for section_name, section_text in self._parse_sections(content):
                if section_name not in section_candidates:
                    section_candidates[section_name] = []
                    section_order.append(section_name)
                section_candidates[section_name].append((priority, section_text))

        # For each section, pick highest priority version
        result_parts: list[str] = []
        for section_name in section_order:
            candidates = section_candidates[section_name]
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0][1]
            if best:
                result_parts.append(best)

        return "\n\n---\n\n".join(result_parts)


def _merge_three_layers(
    global_prompt: str,
    user_prompt: str,
    agent_prompt: str,
) -> str:
    """Merge three priority layers: global → user-level → agent-level.

    Uses SectionMerger for section-based fusion with priority override.
    """
    merger = SectionMerger()
    merger.add_layer("global", global_prompt, priority=0)
    merger.add_layer("user", user_prompt, priority=1)
    merger.add_layer("agent", agent_prompt, priority=2)
    return merger.merge()


def build_system_prompt_from_working_dir(
    working_dir: Path | None = None,
    enabled_files: list[str] | None = None,
    agent_id: str | None = None,
    heartbeat_enabled: bool = False,
    language: str = "zh",
    memory_manager: BaseMemoryManager | None = None,
    global_workspace_dir: Path | None = None,
    global_workspace_dirs: list[Path] | None = None,
    user_workspace_dir: Path | None = None,
) -> str:
    """
    Build system prompt by reading markdown files from working directory.

    This function constructs the system prompt by loading markdown files from
    the specified working directory (workspace_dir for multi-agent setup).
    These files define the agent's behavior, personality, and operational guidelines.

    The files to load are determined by the enabled_files parameter or
    agents.system_prompt_files configuration. If not configured, falls back to
    default files:
    - AGENTS.md - Detailed workflows, rules, and guidelines
    - SOUL.md - Core identity and behavioral principles
    - PROFILE.md - Agent identity and user profile

    All files are optional. If a file doesn't exist or can't be read, it will be
    skipped. If no files can be loaded, returns the default prompt.

    Args:
        working_dir: Directory to read markdown files from (if None, uses
            global WORKING_DIR for backward compatibility)
        enabled_files: List of filenames to load (if None, uses config or defaults)
        agent_id: Agent identifier to include in system prompt (optional)
        heartbeat_enabled: Whether heartbeat is enabled. When False, filters
            heartbeat section from AGENTS.md to avoid confusing instructions.
        language: Language code (``"zh"`` or ``"en"``) for memory prompt.
        memory_manager: Memory manager instance for generating memory prompts.
            If provided, uses its ``get_memory_prompt()`` method instead of
            the standalone function.

    Returns:
        str: Constructed system prompt from markdown files.
             If no files exist, returns the default prompt.

    Example:
        If working_dir contains AGENTS.md, SOUL.md and PROFILE.md, they will be combined:
        "# AGENTS.md\\n\\n...\\n\\n# SOUL.md\\n\\n...\\n\\n# PROFILE.md\\n\\n..."
    """
    from ..constant import WORKING_DIR
    from ..config import load_config

    # Use provided working_dir or fallback to global WORKING_DIR
    if working_dir is None:
        working_dir = Path(WORKING_DIR)

    # Load enabled files from parameter or config
    if enabled_files is None:
        # Use agent-specific config if agent_id provided
        if agent_id:
            from ..config.config import load_agent_config

            try:
                agent_config = load_agent_config(agent_id)
                enabled_files = agent_config.system_prompt_files
            except (ValueError, FileNotFoundError, ConfigurationException):
                # Agent not found in config, fallback to global config
                config = load_config()
                enabled_files = config.agents.system_prompt_files
        else:
            # Fallback to global config for backward compatibility
            config = load_config()
            enabled_files = config.agents.system_prompt_files

    # ── Resolve global template dirs for inheritance ──
    if global_workspace_dir is not None:
        # Backward compat: single-dir caller
        global_workspace_dirs = [global_workspace_dir]
    if not global_workspace_dirs:
        try:
            from .global_agent_utils import get_template_agents
            global_workspace_dirs = get_template_agents()
        except Exception:
            pass

    # ── Build three layers: global → user-level → agent-level ──
    # Global layer (lowest priority): from template agents
    global_prompt = ""
    if global_workspace_dirs:
        global_parts: list[str] = []
        for tpl_dir in global_workspace_dirs:
            if tpl_dir and tpl_dir.is_dir():
                g = PromptBuilder(
                    working_dir=tpl_dir,
                    enabled_files=enabled_files,
                    heartbeat_enabled=heartbeat_enabled,
                    language=language,
                    memory_manager=None,
                )
                part = g.build()
                if part:
                    global_parts.append(part)
        global_prompt = "\n\n".join(global_parts)

    # User-level layer (middle priority): from user workspace root
    user_prompt = ""
    if user_workspace_dir and user_workspace_dir.is_dir():
        u = PromptBuilder(
            working_dir=user_workspace_dir,
            enabled_files=enabled_files,
            heartbeat_enabled=heartbeat_enabled,
            language=language,
            memory_manager=None,
        )
        user_prompt = u.build() or ""

    # ── mtime cache check: skip rebuild if files unchanged ──
    cache_k = _cache_key(working_dir, enabled_files, heartbeat_enabled)
    _cache_stats["total"] += 1
    if cache_k in _prompt_cache:
        cached_prompt, cached_mtimes = _prompt_cache[cache_k]
        current_mtimes = _get_file_mtimes(working_dir, enabled_files)
        if current_mtimes == cached_mtimes:
            _cache_stats["hits"] += 1
            prompt = cached_prompt
            prompt = _merge_three_layers(global_prompt, user_prompt, prompt)
            # ── System-level file operation directive ──
            prompt += _get_file_operation_directive(language)
            if agent_id:
                identity_header = (
                    f"# Agent Identity\n\n"
                    f"Your agent id is `{agent_id}`. "
                    f"This is your unique identifier in the multi-agent system.\n\n"
                )
                return identity_header + prompt
            return prompt

    builder = PromptBuilder(
        working_dir=working_dir,
        enabled_files=enabled_files,
        heartbeat_enabled=heartbeat_enabled,
        language=language,
        memory_manager=memory_manager,
    )
    prompt = builder.build()
    _cache_stats["misses"] += 1

    # ── Merge three layers: global → user → agent (highest priority) ──
    prompt = _merge_three_layers(global_prompt, user_prompt, prompt)

    # ── System-level file operation directive ──
    prompt += _get_file_operation_directive(language)

    # ── Cache the result for next call ──
    current_mtimes = _get_file_mtimes(working_dir, enabled_files)
    _prompt_cache[cache_k] = (prompt, current_mtimes)

    # Add agent identity information at the beginning of the prompt
    if agent_id:
        identity_header = (
            f"# Agent Identity\n\n"
            f"Your agent id is `{agent_id}`. "
            f"This is your unique identifier in the multi-agent system.\n\n"
        )
        prompt = identity_header + prompt

    return prompt


def build_bootstrap_guidance(
    language: str = "zh",
) -> str:
    """Build bootstrap guidance message for first-time setup.

    Args:
        language: Language code (zh/en/ru)

    Returns:
        Formatted bootstrap guidance message
    """
    if language == "zh":
        return (
            "# 引导模式\n"
            "\n"
            "工作目录中存在 `BOOTSTRAP.md` — 首次设置。\n"
            "\n"
            "1. 阅读 BOOTSTRAP.md，友好地表示初次见面，"
            "引导用户完成设置。\n"
            "2. 按照 BOOTSTRAP.md 的指示，"
            "帮助用户定义你的身份和偏好。\n"
            "3. 按指南创建/更新必要文件"
            "（PROFILE.md、MEMORY.md 等）。\n"
            "4. 全部完成后，使用 write_file 创建 "
            "`.bootstrap_completed` 标记文件，内容为空。\n"
            "5. 不要删除 BOOTSTRAP.md。\n"
            "\n"
            "如果用户希望跳过，直接回答下面的问题即可，"
            "并创建 `.bootstrap_completed` 标记文件。\n"
            "\n"
            "---\n"
            "\n"
        )
    # en / ru / other — default to English
    return (
        "# BOOTSTRAP MODE\n"
        "\n"
        "`BOOTSTRAP.md` exists — first-time setup.\n"
        "\n"
        "1. Read BOOTSTRAP.md, greet the user, "
        "and guide them through setup.\n"
        "2. Follow BOOTSTRAP.md instructions "
        "to define identity and preferences.\n"
        "3. Create/update files "
        "(PROFILE.md, MEMORY.md, etc.) as described.\n"
        "4. When all steps are done, use write_file to create "
        "`.bootstrap_completed` flag file (empty content).\n"
        "5. Do NOT delete BOOTSTRAP.md.\n"
        "\n"
        "If the user wants to skip, answer their "
        "question directly instead, "
        "and create `.bootstrap_completed` flag file.\n"
        "\n"
        "---\n"
        "\n"
    )


def _get_active_model_info():
    """Resolve the active model's ModelInfo and model name.

    Tries agent-specific model first, then falls back to global.

    Returns:
        A ``(ModelInfo, model_name)`` tuple.  Both elements are *None*
        when the active model cannot be resolved.
    """
    try:
        from ..app.agent_context import get_current_agent_id
        from ..config.config import load_agent_config
        from ..providers.provider_manager import ProviderManager

        manager = ProviderManager.get_instance()

        # Try to get agent-specific model first
        active = None
        try:
            agent_id = get_current_agent_id()
            agent_config = load_agent_config(agent_id)
            if agent_config.active_model:
                active = agent_config.active_model
        except Exception:
            pass

        # Fallback to global active model
        if not active:
            active = manager.get_active_model()

        if not active:
            return None, None

        provider = manager.get_provider(active.provider_id)
        if not provider:
            return None, None

        for m in provider.models + provider.extra_models:
            if m.id == active.model:
                return m, active.model
        return None, None
    except Exception:
        return None, None


def get_active_model_supports_multimodal() -> bool:
    """Check if the current active model supports multimodal input."""
    model_info, _ = _get_active_model_info()
    if model_info is None:
        return False
    return bool(model_info.supports_multimodal)


def get_active_model_multimodal_raw() -> bool | None:
    """Return the effective multimodal capability flag for the active model.

    Checks ``supports_multimodal``, ``supports_image``, and
    ``supports_video`` — any of them being ``True`` means multimodal
    is confirmed.

    - ``True``: confirmed multimodal support (via any of the three flags)
    - ``False``: confirmed text-only (supports_multimodal is explicitly
      False and neither supports_image nor supports_video is True)
    - ``None``: unknown / not yet probed (all three are None)
    """
    model_info, _ = _get_active_model_info()
    if model_info is None:
        return None
    if model_info.supports_image or model_info.supports_video:
        return True
    return model_info.supports_multimodal


def build_multimodal_hint() -> str:
    """Build a short system-prompt snippet describing multimodal capability."""
    model_info, model_name = _get_active_model_info()
    if model_info is None:
        return ""
    return format_multimodal_hint(model_info, model_name)


def format_multimodal_hint(model_info, _model_name: str) -> str:
    """Format the multimodal hint string for the system prompt."""
    if (
        model_info.supports_image
        or model_info.supports_video
        or model_info.supports_multimodal is None
    ):
        return ""
    return (
        "It appears that you can only understand text content. "
        " Please honestly inform the user about this when "
        " their input includes multimodal information."
    )


_FILE_OPERATION_DIRECTIVE_ZH = (
    "\n\n---\n\n## [系统指令] 文件操作规范\n\n"
    "当用户要求你保存、创建、写入任何文件时，**必须调用 `write_file` 工具实际执行写入**，不要只给出路径建议。\n\n"
    "**默认保存路径：** `files/`（用户「我的空间」文件目录）。\n"
    "- 用户未指定路径 → `files/{有意义的文件名}`\n"
    "- 用户指定相对路径 → `files/{用户路径}`\n"
    "- 用户指定绝对路径 → 按用户指定（须在 workspace 安全范围内）\n\n"
    "**行为要求：**\n"
    "- 不要问「要不要保存」，直接保存\n"
    "- 保存后告知用户文件路径\n"
    "- 完成复杂任务（分析报告、代码、文档）后，主动保存到 `files/`\n"
    "- 深度工作过程中的阶段产物，保存到 `files/.temp/` 目录，完成后清理\n"
)

_FILE_OPERATION_DIRECTIVE_EN = (
    "\n\n---\n\n## [System Directive] File Operation Policy\n\n"
    "When a user asks you to save, create, or write any file, "
    "**you MUST call the `write_file` tool to actually write it**. "
    "Do NOT just suggest a path.\n\n"
    "**Default save path:** `files/` (the user's \"My Space\" file directory).\n"
    "- User did not specify a path → `files/{meaningful_filename}`\n"
    "- User specified a relative path → `files/{user_path}`\n"
    "- User specified an absolute path → use as-is (must be within workspace)\n\n"
    "**Behavior requirements:**\n"
    "- Do NOT ask \"should I save?\" — just save it\n"
    "- Always tell the user the file path after saving\n"
    "- Proactively save after completing complex tasks (reports, code, documents) to `files/`\n"
    "- Save intermediate work products during deep work to `files/.temp/`, clean up when done\n"
)

_FILE_OPERATION_DIRECTIVE_RU = (
    "\n\n---\n\n## [Системная директива] Политика работы с файлами\n\n"
    "Когда пользователь просит сохранить, создать или записать файл, "
    "**обязательно вызовите инструмент `write_file`** для фактической записи. "
    "Не просто предлагайте путь.\n\n"
    "**Путь по умолчанию:** `files/` (каталог «Моё пространство»).\n"
    "- Путь не указан → `files/{осмысленное_имя}`\n"
    "- Относительный путь → `files/{путь_пользователя}`\n"
    "- Абсолютный путь → как есть (в пределах рабочей области)\n\n"
    "**Требования:**\n"
    "- Не спрашивайте «сохранить?» — просто сохраните\n"
    "- Сообщайте путь после сохранения\n"
    "- Автоматически сохраняйте результаты сложных задач в `files/`\n"
    "- Промежуточные результаты сохраняйте в `files/.temp/`, удаляйте при завершении\n"
)


_BOOTSTRAP_GUIDANCE_TAG = "__COAPIS_BOOTSTRAP_GUIDANCE__"


def build_bootstrap_guidance_v2(
    language: str = "zh",
    attempt: int = 1,
    max_attempts: int = 3,
) -> str:
    """Build concise bootstrap guidance for first-time user setup.

    v2: Injected as an independent system message.  The agent answers
    the user's question first, then appends a brief setup prompt.

    Args:
        language: Language code (zh/en).
        attempt: Current attempt number (1-based).
        max_attempts: Maximum allowed attempts.

    Returns:
        System-message text with the guidance tag prefix.
    """
    remaining = max_attempts - attempt
    if language == "zh":
        if attempt == 1:
            tail = "回答末尾问一句用户怎么称呼、喜欢什么风格。"
        elif attempt == 2:
            tail = "回答末尾轻提一句上次的问题，换个说法。"
        else:
            tail = "最后一次，简短提一句，用户不答就不再问。"

        return (
            f"{_BOOTSTRAP_GUIDANCE_TAG}\n"
            f"[内部指令 — 禁止展示给用户] 首次引导({attempt}/{max_attempts})\n"
            f"规则：先完整回答问题。{tail}"
            "用户给了名字/偏好就更新PROFILE.md。"
            "用户明确拒绝或引导完成就创建`.bootstrap_completed`。"
        )
    # English
    if attempt == 1:
        tail_en = "At the end, casually ask what to call them and preferred style."
    elif attempt == 2:
        tail_en = "Drop a brief, differently-worded reminder at the end."
    else:
        tail_en = "Last attempt — very brief. If user doesn't engage, never ask again."

    return (
        f"{_BOOTSTRAP_GUIDANCE_TAG}\n"
        f"[Internal — do NOT show to user] Bootstrap ({attempt}/{max_attempts})\n"
        f"Rules: Answer fully first. {tail_en} "
        "Update PROFILE.md if user shares info. "
        "Create `.bootstrap_completed` when done or if user declines."
    )


def _get_file_operation_directive(language: str = "zh") -> str:
    """Return the system-level file operation directive for the given language."""
    if language == "ru":
        return _FILE_OPERATION_DIRECTIVE_RU
    if language == "en":
        return _FILE_OPERATION_DIRECTIVE_EN
    return _FILE_OPERATION_DIRECTIVE_ZH


__all__ = [
    "build_system_prompt_from_working_dir",
    "build_bootstrap_guidance",
    "build_bootstrap_guidance_v2",
    "_BOOTSTRAP_GUIDANCE_TAG",
    "build_multimodal_hint",
    "format_multimodal_hint",
    "get_active_model_supports_multimodal",
    "get_active_model_multimodal_raw",
    "PromptBuilder",
    "PromptConfig",
    "DEFAULT_SYS_PROMPT",
    "SYS_PROMPT",  # Backward compatibility
]
