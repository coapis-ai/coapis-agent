# -*- coding: utf-8 -*-
# flake8: noqa: E501
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

"""System prompt building utilities.

This module provides utilities for building system prompts from
markdown configuration files in the working directory.
"""
import logging
import re
from pathlib import Path

import yaml

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


class PromptConfig:
    """Configuration for system prompt building."""

    # Default files to load when no config is provided
    # All files are optional - if they don't exist, they'll be skipped
    DEFAULT_FILES = [
        "AGENTS.md",
        "SOUL.md",
        "PROFILE.md",
    ]

    # Core skills to load by default (full description in system prompt)
    # These are high-frequency skills that most users need regularly
    DEFAULT_CORE_SKILLS = [
        "file_reader",      # 文件读取 - 最基础能力
        "make_plan",        # 任务规划 - 复杂任务必备
        "guidance",         # 使用指南 - 帮助用户了解平台
        "coapis_source_index",  # 源码索引 - 快速定位文档
        "browser_use",      # 浏览器自动化 - 复杂网页操作必备
    ]

    # Skills to show as brief list (name only, no full description)
    # Agent should read SKILL.md when needed
    BRIEF_SKILL_HINT = (
        "当用户提到相关场景时，读取对应技能的 SKILL.md 文件获取完整说明。\n"
        "不要猜测技能用法，先读取 SKILL.md。\n"
        "⚠️ 重要：当工具调用失败时，务必读取提示中建议的技能 SKILL.md，获取替代方案。"
    )


# Skill categories for organized display
SKILL_CATEGORIES = {
    "browser": {
        "zh": "🌐 浏览器自动化",
        "en": "🌐 Browser Automation",
        "skills": ["browser_use", "browser_cdp", "browser_visible"],
    },
    "document": {
        "zh": "📝 文档处理",
        "en": "📝 Document Processing",
        "skills": ["docx", "pdf", "pptx", "xlsx", "file_reader"],
    },
    "communication": {
        "zh": "📧 通信与集成",
        "en": "📧 Communication & Integration",
        "skills": ["himalaya", "channel_message", "dingtalk_channel"],
    },
    "agent": {
        "zh": "🤖 智能体协作",
        "en": "🤖 Agent Collaboration",
        "skills": ["chat_with_agent", "multi_agent_collaboration"],
    },
    "scheduling": {
        "zh": "⏰ 任务调度",
        "en": "⏰ Task Scheduling",
        "skills": ["cron"],
    },
    "info": {
        "zh": "📰 信息获取",
        "en": "📰 Information Retrieval",
        "skills": ["news"],
    },
    "utility": {
        "zh": "🧭 辅助工具",
        "en": "🧭 Utility Tools",
        "skills": ["guidance", "QA_source_index", "make_plan"],
    },
}


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
        include_skills: bool = True,
        core_skills: list[str] | None = None,
        trim_mode: bool = False,
    ):
        """Initialize prompt builder.

        Args:
            working_dir: Directory containing markdown configuration files
            enabled_files: List of filenames to load (if None, uses default order)
            heartbeat_enabled: Whether heartbeat is enabled, affects AGENTS.md content
            language: Language code used to select the memory prompt.
            memory_manager: Memory manager instance for generating memory prompts.
            include_skills: Whether to inject dynamic skills section into prompt.
            core_skills: List of core skill names to load with full descriptions.
                If None, uses PromptConfig.DEFAULT_CORE_SKILLS.
            trim_mode: If True, use minimal prompt (skip AGENTS.md, SOUL.md).
                Only load PROFILE.md and core skills. Useful for short conversations.
        """
        self.working_dir = working_dir
        self.enabled_files = enabled_files
        self.heartbeat_enabled = heartbeat_enabled
        self.language = language
        self.memory_manager = memory_manager
        self.include_skills = include_skills
        self.core_skills = core_skills or PromptConfig.DEFAULT_CORE_SKILLS
        self.trim_mode = trim_mode
        self.prompt_parts = []
        self.loaded_count = 0


# Skill categories for organized display
SKILL_CATEGORIES = {
    "browser": {
        "zh": "🌐 浏览器自动化",
        "en": "🌐 Browser Automation",
        "skills": ["browser_use", "browser_cdp", "browser_visible"],
    },
    "document": {
        "zh": "📝 文档处理",
        "en": "📝 Document Processing",
        "skills": ["docx", "pdf", "pptx", "xlsx", "file_reader"],
    },
    "communication": {
        "zh": "📧 通信与集成",
        "en": "📧 Communication & Integration",
        "skills": ["himalaya", "channel_message", "dingtalk_channel"],
    },
    "agent": {
        "zh": "🤖 智能体协作",
        "en": "🤖 Agent Collaboration",
        "skills": ["chat_with_agent", "multi_agent_collaboration"],
    },
    "scheduling": {
        "zh": "⏰ 任务调度",
        "en": "⏰ Task Scheduling",
        "skills": ["cron"],
    },
    "info": {
        "zh": "📰 信息获取",
        "en": "📰 Information Retrieval",
        "skills": ["news"],
    },
    "utility": {
        "zh": "🧭 辅助工具",
        "en": "🧭 Utility Tools",
        "skills": ["guidance", "QA_source_index", "make_plan"],
    },
}


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
        include_skills: bool = True,
        core_skills: list[str] | None = None,
    ):
        """Initialize prompt builder.

        Args:
            working_dir: Directory containing markdown configuration files
            enabled_files: List of filenames to load (if None, uses default order)
            heartbeat_enabled: Whether heartbeat is enabled, affects AGENTS.md content
            language: Language code used to select the memory prompt.
            memory_manager: Memory manager instance for generating memory prompts.
            include_skills: Whether to inject dynamic skills section into prompt.
            core_skills: List of core skill names.
        """
        self.working_dir = working_dir
        self.enabled_files = enabled_files
        self.heartbeat_enabled = heartbeat_enabled
        self.language = language
        self.memory_manager = memory_manager
        self.include_skills = include_skills
        self.core_skills = core_skills or PromptConfig.DEFAULT_CORE_SKILLS
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

    def _discover_skills(self) -> list[dict]:
        """Discover and parse built-in skills from the skills directory.

        Scans the agent/skills/ directory for SKILL.md files with frontmatter,
        extracts name, emoji, and description.

        Returns:
            List of skill dicts with 'name', 'emoji', 'desc' keys.
        """
        # Find the skills directory relative to this module
        module_dir = Path(__file__).parent
        skills_dir = module_dir / "skills"

        if not skills_dir.exists():
            return []

        skills = []
        lang_suffix = "-zh" if self.language.startswith("zh") else "-en"

        for skill_folder in sorted(skills_dir.iterdir()):
            if not skill_folder.is_dir():
                continue
            if not skill_folder.name.endswith(lang_suffix):
                continue

            skill_name = skill_folder.name[: -len(lang_suffix)]
            skill_md = skill_folder / "SKILL.md"

            if not skill_md.exists():
                continue

            try:
                content = skill_md.read_text(encoding="utf-8")
                if not content.startswith("---"):
                    continue

                parts = content.split("---", 2)
                if len(parts) < 3:
                    continue

                fm = yaml.safe_load(parts[1])
                if not fm:
                    continue

                desc = fm.get("description", "")
                if not desc:
                    continue

                emoji = ""
                meta = fm.get("metadata", {}) or {}
                qp = meta.get("coapis", {}) or {}
                emoji = qp.get("emoji", "")

                skills.append(
                    {"name": skill_name, "emoji": emoji, "desc": desc}
                )
            except Exception as e:
                logger.debug("Failed to parse skill %s: %s", skill_folder.name, e)

        return skills

    def _build_skills_section(self, skills: list[dict]) -> str:
        """Build a categorized skills section for the system prompt.

        Core skills (high-frequency) are shown with full descriptions.
        Other skills are shown as a brief list to save tokens.

        Args:
            skills: List of skill dicts from _discover_skills()

        Returns:
            Formatted markdown section string.
        """
        if not skills:
            return ""

        # Build name->skill mapping
        skill_map = {s["name"]: s for s in skills}

        # Separate core skills from others
        core_skill_list = [
            skill_map[name]
            for name in self.core_skills
            if name in skill_map
        ]
        other_skills = [
            s for s in skills if s["name"] not in self.core_skills
        ]

        # Group by category
        lang_key = "zh" if self.language.startswith("zh") else "en"
        lines = [
            "# 内置技能" if lang_key == "zh" else "# Built-in Skills",
            "",
        ]

        # Core skills - full descriptions by category
        if core_skill_list:
            for cat_key, cat_info in SKILL_CATEGORIES.items():
                cat_label = cat_info[lang_key]
                cat_core_skills = [
                    s for s in core_skill_list
                    if s["name"] in cat_info["skills"]
                ]

                if not cat_core_skills:
                    continue

                lines.append(f"## {cat_label}")
                lines.append("")
                for s in cat_core_skills:
                    emoji_prefix = f"{s['emoji']} " if s['emoji'] else ""
                    lines.append(f"- {emoji_prefix}**{s['name']}**: {s['desc']}")
                lines.append("")

        # Other skills - brief list
        if other_skills:
            if lang_key == "zh":
                lines.append("## 其他可用技能")
                lines.append("")
                lines.append("以下技能按需加载（需要时读取 SKILL.md）：")
                lines.append("")
            else:
                lines.append("## Additional Skills")
                lines.append("")
                lines.append(
                    "Load on demand (read SKILL.md when needed):"
                )
                lines.append("")

            # Group other skills by category
            for cat_key, cat_info in SKILL_CATEGORIES.items():
                cat_label = cat_info[lang_key]
                cat_other_skills = [
                    skill_map[name]
                    for name in cat_info["skills"]
                    if name in skill_map
                    and name not in self.core_skills
                ]

                if not cat_other_skills:
                    continue

                skill_names = ", ".join([s["name"] for s in cat_other_skills])
                lines.append(f"- **{cat_label}**: {skill_names}")

            lines.append("")
            lines.append(PromptConfig.BRIEF_SKILL_HINT)
            lines.append("")

        # Add platform capabilities section (精简版 - 避免与平台身份重复)
        if self.language.startswith("zh"):
            lines.append("## 平台核心能力")
            lines.append("")
            lines.append("- **智能体自进化**: 经验提取→知识流动→全局晋升")
            lines.append("- **多租户隔离**: 4级角色 + 数据权限隔离")
            lines.append("- **上下文压缩**: 4层策略，零LLM成本")
            lines.append("- **企业功能**: 监控/SSO/技能市场/审计")
            lines.append("")
        else:
            lines.append("## Platform Capabilities")
            lines.append("")
            lines.append("- **Agent Evolution**: Experience→knowledge→promotion")
            lines.append("- **Multi-tenant**: 4-tier RBAC + isolation")
            lines.append("- **Context Compression**: 4-tier, zero LLM cost")
            lines.append("- **Enterprise**: Monitoring/SSO/Skills/Audit")
            lines.append("")

        return "\n".join(lines)

    def _build_identity_section(self) -> str:
        """Build the platform identity introduction section."""
        if self.language.startswith("zh"):
            return """## 平台身份

你是 **CoApis** 平台的智能助手。
核心能力：多智能体协作、自进化、多租户隔离、企业级功能、内置技能、上下文压缩、权限控制。
当用户询问"你是谁"、"你的能力"等问题时，基于以上信息回答。不要虚构不存在的功能。"""
        else:
            return """## Platform Identity

You are an intelligent assistant on the **CoApis** platform.
Core capabilities: Multi-Agent, Self-Evolution, Multi-tenant, Enterprise features, Built-in Skills, Context Compression, Permission Control.
When users ask "who are you" or "what can you do", answer based on the above. Do not fabricate non-existent capabilities."""

    def build(self) -> str:
        """Build the system prompt from markdown files.

        All files are optional. If no files can be loaded, returns the default prompt.

        Returns:
            Constructed system prompt string
        """
        # Inject platform identity as the first section
        identity_section = self._build_identity_section()
        self.prompt_parts.append(identity_section)

        # Determine which files to load
        if self.trim_mode:
            # Trim mode: only load PROFILE.md (skip AGENTS.md, SOUL.md)
            files_to_load = ["PROFILE.md"]
        else:
            files_to_load = (
                PromptConfig.DEFAULT_FILES
                if self.enabled_files is None
                else self.enabled_files
            )

        # Load all files (all are optional)
        for filename in files_to_load:
            self._load_file(filename)

        # Inject dynamic skills section
        if self.include_skills:
            skills = self._discover_skills()
            if skills:
                skills_section = self._build_skills_section(skills)
                if skills_section:
                    self.prompt_parts.append(skills_section)
                    logger.debug(
                        "Injected %d skills into system prompt",
                        len(skills),
                    )

        if not self.prompt_parts:
            logger.warning("No content loaded from working directory")
            return DEFAULT_SYS_PROMPT

        # Join all parts with double newlines
        final_prompt = "\n\n".join(self.prompt_parts)

        # Add language instruction to ensure LLM responds in user's language
        if self.language.startswith("zh"):
            final_prompt += (
                "\n\n## 语言要求\n"
                "请始终使用中文回复用户。包括思考过程、分析内容和最终回答，"
                "都必须使用中文。除非用户明确要求使用其他语言。"
            )
        elif self.language.startswith("en"):
            final_prompt += (
                "\n\n## Language Requirement\n"
                "Always respond in English. This includes your thinking process, "
                "analysis, and final answer. Only use another language when the "
                "user explicitly requests it."
            )

        logger.debug(
            "System prompt built from %d file(s), total length: %d chars",
            self.loaded_count,
            len(final_prompt),
        )

        return final_prompt


def build_system_prompt_from_working_dir(
    working_dir: Path | None = None,
    enabled_files: list[str] | None = None,
    agent_id: str | None = None,
    heartbeat_enabled: bool = False,
    language: str = "zh",
    memory_manager: BaseMemoryManager | None = None,
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

    builder = PromptBuilder(
        working_dir=working_dir,
        enabled_files=enabled_files,
        heartbeat_enabled=heartbeat_enabled,
        language=language,
        memory_manager=memory_manager,
    )
    prompt = builder.build()

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
            "4. 完成后删除 BOOTSTRAP.md。\n"
            "\n"
            "如果用户希望跳过，直接回答下面的问题即可。\n"
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
        "4. Delete BOOTSTRAP.md when done.\n"
        "\n"
        "If the user wants to skip, answer their "
        "question directly instead.\n"
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


__all__ = [
    "build_system_prompt_from_working_dir",
    "build_bootstrap_guidance",
    "build_multimodal_hint",
    "format_multimodal_hint",
    "get_active_model_supports_multimodal",
    "get_active_model_multimodal_raw",
    "PromptBuilder",
    "PromptConfig",
    "DEFAULT_SYS_PROMPT",
    "SYS_PROMPT",  # Backward compatibility
]
