"""SkillSelector — 意图驱动的技能选择器。

三级选择策略：
  Stage 1: 关键词精确匹配 (<1ms)
  Stage 2: LLM 意图分类 (~500ms, 可选)
  Stage 3: 兜底加载 always_load 技能

用法:
    selector = SkillSelector(config)
    selector.build_index(all_skills)
    selected = selector.select(user_message)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SkillSelector:
    """技能意图选择器 — 根据用户消息选择要加载的技能。"""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        # keyword (lowercase) → [skill_name, ...]
        self.keyword_index: dict[str, list[str]] = {}
        # skill_name → [keyword (lowercase), ...]
        self.skill_keywords: dict[str, list[str]] = {}
        # skill_name → full metadata dict
        self.skill_meta: dict[str, dict] = {}
        # always-load skill names
        self.always_load_skills: list[str] = []
        # whether index has been built
        self._built = False

    def build_index(self, skills: list[dict[str, Any]]) -> None:
        """Build keyword index from skill metadata list.

        Each skill dict should have at least:
          - name: str
          - dir: str (skill directory)
          And optionally:
          - trigger_keywords: list[str]
          - always_load: bool
        """
        self.keyword_index.clear()
        self.skill_keywords.clear()
        self.skill_meta.clear()
        self.always_load_skills.clear()

        for skill in skills:
            name = skill.get("name", "")
            if not name:
                continue

            self.skill_meta[name] = skill

            # Extract keywords, normalize to lowercase
            keywords = skill.get("trigger_keywords", [])
            kw_lower = [kw.lower() for kw in keywords if len(kw) >= self.config.get("min_keyword_length", 1)]
            self.skill_keywords[name] = kw_lower

            # Build inverted index
            for kw in kw_lower:
                if kw not in self.keyword_index:
                    self.keyword_index[kw] = []
                if name not in self.keyword_index[kw]:
                    self.keyword_index[kw].append(name)

            # Track always-load skills
            if skill.get("always_load", False):
                if name not in self.always_load_skills:
                    self.always_load_skills.append(name)

        self._built = True
        logger.info(
            "SkillSelector index built: %d skills, %d keywords, %d always-load",
            len(self.skill_meta), len(self.keyword_index), len(self.always_load_skills),
        )

    def select(self, user_message: str) -> list[str]:
        """Select skills matching the user message.

        Returns list of skill names to register.
        """
        if not self._built:
            logger.warning("SkillSelector index not built, returning always_load only")
            return list(self.always_load_skills)

        if not user_message or not user_message.strip():
            return list(self.always_load_skills)

        selected: list[str] = []

        # Stage 1: Keyword matching
        keyword_matched = self._keyword_match(user_message)
        if keyword_matched:
            selected.extend(keyword_matched)
            logger.debug("Keyword matched skills: %s", keyword_matched)

        # Stage 2: LLM classification (only if keyword didn't match)
        if not selected and self.config.get("enable_llm_fallback", True):
            llm_matched = self._llm_classify_sync(user_message)
            if llm_matched:
                selected.extend(llm_matched)
                logger.debug("LLM matched skills: %s", llm_matched)

        # Stage 3: Fallback to always_load
        if not selected:
            selected = list(self.always_load_skills)
            logger.debug("No match, using always_load: %s", selected)

        # Always include always_load skills
        for s in self.always_load_skills:
            if s not in selected:
                selected.append(s)

        # Deduplicate and cap
        seen = set()
        deduped = []
        max_skills = self.config.get("max_selected_skills", 15)
        for s in selected:
            if s not in seen and s in self.skill_meta:
                seen.add(s)
                deduped.append(s)
                if len(deduped) >= max_skills:
                    break

        return deduped

    def _keyword_match(self, message: str) -> list[str]:
        """Stage 1: Exact keyword matching."""
        message_lower = message.lower()
        matched: set[str] = set()

        for keyword, skill_names in self.keyword_index.items():
            if keyword in message_lower:
                for name in skill_names:
                    matched.add(name)

        return list(matched)

    def _llm_classify_sync(self, message: str) -> list[str]:
        """Stage 2: LLM intent classification (synchronous wrapper)."""
        # Build skill summaries for LLM
        skill_summaries = {}
        # Only send on-demand skills (non-always_load) to LLM
        for name, meta in self.skill_meta.items():
            if name in self.always_load_skills:
                continue
            desc = meta.get("description", "")
            hints = meta.get("intent_hints", "")
            if hints:
                skill_summaries[name] = f"{desc} ||| {hints}"
            else:
                skill_summaries[name] = desc

        if not skill_summaries:
            return []

        try:
            from .intent_classifier import classify_intent_llm
            import asyncio

            # Check if there's a running event loop
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context, schedule as task
                # This shouldn't happen in reply() flow, but handle it
                logger.debug("Skipping LLM classification (in async context)")
                return []
            except RuntimeError:
                # No running loop, safe to use asyncio.run()
                timeout = self.config.get("llm_timeout_ms", 3000) / 1000.0
                result = asyncio.run(
                    classify_intent_llm(message, skill_summaries, timeout=timeout)
                )
                if result:
                    logger.info("LLM classified skills: %s", result)
                return result or []

        except Exception as e:
            logger.debug("LLM classification failed: %s", e)
            return []

    def get_skill_dir(self, skill_name: str) -> str | None:
        """Get the directory path for a skill by name."""
        meta = self.skill_meta.get(skill_name)
        if meta:
            return meta.get("dir")
        return None

    def get_stats(self) -> dict:
        """Return index statistics."""
        return {
            "total_skills": len(self.skill_meta),
            "total_keywords": len(self.keyword_index),
            "always_load_count": len(self.always_load_skills),
            "always_load_skills": list(self.always_load_skills),
            "built": self._built,
        }
