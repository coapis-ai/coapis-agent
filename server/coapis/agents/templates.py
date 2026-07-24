# -*- coding: utf-8 -*-
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

"""Shared agent template definitions and builders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config.config import (
    AgentProfileConfig,
    ChannelConfig,
    HeartbeatConfig,
    MCPConfig,
)
from ..constant import BUILTIN_QA_AGENT_NAME, BUILTIN_QA_AGENT_SKILL_NAMES

DEFAULT_AGENT_TEMPLATE = "default"
LOCAL_AGENT_TEMPLATE = "local"
QA_AGENT_TEMPLATE = "qa"
SUPPORTED_AGENT_TEMPLATES = (
    DEFAULT_AGENT_TEMPLATE,
    LOCAL_AGENT_TEMPLATE,
    QA_AGENT_TEMPLATE,
)

LOCAL_TEMPLATE_SKILL_NAMES = ("make_plan",)
QA_TEMPLATE_DESCRIPTION = (
    "Builtin Q&A helper for CoApis setup, local config under "
    "COAPIS_WORKING_DIR, and documentation. Prefer reading files "
    "before answering; use absolute paths for code outside this "
    "workspace."
)


@dataclass(frozen=True)
class AgentTemplateBuildResult:
    """Materialized result for creating an agent from a builtin template."""

    agent_config: AgentProfileConfig
    initial_skill_names: tuple[str, ...]
    md_template_id: str | None


def list_supported_agent_templates() -> tuple[str, ...]:
    """Return builtin agent template IDs supported by the application."""
    return SUPPORTED_AGENT_TEMPLATES


def get_workspace_md_template_id(template_id: str | None) -> str | None:
    """Map an agent template id to the workspace markdown template id."""
    if template_id in {LOCAL_AGENT_TEMPLATE, QA_AGENT_TEMPLATE}:
        return template_id
    return None


def build_agent_template(
    template_id: str,
    *,
    agent_id: str,
    workspace_dir: Path,
    fallback_language: str,
    name: str | None = None,
    description: str | None = None,
    language: str | None = None,
    semantic_agent_id: str | None = None,
) -> AgentTemplateBuildResult:
    """Build a builtin template into a concrete agent configuration.
    
    Args:
        agent_id: ASCII-safe internal agent ID (e.g., "agent:20")
        semantic_agent_id: Optional semantic ID for display (e.g., "user:张三")
    """
    resolved_language = language or fallback_language or "zh"
    
    # Use semantic_agent_id for display, agent_id for runtime
    display_id = semantic_agent_id or agent_id

    if template_id == DEFAULT_AGENT_TEMPLATE:
        if name is None:
            raise ValueError("Default template requires a name")
        agent_config = AgentProfileConfig(
            id=display_id,  # Semantic ID for display
            agent_id=agent_id,  # ASCII-safe internal ID
            name=name,
            description=description or "",
            workspace_dir=str(workspace_dir),
            template_id=template_id,
            language=resolved_language,
            channels=ChannelConfig(),
            mcp=MCPConfig(),
            heartbeat=HeartbeatConfig(),
        )
        return AgentTemplateBuildResult(
            agent_config=agent_config,
            initial_skill_names=(),
            md_template_id=get_workspace_md_template_id(template_id),
        )

    if template_id == LOCAL_AGENT_TEMPLATE:
        agent_config = AgentProfileConfig(
            id=display_id,  # Semantic ID for display
            agent_id=agent_id,  # ASCII-safe internal ID
            name=name or "Local Agent",
            description=(
                description or "An agent running on local deployed models."
            ),
            workspace_dir=str(workspace_dir),
            template_id=template_id,
            language=resolved_language,
            channels=ChannelConfig(),
            mcp=MCPConfig(),
            heartbeat=HeartbeatConfig(),
        )
        return AgentTemplateBuildResult(
            agent_config=agent_config,
            initial_skill_names=LOCAL_TEMPLATE_SKILL_NAMES,
            md_template_id=get_workspace_md_template_id(template_id),
        )

    if template_id == QA_AGENT_TEMPLATE:
        agent_config = AgentProfileConfig(
            id=display_id,  # Semantic ID for display
            agent_id=agent_id,  # ASCII-safe internal ID
            name=name or BUILTIN_QA_AGENT_NAME,
            description=description or QA_TEMPLATE_DESCRIPTION,
            workspace_dir=str(workspace_dir),
            template_id=template_id,
            language=resolved_language,
            channels=ChannelConfig(),
            mcp=MCPConfig(),
            heartbeat=HeartbeatConfig(),
        )
        return AgentTemplateBuildResult(
            agent_config=agent_config,
            initial_skill_names=tuple(BUILTIN_QA_AGENT_SKILL_NAMES),
            md_template_id=get_workspace_md_template_id(template_id),
        )

    raise ValueError(
        f"Unsupported template: {template_id!r}. "
        f"Expected one of {SUPPORTED_AGENT_TEMPLATES}.",
    )
