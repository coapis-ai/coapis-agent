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

"""SkillManager - Manages discoverable, hot-reloadable skills.

Inspired by CoApis's SkillsHub + SkillsManager.
Skills are directories with SKILL.md, scripts, and metadata.
"""

import json
import hashlib
import logging
import asyncio
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

#: Hard cap for one skill's line in the system-prompt index (B0-4, 2026-10-17).
#: Measured on dev: 17 skills × avg 234 chars of frontmatter description =
#: **3,983 chars of system prompt on every turn**.  An index only has to say
#: *when* the skill applies; the body is read on demand, so the description
#: is not the place to pay for.  ``index_hint`` in the frontmatter is the
#: author-written trigger line; without it the description is cut to this
#: length, which keeps the whole index near 1.7K chars.
SKILL_INDEX_HINT_CHARS = 60


def skill_index_hint(skill: dict) -> str:
    """One-line trigger text for the skill index (``index_hint`` if present)."""
    text = (skill.get("index_hint") or "").strip() or (
        skill.get("description") or ""
    ).strip()
    text = " ".join(text.split())
    if len(text) <= SKILL_INDEX_HINT_CHARS:
        return text
    return text[: SKILL_INDEX_HINT_CHARS - 1].rstrip() + "…"


#: Phrases that turn a skill's index line into a **trigger** the model can
#: match a user request against, instead of a description of what the file
#: contains.  B8 (2026-10-19): 18 of 21 skill references were "ghosts" -- the
#: index listed skills, nothing in the runtime ever matched a request to them,
#: and the reason is that a description like "Tools for PDF work" gives the
#: model nothing to match "帮我把这个 PDF 转成 Word" against.
_TRIGGER_MARKERS = (
    "use this skill when",
    "use when",
    "use this when",
    "when the user",
    "when you need",
    "when asked",
    "triggers when",
    "asks to",
    "asks for",
    "phrases like",
    "触发",
    "使用场景",
    "当用户",
    "当用户",
    "适用于",
    "用于用户",
    "需要时",
)


def has_trigger_sentence(skill: dict) -> bool:
    """True when the skill carries a sentence a request can be matched to.

    Checks the author-written ``index_hint`` first, then the description.
    """
    for text in (
        skill.get("index_hint") or "",
        skill.get("description") or "",
    ):
        low = str(text).lower()
        if any(marker in low for marker in _TRIGGER_MARKERS):
            return True
    return False


def missing_trigger_skills(skills: Iterable[dict]) -> list[str]:
    """Names of skills whose index line is a description, not a trigger."""
    return [
        str(skill.get("name") or "?")
        for skill in skills
        if not has_trigger_sentence(skill)
    ]


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

    def __init__(self, skills_dir: Path, extra_dirs: Optional[Iterable[Path]] = None):
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        # The loader resolves skills from the pool *and* the user/agent
        # manifests (resolve_effective_skills searches agent dir, user skills
        # dir and the skill pool).  This manager used to scan skills_dir only,
        # so the index the model read was a subset of what it could load —
        # measured on dev: 5 skills in the index, 21 loadable.  extra_dirs
        # brings the catalogue in; skills_dir is scanned last so a skill the
        # workspace owns overrides the pool copy.
        self.extra_dirs = [Path(p) for p in (extra_dirs or []) if p]
        self._skills: Dict[str, dict] = {}
        # Cache sentinel MUST be None, never "".  get_index_prompt() treats a
        # cached value as valid when it "is not None"; seeding it with "" (as
        # invalidate_index_cache used to) made the very first compact call
        # return an empty skill index — the model then saw no skills at all on
        # every turn after the first.  Measured on dev 2026-10-21: 19 skills
        # discovered, index length 0 chars.
        # One LRU keyed by filter+mode+query; see get_index_prompt().
        self._query_index_cache: "OrderedDict[str, str]" = OrderedDict()

    async def discover(self):
        """Discover all skills in skills directory."""
        logger.info(f"Discovering skills in {self.skills_dir}")

        # skills_dir is scanned last so a skill the workspace owns overrides
        # the pool copy of the same name.
        scan_dirs = [*self.extra_dirs, self.skills_dir]
        entries = 0
        for base in scan_dirs:
            if not base.exists():
                continue
            for skill_dir in base.iterdir():
                if not skill_dir.is_dir():
                    continue

                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue

                skill = self._load_skill(skill_dir)
                if skill:
                    self._skills[skill["name"]] = skill
                    entries += 1
                    logger.debug(f"Discovered skill: {skill['name']}")

        logger.info(
            f"Discovered {len(self._skills)} skills from "
            f"{len(scan_dirs)} director{'y' if len(scan_dirs) == 1 else 'ies'}",
        )

        # B8: a skill whose index line describes the file instead of naming
        # the situation it applies to is a skill the model cannot select.  It
        # is listed in the system prompt, costs the prompt its characters, and
        # never fires -- 18 of 21 references measured on dev 2026-10-17 were
        # exactly that.  Say it at discovery, where the author can still fix
        # it, instead of leaving it as a runtime mystery.
        silent = missing_trigger_skills(self._skills.values())
        if silent:
            logger.warning(
                "%d of %d skills have no trigger sentence (no index_hint and "
                "no 'Use this skill when…' in the description), so the model "
                "has nothing to match a user request against: %s. Add an "
                "`index_hint:` line to each SKILL.md frontmatter.",
                len(silent),
                len(self._skills),
                ", ".join(sorted(silent)),
            )

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
        index_hint = self._parse_index_hint(content)

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
            "index_hint": index_hint,
            "trigger_keywords": self._parse_trigger_keywords(content),
            "path": str(skill_dir),
            "enabled": meta.get("enabled", True),
            "version": meta.get("version", "1.0.0"),
            "tags": meta.get("tags", []),
            "has_trigger": has_trigger_sentence(
                {"index_hint": index_hint, "description": description or ""},
            ),
        }

    @staticmethod
    def _parse_trigger_keywords(content: str) -> List[str]:
        """Collect the trigger words a skill declares in its frontmatter.

        Reads, in priority order: top-level ``trigger_keywords``,
        ``triggers.keywords``, ``triggers.intent_hints``, top-level ``trigger``.
        ``triggers.patterns`` is deliberately **excluded** — those are regexes
        and belong to the regex channel (see SkillSelector), not to literal
        keyword matching, where they could never fire.

        Why this exists: the prompt layer used to match queries against a
        hard-coded English ``_TRIGGER_MAP`` only, so the Chinese trigger words
        skill authors declare in SKILL.md had no effect on what the model was
        shown, while the load layer (SkillSelector) did read them — the two
        layers answered the same request with different skill sets.
        """
        out: List[str] = []
        if not content.startswith("---"):
            return out
        parts = content.split("---", 2)
        if len(parts) < 3:
            return out
        try:
            import yaml

            meta = yaml.safe_load(parts[1])
        except Exception:
            return out
        if not isinstance(meta, dict):
            return out

        top = meta.get("trigger_keywords", [])
        if isinstance(top, list):
            out.extend(str(k) for k in top if k)

        triggers = meta.get("triggers", {})
        if isinstance(triggers, dict):
            for key in ("keywords", "intent_hints"):
                vals = triggers.get(key, [])
                if isinstance(vals, list):
                    out.extend(str(v) for v in vals if v)
        elif isinstance(triggers, list):
            out.extend(str(v) for v in triggers if v)

        trigger_str = meta.get("trigger", "")
        if isinstance(trigger_str, str) and trigger_str:
            for piece in trigger_str.replace("；", ",").replace("，", ",").split(","):
                piece = piece.strip()
                if piece:
                    out.append(piece)

        seen: set = set()
        ordered: List[str] = []
        for kw in out:
            low = kw.lower()
            if low not in seen:
                seen.add(low)
                ordered.append(kw)
        return ordered

    @staticmethod
    def _parse_index_hint(content: str) -> str:
        """Read the optional ``index_hint:`` frontmatter key.

        The index line the model sees every turn; authors who care about it
        write it, everyone else gets a truncation of ``description``.
        """
        if not content.startswith("---"):
            return ""
        parts = content.split("---", 2)
        if len(parts) < 2:
            return ""
        for line in parts[1].split("\n"):
            if line.startswith("index_hint:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
        return ""

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

    def invalidate_index_cache(self) -> None:
        """Invalidate cached index prompt (call after skill changes).

        Uses ``None`` as the "no cache" sentinel: ``get_index_prompt`` accepts
        any non-None cached value as a hit, so writing ``""`` here silently
        disabled the compact index forever (an empty index is a *valid* cached
        value, so it was never rebuilt).
        """
        self._query_index_cache.clear()

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
    #: How many skills the no-match fallback may list.  Chosen so the index
    #: stays well under the full catalogue (19 skills on dev measured 2.1K
    #: chars of index) while still giving the model something to pick from.
    FALLBACK_SKILL_CAP = 8

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

    @staticmethod
    def _query_tokens(text: str) -> List[str]:
        """Split a query into matchable tokens, CJK-aware.

        ``text.split()`` is useless on Chinese: "读取文档" is a single token,
        so the old fallback compared a whole sentence against a skill
        description and matched nothing, which dropped every Chinese request
        into the "return all skills" branch.  Here Chinese runs become
        character bigrams ("读取文档" → 读取/取文/文档) and Latin words stay
        words, so matching works in both languages.
        """
        import re

        low = text.lower()
        tokens: List[str] = []
        for word in re.findall(r"[a-z0-9][a-z0-9._-]{1,}", low):
            tokens.append(word)
        for run in re.findall(r"[\u4e00-\u9fff]+", low):
            if len(run) == 1:
                continue
            for i in range(len(run) - 1):
                tokens.append(run[i : i + 2])
            if len(run) >= 3:
                tokens.append(run)
        return tokens

    def match_skills_by_query(self, query: str) -> List[str]:
        """Match relevant skill names to a query, zero LLM cost.

        Tier 1 — the skill's own declared trigger words (SKILL.md
        ``trigger_keywords`` / ``triggers.*``).  This is the channel skill
        authors actually maintain, and it is mostly Chinese; the prompt layer
        used to ignore it entirely.
        Tier 2 — the hard-coded ``_TRIGGER_MAP`` alias table (English
        synonyms, file suffixes, product names).  Kept as a supplement, not
        the authority.
        Tier 3 — CJK bigram / Latin word matching against the index hint,
        description and skill name.
        Fallback — never "all skills": that flooded the index and cancelled
        the point of on-demand loading.  We return the always-load skills
        plus the closest few by name relevance.
        """
        query_lower = (query or "").lower()
        if not query_lower.strip():
            return self._fallback_skills()

        scores: Dict[str, int] = {}

        def _bump(name: str, points: int) -> None:
            scores[name] = scores.get(name, 0) + points

        # Tier 1: declared trigger words (highest precision).
        for name, skill in self._skills.items():
            if not skill.get("enabled", True):
                continue
            for kw in skill.get("trigger_keywords") or []:
                kw_low = str(kw).lower().strip()
                if len(kw_low) >= 2 and kw_low in query_lower:
                    _bump(name, 4)

        # Tier 2: hard-coded alias table.
        for keyword, skill_names in self._TRIGGER_MAP.items():
            if keyword in query_lower:
                for sn in skill_names:
                    found = self._find_skill_by_normalized_name(sn.replace("-", "_"))
                    if found:
                        _bump(found, 3)

        if scores:
            return sorted(scores, key=lambda n: (-scores[n], n))

        # Tier 3: token matching against the trigger-facing text only.
        tokens = [t for t in self._query_tokens(query_lower) if len(t) >= 2]
        if tokens:
            for name, skill in self._skills.items():
                if not skill.get("enabled", True):
                    continue
                hay = " ".join(
                    [
                        str(skill.get("index_hint", "")),
                        str(skill.get("description", "")),
                        name,
                        " ".join(str(k) for k in skill.get("trigger_keywords") or []),
                    ]
                ).lower().replace("-", "_")
                hits = sum(1 for t in tokens if t in hay)
                if hits:
                    scores[name] = hits

        if scores:
            return sorted(scores, key=lambda n: (-scores[n], n))

        return self._fallback_skills()

    def _fallback_skills(self) -> List[str]:
        """Skills to show when a query matches nothing.

        The old behaviour returned *every* enabled skill, which made the
        query-filtered index the same size as the full one.  Always-load
        skills plus a small, name-relevance-ordered set keeps the index
        useful without paying for the whole catalogue.
        """
        enabled = [n for n, s in self._skills.items() if s.get("enabled", True)]
        if not enabled:
            return []
        always = [n for n in enabled if self._skills[n].get("always_load")]
        rest = [n for n in enabled if n not in always]
        # Prefer skills whose index line states *when* to use them: a skill
        # with no trigger sentence is one the model cannot select anyway.
        rest.sort(key=lambda n: (not self._skills[n].get("has_trigger"), len(n)))
        picked = always + rest[: self.FALLBACK_SKILL_CAP]
        return picked or enabled[: self.FALLBACK_SKILL_CAP]

    def _find_skill_by_normalized_name(self, normalized: str) -> Optional[str]:
        """Find actual skill name from normalized version (handles - vs _)."""
        for name in self._skills:
            if name.replace("-", "_") == normalized:
                return name
        return None

    #: Above this many matched skills, the per-skill trigger lines stop paying
    #: for themselves and the index degrades to a name list.  Guards against
    #: a broad match re-inflating the index to full-catalogue size.
    INDEX_DETAIL_CAP = 10
    #: LRU ceiling for the per-query index cache.  Keys used to be
    #: ``hash(query) % 10000``: with ~120 distinct queries a collision became
    #: the coin flip, and because the manager is a per-workspace instance one
    #: session could serve another session's skill set.
    QUERY_CACHE_CAP = 64

    def get_index_prompt(self, compact: bool = False, query: str = None, only=None) -> str:
        """Generate skills index for system prompt (cached).

        Args:
            compact: If True, generate ultra-compact index (name only, no descriptions).
                    Reduces tokens from ~2138 to ~180 (91% reduction).
            query: If provided, only include skills matching the query (on-demand loading).
                  Further reduces tokens by filtering irrelevant skills.
            only: Optional iterable of skill names the agent can actually use.  The
                  loader resolves skills from the pool *and* the user/agent manifests
                  (``resolve_effective_skills``), while this manager scans only
                  ``skills_dir``; without the filter the index showed 5 workspace
                  skills while 21 were loadable, so the model never saw most of
                  what it could use.  Passing ``toolkit.skills`` aligns the two.

        Returns:
            Skills index string
        """
        allowed = set(only) if only is not None else None
        # Cache keys must carry the filter: one manager instance is reused
        # across turns, and a turn with a different skill set must not serve a
        # cached index built for another one.
        filter_fp = ""
        if allowed is not None:
            digest = hashlib.sha1("|".join(sorted(allowed)).encode("utf-8"))
            filter_fp = digest.hexdigest()[:12] + "|"

        # Determine which skills to include
        if query:
            matched_names = self.match_skills_by_query(query)
            cache_key = f"{filter_fp}{query}"
        elif compact:
            matched_names = [n for n, s in self._skills.items() if s.get("enabled", True)]
            cache_key = f"{filter_fp}compact"
        else:
            matched_names = [n for n, s in self._skills.items() if s.get("enabled", True)]
            cache_key = f"{filter_fp}full"

        # All three modes share one LRU keyed by filter+mode+query.  Keeping
        # compact/full in single fields would let one turn's loadable set serve
        # another turn's cached index.
        cached = self._query_index_cache.get(cache_key)
        if cached is not None:
            self._query_index_cache.move_to_end(cache_key)
            return cached

        if allowed is not None:
            matched_names = [n for n in matched_names if n in allowed]

        def _store(value: str) -> str:
            self._query_index_cache[cache_key] = value
            self._query_index_cache.move_to_end(cache_key)
            while len(self._query_index_cache) > self.QUERY_CACHE_CAP:
                self._query_index_cache.popitem(last=False)
            return value

        if not matched_names:
            return _store("")

        # Build index from matched skills only
        matched_skills = [self._skills[n] for n in matched_names if n in self._skills]

        # Many matches → names only; few matches → the trigger line is worth
        # it.  Applies to the query path only: the unfiltered first-turn index
        # is exactly where the model needs the "when to use" line, and
        # collapsing it to bare names would cost skill discovery to save
        # ~1.1K chars.
        use_compact = compact or (
            bool(query) and len(matched_skills) > self.INDEX_DETAIL_CAP
        )

        if use_compact:
            names = [s['name'] for s in matched_skills if s.get("enabled", True)]
            result = ", ".join(sorted(names))
        else:
            lines = ["Available Skills:"]
            for skill in matched_skills:
                if skill.get("enabled", True):
                    lines.append(
                        f"- **{skill['name']}**: {skill_index_hint(skill)}",
                    )
            result = "\n".join(lines)

        return _store(result)
