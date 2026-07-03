# -*- coding: utf-8 -*-
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

"""CoApis Agent - Main agent implementation.

This module provides the main CoApisAgent class built on ReActAgent,
with integrated tools, skills, and memory management.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, List, Literal, Optional, Type, TYPE_CHECKING

from agentscope.agent import ReActAgent
from agentscope.agent._react_agent import _MemoryMark
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg
from agentscope.tool import Toolkit
from anyio import ClosedResourceError
from pydantic import BaseModel

from ..app.mcp import HttpStatefulClient, StdIOStatefulClient
from .command_handler import CommandHandler
from .hooks import BootstrapHook
from .model_factory import create_model_and_formatter
from .prompt import (
    build_multimodal_hint,
    build_system_prompt_from_working_dir,
    get_active_model_supports_multimodal,
)
from .skills_manager import (
    apply_skill_config_env_overrides,
    ensure_skills_initialized,
    get_workspace_skills_dir,
    resolve_effective_skills,
)
from .tool_guard_mixin import ToolGuardMixin
from ..security.skill_scanner import scan_skill_directory, SkillScanError
from .utils.usage_tracker import record_tool_call, record_skill_trigger
from .utils.trigger_tracker import get_trigger_tracker, TriggerTracker
from .utils.tool_result_cache import get_cache, is_idempotent
# Tool functions are now accessed via the registry system (get_registered_tools())
# Direct imports are no longer needed — the framework auto-discovers tools.
from .utils import process_file_and_media_blocks_in_message
from ..constant import (
    MEDIA_UNSUPPORTED_PLACEHOLDER,
    WORKING_DIR,
)
from ..providers.model_capability_cache import get_capability_cache

if TYPE_CHECKING:
    from ..agents.memory import BaseMemoryManager
    from ..agents.context import BaseContextManager
    from ..config.config import AgentProfileConfig
    from .context import AgentContext

logger = logging.getLogger(__name__)

# Valid namesake strategies for tool registration
NamesakeStrategy = Literal["override", "skip", "raise", "rename"]


def _wrap_tool_for_fault_tolerance(func, tool_name: str):
    """Wrap a tool function for fault tolerance.

    1. Convert dict returns → ToolResponse (agentscope requirement)
    2. Catch exceptions → return error ToolResponse instead of crashing
    """
    import inspect as _inspect
    from agentscope.tool import ToolResponse as _TR
    from agentscope.message import TextBlock as _TB

    def _dict_to_tool_response(d: dict) -> _TR:
        """Convert a dict to a ToolResponse."""
        if "error" in d:
            text = f"[Tool Error] {d['error']}"
        elif "content" in d and isinstance(d["content"], str):
            text = d["content"]
        else:
            text = str(d)
        return _TR(content=[_TB(type="text", text=text)])

    def _error_tool_response(tool_name: str, exc: Exception) -> _TR:
        """Create an error ToolResponse from an exception."""
        text = f"[Tool Error] {tool_name} failed: {type(exc).__name__}: {str(exc)[:500]}"
        return _TR(content=[_TB(type="text", text=text)])

    if _inspect.iscoroutinefunction(func):
        async def _async_wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                if isinstance(result, dict):
                    return _dict_to_tool_response(result)
                return result
            except Exception as e:
                logger.warning("Tool %s failed: %s", tool_name, e, exc_info=True)
                return _error_tool_response(tool_name, e)
        _async_wrapper.__name__ = getattr(func, '__name__', tool_name)
        _async_wrapper.__doc__ = getattr(func, '__doc__', '')
        # Preserve original_func for agentscope introspection
        _async_wrapper.original_func = getattr(func, 'original_func', func)
        return _async_wrapper
    else:
        def _sync_wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                if isinstance(result, dict):
                    return _dict_to_tool_response(result)
                return result
            except Exception as e:
                logger.warning("Tool %s failed: %s", tool_name, e, exc_info=True)
                return _error_tool_response(tool_name, e)
        _sync_wrapper.__name__ = getattr(func, '__name__', tool_name)
        _sync_wrapper.__doc__ = getattr(func, '__doc__', '')
        _sync_wrapper.original_func = getattr(func, 'original_func', func)
        return _sync_wrapper


class CoApisAgent(ToolGuardMixin, ReActAgent):
    """CoApis Agent with integrated tools, skills, and memory management.

    This agent extends ReActAgent with:
    - Built-in tools (shell, file operations, browser, etc.)
    - Dynamic skill loading from working directory
    - Memory management with auto-compaction
    - Bootstrap guidance for first-time setup
    - System command handling (/compact, /new, etc.)
    - Tool-guard security interception (via ToolGuardMixin)

    MRO note
    ~~~~~~~~
    ``ToolGuardMixin`` overrides ``_acting`` and ``_reasoning`` via
    Python's MRO: CoApisAgent → ToolGuardMixin → ReActAgent.  If you
    add a ``_acting`` or ``_reasoning`` override in this class, you
    **must** call ``super()._acting(...)`` / ``super()._reasoning(...)``
    so the guard interception remains active.
    """

    def __init__(
        self,
        agent_config: "AgentProfileConfig",
        env_context: Optional[str] = None,
        mcp_clients: Optional[List[Any]] = None,
        memory_manager: BaseMemoryManager | None = None,
        context_manager: BaseContextManager | None = None,
        request_context: Optional[dict[str, str]] = None,
        namesake_strategy: NamesakeStrategy = "skip",
        workspace_dir: Path | None = None,
        task_tracker: Any | None = None,
        plan_notebook: Any | None = None,
    ):
        """Initialize CoApisAgent.

        Args:
            agent_config: Agent profile configuration containing all settings
                including running config (max_iters, max_input_length,
                memory_compact_threshold, etc.) and language setting.
            env_context: Optional environment context to prepend to
                system prompt
            mcp_clients: Optional list of MCP clients for tool
                integration
            memory_manager: Optional memory manager instance. Pass ``None``
                to disable the memory manager entirely.
            context_manager: Optional context manager instance
            request_context: Optional request context with session_id,
                user_id, channel, agent_id
            namesake_strategy: Strategy to handle namesake tool functions.
                Options: "override", "skip", "raise", "rename"
                (default: "skip")
            workspace_dir: Workspace directory for reading prompt files
                (if None, uses global WORKING_DIR)
        """
        # Framework requires super().__init__() before any self.xxx assignment.
        # Call it first with a minimal placeholder, then overwrite everything.
        from agentscope.model import OpenAIChatModel
        super().__init__(
            name="Friday",
            model=None,
            sys_prompt="",
            toolkit=None,
            memory=InMemoryMemory(),
            formatter=None,
            max_iters=15,
        )

        # Now safe to set all attributes
        self._agent_config = agent_config
        self._env_context = env_context
        self._request_context = dict(request_context or {})
        self._mcp_clients = mcp_clients or []
        self._namesake_strategy = namesake_strategy
        self._workspace_dir = workspace_dir
        self._task_tracker = task_tracker
        self.plan_notebook = plan_notebook  # Connect PlanNotebook to agent

        # Extract configuration from agent_config
        running_config = agent_config.running
        self._language = agent_config.language

        # ── Auto-detect scene from first user message ──
        if not getattr(self._agent_config, "scene", None):
            user_msg = self._request_context.get("first_message", "")
            if user_msg:
                from .tools.scene_classifier import classify_scene
                detected = classify_scene(user_msg)
                if detected:
                    self._agent_config.scene = detected
                    logger.info("Auto-detected scene: %s", detected)

        # Initialize toolkit with built-in tools
        toolkit = self._create_toolkit(namesake_strategy=namesake_strategy)

        # Load and register skills
        self._register_skills(toolkit)

        # Initialize memory_manager and context_manager for use
        # in _build_sys_prompt
        self.memory_manager = memory_manager
        self.context_manager = context_manager

        # Build system prompt
        sys_prompt = self._build_sys_prompt()

        # Create model and formatter using factory method
        model, formatter = create_model_and_formatter(agent_id=agent_config.id)
        model_info = (
            f"{agent_config.active_model.provider_id}/"
            f"{agent_config.active_model.model}"
            if agent_config.active_model
            else "global-fallback"
        )
        logger.info(
            f"Agent '{agent_config.id}' initialized with model: "
            f"{model_info} (class: {model.__class__.__name__})",
        )

        # Now set the real values on the parent (overwriting placeholders)
        self.model = model
        self._sys_prompt = sys_prompt  # property getter reads from _sys_prompt
        self.toolkit = toolkit
        self.formatter = formatter
        self.max_iters = running_config.max_iters

        # ── ToolSchemaRouter: dynamic schema trimming ──
        from .utils.tool_schema_router import ToolSchemaRouter
        self._schema_router = ToolSchemaRouter()
        self._enable_full_schemas = False  # Toggle via /tools full
        # Wrap toolkit.get_json_schemas to apply per-turn filtering
        _original_get_schemas = self.toolkit.get_json_schemas

        def _filtered_get_schemas():
            all_schemas = _original_get_schemas()
            if self._enable_full_schemas:
                return all_schemas
            try:
                # Get recent messages for intent detection
                recent = []
                if hasattr(self, "memory"):
                    # memory is async, but get_json_schemas is sync
                    # Use last cached messages if available
                    if hasattr(self, "_recent_tool_msgs"):
                        recent = self._recent_tool_msgs
                return self._schema_router.route(all_schemas, recent)
            except Exception:
                return all_schemas

        self.toolkit.get_json_schemas = _filtered_get_schemas

        # Configure agentscope built-in memory compression
        self.compression_config = self._build_compression_config(
            running_config, model
        )

        # Register memory tools provided by the memory manager
        if self.memory_manager is not None:
            memory_tools = self.memory_manager.list_memory_tools()
            for tool_fn in memory_tools:
                self.toolkit.register_tool_function(
                    tool_fn,
                    namesake_strategy=self._namesake_strategy,
                )
            logger.debug(
                "Registered memory tools: %s",
                [fn.__name__ for fn in memory_tools],
            )

        # Configure context manager memory if available
        if self.context_manager is not None:
            self.memory: "AgentContext" = (
                self.context_manager.get_agent_context()
            )
            logger.debug("Context manager configured")

        # Initialize Session Execution Manager (SEM) if configured
        self._session_execution_manager = None
        if running_config.session_execution is not None:
            try:
                from .session_execution import (
                    SessionExecutionConfig,
                    SessionExecutionManager,
                )
                sem_config = SessionExecutionConfig(
                    **running_config.session_execution
                )
                if sem_config.enabled:
                    self._session_execution_manager = (
                        SessionExecutionManager(sem_config)
                    )
                    logger.info(
                        "Session Execution Manager enabled for agent '%s'",
                        agent_config.id,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to initialize Session Execution Manager: %s. "
                    "SEM will be disabled.",
                    e,
                )

        # Setup command handler
        self.command_handler = CommandHandler(
            agent_name=self.name,
            memory=self.memory,
            memory_manager=self.memory_manager,
            context_manager=self.context_manager,
        )

        # Register hooks
        self._register_hooks()

    def _build_compression_config(
        self, running_config, model
    ) -> "CompressionConfig | None":
        """Build agentscope CompressionConfig from agent's running config.

        Uses the light_context_config.context_compact_config settings to
        configure agentscope's built-in memory compression mechanism.

        Args:
            running_config: The agent's running configuration.
            model: The LLM model instance for compression.

        Returns:
            CompressionConfig if compression is enabled, None otherwise.
        """
        try:
            from agentscope.agent._react_agent import (
                _ReActAgentWithToolkit as ReActAgentWithToolkit,
            )

            CompressionConfig = ReActAgentWithToolkit.CompressionConfig

            lcc = running_config.light_context_config
            ccc = lcc.context_compact_config

            if not ccc.enabled:
                logger.debug("Context compaction disabled in config")
                return None

            # Calculate threshold in tokens
            trigger_threshold = int(
                running_config.max_input_length * ccc.compact_threshold_ratio
            )

            # Use CharTokenCounter for lightweight estimation
            from agentscope.token import CharTokenCounter

            token_counter = CharTokenCounter()

            # CharTokenCounter counts characters, so multiply threshold
            # by avg chars per token (~4) to align with token-based config
            # Use the configured divisor for accurate conversion
            divisor = lcc.token_count_estimate_divisor
            char_threshold = trigger_threshold * divisor

            config = CompressionConfig(
                enable=True,
                agent_token_counter=token_counter,
                trigger_threshold=char_threshold,
                keep_recent=3,
            )
            logger.info(
                f"Memory compression enabled: trigger_threshold="
                f"{trigger_threshold} tokens (~{char_threshold} chars), "
                f"keep_recent=3"
            )
            return config
        except Exception as e:
            logger.warning(
                f"Failed to build compression config: {e}. "
                "Memory compression disabled."
            )
            return None

    def _create_toolkit(
        self,
        namesake_strategy: NamesakeStrategy = "skip",
    ) -> Toolkit:
        """Create and populate toolkit with built-in tools.

        Args:
            namesake_strategy: Strategy to handle namesake tool functions.
                Options: "override", "skip", "raise", "rename"
                (default: "skip")

        Returns:
            Configured toolkit instance
        """
        toolkit = Toolkit()

        # Check which tools are enabled from agent config
        enabled_tools = {}
        async_execution_tools = {}
        try:
            if hasattr(self._agent_config, "tools") and hasattr(
                self._agent_config.tools,
                "builtin_tools",
            ):
                builtin_tools = self._agent_config.tools.builtin_tools
                enabled_tools = {
                    name: tool.enabled for name, tool in builtin_tools.items()
                }
                # Only execute_shell_command supports async_execution
                async_execution_tools = {
                    "execute_shell_command": builtin_tools.get(
                        "execute_shell_command",
                    ).async_execution
                    if "execute_shell_command" in builtin_tools
                    else False,
                }
        except Exception as e:
            logger.warning(
                f"Failed to load agent tools config: {e}, "
                "all tools will be disabled",
            )

        # ── Discover tools from plugin registry ──
        from .tools.registry import get_registered_tools
        registered = get_registered_tools()
        tool_functions = {name: reg.func for name, reg in registered.items()}

        # ── Scene-based dynamic injection ──
        # core tools are always injected; others require matching scene
        CORE_SCENE = "core"
        agent_scene = getattr(self._agent_config, "scene", None) or self._request_context.get("scene", None)
        # If agent_scene is set, only inject core + matching scene tools
        # If not set, inject all tools (backward compatible fallback)
        scene_filter = agent_scene is not None

        # Register only enabled tools
        for tool_name, tool_func in tool_functions.items():
            # If tool not in config, enable by default (backward compatibility)
            if not enabled_tools.get(tool_name, True):
                logger.debug("Skipped disabled tool: %s", tool_name)
                continue

            # Scene-based filtering: skip non-core tools that don't match scene
            if scene_filter:
                reg = registered.get(tool_name)
                tool_scene = getattr(reg, "scene", "general") if reg else "general"
                if tool_scene != CORE_SCENE and tool_scene != agent_scene:
                    logger.debug("Skipped scene-mismatched tool: %s (scene=%s, agent_scene=%s)", tool_name, tool_scene, agent_scene)
                    continue

            # Get async_execution setting (default to False for backward
            # compatibility)
            async_exec = async_execution_tools.get(tool_name, False)

            # Wrap tool function for fault tolerance:
            # 1. Convert dict returns to ToolResponse (agentscope requirement)
            # 2. Catch exceptions and return error ToolResponse instead of crashing
            wrapped_func = _wrap_tool_for_fault_tolerance(tool_func, tool_name)

            toolkit.register_tool_function(
                wrapped_func,
                namesake_strategy=namesake_strategy,
                async_execution=async_exec,
            )
            logger.debug(
                "Registered tool: %s (async_execution=%s)",
                tool_name,
                async_exec,
            )

        # Auto-register background task management tools if any *enabled*
        # tool has async_execution set
        has_async_tools = any(
            async_execution_tools.get(name, False)
            for name in tool_functions
            if enabled_tools.get(name, True)
        )
        if has_async_tools:
            try:
                toolkit.register_tool_function(
                    toolkit.view_task,
                    namesake_strategy=namesake_strategy,
                )
                toolkit.register_tool_function(
                    toolkit.wait_task,
                    namesake_strategy=namesake_strategy,
                )
                toolkit.register_tool_function(
                    toolkit.cancel_task,
                    namesake_strategy=namesake_strategy,
                )
                logger.debug(
                    "Registered background task management tools "
                    "(view_task, wait_task, cancel_task)",
                )
            except Exception as e:
                logger.warning(
                    f"Failed to register task management tools: {e}",
                )

        return toolkit

    def _register_skills(self, toolkit: Toolkit) -> None:
        """Load and register skills from workspace directory.

        Two-tier loading strategy:
        - always_load=True skills: registered immediately (core)
        - always_load=False skills: deferred until user intent match (on-demand)

        Also builds a SkillSelector index for fast keyword-based skill selection.

        Args:
            toolkit: Toolkit to register skills to
        """
        workspace_dir = self._workspace_dir or WORKING_DIR

        ensure_skills_initialized(workspace_dir)

        request_context = getattr(self, "_request_context", {})
        channel_name = request_context.get("channel", "console")

        effective_skills = resolve_effective_skills(
            workspace_dir,
            channel_name,
        )

        working_skills_dir = get_workspace_skills_dir(Path(workspace_dir))

        # Store on-demand skills for lazy loading
        # Value: (skill_dir, trigger_keywords)
        self._on_demand_skills: dict[str, tuple[Path, list[str]]] = {}
        self._core_skills: dict[str, Path] = {}
        self._toolkit = toolkit

        # Skill pool for fallback when skill not in workspace
        from .skills_manager import get_skill_pool_dir
        skill_pool_dir = get_skill_pool_dir()

        # ── Collect all skill metadata for SkillSelector index ──
        skill_meta_list: list[dict] = []

        for skill_name in effective_skills:
            skill_dir = working_skills_dir / skill_name
            # Fallback: if not in workspace, try skill pool
            if not skill_dir.exists():
                pool_dir = skill_pool_dir / skill_name
                if pool_dir.exists():
                    skill_dir = pool_dir
                else:
                    continue

            # Read always_load from SKILL.md frontmatter (new field)
            always_load = self._get_skill_always_load(skill_dir)
            # Fallback: read legacy priority field
            priority = self._get_skill_priority(skill_dir)
            # Use clean trigger_keywords for SkillSelector index
            # (NOT _get_skill_triggers which mixes in patterns/hints)
            trigger_keywords = self._get_skill_trigger_keywords(skill_dir)
            # Keep legacy triggers for _load_on_demand_skills Phase 2 fallback
            legacy_triggers = self._get_skill_triggers(skill_dir, getattr(self, '_workspace_dir', None))
            desc = self._get_skill_summary(skill_dir)

            # Build metadata for SkillSelector (clean keywords only)
            skill_meta_list.append({
                "name": skill_name,
                "dir": str(skill_dir),
                "trigger_keywords": trigger_keywords,
                "always_load": always_load,
                "description": desc,
            })

            # Classify: always_load → core, otherwise → on-demand
            if always_load or priority == "core":
                self._core_skills[skill_name] = skill_dir
                try:
                    toolkit.register_agent_skill(str(skill_dir))
                    logger.debug("Registered core skill: %s", skill_name)
                except Exception as e:
                    logger.error(
                        "Failed to register skill '%s': %s",
                        skill_name, e,
                    )
            else:
                self._on_demand_skills[skill_name] = (skill_dir, legacy_triggers)
                # Register summary-only entry so LLM knows the skill exists
                self._register_skill_summary(toolkit, skill_dir)
                logger.debug(
                    "Deferred on-demand skill: %s (triggers=%s, pool=%s)",
                    skill_name, triggers, skill_dir == (skill_pool_dir / skill_name),
                )

        # ── Build SkillSelector index for fast keyword matching ──
        try:
            from .utils.skill_selector import SkillSelector
            self._skill_selector = SkillSelector({
                "enable_llm_fallback": False,  # LLM handled by _load_on_demand_skills
                "max_selected_skills": 15,
                "min_keyword_length": 2,
            })
            self._skill_selector.build_index(skill_meta_list)
            logger.info(
                "SkillSelector index built: %d keywords, %d always-load",
                len(self._skill_selector.keyword_index),
                len(self._skill_selector.always_load_skills),
            )
        except Exception as e:
            logger.warning("Failed to build SkillSelector index: %s", e)
            self._skill_selector = None

        logger.info(
            "Skills loaded: %d core (always_load), %d on-demand (deferred)",
            len(self._core_skills), len(self._on_demand_skills),
        )

    @staticmethod
    def _get_skill_summary(skill_dir: Path, max_len: int = 120) -> str:
        """Extract short summary from SKILL.md for prompt preview."""
        try:
            md_file = skill_dir / "SKILL.md"
            if not md_file.exists():
                return ""
            content = md_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    import yaml
                    meta = yaml.safe_load(parts[1]) or {}
                    desc = str(meta.get("description", ""))
                    if len(desc) > max_len:
                        # Cut at sentence boundary if possible
                        cut = desc[:max_len]
                        for sep in ("。", ".", "！", "!", "；", ";", "，", ","):
                            idx = cut.rfind(sep)
                            if idx > max_len // 2:
                                cut = cut[:idx + 1]
                                break
                        else:
                            cut = cut.rstrip() + "…"
                        return cut
                    return desc
        except Exception:
            pass
        return ""

    @staticmethod
    def _register_skill_summary(toolkit, skill_dir: Path) -> None:
        """Register an on-demand skill with summary-only description.

        Inserts a lightweight entry into toolkit.skills so the LLM sees
        the skill in its prompt without loading the full SKILL.md body.
        """
        try:
            md_file = skill_dir / "SKILL.md"
            if not md_file.exists():
                return
            import yaml as _yaml
            content = md_file.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return
            parts = content.split("---", 2)
            if len(parts) < 3:
                return
            meta = _yaml.safe_load(parts[1]) or {}
            name = meta.get("name", skill_dir.name)
            if name in toolkit.skills:
                return
            summary = CoApisAgent._get_skill_summary(skill_dir)
            if not summary:
                return
            toolkit.skills[name] = {
                "name": name,
                "description": summary,
                "dir": str(skill_dir),
            }
            logger.debug("Registered summary for on-demand skill: %s", name)
        except Exception as e:
            logger.debug("Failed to register skill summary for '%s': %s", skill_dir.name, e)

    @staticmethod
    def _get_skill_priority(skill_dir: Path) -> str:
        """Read priority field from SKILL.md frontmatter."""
        try:
            md_file = skill_dir / "SKILL.md"
            if not md_file.exists():
                return "core"
            content = md_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    import yaml
                    meta = yaml.safe_load(parts[1]) or {}
                    coapis = meta.get("metadata", {}).get("coapis", {})
                    return coapis.get("priority", "core")
        except Exception:
            pass
        return "core"

    @staticmethod
    def _get_skill_always_load(skill_dir: Path) -> bool:
        """Read always_load field from SKILL.md frontmatter."""
        try:
            md_file = skill_dir / "SKILL.md"
            if not md_file.exists():
                return False
            content = md_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    import yaml
                    meta = yaml.safe_load(parts[1]) or {}
                    return bool(meta.get("always_load", False))
        except Exception:
            pass
        return False

    @staticmethod
    def _get_skill_trigger_keywords(skill_dir: Path) -> list[str]:
        """Read top-level trigger_keywords from SKILL.md frontmatter.

        Unlike _get_skill_triggers() which mixes keywords + patterns + hints,
        this only reads the clean trigger_keywords list used by SkillSelector.
        """
        try:
            md_file = skill_dir / "SKILL.md"
            if not md_file.exists():
                return []
            content = md_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    import yaml
                    meta = yaml.safe_load(parts[1]) or {}
                    kw = meta.get("trigger_keywords", [])
                    if isinstance(kw, list):
                        return [str(k) for k in kw if k]
        except Exception:
            pass
        return []

    @staticmethod
    def _get_skill_intent_hints(skill_dir: Path) -> list[str]:
        """Extract intent_hints from SKILL.md frontmatter triggers block."""
        try:
            md_file = skill_dir / "SKILL.md"
            if not md_file.exists():
                return []
            content = md_file.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return []
            parts = content.split("---", 2)
            if len(parts) < 3:
                return []
            import yaml
            meta = yaml.safe_load(parts[1]) or {}
            triggers_block = meta.get("triggers", {})
            if isinstance(triggers_block, dict):
                hints = triggers_block.get("intent_hints", [])
                return [str(h) for h in hints if h]
        except Exception:
            pass
        return []

    @staticmethod
    def _get_skill_triggers(skill_dir: Path, workspace_dir: Path | None = None) -> list[str]:
        """Extract trigger keywords from SKILL.md frontmatter + user overrides.

        Priority:
        1. Top-level `triggers` field in frontmatter (keywords + patterns)
        2. metadata.coapis.triggers (legacy explicit list)
        3. Keywords extracted from description field
        4. User-level overrides from workspaces/{user}/skill_triggers/{skill_name}.json
           - added_keywords: additional triggers
           - removed_keywords: suppressed triggers
           - refined_keywords: replace all triggers entirely
        """
        try:
            md_file = skill_dir / "SKILL.md"
            if not md_file.exists():
                return []
            content = md_file.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return []
            parts = content.split("---", 2)
            if len(parts) < 3:
                return []
            import yaml
            meta = yaml.safe_load(parts[1]) or {}
            coapis = meta.get("metadata", {}).get("coapis", {})

            # 1. Top-level triggers field (new format with keywords/patterns/intent_hints)
            triggers_block = meta.get("triggers", {})
            if isinstance(triggers_block, dict):
                keywords = triggers_block.get("keywords", [])
                patterns = triggers_block.get("patterns", [])
                intent_hints = triggers_block.get("intent_hints", [])
                base_triggers = []
                if keywords:
                    base_triggers.extend([str(t).lower() for t in keywords if t])
                if patterns:
                    # patterns 是正则表达式，转换为简单关键词匹配
                    import re
                    for pat in patterns:
                        try:
                            # 提取正则中的字面量部分
                            literals = re.findall(r'[\u4e00-\u9fff\w]+', str(pat))
                            base_triggers.extend([l.lower() for l in literals if len(l) >= 2])
                        except Exception:
                            pass
                if intent_hints:
                    # intent_hints 也作为触发词（用于 LLM 分类辅助）
                    base_triggers.extend([str(h).lower() for h in intent_hints if h])
                if base_triggers:
                    # 2. Fallback: metadata.coapis.triggers
                    pass
                else:
                    explicit = coapis.get("triggers", [])
                    if explicit:
                        base_triggers = [t.lower() for t in explicit]
                    else:
                        # 3. Extract from description
                        desc = str(meta.get("description", ""))
                        base_triggers = CoApisAgent._extract_keywords_from_description(desc)
            else:
                # triggers 不是 dict，尝试旧格式
                explicit = coapis.get("triggers", [])
                if explicit:
                    base_triggers = [t.lower() for t in explicit]
                else:
                    # 3. Extract from description
                    desc = str(meta.get("description", ""))
                    base_triggers = CoApisAgent._extract_keywords_from_description(desc)

            # 3. User-level overrides (if workspace_dir provided)
            if workspace_dir:
                skill_name = skill_dir.name
                override_path = (
                    workspace_dir / "skill_triggers" / f"{skill_name}.json"
                )
                # Security: validate override_path is within expected directory
                expected_dir = (workspace_dir / "skill_triggers").resolve()
                if override_path.resolve().parent != expected_dir:
                    return base_triggers  # Path traversal attempt
                if override_path.exists():
                    try:
                        import json as _json
                        overrides = _json.loads(override_path.read_text(encoding="utf-8"))
                        # Security: limit override size to prevent abuse
                        if isinstance(overrides, dict) and len(str(overrides)) > 4096:
                            return base_triggers
                        # Security: block overly generic single-char triggers
                        _GENERIC_WORDS = {
                            "a", "i", "do", "go", "it", "is", "be", "ok",
                            "run", "get", "set", "put", "use", "try", "fix",
                            "help", "make", "edit", "show", "list", "open",
                        }
                        refined = overrides.get("refined_keywords", [])
                        if refined:
                            refined = [t.lower() for t in refined
                                       if isinstance(t, str) and len(t) >= 2
                                       and t.lower() not in _GENERIC_WORDS]
                            if refined:
                                return refined
                        added = [t.lower() for t in overrides.get("added_keywords", [])
                                 if isinstance(t, str) and len(t) >= 2
                                 and t.lower() not in _GENERIC_WORDS]
                        removed = {t.lower() for t in overrides.get("removed_keywords", [])
                                   if isinstance(t, str)}
                        base_triggers = [t for t in base_triggers if t not in removed]
                        base_triggers.extend(k for k in added if k not in base_triggers)
                    except Exception:
                        pass  # Ignore corrupt override files

            # 4. 触发词效能过滤：低权重触发词自动降级
            try:
                from .utils.trigger_effectiveness import get_trigger_effectiveness
                eff_tracker = get_trigger_effectiveness()
                _skill_name = skill_dir.name
                base_triggers = eff_tracker.get_effective_triggers(
                    _skill_name, base_triggers, min_weight=0.2,
                )
            except Exception:
                pass

            return base_triggers
        except Exception:
            return []

    @staticmethod
    def _extract_keywords_from_description(description: str) -> list[str]:
        """Extract meaningful keywords from a skill description string.

        Strategy:
        - Split on punctuation/delimiters into phrases
        - For Chinese: also split on common sentence particles
        - Filter stop words, too-short, too-long tokens
        - Extract quoted phrases as high-priority keywords
        """
        import re
        # Common stop words to exclude
        stop_words = {
            # English
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "this", "that", "these", "those", "it", "its", "i", "me",
            "my", "we", "our", "you", "your", "he", "she", "they",
            "them", "their", "his", "her", "and", "or", "but", "not",
            "no", "nor", "so", "yet", "for", "at", "by", "from", "in",
            "into", "of", "on", "to", "with", "as", "if", "then",
            "than", "too", "very", "just", "about", "above", "after",
            "before", "between", "during", "through", "under", "again",
            "further", "once", "here", "there", "when", "where", "why",
            "how", "all", "each", "every", "both", "few", "more",
            "most", "other", "some", "such", "only", "own", "same",
            "use", "used", "using", "also", "any", "what", "which",
            "who", "whom", "new", "get", "set", "run", "see", "make",
            "skill", "tool", "file", "when", "need", "user",
            "se", "ser", "yo", "rl", "ls", "lsm", "rowser", "sually",
            # Chinese
            "的", "是", "在", "了", "和", "与", "或", "但", "当",
            "这", "那", "它", "你", "我", "他", "她", "们", "对",
            "从", "到", "用", "被", "将", "会", "能", "可", "要",
            "做", "有", "没", "不", "就", "都", "而", "及", "等",
            "如果", "因为", "所以", "可以", "需要", "使用", "通过",
            "进行", "提供", "支持", "包含", "包括", "以及", "或者",
            "一个", "这个", "那个", "时候", "用户", "功能", "本",
            "后", "前", "上", "下", "中", "里", "内", "外",
            "以", "于", "则", "其", "此", "该", "让", "把",
            "时", "地", "得", "着", "过", "来", "去", "说",
            "如", "已", "并", "更", "再", "又", "才", "只",
            "非", "未", "无", "每", "各", "某", "另", "其他",
            "请", "帮", "帮帮", "一下", "什么", "怎么", "哪些",
            "这些", "那些", "自己", "目前", "当前", "现在",
            "适用于", "用于", "使用此", "使用本",
        }

        # 1. Extract quoted phrases first (high-priority keywords)
        quoted = re.findall(r'[""\'`]([^""\'`]{2,})[""\'`]', description)
        seen = set()
        keywords = []
        for q in quoted:
            q = q.strip().lower()
            if q not in seen and q not in stop_words and 2 <= len(q) <= 20:
                seen.add(q)
                keywords.append(q)

        # 2. Remove quoted portions to avoid backtick splitting artifacts
        cleaned = re.sub(r'[""\'`][^""\'`]{2,}[""\'`]', ' ', description)

        # 3. Split description into tokens on delimiters
        #    Split on: comma, semicolon, colon, parens, brackets, pipe, slash, period, newline
        tokens = re.split(r'[,，、;；:：\.\。\!\！\?\？\(\)（）\[\]【】\|/\n\r]+', cleaned)

        for token in tokens:
            # Further split on spaces
            sub_tokens = token.split()
            for w in sub_tokens:
                # Use regex to remove leading/trailing punctuation (not word chars)
                w = re.sub(r'^[^\w]+|[^\w]+$', '', w).lower()
                if len(w) < 2 or len(w) > 20:
                    continue
                if w in stop_words or w in seen:
                    continue
                # Skip tokens that are mostly punctuation
                if len(re.sub(r'[^\w]', '', w)) < 2:
                    continue
                seen.add(w)
                keywords.append(w)

        return keywords[:15]  # Cap at 15 keywords

    def _scan_and_register_skill(
        self,
        skill_name: str,
        skill_dir: Path,
        trigger_method: str,
        matched_keywords: list[str],
        user_message: str,
        tracker: Any,
        ctx: dict[str, Any],
    ) -> bool:
        """Security-scan a skill, then register it if safe.

        Returns True if the skill was registered successfully, False otherwise.
        """
        # ── Security scan gate ──
        try:
            scan_result = scan_skill_directory(
                str(skill_dir),
                skill_name=skill_name,
            )
            if scan_result is not None and not scan_result.is_safe:
                logger.warning(
                    "Security scan blocked on-demand skill '%s': "
                    "%d finding(s), max severity=%s",
                    skill_name,
                    len(scan_result.findings),
                    scan_result.max_severity.value,
                )
                return False
        except SkillScanError as exc:
            logger.error(
                "Security scan rejected on-demand skill '%s': %s",
                skill_name,
                exc,
            )
            return False
        except Exception as exc:
            logger.warning(
                "Security scan of skill '%s' failed (proceeding with caution): %s",
                skill_name,
                exc,
            )

        # ── Register the skill ──
        self._toolkit.register_agent_skill(str(skill_dir))
        trigger_id = tracker.record_trigger_event(
            skill_name=skill_name,
            trigger_method=trigger_method,
            matched_keywords=matched_keywords,
            user_message=user_message,
            user=ctx.get("username", "unknown"),
            agent=ctx.get("agent_id", "default"),
        )
        try:
            record_skill_trigger(
                skill_name=skill_name,
                matched_keywords=matched_keywords,
                user=ctx.get("username", "unknown"),
                agent=ctx.get("agent_id", "default"),
            )
        except Exception:
            pass
        logger.info(
            "Loaded on-demand skill: %s (method=%s, trigger_id=%s)",
            skill_name, trigger_method, trigger_id,
        )
        return True

    def _load_on_demand_skills(self, user_message: str) -> None:
        """Load on-demand skills matching user intent.

        Classification strategy (hybrid):
        1. Try LLM intent classification first (natural language understanding)
        2. Fall back to keyword matching if LLM fails or unavailable
        3. Both methods can trigger skills independently

        All skills pass through security scanning before registration.
        Unsafe skills are blocked per the configured scan mode.

        Args:
            user_message: The user's input message for intent detection
        """
        if not hasattr(self, "_on_demand_skills") or not self._on_demand_skills:
            return

        ctx = getattr(self, "_request_context", None) or {}
        tracker = get_trigger_tracker()
        loaded = []

        # ── 详细触发日志 ──
        all_on_demand = list(self._on_demand_skills.keys())
        logger.info(
            "[TriggerDebug] Start on-demand skill analysis | msg=%s | available_skills=%s",
            user_message[:80], all_on_demand,
        )

        # ── Phase 1: LLM intent classification (async, best-effort) ──
        llm_matched_names = self._llm_classify_skills(user_message)
        logger.info(
            "[TriggerDebug] LLM classification result: matched=%s",
            llm_matched_names if llm_matched_names else "[]",
        )

        for skill_name in llm_matched_names:
            if skill_name not in self._on_demand_skills:
                logger.debug(
                    "[TriggerDebug] LLM matched '%s' but not in on-demand pool, skip",
                    skill_name,
                )
                continue
            skill_dir, keywords = self._on_demand_skills[skill_name]
            try:
                if self._scan_and_register_skill(
                    skill_name=skill_name,
                    skill_dir=skill_dir,
                    trigger_method="llm",
                    matched_keywords=["llm_classify"],
                    user_message=user_message,
                    tracker=tracker,
                    ctx=ctx,
                ):
                    loaded.append(skill_name)
                    del self._on_demand_skills[skill_name]
                    logger.info(
                        "[TriggerDebug] ✓ Loaded skill '%s' via LLM classification",
                        skill_name,
                    )
            except Exception as e:
                logger.error("Failed to load on-demand skill '%s': %s", skill_name, e)

        # ── Phase 2: Keyword matching via SkillSelector index (fast) ──
        # Use the inverted index built in _register_skills() for O(1) keyword lookup
        # instead of iterating all on-demand skills
        skill_selector = getattr(self, "_skill_selector", None)
        if skill_selector:
            # Use SkillSelector's fast keyword index
            selector_matched = skill_selector._keyword_match(user_message)
            for skill_name in selector_matched:
                if skill_name in loaded or skill_name not in self._on_demand_skills:
                    continue
                skill_dir, keywords = self._on_demand_skills[skill_name]
                # Find which keywords matched for logging
                msg_lower = user_message.lower()
                matched = [kw for kw in keywords if kw in msg_lower]
                try:
                    if self._scan_and_register_skill(
                        skill_name=skill_name,
                        skill_dir=skill_dir,
                        trigger_method="keyword",
                        matched_keywords=matched or ["selector_index"],
                        user_message=user_message,
                        tracker=tracker,
                        ctx=ctx,
                    ):
                        loaded.append(skill_name)
                        del self._on_demand_skills[skill_name]
                        logger.info(
                            "[TriggerDebug] ✓ Loaded skill '%s' via SkillSelector keyword match: %s",
                            skill_name, matched,
                        )
                except Exception as e:
                    logger.error("Failed to load on-demand skill '%s': %s", skill_name, e)
        else:
            # Fallback: original linear scan if SkillSelector not available
            msg_lower = user_message.lower()
            keyword_log = {}
            for skill_name, (skill_dir, keywords) in list(self._on_demand_skills.items()):
                if skill_name in loaded:
                    continue
                if not keywords:
                    keyword_log[skill_name] = {"triggers": [], "matched": [], "result": "no_triggers"}
                    continue
                matched = [kw for kw in keywords if kw in msg_lower]
                keyword_log[skill_name] = {
                    "triggers": keywords[:10],
                    "matched": matched,
                    "result": "matched" if matched else "no_match",
                }
                if matched:
                    try:
                        if self._scan_and_register_skill(
                            skill_name=skill_name,
                            skill_dir=skill_dir,
                            trigger_method="keyword",
                            matched_keywords=matched,
                            user_message=user_message,
                            tracker=tracker,
                            ctx=ctx,
                        ):
                            loaded.append(skill_name)
                            del self._on_demand_skills[skill_name]
                            logger.info(
                                "[TriggerDebug] ✓ Loaded skill '%s' via keyword match: %s",
                                skill_name, matched,
                            )
                    except Exception as e:
                        logger.error("Failed to load on-demand skill '%s': %s", skill_name, e)

            # 输出未匹配技能的详情
            not_loaded = {k: v for k, v in keyword_log.items() if v["result"] != "matched" and k not in loaded}
            if not_loaded:
                logger.info(
                    "[TriggerDebug] Not loaded skills detail: %s",
                    {k: v["result"] for k, v in not_loaded.items()},
                )

        if loaded:
            logger.info("[TriggerDebug] Final loaded %d on-demand skills: %s", len(loaded), loaded)
        else:
            logger.info("[TriggerDebug] No on-demand skills loaded for this message")

    def _llm_classify_skills(self, user_message: str) -> list[str]:
        """Try LLM-based intent classification. Returns matching skill names."""
        try:
            from .utils.intent_classifier import classify_intent_llm
            # Build skill summaries for the classifier, including intent_hints
            summaries = {}
            for name, (skill_dir, _kw) in getattr(self, "_on_demand_skills", {}).items():
                # 获取完整描述（不截断）
                summary = self._get_skill_summary(skill_dir, max_len=500)
                if not summary:
                    continue
                # 尝试读取 intent_hints
                intent_hints = self._get_skill_intent_hints(skill_dir)
                if intent_hints:
                    summaries[name] = f"{summary} ||| {', '.join(intent_hints)}"
                else:
                    summaries[name] = summary
            if not summaries:
                return []
            # Note: classify_intent_llm is async, but _load_on_demand_skills is sync.
            # Use asyncio.run in a thread-safe way for the lightweight call.
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                # We're already in an async context, create a task
                # But since this is called from reply() which is sync,
                # we need to handle differently
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, classify_intent_llm(user_message, summaries, timeout=3.0))
                    result = future.result(timeout=5.0)
            except RuntimeError:
                result = asyncio.run(classify_intent_llm(user_message, summaries, timeout=3.0))
            return result if result else []
        except Exception as e:
            logger.debug("LLM skill classification skipped: %s", e)
            return []

    # ── Global auto-assist: detect uncertainty, consult global knowledge ──

    # Uncertainty indicators (Chinese + English)
    _UNCERTAINTY_PATTERNS = [
        "不确定", "不知道", "不清楚", "无法确认", "没有相关信息",
        "抱歉", "遗憾", "未能找到", "无法回答", "没有找到",
        "i'm not sure", "i am not sure", "i don't know", "i cannot",
        "no information", "not sure", "cannot find", "unable to",
        "无法确定", "难以判断", "缺少信息", "信息不足",
    ]

    def _detect_uncertainty(self, response_text: str) -> bool:
        """Check if response indicates uncertainty / inability to answer."""
        if not response_text:
            return False
        text_lower = response_text.lower()
        # If response is very short, likely a genuine answer, skip
        if len(response_text) < 15:
            return False
        matches = sum(1 for p in self._UNCERTAINTY_PATTERNS if p in text_lower)
        # Need at least 2 indicators to be confident it's uncertain
        return matches >= 2

    def _query_global_memory(self, query: str) -> str:
        """Query global agent's MEMORY.md for relevant knowledge."""
        try:
            from ..constant import AGENTS_DIR
            global_mem = AGENTS_DIR / "default" / "MEMORY.md"
            if not global_mem.exists():
                return ""

            content = global_mem.read_text(encoding="utf-8").strip()
            if not content or len(content) < 20:
                return ""

            # Simple keyword-based relevance check
            import re as _re
            query_words = set(_re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', query.lower()))
            mem_words = set(_re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', content.lower()))
            if not query_words:
                return ""

            overlap = len(query_words & mem_words)
            if overlap < 2:
                return ""

            # Return relevant sections (split by ## headings)
            sections = content.split("\n## ")
            relevant = []
            for section in sections:
                if not section.strip():
                    continue
                section_lower = section.lower()
                if any(w in section_lower for w in query_words):
                    relevant.append(section.strip())

            if relevant:
                result = "\n\n".join(relevant[:3])  # Max 3 sections
                logger.info(
                    "[GlobalAssist] Found %d relevant sections (%d chars) for query: %s",
                    len(relevant), len(result), query[:50],
                )
                return result[:3000]  # Cap at 3000 chars
            return ""

        except Exception as e:
            logger.debug("[GlobalAssist] Failed to query global memory: %s", e)
            return ""

    async def _async_reme_search(self, query: str) -> list[str]:
        """Async memory search (file-based + LLM rerank).

        Called from reply() (async context) to pre-fetch relevant
        long-term memories before building the system prompt.

        Args:
            query: User query text for semantic search

        Returns:
            List of relevant text snippets (max 5)
        """
        if not self.memory_manager or not hasattr(self.memory_manager, 'memory_search'):
            return []

        try:
            from .memory.reme_parser import parse_reme_response

            result = await self.memory_manager.memory_search(
                query=query,
                max_results=5,
                min_score=0.1,
            )
            snippets = parse_reme_response(result)
            if snippets:
                logger.info(
                    "[MemorySearch] Retrieved %d memories for: %s",
                    len(snippets), query[:50],
                )
            return snippets[:5]
        except Exception as e:
            logger.debug("[MemorySearch] Search failed: %s", e)
            return []

    def _build_sys_prompt(self) -> str:
        """Build system prompt from working dir files and env context.

        Returns:
            Complete system prompt string
        """
        # Get agent_id from request_context
        agent_id = (
            self._request_context.get("agent_id")
            if self._request_context
            else None
        )

        # Check if heartbeat is enabled in agent config
        heartbeat_enabled = False
        if (
            hasattr(self._agent_config, "heartbeat")
            and self._agent_config.heartbeat is not None
        ):
            heartbeat_enabled = self._agent_config.heartbeat.enabled

        # Build base system prompt from structural files
        # (AGENTS.md, SOUL.md, PROFILE.md, HEARTBEAT.md)
        # MEMORY.md is handled separately by MemoryInjector below
        structural_files = [
            f for f in (
                self._agent_config.system_prompt_files
                or ["AGENTS.md", "SOUL.md", "PROFILE.md"]
            )
            if f != "MEMORY.md"
        ]

        # Resolve global workspace dirs for inheritance (config-driven)
        global_ws_dirs: list = []
        user_ws_dir = None
        try:
            from .global_agent_utils import get_template_agents
            # Skip inheritance for global agents (they ARE the source)
            is_global = getattr(self._agent_config, 'is_global', False)
            agent_ws = str(self._workspace_dir) if self._workspace_dir else ""
            if not is_global:
                for tpl_dir in get_template_agents():
                    if str(tpl_dir) not in agent_ws:
                        global_ws_dirs.append(tpl_dir)

                # Resolve user-level workspace dir
                # Sub-agent path: .../workspaces/{username}/agents/{agent_id}/
                # User root:      .../workspaces/{username}/
                if self._workspace_dir:
                    ws_path = Path(self._workspace_dir)
                    ws_str = str(ws_path)
                    if "/workspaces/" in ws_str:
                        if ws_path.parent.name == "agents":
                            # Sub-agent: .../workspaces/{username}/agents/{id}/ → .../workspaces/{username}/
                            user_ws_dir = ws_path.parent.parent
                        elif ws_path.name == "agents":
                            # At agents/ dir: .../workspaces/{username}/agents/ → .../workspaces/{username}/
                            user_ws_dir = ws_path.parent
                        else:
                            # At user root or under it: use as-is
                            user_ws_dir = ws_path
        except Exception:
            pass

        sys_prompt = build_system_prompt_from_working_dir(
            working_dir=self._workspace_dir,
            agent_id=agent_id,
            heartbeat_enabled=heartbeat_enabled,
            language=self._language,
            memory_manager=None,  # Don't let PromptBuilder handle memory
            enabled_files=structural_files,
            global_workspace_dirs=global_ws_dirs if global_ws_dirs else None,
            user_workspace_dir=user_ws_dir,
        )

        # ── MemoryInjector: two-level memory injection ──
        # User-level (workspaces/{username}/): base preferences, habits
        # Agent-level (workspace_dir): agent-specific knowledge, skills
        try:
            from ..foundation.memory_injector import MemoryInjector
            from ..foundation.memory_quota import MemoryQuota

            injector = MemoryInjector(MemoryQuota())

            # --- User-level memory (Level 1: base) ---
            user_memory = ""
            user_profile = ""
            # user_ws_dir already resolved above (workspaces/{username}/)
            if user_ws_dir and user_ws_dir != self._workspace_dir:
                user_mem_file = Path(user_ws_dir) / "MEMORY.md"
                if user_mem_file.exists():
                    umem = user_mem_file.read_text(encoding="utf-8").strip()
                    if umem:
                        user_memory = umem

                user_profile_file = Path(user_ws_dir) / "USER.md"
                if user_profile_file.exists():
                    uprof = user_profile_file.read_text(encoding="utf-8").strip()
                    if uprof:
                        user_profile = uprof

            # --- Agent-level memory (Level 2: supplement) ---
            agent_memory = ""
            agent_mem_file = self._workspace_dir / "MEMORY.md"
            if agent_mem_file.exists():
                amem = agent_mem_file.read_text(encoding="utf-8").strip()
                if amem:
                    agent_memory = amem

            # Build core memory: user-level first, then agent-level
            core_memory = ""
            if user_memory:
                core_memory += f"## 用户记忆\n{user_memory}\n\n"
            if user_profile:
                core_memory += f"## 用户画像\n{user_profile}\n\n"
            if agent_memory:
                core_memory += f"## 智能体记忆\n{agent_memory}"

            core_memory = core_memory.strip()

            # Long-term memory: from pre-fetched semantic search or fallback
            long_term_memories: list[str] = []
            if self.memory_manager is not None:
                # Use pre-fetched semantic memories from reply() async context
                pre_fetched = getattr(self, '_pre_fetched_memories', [])
                if pre_fetched:
                    long_term_memories.extend(pre_fetched)
                    logger.info(
                        "[MemoryInjector] Using %d pre-fetched semantic memories",
                        len(pre_fetched),
                    )
                else:
                    # Fallback: static guidance prompt
                    try:
                        mem_prompt = self.memory_manager.get_memory_prompt(
                            self._language or "zh",
                        )
                        if mem_prompt and len(mem_prompt) > 20:
                            long_term_memories.append(mem_prompt[:2000])
                    except Exception:
                        pass

            # ── 读取已批准的进化经验 ──
            try:
                import json as _json
                _exp_file = (
                    Path(os.environ.get("COAPIS_DATA_DIR", "/data"))
                    / "evolution" / "experiences" / "approved.jsonl"
                )
                if _exp_file.exists():
                    _experiences = []
                    for _line in _exp_file.read_text(encoding="utf-8").splitlines():
                        _line = _line.strip()
                        if not _line:
                            continue
                        try:
                            _exp = _json.loads(_line)
                            _exp_agent = _exp.get("source_agent", "")
                            if _exp_agent and agent_id and _exp_agent != agent_id:
                                continue
                            _experiences.append(_exp)
                        except _json.JSONDecodeError:
                            continue

                    _experiences.sort(key=lambda x: x.get("confidence", 0), reverse=True)
                    _top_exps = _experiences[:15]

                    if _top_exps:
                        _exp_text = "以下是从过往对话中提炼的经验教训，在回答时参考：\n"
                        for _i, _exp in enumerate(_top_exps, 1):
                            _title = _exp.get("title", "")
                            _content = _exp.get("content", "")
                            _etype = _exp.get("experience_type", "")
                            if _title or _content:
                                _exp_text += f"\n{_i}. [{_etype}] {_title}\n   {_content}\n"
                        long_term_memories.append(_exp_text)
                        logger.info(
                            "[Evolution] Injected %d approved experiences into context",
                            len(_top_exps),
                        )
            except Exception as _exp_err:
                logger.debug("[Evolution] Failed to load experiences: %s", _exp_err)

            # ── 读取全局基础层经验 ──
            try:
                import json as _json2
                _found_file = (
                    Path(os.environ.get("COAPIS_DATA_DIR", "/data"))
                    / "cross_evolution" / "foundation.json"
                )
                if _found_file.exists():
                    _found_data = _json2.loads(
                        _found_file.read_text(encoding="utf-8")
                    )
                    if isinstance(_found_data, list) and _found_data:
                        _found_data.sort(key=lambda x: x.get("confidence", 0), reverse=True)
                        _top_found = _found_data[:10]
                        if _top_found:
                            _found_text = "以下是跨智能体共享的核心经验：\n"
                            for _i, _exp in enumerate(_top_found, 1):
                                _title = _exp.get("title", "")
                                _content = _exp.get("content", "")
                                if _title or _content:
                                    _found_text += f"\n{_i}. {_title}\n   {_content}\n"
                            long_term_memories.append(_found_text)
                            logger.info(
                                "[Evolution] Injected %d foundation experiences",
                                len(_top_found),
                            )
            except Exception as _found_err:
                logger.debug("[Evolution] Failed to load foundation: %s", _found_err)

            # 从 request_context 获取 role（用于记忆配额控制）
            _role = self._request_context.get("role", "")

            injection = injector.build_context(
                core_memory=core_memory,
                long_term_memories=long_term_memories,
                short_term_memory="",
                query="",
                role=_role,
            )

            # Append memory section to system prompt
            memory_section = injection.to_prompt()
            if memory_section:
                sys_prompt = sys_prompt + "\n\n" + memory_section

            logger.info(
                "[MemoryInjector] user_memory=%d chars, user_profile=%d chars, "
                "agent_memory=%d chars, long_term=%d entries",
                len(user_memory), len(user_profile),
                len(agent_memory), len(long_term_memories),
            )

        except Exception as mem_err:
            logger.debug(
                "MemoryInjector failed, falling back to file load: %s",
                mem_err,
            )
            # Fallback: load MEMORY.md directly
            mem_file = self._workspace_dir / "MEMORY.md"
            if mem_file.exists():
                mem_content = mem_file.read_text(encoding="utf-8").strip()
                if mem_content:
                    sys_prompt += f"\n\n# MEMORY.md\n\n{mem_content}"
        # ── End MemoryInjector ──

        logger.debug("System prompt:\n%s...", sys_prompt[:200])

        # Inject multimodal capability awareness
        multimodal_hint = build_multimodal_hint()
        if multimodal_hint:
            sys_prompt = sys_prompt + "\n\n" + multimodal_hint

        if self._env_context is not None:
            sys_prompt = sys_prompt + "\n\n" + self._env_context

        # Inject agent skill prompt — tells LLM which skills are available
        try:
            agent_skill_prompt = self.toolkit.get_agent_skill_prompt()
            if agent_skill_prompt:
                sys_prompt = sys_prompt + "\n\n" + agent_skill_prompt
        except Exception as e:
            logger.warning("Failed to inject skill prompt: %s", e)

        return sys_prompt

    def _register_hooks(self) -> None:
        """Register pre-reasoning and pre-acting hooks."""
        # Bootstrap hook - checks BOOTSTRAP.md on first interaction
        # Use workspace_dir if available, else fallback to WORKING_DIR
        working_dir = (
            self._workspace_dir if self._workspace_dir else WORKING_DIR
        )
        bootstrap_hook = BootstrapHook(
            working_dir=working_dir,
            language=self._language,
        )
        self.register_instance_hook(
            hook_type="pre_reasoning",
            hook_name="bootstrap_hook",
            hook=bootstrap_hook.__call__,
        )
        logger.debug("Registered bootstrap hook")

        # Context manager hooks - delegate compaction / tool-result pruning
        # to the context manager's lifecycle methods
        if self.context_manager is not None:
            self.register_instance_hook(
                hook_type="pre_reply",
                hook_name="context_pre_reply",
                hook=self.context_manager.pre_reply,
            )
            self.register_instance_hook(
                hook_type="pre_reasoning",
                hook_name="context_pre_reasoning",
                hook=self.context_manager.pre_reasoning,
            )
            self.register_instance_hook(
                hook_type="post_acting",
                hook_name="context_post_acting",
                hook=self.context_manager.post_acting,
            )
            self.register_instance_hook(
                hook_type="post_reply",
                hook_name="context_post_reply",
                hook=self.context_manager.post_reply,
            )
            logger.debug("Registered context manager hooks")

        # Session Execution Manager hooks
        if self._session_execution_manager is not None:
            sem = self._session_execution_manager

            async def _sem_pre_reasoning(_self, *args, **kwargs):
                """SEM pre-reasoning hook: check and intervene."""
                try:
                    session_id = self._request_context.get(
                        "session_id", "default"
                    )
                    sem.record_iteration(session_id)
                    intervention = sem.check_and_intervene(session_id)
                    if intervention is not None:
                        logger.warning(
                            "SEM intervention: session=%s, level=%s",
                            session_id,
                            intervention.value,
                        )
                except Exception as e:
                    logger.error("SEM pre_reasoning hook error: %s", e)

            async def _sem_post_acting(_self, *args, **kwargs):
                """SEM post-acting hook: record tool call."""
                try:
                    session_id = self._request_context.get(
                        "session_id", "default"
                    )
                    # Extract tool call info from kwargs if available
                    tool_call = kwargs.get("tool_call", {})
                    tool_name = str(tool_call.get("name", ""))
                    tool_input = tool_call.get("input", {})
                    tool_output = kwargs.get("tool_result", "")
                    sem.record_tool_call(
                        session_id, tool_name, tool_input, tool_output
                    )
                except Exception as e:
                    logger.error("SEM post_acting hook error: %s", e)

            self.register_instance_hook(
                hook_type="pre_reasoning",
                hook_name="sem_pre_reasoning",
                hook=_sem_pre_reasoning,
            )
            self.register_instance_hook(
                hook_type="post_acting",
                hook_name="sem_post_acting",
                hook=_sem_post_acting,
            )
            logger.debug("Registered SEM hooks")

    def rebuild_sys_prompt(self) -> None:
        """Rebuild and replace the system prompt.

        Useful after load_session_state to ensure the prompt reflects
        the latest AGENTS.md / SOUL.md / PROFILE.md on disk.

        Updates both self._sys_prompt and the first system-role
        message stored in self.memory.content (if one exists).
        """
        self._sys_prompt = self._build_sys_prompt()

        if self.memory is None:
            logger.warning(
                "rebuild_sys_prompt: self.memory is None, "
                "skipping in-memory system prompt update.",
            )
            return

        for msg, _marks in self.memory.content:
            if msg.role == "system":
                msg.content = self.sys_prompt
            break

    async def register_mcp_clients(
        self,
        namesake_strategy: NamesakeStrategy = "skip",
    ) -> None:
        """Register MCP clients on this agent's toolkit after construction.

        Args:
            namesake_strategy: Strategy to handle namesake tool functions.
                Options: "override", "skip", "raise", "rename"
                (default: "skip")
        """
        for i, client in enumerate(self._mcp_clients):
            client_name = getattr(client, "name", repr(client))
            try:
                await self.toolkit.register_mcp_client(
                    client,
                    namesake_strategy=namesake_strategy,
                    execution_timeout=client.timeout,
                )
            except (ClosedResourceError, asyncio.CancelledError) as error:
                if self._should_propagate_cancelled_error(error):
                    raise
                logger.warning(
                    "MCP client '%s' session interrupted while listing tools; "
                    "trying recovery",
                    client_name,
                )
                recovered_client = await self._recover_mcp_client(client)
                if recovered_client is not None:
                    self._mcp_clients[i] = recovered_client
                    try:
                        await self.toolkit.register_mcp_client(
                            recovered_client,
                            namesake_strategy=namesake_strategy,
                            exeution_timeout=client.timeout,
                        )
                        continue
                    except asyncio.CancelledError as recover_error:
                        if self._should_propagate_cancelled_error(
                            recover_error,
                        ):
                            raise
                        logger.warning(
                            "MCP client '%s' registration cancelled after "
                            "recovery, skipping",
                            client_name,
                        )
                    except Exception as e:  # pylint: disable=broad-except
                        logger.warning(
                            "MCP client '%s' still unavailable after "
                            "recovery, skipping: %s",
                            client_name,
                            e,
                        )
                else:
                    logger.warning(
                        "MCP client '%s' recovery failed, skipping",
                        client_name,
                    )
            except Exception as e:  # pylint: disable=broad-except
                logger.warning(
                    "Failed to register MCP client '%s', skipping: %s",
                    client_name,
                    e,
                    exc_info=True,
                )

    async def _recover_mcp_client(self, client: Any) -> Any | None:
        """Recover MCP client from broken session and return healthy client."""
        if await self._reconnect_mcp_client(client):
            return client

        rebuilt_client = self._rebuild_mcp_client(client)
        if rebuilt_client is None:
            return None

        if await self._reconnect_mcp_client(rebuilt_client):
            return self._reuse_shared_client_reference(
                original_client=client,
                rebuilt_client=rebuilt_client,
            )

        return None

    @staticmethod
    def _reuse_shared_client_reference(
        original_client: Any,
        rebuilt_client: Any,
    ) -> Any:
        """Keep manager-shared client reference stable after rebuild."""
        original_dict = getattr(original_client, "__dict__", None)
        rebuilt_dict = getattr(rebuilt_client, "__dict__", None)
        if isinstance(original_dict, dict) and isinstance(rebuilt_dict, dict):
            original_dict.update(rebuilt_dict)
            return original_client
        return rebuilt_client

    @staticmethod
    def _should_propagate_cancelled_error(error: BaseException) -> bool:
        """Only swallow MCP-internal cancellations, not task cancellation."""
        if not isinstance(error, asyncio.CancelledError):
            return False

        task = asyncio.current_task()
        if task is None:
            return False

        cancelling = getattr(task, "cancelling", None)
        if callable(cancelling):
            return cancelling() > 0

        # Python < 3.11: Task.cancelling() is unavailable.
        # Fall back to propagating CancelledError to avoid swallowing
        # genuine task cancellations when we cannot inspect the state.
        return True

    @staticmethod
    async def _reconnect_mcp_client(
        client: Any,
        timeout: float = 60.0,
    ) -> bool:
        """Best-effort reconnect for stateful MCP clients."""
        close_fn = getattr(client, "close", None)
        if callable(close_fn):
            try:
                await close_fn()
            except asyncio.CancelledError:  # pylint: disable=try-except-raise
                raise
            except Exception:  # pylint: disable=broad-except
                pass

        connect_fn = getattr(client, "connect", None)
        if not callable(connect_fn):
            return False

        try:
            await asyncio.wait_for(connect_fn(), timeout=timeout)
            return True
        except asyncio.CancelledError:  # pylint: disable=try-except-raise
            raise
        except asyncio.TimeoutError:
            return False
        except Exception:  # pylint: disable=broad-except
            return False

    @staticmethod
    def _rebuild_mcp_client(client: Any) -> Any | None:
        """Rebuild a fresh MCP client instance from stored config metadata."""
        rebuild_info = getattr(client, "_coapis_rebuild_info", None)
        if not isinstance(rebuild_info, dict):
            return None

        transport = rebuild_info.get("transport")
        name = rebuild_info.get("name")

        try:
            if transport == "stdio":
                rebuilt_client = StdIOStatefulClient(
                    name=name,
                    command=rebuild_info.get("command"),
                    args=rebuild_info.get("args", []),
                    env=rebuild_info.get("env", {}),
                    cwd=rebuild_info.get("cwd"),
                )
                setattr(rebuilt_client, "_coapis_rebuild_info", rebuild_info)
                return rebuilt_client

            raw_headers = rebuild_info.get("headers") or {}
            headers = (
                {k: os.path.expandvars(v) for k, v in raw_headers.items()}
                if raw_headers
                else None
            )
            rebuilt_client = HttpStatefulClient(
                name=name,
                transport=transport,
                url=rebuild_info.get("url"),
                headers=headers,
            )
            setattr(rebuilt_client, "_coapis_rebuild_info", rebuild_info)
            return rebuilt_client
        except Exception:  # pylint: disable=broad-except
            return None

    # ------------------------------------------------------------------
    # Media-block fallback: strip unsupported media blocks (image, audio,
    # video) from memory and retry when the model rejects them.
    # ------------------------------------------------------------------

    _MEDIA_BLOCK_TYPES = {"image", "audio", "video"}

    # ------------------------------------------------------------------
    # Plan gate: block non-create_plan tools when /plan gate is active
    # ------------------------------------------------------------------

    _PLAN_TOOLS_WITH_JSON_ARGS = frozenset(
        {
            "create_plan",
            "revise_current_plan",
        },
    )
    _PLAN_JSON_KEYS = ("subtask", "subtasks")

    @staticmethod
    def _fix_stringified_json_args(tool_call) -> None:
        """Parse JSON-string arguments that models sometimes produce for
        nested objects (e.g. ``subtask``).  Modifies *tool_call* in place."""
        import json as _json

        inp = tool_call.get("input")
        if not isinstance(inp, dict):
            return
        for key in CoApisAgent._PLAN_JSON_KEYS:
            val = inp.get(key)
            if isinstance(val, str):
                try:
                    inp[key] = _json.loads(val)
                except (ValueError, TypeError):
                    pass
            elif isinstance(val, list):
                for i, item in enumerate(val):
                    if isinstance(item, str):
                        try:
                            val[i] = _json.loads(item)
                        except (ValueError, TypeError):
                            pass

    async def _acting(self, tool_call) -> dict | None:
        """Check plan tool gate before delegating to ToolGuardMixin."""
        import time as _time
        from ..plan.hints import check_plan_tool_gate

        tool_name = str(tool_call.get("name", ""))

        # ── SEM check: intervene if needed ──
        if self._session_execution_manager is not None:
            session_id = self._request_context.get("session_id", "default")
            intervention = self._session_execution_manager.check_and_intervene(
                session_id
            )
            if intervention is not None:
                from agentscope.message import TextBlock
                block_msg = (
                    f"[SEM 干预] 会话执行已达到 {intervention.value} 级别。"
                    f"请基于已有信息直接给出结论，不要再调用工具。"
                )
                return {
                    "content": [TextBlock(type="text", text=block_msg)],
                    "metadata": {"tool_call_id": getattr(tool_call, "id", "")},
                }

        if tool_name in self._PLAN_TOOLS_WITH_JSON_ARGS:
            self._fix_stringified_json_args(tool_call)

        nb = getattr(self, "plan_notebook", None)
        if nb is not None:
            err = check_plan_tool_gate(nb, tool_name)
            if err:
                from agentscope.message import ToolResultBlock

                tool_res_msg = Msg(
                    "system",
                    [
                        ToolResultBlock(
                            type="tool_result",
                            id=tool_call["id"],
                            name=tool_name,
                            output=[{"type": "text", "text": err}],
                        ),
                    ],
                    "system",
                )
                await self.print(tool_res_msg, True)
                await self.memory.add(tool_res_msg)
                return None

        # ── Loop-level protection: track consecutive same-tool calls ──
        if not hasattr(self, "_recent_tool_calls"):
            self._recent_tool_calls: list[str] = []
            self._consecutive_same_tool: int = 0
            self._last_acting_tool: str = ""

        # Track consecutive same-tool calls
        if tool_name == self._last_acting_tool:
            self._consecutive_same_tool += 1
        else:
            self._consecutive_same_tool = 1
            self._last_acting_tool = tool_name

        # Check if same tool called 3+ times consecutively
        if self._consecutive_same_tool >= 3:
            logger.warning(
                "Loop-level protection: %s called %d times consecutively",
                tool_name, self._consecutive_same_tool,
            )
            from agentscope.message import TextBlock
            block_msg = (
                f"[循环保护] {tool_name} 已连续调用 {self._consecutive_same_tool} 次，"
                f"已触发循环保护。请基于已有信息直接给出结论。"
            )
            return {
                "content": [TextBlock(type="text", text=block_msg)],
                "metadata": {"tool_call_id": getattr(tool_call, "id", "")},
            }

        # ── Cache check for idempotent tools ──
        _cache = get_cache() if is_idempotent(tool_name) else None
        _tool_params = tool_call.get("input")
        if _cache is not None:
            _cached = _cache.get(tool_name, _tool_params)
            if _cached is not None:
                logger.debug("Cache hit for %s", tool_name)
                return _cached

        # ── Usage tracking: record tool call timing ──
        _t0 = _time.monotonic()
        _success = True
        _error_msg = None
        _output_len = 0
        try:
            result = await super()._acting(tool_call)
            # Estimate output length from result
            if result is not None:
                try:
                    _output_len = len(str(result))
                except Exception:
                    pass
            # Store in cache for idempotent tools
            if _cache is not None and result is not None:
                try:
                    _cache.put(tool_name, _tool_params, result)
                except Exception:
                    pass
            # Invalidate read_file cache on file mutations
            if tool_name in ("write_file", "edit_file"):
                try:
                    get_cache().invalidate("read_file")
                    get_cache().invalidate("grep_search")
                    get_cache().invalidate("glob_search")
                    logger.debug("Cache invalidated after %s", tool_name)
                except Exception:
                    pass
            return result
        except Exception as exc:
            _success = False
            _error_msg = str(exc)[:500]
            logger.warning(
                "Tool %s execution failed: %s — returning error to agent instead of crashing",
                tool_name, _error_msg,
            )
            # Return error message as tool result instead of crashing the stream.
            # The agent will see the error and can decide what to do next.
            from agentscope.message import ToolResultBlock
            error_msg = Msg(
                "system",
                [ToolResultBlock(
                    type="tool_result",
                    id=tool_call.get("id", ""),
                    name=tool_name,
                    output=[{"type": "text", "text": f"[Tool Error] {tool_name}: {_error_msg}"}],
                )],
                "system",
            )
            await self.print(error_msg, True)
            await self.memory.add(error_msg)
            return None
        finally:
            try:
                _ctx = getattr(self, "_request_context", None) or {}
                _dur_ms = (_time.monotonic() - _t0) * 1000
                record_tool_call(
                    tool_name=tool_name,
                    params=tool_call.get("input"),
                    duration_ms=_dur_ms,
                    success=_success,
                    error=_error_msg,
                    user=_ctx.get("username", "unknown"),
                    agent=_ctx.get("agent_id", "default"),
                    output_len=_output_len,
                )
                # ── Trigger outcome: record execution result for active triggers ──
                try:
                    tracker = get_trigger_tracker()
                    active = tracker.get_active_trigger_ids()
                    if active:
                        for _sk, _tid in active.items():
                            tracker.record_trigger_outcome(
                                trigger_id=_tid,
                                tools_used=[tool_name],
                                tool_success=_success,
                                duration_ms=_dur_ms,
                            )
                except Exception:
                    pass
            except Exception:
                pass  # Never let tracking break tool execution

        if nb is not None and tool_name == "revise_current_plan":
            nb._plan_just_mutated = True  # pylint: disable=protected-access

        return result

    _AUTO_CONTINUE_MAX_EXTRA = 2
    _AUTO_CONTINUE_TAIL_CHARS = 600

    _AUTO_CONTINUE_HINT_EN = (
        "<system-hint>"
        "Your previous assistant turn had text only (no tool calls). "
        "Use the trailing excerpt in <previous-assistant-tail> (if present) "
        "plus the conversation to decide in this **reasoning** step: if the "
        "user's task still needs tools, emit tool_use now; if it is fully "
        "done, reply with a short text only (no tools). "
        "Do not stop with plans or code fences alone when tools are still "
        "needed."
        "</system-hint>"
    )
    _AUTO_CONTINUE_HINT_ZH = (
        "<system-hint>"
        "上轮助手仅文字、未调工具。请结合上下文与 <previous-assistant-tail> "
        "（若有）在本轮推理中判断：仍需执行则立刻 tool；已完结则简短收尾。"
        "需要操作时勿只输出计划或代码块。"
        "</system-hint>"
    )

    def _auto_continue_system_hint(self) -> str:
        """Pick hint by agent language (zh vs others)."""
        raw_lang = getattr(self._agent_config, "language", None)
        lang = (raw_lang or "").strip().lower()
        if lang == "zh":
            return self._AUTO_CONTINUE_HINT_ZH
        return self._AUTO_CONTINUE_HINT_EN

    @staticmethod
    def _auto_continue_tail_context(msg: Msg, max_chars: int) -> str:
        """Assistant text suffix for hint (fixed cut, not sentence NLP)."""
        raw = msg.get_text_content() if msg is not None else ""
        text = (raw or "").strip()
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return text[-max_chars:].lstrip()

    async def _auto_continue_if_text_only(
        self,
        msg: Msg,
        tool_choice: Literal["auto", "none", "required"] | None,
    ) -> Msg:
        """Nudge the model when it returns text-only mid-task.

        Injects a language-matched hint (with a trailing excerpt of the
        assistant text for self-review) and runs up to
        ``_AUTO_CONTINUE_MAX_EXTRA`` extra ``_reasoning`` passes until a
        tool_use appears or the cap is
        hit.  Uses the original ``tool_choice`` unchanged (no switching).
        If an extra pass still returns text-only, keep the prior response to
        avoid repeated duplicated answers.
        """
        from ..plan.hints import should_skip_auto_continue

        nb = getattr(self, "plan_notebook", None)
        if should_skip_auto_continue(nb):
            return msg

        running = self._agent_config.running
        if not running.auto_continue_on_text_only:
            return msg
        if msg is None or msg.has_content_blocks("tool_use"):
            return msg

        extra = 0
        while extra < self._AUTO_CONTINUE_MAX_EXTRA:
            if msg.has_content_blocks("tool_use"):
                break
            extra += 1
            tail = self._auto_continue_tail_context(
                msg,
                self._AUTO_CONTINUE_TAIL_CHARS,
            )
            hint_body = self._auto_continue_system_hint()
            if tail:
                hint_body += (
                    "\n\n<previous-assistant-tail>\n"
                    f"{tail}\n"
                    "</previous-assistant-tail>"
                )
            logger.info(
                "Auto-continue: text-only (%d/%d); hint + _reasoning "
                "tool_choice=%r",
                extra,
                self._AUTO_CONTINUE_MAX_EXTRA,
                tool_choice,
            )
            hint_msg = Msg("user", hint_body, "user")
            await self.memory.add(hint_msg, marks=_MemoryMark.HINT)
            try:
                next_msg = await super()._reasoning(tool_choice=tool_choice)
            except Exception:
                logger.warning(
                    "Auto-continue extra _reasoning failed; "
                    "keeping prior response",
                    exc_info=True,
                )
                break
            if next_msg.has_content_blocks("tool_use"):
                msg = next_msg
                continue
            logger.info(
                "Auto-continue extra _reasoning still text-only; "
                "keeping prior response",
            )
            break

        return msg

    def _get_model_key(self) -> str | None:
        """Return the capability-cache key for the active model."""
        model = getattr(self, "model", None)
        return getattr(model, "model_key", None)

    def _model_rejects_media(self) -> bool:
        """Check the capability cache for a learned ``rejects_media`` flag."""
        key = self._get_model_key()
        if key is None:
            return False
        return get_capability_cache().get(key, "rejects_media", False)

    def _proactive_strip_media_blocks(self) -> int:
        """Proactively strip media blocks from memory before model call.

        Only called when the active model does not support multimodal.
        Returns the number of blocks stripped.
        """
        return self._strip_media_blocks_from_memory()

    def _uses_request_time_media_normalization(self) -> bool:
        """Return True when request-time normalization can handle media."""
        return getattr(self, "formatter", None) is not None

    def _set_formatter_media_strip(self, enabled: bool) -> None:
        """Toggle request-time media stripping on the active formatter."""
        formatter = getattr(self, "formatter", None)
        if formatter is None:
            return
        setattr(formatter, "_coapis_force_strip_media", enabled)

    # pylint: disable=too-many-branches
    async def _reasoning(
        self,
        tool_choice: Literal["auto", "none", "required"] | None = None,
    ) -> Msg:
        """Override reasoning with proactive media filtering.

        1. Proactive layer: if the model does not support
           multimodal **or** the capability cache records a previous
           ``rejects_media`` finding, strip media blocks *before* calling.
        2. Passive layer: if the model call still fails with a
           bad-request / media error, strip remaining blocks and retry,
           then record the finding in the capability cache.
        3. If the model IS marked as multimodal but still errors on
           media, log a warning about possibly inaccurate capability flag.

        Calls ``super()._reasoning`` to keep the ToolGuardMixin
        interception active.
        """
        # --- Cache recent messages for ToolSchemaRouter ---
        try:
            memory_msgs = await self.memory.get_memory()
            self._recent_tool_msgs = [
                {"content": m.get("content", ""), "role": m.get("role", "")}
                for m in memory_msgs[-5:]
            ]
        except Exception:
            self._recent_tool_msgs = []

        # --- Thinking budget control ---
        try:
            from .utils.thinking_budget import ThinkingBudgetManager
            if not hasattr(self, "_thinking_budget_mgr"):
                self._thinking_budget_mgr = ThinkingBudgetManager()
            # Classify from the last user message
            user_query = ""
            if self._recent_tool_msgs:
                for m in reversed(self._recent_tool_msgs):
                    if m.get("role") == "user":
                        content = m.get("content", "")
                        if isinstance(content, str):
                            user_query = content
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    user_query += block.get("text", "")
                                elif hasattr(block, "text"):
                                    user_query += block.text
                        break
            complexity = self._thinking_budget_mgr.classify(
                user_query, self._recent_tool_msgs,
            )
            budget_kwargs = self._thinking_budget_mgr.apply_budget(complexity)
            # Set reasoning_effort on the underlying model for this turn
            _original_effort = getattr(self.model, "reasoning_effort", None)
            if "reasoning_effort" in budget_kwargs:
                self.model.reasoning_effort = budget_kwargs["reasoning_effort"]
            self._last_complexity = complexity
        except Exception:
            complexity = "normal"
            _original_effort = None

        # --- Proactive filtering layer ---
        should_strip = (
            not get_active_model_supports_multimodal()
            or self._model_rejects_media()
        )
        if should_strip:
            if self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(True)
                logger.debug(
                    "Formatter will strip media from copied messages "
                    "before reasoning.",
                )
            else:
                n = self._proactive_strip_media_blocks()
                if n > 0:
                    logger.warning(
                        "Proactively stripped %d media block(s) - "
                        "model does not support multimodal.",
                        n,
                    )

        # --- Passive fallback layer (existing logic) ---
        try:
            msg = await super()._reasoning(tool_choice=tool_choice)
        except Exception as e:
            if not self._is_bad_request_or_media_error(e):
                raise

            model_key = self._get_model_key()

            if self._uses_request_time_media_normalization():
                if get_active_model_supports_multimodal():
                    logger.warning(
                        "Model marked multimodal but "
                        "rejected media. "
                        "Capability flag may be wrong.",
                    )
                self._set_formatter_media_strip(True)
                try:
                    logger.warning(
                        "_reasoning failed (%s). "
                        "Retrying with request-time media stripping.",
                        e,
                    )
                    msg = await super()._reasoning(tool_choice=tool_choice)
                    if model_key:
                        get_capability_cache().learn(
                            model_key,
                            "rejects_media",
                            True,
                        )
                    return msg
                finally:
                    self._set_formatter_media_strip(False)

            n_stripped = self._strip_media_blocks_from_memory()
            if n_stripped == 0:
                raise

            if get_active_model_supports_multimodal():
                logger.warning(
                    "Model marked multimodal but "
                    "rejected media. "
                    "Capability flag may be wrong.",
                )

            logger.warning(
                "_reasoning failed (%s). "
                "Stripped %d media block(s) from memory, retrying.",
                e,
                n_stripped,
            )
            msg = await super()._reasoning(tool_choice=tool_choice)
            if model_key:
                get_capability_cache().learn(
                    model_key,
                    "rejects_media",
                    True,
                )
        finally:
            if should_strip and self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(False)
            # Restore original reasoning_effort after this turn
            try:
                if _original_effort is not None:
                    self.model.reasoning_effort = _original_effort
                elif hasattr(self.model, "reasoning_effort"):
                    self.model.reasoning_effort = None
            except Exception:
                pass

        return await self._auto_continue_if_text_only(msg, tool_choice)

    # pylint: disable=too-many-branches
    async def _summarizing(self) -> Msg:
        """Override summarizing with proactive media filtering,
        passive fallback, and tool_use block filtering.

        1. Proactive layer: if the model does not support multimodal
           **or** the capability cache records ``rejects_media``,
           strip media blocks *before* calling the model.
        2. Passive layer: if the model call still fails with a
           bad-request / media error, strip remaining blocks and retry,
           then record the finding in the capability cache.
        3. If the model IS marked as multimodal but still errors on
           media, log a warning about possibly inaccurate capability flag.

        Some models (e.g. kimi-k2.5) generate tool_use blocks even when
        no tools are provided.  We set ``_in_summarizing`` so that
        ``print`` can strip tool_use blocks from streaming chunks.
        """
        # --- Proactive filtering layer ---
        should_strip = (
            not get_active_model_supports_multimodal()
            or self._model_rejects_media()
        )
        if should_strip:
            if self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(True)
                logger.debug(
                    "Formatter will strip media from copied messages "
                    "before summarizing.",
                )
            else:
                n = self._proactive_strip_media_blocks()
                if n > 0:
                    logger.warning(
                        "Proactively stripped %d media block(s) - "
                        "model does not support multimodal.",
                        n,
                    )

        # --- Passive fallback layer ---
        self._in_summarizing = True
        try:
            try:
                msg = await super()._summarizing()
            except Exception as e:
                if not self._is_bad_request_or_media_error(e):
                    raise

                model_key = self._get_model_key()

                if self._uses_request_time_media_normalization():
                    if get_active_model_supports_multimodal():
                        logger.warning(
                            "Model marked multimodal but "
                            "rejected media. "
                            "Capability flag may be wrong.",
                        )
                    self._set_formatter_media_strip(True)
                    try:
                        logger.warning(
                            "_summarizing failed (%s). "
                            "Retrying with request-time media stripping.",
                            e,
                        )
                        msg = await super()._summarizing()
                        if model_key:
                            get_capability_cache().learn(
                                model_key,
                                "rejects_media",
                                True,
                            )
                    finally:
                        self._set_formatter_media_strip(False)
                else:
                    n_stripped = self._strip_media_blocks_from_memory()
                    if n_stripped == 0:
                        raise

                    if get_active_model_supports_multimodal():
                        logger.warning(
                            "Model marked multimodal but "
                            "rejected media. "
                            "Capability flag may be wrong.",
                        )

                    logger.warning(
                        "_summarizing failed (%s). "
                        "Stripped %d media block(s) from memory, retrying.",
                        e,
                        n_stripped,
                    )
                    msg = await super()._summarizing()
                    if model_key:
                        get_capability_cache().learn(
                            model_key,
                            "rejects_media",
                            True,
                        )
        finally:
            self._in_summarizing = False
            if should_strip and self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(False)

        return self._strip_tool_use_from_msg(msg)

    async def print(
        self,
        msg: Msg,
        last: bool = True,
        speech: Any = None,
    ) -> None:
        """Filter tool_use blocks during _summarizing before they hit the
        message queue, preventing the frontend from briefly rendering
        phantom tool calls that will never be executed.

        On the *final* streaming event (``last=True``), append the
        round-end notice so users see it immediately instead of only
        after a page refresh.  Intermediate events that become empty
        after filtering are silently skipped to avoid blank UI flashes.
        """

        if not getattr(self, "_in_summarizing", False):
            return await super().print(msg, last, speech=speech)

        original = msg.content
        modified = False

        if isinstance(original, list):
            filtered = [
                b
                for b in original
                if not (isinstance(b, dict) and b.get("type") == "tool_use")
            ]
            if not filtered and not last:
                return
            if len(filtered) != len(original) or last:
                msg.content = filtered
                if last:
                    msg.content.append(
                        {"type": "text", "text": self._ROUND_END_NOTICE},
                    )
                modified = True
        elif isinstance(original, str) and last:
            msg.content = original + self._ROUND_END_NOTICE
            modified = True
        if modified:
            try:
                return await super().print(msg, last, speech=speech)
            finally:
                msg.content = original
        return await super().print(msg, last, speech=speech)

    _ROUND_END_NOTICE = (
        "\n\n---\n"
        "本轮调用已达最大次数，回复已终止，请继续输入。\n"
        "Maximum iterations reached for this round. "
        "Please send a new message to continue."
    )

    @staticmethod
    def _strip_tool_use_from_msg(msg: Msg) -> Msg:
        """Remove tool_use blocks from a message and append a user notice.

        When _summarizing is called without tools, some models still
        return tool_use blocks.  Those blocks can never be executed, so
        strip them and append a bilingual notice telling the user this
        round of calls has ended.
        """
        if isinstance(msg.content, str):
            msg.content += CoApisAgent._ROUND_END_NOTICE
            return msg

        filtered = [
            block
            for block in msg.content
            if not (
                isinstance(block, dict) and block.get("type") == "tool_use"
            )
        ]

        n_removed = len(msg.content) - len(filtered)
        if n_removed:
            logger.debug(
                "Stripped %d tool_use block(s) from _summarizing response",
                n_removed,
            )

        filtered.append(
            {"type": "text", "text": CoApisAgent._ROUND_END_NOTICE},
        )
        msg.content = filtered
        return msg

    @staticmethod
    def _is_bad_request_or_media_error(exc: Exception) -> bool:
        """Return True for 400-class or media-related model errors.

        Targets bad-request (400) errors because unsupported media
        content typically causes request validation failures.  Keyword
        matching provides an extra safety net for providers that use
        non-standard status codes.
        """
        status = getattr(exc, "status_code", None)
        if status == 400:
            return True

        error_str = str(exc).lower()
        keywords = [
            "image",
            "audio",
            "video",
            "vision",
            "multimodal",
            "image_url",
        ]
        return any(kw in error_str for kw in keywords)

    def _strip_media_blocks_from_memory(self) -> int:
        """Remove media blocks (image/audio/video) from all messages.

        Also strips media blocks nested inside ToolResultBlock outputs.
        Inserts placeholder text when stripping leaves content empty to
        avoid malformed API requests.

        Returns:
            Total number of media blocks removed.
        """
        media_types = self._MEDIA_BLOCK_TYPES
        total_stripped = 0

        for msg, _marks in self.memory.content:
            if not isinstance(msg.content, list):
                continue

            new_content = []
            stripped_this_message = 0
            for block in msg.content:
                if (
                    isinstance(block, dict)
                    and block.get("type") in media_types
                ):
                    total_stripped += 1
                    stripped_this_message += 1
                    continue

                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and isinstance(block.get("output"), list)
                ):
                    original_len = len(block["output"])
                    block["output"] = [
                        item
                        for item in block["output"]
                        if not (
                            isinstance(item, dict)
                            and item.get("type") in media_types
                        )
                    ]
                    stripped_count = original_len - len(block["output"])
                    total_stripped += stripped_count
                    stripped_this_message += stripped_count
                    if stripped_count > 0 and not block["output"]:
                        block["output"] = MEDIA_UNSUPPORTED_PLACEHOLDER

                new_content.append(block)

            if not new_content and stripped_this_message > 0:
                new_content.append(
                    {
                        "type": "text",
                        "text": MEDIA_UNSUPPORTED_PLACEHOLDER,
                    },
                )

            msg.content = new_content

        return total_stripped

    # pylint: disable=protected-access
    async def reply(
        self,
        msg: Msg | list[Msg] | None = None,
        structured_model: Type[BaseModel] | None = None,
    ) -> Msg:
        """Override reply to process file blocks and handle commands.

        Args:
            msg: Input message(s) from user
            structured_model: Optional pydantic model for structured output

        Returns:
            Response message
        """
        # Set workspace_dir and recent_max_bytes in context for tool functions
        from ..config.context import (
            set_current_workspace_dir,
            set_current_recent_max_bytes,
            set_current_shell_command_timeout,
        )

        set_current_workspace_dir(self._workspace_dir)
        light_ctx = self._agent_config.running.light_context_config
        pruning_config = light_ctx.tool_result_pruning_config
        set_current_recent_max_bytes(
            pruning_config.pruning_recent_msg_max_bytes,
        )
        set_current_shell_command_timeout(
            self._agent_config.running.shell_command_timeout,
        )

        # Process file and media blocks in messages
        if msg is not None:
            await process_file_and_media_blocks_in_message(msg)

        # Check if message is a system command
        last_msg = msg[-1] if isinstance(msg, list) else msg
        query = (
            last_msg.get_text_content() if isinstance(last_msg, Msg) else None
        )

        if self.command_handler.is_command(query):
            logger.info(f"Received command: {query}")
            msg = await self.command_handler.handle_command(query)
            await self.print(msg)
            return msg

        # Normal message processing
        logger.info("CoApisAgent.reply: max_iters=%s", self.max_iters)

        # Intent-based skill loading: load on-demand skills matching user message
        if query:
            self._load_on_demand_skills(query)

        # ── Semantic search: pre-fetch long-term memories ──
        semantic_memories: list[str] = []
        if query and self.memory_manager is not None:
            semantic_memories = await self._async_reme_search(query)
        # Store for _build_sys_prompt to consume
        self._pre_fetched_memories = semantic_memories

        request_context = getattr(self, "_request_context", {}) or {}
        channel_name = request_context.get("channel", "console")
        workspace_dir = Path(self._workspace_dir or WORKING_DIR)

        # Check if this is a global agent (skip auto-assist for global agents)
        is_global = getattr(self._agent_config, 'is_global', False)

        with apply_skill_config_env_overrides(workspace_dir, channel_name):
            response = await super().reply(
                msg=msg,
                structured_model=structured_model,
            )

        # ── Global auto-assist: if response is uncertain, consult global knowledge ──
        if not is_global and query and response:
            response_text = response.get_text_content() or ""
            if self._detect_uncertainty(response_text):
                global_knowledge = self._query_global_memory(query)
                if global_knowledge:
                    logger.info(
                        "[GlobalAssist] Response uncertain, injecting global knowledge (%d chars)",
                        len(global_knowledge),
                    )
                    # Inject global knowledge as a system hint and retry
                    hint_msg = Msg(
                        role="user",
                        content=(
                            f"[系统提示：以下来自全局知识库的信息可能对回答有帮助，请参考后重新回答]\n\n"
                            f"--- 全局知识 ---\n{global_knowledge}\n--- 结束 ---\n\n"
                            f"原始问题：{query}"
                        ),
                        name="system_hint",
                    )
                    # Replace last user message with enhanced version
                    if isinstance(msg, list) and msg:
                        enhanced_msg = list(msg[:-1]) + [hint_msg]
                    elif isinstance(msg, Msg):
                        enhanced_msg = [hint_msg]
                    else:
                        enhanced_msg = [hint_msg]

                    with apply_skill_config_env_overrides(workspace_dir, channel_name):
                        response = await super().reply(
                            msg=enhanced_msg,
                            structured_model=structured_model,
                        )
                    logger.info("[GlobalAssist] Replied with global knowledge context")

        return response

    async def interrupt(self, msg: Msg | list[Msg] | None = None) -> None:
        """Interrupt the current reply process and wait for cleanup."""
        if self._reply_task and not self._reply_task.done():
            task = self._reply_task
            task.cancel(msg)
            try:
                await task
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise
            except Exception:
                logger.warning(
                    "Exception occurred during interrupt cleanup",
                    exc_info=True,
                )
