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

"""SkillManager - Manages discoverable, hot-reloadable skills.

Inspired by CoApis's SkillsHub + SkillsManager.
Skills are directories with SKILL.md, scripts, and metadata.
"""

import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SkillManager:
    """Manages agent skills with discovery and hot-reload.

    Skill structure:
    ```
    skills/
    └── skill-name/
        ├── SKILL.md          # Skill documentation
        ├── _meta.json        # Metadata (optional)
        ├── scripts/          # Skill scripts (optional)
        ├── references/       # Reference docs (optional)
        └── hooks/            # Event hooks (optional)
    ```
    """

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._skills: Dict[str, dict] = {}

    async def discover(self):
        """Discover all skills in skills directory."""
        logger.info(f"Discovering skills in {self.skills_dir}")

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            skill = self._load_skill(skill_dir)
            if skill:
                self._skills[skill["name"]] = skill
                logger.debug(f"Discovered skill: {skill['name']}")

        logger.info(f"Discovered {len(self._skills)} skills")

        # Apply skill descriptions from data pack (language-aware override)
        try:
            self.apply_descriptions_from_pack("zh")
        except Exception:
            pass

    def _load_skill(self, skill_dir: Path) -> Optional[dict]:
        """Load a single skill from directory."""
        skill_md = skill_dir / "SKILL.md"
        meta_file = skill_dir / "_meta.json"

        # Parse SKILL.md frontmatter
        content = skill_md.read_text()
        name, description = self._parse_frontmatter(content)

        if not name:
            return None

        # Load optional metadata
        meta = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
            except json.JSONDecodeError:
                logger.warning(f"Invalid _meta.json in {skill_dir}")

        return {
            "name": name,
            "description": description or "",
            "path": str(skill_dir),
            "enabled": meta.get("enabled", True),
            "version": meta.get("version", "1.0.0"),
            "tags": meta.get("tags", []),
        }

    def _parse_frontmatter(self, content: str) -> tuple:
        """Parse YAML frontmatter from SKILL.md."""
        name = ""
        description = ""

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 2:
                yaml_block = parts[1]
                for line in yaml_block.split("\n"):
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("description:"):
                        description = line.split(":", 1)[1].strip().strip('"').strip("'")

        return name, description

    def apply_descriptions_from_pack(self, language: str = "zh") -> int:
        """从数据包加载技能描述并覆盖 YAML frontmatter 中的描述.

        Args:
            language: 语言代码

        Returns:
            覆盖的技能数量
        """
        try:
            from coapis.system.data_loader import load_skill_descriptions
            descriptions = load_skill_descriptions(language)
        except Exception:
            return 0

        count = 0
        for name, desc in descriptions.items():
            if name in self._skills and desc:
                self._skills[name]["description"] = desc
                count += 1
        if count:
            logger.info("Applied %d skill descriptions from data pack (lang=%s)", count, language)
            # Invalidate cache after description changes
            self.invalidate_index_cache()
        return count

    def get_skill(self, name: str) -> Optional[dict]:
        """Get skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> List[dict]:
        """List all discovered skills."""
        return list(self._skills.values())

    def get_index_prompt(self, compact: bool = False) -> str:
        """Generate skills index for system prompt (cached).

        Args:
            compact: If True, generate ultra-compact index (name only, no descriptions).
                    Reduces tokens from ~2138 to ~180 (91% reduction).

        Returns:
            Skills index string
        """
        cache_key = '_index_prompt_cache_compact' if compact else '_index_prompt_cache'

        # Use cached version if available
        if hasattr(self, cache_key):
            cached = getattr(self, cache_key)
            if cached is not None:
                return cached

        if not self._skills:
            setattr(self, cache_key, "")
            return ""

        if compact:
            # Ultra-compact: just skill names, one per line
            # Model can still identify skills by name when needed
            names = [s['name'] for s in self._skills.values() if s.get("enabled", True)]
            result = ", ".join(sorted(names))
            setattr(self, cache_key, result)
            return result
        else:
            # Full format with descriptions
            lines = ["Available Skills:"]
            for skill in self._skills.values():
                if skill.get("enabled", True):
                    lines.append(f"- **{skill['name']}**: {skill['description']}")

            result = "\n".join(lines)
            setattr(self, cache_key, result)
            return result

    def invalidate_index_cache(self) -> None:
        """Invalidate cached index prompt (call after skill changes)."""
        self._index_prompt_cache = ""
        self._index_prompt_cache_compact = ""

    async def hot_reload(self, skill_name: str):
        """Hot-reload a specific skill."""
        skill_dir = Path(self._skills.get(skill_name, {}).get("path", ""))
        if skill_dir.exists():
            new_skill = self._load_skill(skill_dir)
            if new_skill:
                self._skills[skill_name] = new_skill
                logger.info(f"Hot-reloaded skill: {skill_name}")

    async def create_skill(self, name: str, description: str, content: str) -> bool:
        """Create a new skill.

        Args:
            name: Skill name
            description: Skill description
            content: SKILL.md content

        Returns:
            True if created successfully
        """
        skill_dir = self.skills_dir / name
        if skill_dir.exists():
            logger.warning(f"Skill already exists: {name}")
            return False

        # Create skill structure
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(content)
        (skill_dir / "scripts").mkdir(exist_ok=True)
        (skill_dir / "references").mkdir(exist_ok=True)

        # Load and register
        skill = self._load_skill(skill_dir)
        if skill:
            self._skills[name] = skill
            logger.info(f"Created skill: {name}")
            return True

        return False

    async def remove_skill(self, name: str) -> bool:
        """Remove a skill."""
        if name not in self._skills:
            return False

        skill_dir = Path(self._skills[name]["path"])
        if skill_dir.exists():
            import shutil
            shutil.rmtree(skill_dir)

        del self._skills[name]
        logger.info(f"Removed skill: {name}")
        return True

    # ================================================================
    # On-demand skill loading — match skills by query keywords/triggers
    # ================================================================

    # Keyword-to-skill mapping: extracted from SKILL.md trigger words
    # Maps common query keywords to skill names for fast matching
    _TRIGGER_MAP: Dict[str, List[str]] = {
        # Browser automation
        "browser": ["browser_use", "browser_cdp", "browser_visible"],
        "login": ["browser_use", "browser_cdp"],
        "screenshot": ["browser_use", "browser_visible"],
        "web": ["browser_use", "browser_cdp", "news"],
        "scrape": ["browser_use"],
        "navigate": ["browser_use", "browser_cdp"],
        "click": ["browser_use"],
        "form": ["browser_use"],
        # File handling
        "pdf": ["pdf"],
        "word": ["docx"],
        "excel": ["xlsx"],
        "spreadsheet": ["xlsx"],
        "ppt": ["pptx"],
        "powerpoint": ["pptx"],
        "document": ["docx", "pdf", "file_reader"],
        "file": ["file_reader", "markitdown"],
        "image": ["file_reader", "markitdown"],
        "ocr": ["markitdown"],
        "read": ["file_reader", "markitdown"],
        "convert": ["markitdown"],
        # Communication
        "email": ["himalaya"],
        "mail": ["himalaya"],
        "dingtalk": ["dingtalk_channel"],
        "wecom": ["channel_message"],
        "channel": ["channel_message", "dingtalk_channel"],
        "message": ["channel_message"],
        "send": ["channel_message", "himalaya"],
        # Agent collaboration
        "agent": ["multi_agent_collaboration", "chat_with_agent"],
        "collaborat": ["multi_agent_collaboration"],
        "chat with agent": ["chat_with_agent"],
        # Scheduling
        "cron": ["cron"],
        "schedule": ["cron"],
        "recurring": ["cron"],
        "periodic": ["cron"],
        "timer": ["cron"],
        # Planning
        "plan": ["make_plan"],
        "task": ["make_plan"],
        # Search / Research
        "search": ["web_search"],
        "news": ["news"],
        "research": ["web_search", "news"],
        "lookup": ["web_search"],
        # Guidance / Help
        "help": ["guidance"],
        "install": ["guidance"],
        "configure": ["guidance"],
        "setup": ["guidance"],
        # Humanizer
        "humanize": ["humanizer_academic_zh"],
        "polish": ["humanizer_academic_zh"],
        "rewrite": ["humanizer_academic_zh"],
        "ai味": ["humanizer_academic_zh"],
        "aigc": ["humanizer_academic_zh"],
        # Source index
        "source": ["coapis_source_index"],
        "docs": ["coapis_source_index"],
        # Skill creation
        "create skill": ["skill_creator"],
        "new skill": ["skill_creator"],
    }

    async def execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """Execute a tool by name with arguments.

        Delegates to core tool functions (read_file, write_file, etc.)
        using direct imports to avoid relative import issues.

        Args:
            tool_name: Name of the tool to execute
            tool_args: Arguments dict for the tool

        Returns:
            Tool execution result as string

        Raises:
            ValueError: If tool is unknown
            Exception: If tool execution fails
        """
        # Lazy-load tool functions on first call
        if not hasattr(self, '_tool_funcs'):
            self._tool_funcs = {}
            try:
                from coapis.agents.tools.file_io import read_file, write_file, edit_file
                from coapis.agents.tools.file_search import grep_search, glob_search
                self._tool_funcs = {
                    "read_file": read_file,
                    "write_file": write_file,
                    "edit_file": edit_file,
                    "grep_search": grep_search,
                    "glob_search": glob_search,
                }
            except Exception as e:
                logger.warning(f"Failed to load tool functions: {e}")
            # execute_shell_command has relative imports that break here,
            # use a simple subprocess fallback
            import subprocess as _sp
            async def _shell_fallback(command="", **kw):
                r = _sp.run(command, shell=True, capture_output=True, text=True, timeout=30)
                out = r.stdout + r.stderr
                return out[:4096] if out else "(no output)"
            self._tool_funcs["execute_shell_command"] = _shell_fallback

        func = self._tool_funcs.get(tool_name)
        if func:
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(**tool_args)
                else:
                    result = func(**tool_args)
                return str(result) if result is not None else "(empty result)"
            except Exception as e:
                logger.error(f"Tool {tool_name} failed: {e}")
                return f"Tool error: {e}"

        raise ValueError(f"Unknown tool: {tool_name}")

    def match_skills_by_query(self, query: str) -> List[str]:
        """Match relevant skill names based on query keywords.

        Uses a keyword-to-skiname mapping for fast, zero-LLM-cost matching.
        Falls back to description keyword matching if no trigger match found.

        Args:
            query: User's input query text

        Returns:
            List of matched skill names (sorted by relevance)
        """
        query_lower = query.lower()
        matched = set()

        # 1. Trigger map matching (fast, deterministic)
        for keyword, skill_names in self._TRIGGER_MAP.items():
            if keyword in query_lower:
                for sn in skill_names:
                    # Normalize: skill names may use underscores or hyphens
                    normalized = sn.replace("-", "_")
                    # Check if this skill actually exists
                    if self._find_skill_by_normalized_name(normalized):
                        matched.add(normalized)

        # 2. Description keyword matching (fallback for unmatched queries)
        if not matched:
            for name, skill in self._skills.items():
                if not skill.get("enabled", True):
                    continue
                desc_lower = (skill.get("description", "") + " " + name).lower()
                # Check if any word from query appears in description
                query_words = set(query_lower.split())
                for word in query_words:
                    if len(word) >= 3 and word in desc_lower:
                        matched.add(name)
                        break

        # 3. If still no match, return all enabled skills (safe fallback)
        if not matched:
            return [n for n, s in self._skills.items() if s.get("enabled", True)]

        return sorted(matched)

    def _find_skill_by_normalized_name(self, normalized: str) -> Optional[str]:
        """Find actual skill name from normalized version (handles - vs _)."""
        for name in self._skills:
            if name.replace("-", "_") == normalized:
                return name
        return None

    def get_index_prompt(self, compact: bool = False, query: str = None) -> str:
        """Generate skills index for system prompt (cached).

        Args:
            compact: If True, generate ultra-compact index (name only, no descriptions).
                    Reduces tokens from ~2138 to ~180 (91% reduction).
            query: If provided, only include skills matching the query (on-demand loading).
                  Further reduces tokens by filtering irrelevant skills.

        Returns:
            Skills index string
        """
        # Determine which skills to include
        if query:
            matched_names = self.match_skills_by_query(query)
            cache_key = f'_index_prompt_cache_query_{hash(query) % 10000}'
        elif compact:
            matched_names = [n for n, s in self._skills.items() if s.get("enabled", True)]
            cache_key = '_index_prompt_cache_compact'
        else:
            matched_names = [n for n, s in self._skills.items() if s.get("enabled", True)]
            cache_key = '_index_prompt_cache'

        # Use cached version if available
        if hasattr(self, cache_key):
            cached = getattr(self, cache_key)
            if cached is not None:
                return cached

        if not matched_names:
            setattr(self, cache_key, "")
            return ""

        # Build index from matched skills only
        matched_skills = [self._skills[n] for n in matched_names if n in self._skills]

        if compact:
            names = [s['name'] for s in matched_skills if s.get("enabled", True)]
            result = ", ".join(sorted(names))
        else:
            lines = ["Available Skills:"]
            for skill in matched_skills:
                if skill.get("enabled", True):
                    lines.append(f"- **{skill['name']}**: {skill['description']}")
            result = "\n".join(lines)

        setattr(self, cache_key, result)
        return result
