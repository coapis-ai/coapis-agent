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

"""Tool for materializing skill proposals into workspace skills."""

import logging
import re
from pathlib import Path

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from .registry import register_tool

logger = logging.getLogger(__name__)


def _tool_text_response(text: str) -> ToolResponse:
    """Wrap text in a single-TextBlock ToolResponse."""
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _normalize_skill_dir_name(name: str) -> str:
    """Normalize skill directory name to ASCII-safe format."""
    name = name.strip().lower()
    name = re.sub(r'[^a-z0-9_\-]', '_', name)
    name = re.sub(r'_+', '_', name)
    return name.strip('_') or 'skill'


def _get_workspace_dir() -> Path | None:
    """Get current workspace directory from context."""
    from ...config.session_context import get_current_workspace_dir
    ws_dir = get_current_workspace_dir()
    return Path(ws_dir) if ws_dir else None


@register_tool(
    name="materialize_skill",
    description="将确认的技能方案持久化到工作区，创建 SKILL.md 和注册表条目",
    category="builtin",
    tags=["skill", "create", "workspace"],
    scene="ai",
)
async def materialize_skill(
    name: str,
    description: str,
    body: str,
) -> ToolResponse:
    """Persist a confirmed skill proposal into the workspace.

    Writes SKILL.md and updates the workspace skill manifest.

    Args:
        name: Skill directory name (will be normalized).
        description: The SKILL.md trigger string
            (``Use this skill when …``). Keep it ≤ ~200 chars.
        body: The SKILL.md body content, no frontmatter.

    Returns:
        ToolResponse with success/failure message.
    """
    if not name or not description or not body:
        return _tool_text_response(
            "**materialize_skill is missing required input**\n\n"
            "Need non-empty `name`, `description`, and `body`. "
            "Re-derive them from `plan.name` and `plan.description` "
            "and call `materialize_skill` again. "
            "Do NOT call `finish_subtask` yet.",
        )

    workspace_dir = _get_workspace_dir()
    if workspace_dir is None:
        return _tool_text_response(
            "**Workspace directory not set in context**; cannot "
            "materialize. This is an internal error — abandon "
            "the plan.",
        )

    # Normalize skill name
    try:
        normalized_name = _normalize_skill_dir_name(name)
    except Exception as e:
        return _tool_text_response(
            f"**Invalid skill name** `{name}`: {e}\n\n"
            "Call `revise_current_plan` to fix `plan.name` and "
            "try again.",
        )

    # Check for name conflict
    skill_root = workspace_dir / "skills"
    skill_dir = skill_root / normalized_name
    if skill_dir.exists():
        return _tool_text_response(
            f"**Skill named `{normalized_name}` already exists in "
            f"this workspace.**\n\n"
            f"Call `revise_current_plan` to switch `plan.name` to "
            f"a unique name and try again.",
        )

    # Create skill directory and files
    try:
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Write SKILL.md
        skill_md_path = skill_dir / "SKILL.md"
        skill_md_content = f"# {normalized_name}\n\n{description}\n\n{body}"
        skill_md_path.write_text(skill_md_content, encoding="utf-8")

        # Update skill manifest (skill.json)
        manifest_path = workspace_dir / "skill.json"
        manifest = {}
        if manifest_path.exists():
            import json
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}

        if "skills" not in manifest:
            manifest["skills"] = {}

        manifest["skills"][normalized_name] = {
            "description": description,
            "source": "customized",
            "enabled": True,
        }

        import json
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return _tool_text_response(
            f"**Skill `{normalized_name}` created successfully!**\n\n"
            f"- SKILL.md written to `{skill_dir}/SKILL.md`\n"
            f"- Manifest updated at `{manifest_path}`\n"
            f"- Skill is now enabled\n\n"
            f"You can now call `finish_subtask` to complete the plan.",
        )

    except Exception as e:
        logger.exception(f"Failed to materialize skill {normalized_name}")
        return _tool_text_response(
            f"**Failed to create skill** `{normalized_name}`: {e}\n\n"
            "Check workspace permissions and try again.",
        )
