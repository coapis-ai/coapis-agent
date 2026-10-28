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
import re
from typing import Any

logger = logging.getLogger(__name__)


class SkillSelector:
    """技能意图选择器 — 根据用户消息选择要加载的技能。"""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        scene_skills: list[str] | None = None,
    ):
        self.config = config or {}
        # keyword (lowercase) → [skill_name, ...]
        self.keyword_index: dict[str, list[str]] = {}
        # skill_name → [keyword (lowercase), ...]
        self.skill_keywords: dict[str, list[str]] = {}
        # skill_name → full metadata dict
        self.skill_meta: dict[str, dict] = {}
        #: ``triggers.patterns`` per skill, kept as regexes (see
        #: _extract_frontmatter_patterns) and matched in _score_skill.
        self.skill_patterns: dict[str, list[str]] = {}
        # always-load skill names
        self.always_load_skills: list[str] = []
        # Scene priority skills, ordered by scene config order (= priority).
        # Declared by scene config → authoritative source for Stage 0.
        self.scene_skills: list[str] = [s for s in (scene_skills or []) if s]
        # skill_name → {keyword (lowercase) → weight}: frontmatter triggers
        # carry double weight vs. description-derived keywords (S5).
        self._kw_weight: dict[str, dict[str, int]] = {}
        # whether index has been built
        self._built = False

    # ── S3: frontmatter trigger parsing ──

    @staticmethod
    def _extract_frontmatter_keywords(skill_dir: str) -> list[str]:
        """Collect trigger keywords declared in SKILL.md frontmatter.

        Reads, in priority order:
          - top-level ``trigger_keywords``
          - ``triggers.keywords``
          - ``triggers.intent_hints``
          - top-level ``trigger`` (free text, split on separators)

        ``triggers.patterns`` is handled by _extract_frontmatter_patterns and
        the regex channel in _score_skill, not here.
        """
        import os
        import yaml

        md_file = os.path.join(skill_dir, "SKILL.md")
        if not os.path.exists(md_file):
            return []
        try:
            content = open(md_file, encoding="utf-8").read()
            if not content.startswith("---"):
                return []
            parts = content.split("---", 2)
            if len(parts) < 3:
                return []
            meta = yaml.safe_load(parts[1]) or {}
            if not isinstance(meta, dict):
                return []

            collected: list[str] = []
            top_kw = meta.get("trigger_keywords", [])
            if isinstance(top_kw, list):
                collected.extend(str(k) for k in top_kw if k)

            triggers = meta.get("triggers", {})
            if isinstance(triggers, dict):
                # ``patterns`` is NOT collected here: they are regexes, and a
                # regex string compared as a literal substring can never match
                # a user message.  They go to the regex channel instead
                # (see _extract_frontmatter_patterns / _score_skill).
                for key in ("keywords", "intent_hints"):
                    vals = triggers.get(key, [])
                    if isinstance(vals, list):
                        collected.extend(str(v) for v in vals if v)
            elif isinstance(triggers, list):
                collected.extend(str(v) for v in triggers if v)

            trigger_str = meta.get("trigger", "")
            if isinstance(trigger_str, str) and trigger_str:
                for piece in trigger_str.replace("；", ",").replace("，", ",").split(","):
                    piece = piece.strip()
                    if piece:
                        collected.append(piece)

            # Deduplicate, keep order
            seen: set[str] = set()
            ordered: list[str] = []
            for kw in collected:
                low = kw.lower()
                if low not in seen:
                    seen.add(low)
                    ordered.append(kw)
            return ordered
        except Exception as e:  # pragma: no cover — frontmatter parse is best-effort
            logger.debug("frontmatter trigger parse failed for %s: %s", skill_dir, e)
            return []

    def build_index(
        self,
        skills: "list[dict[str, Any]] | dict[str, dict[str, Any]]",
        scene_skills: list[str] | None = None,
    ) -> None:
        """Build keyword index from skill metadata.

        Accepts either a list of skill dicts (each carrying ``name``) or a
        dict keyed by skill name (the metadata dict produced in
        ``CoAPIsAgent._register_skills``). ``scene_skills`` overrides the
        scene-declared priority set.

        Each skill dict should have at least:
          - name: str
          - dir: str (skill directory)
          And optionally:
          - trigger_keywords: list[str]
          - keyword_weights: dict[str, float]  (explicit per-keyword weight)
          - always_load: bool
        """
        if isinstance(skills, dict):
            skills = [{**meta, "name": name} for name, meta in skills.items()]

        if scene_skills is not None:
            self.scene_skills = list(scene_skills)

        self.keyword_index.clear()
        self.skill_keywords.clear()
        self.skill_meta.clear()
        self.skill_patterns.clear()
        self.always_load_skills.clear()

        for skill in skills:
            name = skill.get("name", "")
            if not name:
                continue

            self.skill_meta[name] = skill

            # Extract keywords, normalize to lowercase.
            # Declared triggers (frontmatter) carry double weight (S5);
            # description-derived keywords keep weight 1.
            weights: dict[str, int] = {}
            for kw in skill.get("trigger_keywords", []):
                if len(kw) >= self.config.get("min_keyword_length", 1):
                    low = kw.lower()
                    if weights.get(low, 0) < 2:
                        weights[low] = 2
            # S3: frontmatter trigger / triggers.{keywords,patterns,intent_hints}
            for kw in self._extract_frontmatter_keywords(skill.get("dir", "")):
                if len(kw) >= self.config.get("min_keyword_length", 1):
                    low = kw.lower()
                    if weights.get(low, 0) < 2:
                        weights[low] = 2
            # triggers.patterns → regex channel (never literal keywords)
            self.skill_patterns[name] = self._extract_frontmatter_patterns(
                skill.get("dir", ""),
            )
            # Description text is NOT a keyword source: splitting free-form
            # prose floods the index with generic verbs (进行/加密/表格/创建…)
            # that fire on unrelated messages. Only explicit, high-precision
            # signals are admitted: declared triggers, file suffixes, and the
            # skill's own name.
            for kw in self._extract_suffixes(skill.get("description", "")):
                low = kw.lower()
                if weights.get(low, 0) < 2:
                    weights[low] = 2
            name_kw = name.lower()
            if len(name_kw) >= self.config.get("min_keyword_length", 1):
                if weights.get(name_kw, 0) < 2:
                    weights[name_kw] = 2

            # Explicit caller-supplied weights (e.g. pre-computed frontmatter
            # weights in a metadata dict) win at their declared value, never
            # below what we derived from description text.
            for kw, w in (skill.get("keyword_weights") or {}).items():
                low = kw.lower()
                if len(low) >= self.config.get("min_keyword_length", 1):
                    if weights.get(low, 0) < float(w):
                        weights[low] = float(w)

            self.skill_keywords[name] = list(weights.keys())
            self._kw_weight[name] = weights

            # Build inverted index
            for kw in weights:
                if kw not in self.keyword_index:
                    self.keyword_index[kw] = []
                if name not in self.keyword_index[kw]:
                    self.keyword_index[kw].append(name)

            # Track always-load skills
            if skill.get("always_load", False):
                if name not in self.always_load_skills:
                    self.always_load_skills.append(name)

        # Scene-declared skills missing from the index are ghosts — surface them.
        for scene_skill in self.scene_skills:
            if scene_skill not in self.skill_meta:
                logger.warning(
                    "[SceneGhost] scene declares skill '%s' but it is not "
                    "installed in this workspace — it can never trigger.",
                    scene_skill,
                )

        self._built = True
        logger.info(
            "SkillSelector index built: %d skills, %d keywords, %d always-load, %d scene-priority",
            len(self.skill_meta), len(self.keyword_index),
            len(self.always_load_skills), len(self.scene_skills),
        )

    def select(
        self,
        user_message: str,
        scene_skills: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[str]:
        """Select skills matching the user message.

        ``scene_skills`` (ordered by scene config = priority order) is the
        authoritative Stage 0 candidate set: scene-declared skills that match
        the message are selected ahead of everything else. ``top_k`` caps the
        result for callers that want a smaller set than the configured maximum.
        """
        prepared = self._prepare_selection(user_message, scene_skills)
        if prepared is None:
            return list(self.always_load_skills)
        scene_names, selected = prepared

        # Stage 2: LLM classification (only if keyword didn't match)
        if not selected and self.config.get("enable_llm_fallback", True):
            llm_matched = self._llm_classify_sync(
                user_message, self._llm_candidates(scene_names),
            )
            if llm_matched:
                selected.extend(llm_matched)
                logger.debug("LLM matched skills: %s", llm_matched)

        return self._finalize_selection(selected, top_k)

    async def select_async(
        self,
        user_message: str,
        scene_skills: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[str]:
        """异步入口（第0批 F1）：Stage 2 兜底判 **await 直连**。

        ``select()`` 在已有事件循环的上下文里无法 await，只能告警跳过；
        异步调用链（reply() 等）应使用本方法，兜底判不再静默失效。
        """
        prepared = self._prepare_selection(user_message, scene_skills)
        if prepared is None:
            return list(self.always_load_skills)
        scene_names, selected = prepared

        if not selected and self.config.get("enable_llm_fallback", True):
            llm_matched = await self._llm_classify(
                user_message, self._llm_candidates(scene_names),
            )
            if llm_matched:
                selected.extend(llm_matched)
                logger.debug("LLM matched skills: %s", llm_matched)

        return self._finalize_selection(selected, top_k)

    def _prepare_selection(
        self,
        user_message: str,
        scene_skills: list[str] | None,
    ) -> tuple[list[str], list[str]] | None:
        """Stage 0（场景优先）+ Stage 1（关键词）。

        Returns ``(scene_names, selected)``; ``None`` when there is nothing
        to select from (index not built / empty message).
        """
        if not self._built:
            logger.warning("SkillSelector index not built, returning always_load only")
            return None

        if not user_message or not user_message.strip():
            return None

        scene_names = list(scene_skills) if scene_skills is not None else self.scene_skills
        selected: list[str] = []

        # Stage 0: Scene priority — scene-declared skills that match go first.
        scene_matched = [
            n for n in scene_names
            if n in self.skill_meta and self._score_skill(user_message, n) > 0
        ]
        if scene_matched:
            selected.extend(scene_matched)
            logger.debug("Scene-priority matched skills: %s", scene_matched)

        # Stage 1: Keyword matching (weighted, scene skills boosted)
        keyword_matched = self._keyword_match(user_message, scene_names)
        if keyword_matched:
            selected.extend(keyword_matched)
            logger.debug("Keyword matched skills: %s", keyword_matched)

        return scene_names, selected

    def _llm_candidates(self, scene_names: list[str]) -> list[str] | None:
        """When keywords found nothing, restrict LLM candidates to the scene
        skill set — the scene config is the best prior we have."""
        if scene_names:
            return [n for n in scene_names if n in self.skill_meta]
        return None

    def _finalize_selection(
        self,
        selected: list[str],
        top_k: int | None,
    ) -> list[str]:
        """Stage 3（always_load 兜底）+ 去重 + 上限截断。"""
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
        max_skills = (
            top_k if top_k is not None
            else self.config.get("max_selected_skills", 15)
        )
        for s in selected:
            if s not in seen and s in self.skill_meta:
                seen.add(s)
                deduped.append(s)
                if len(deduped) >= max_skills:
                    break

        return deduped

    def _extract_frontmatter_patterns(self, skill_dir: str) -> list[str]:
        """Read ``triggers.patterns`` as **regexes** for the regex channel.

        These were previously fed through the literal-keyword path, where a
        pattern like ``^上传.*文件`` is a string no user message contains —
        so every skill that expressed its triggers as patterns (cron,
        make-skill, pdf, xlsx, …) had declarations that could never fire.
        Invalid regexes are dropped with a warning rather than killing the
        selector.
        """
        import os

        if not skill_dir:
            return []
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if not os.path.exists(skill_md):
            return []
        try:
            content = open(skill_md, encoding="utf-8", errors="replace").read()
        except OSError:
            return []
        if not content.startswith("---"):
            return []
        parts = content.split("---", 2)
        if len(parts) < 3:
            return []
        try:
            import yaml

            meta = yaml.safe_load(parts[1])
        except Exception:
            return []
        if not isinstance(meta, dict):
            return []

        raw: list[str] = []
        triggers = meta.get("triggers", {})
        if isinstance(triggers, dict):
            vals = triggers.get("patterns", {})
            if isinstance(vals, list):
                raw.extend(str(v) for v in vals if v)
        out: list[str] = []
        for pat in raw:
            try:
                re.compile(pat)
            except re.error as exc:
                logger.warning(
                    "Skill %s: invalid trigger pattern %r (%s) — skipped",
                    os.path.basename(str(skill_dir)), pat, exc,
                )
                continue
            out.append(pat)
        return out

    @staticmethod
    def _extract_suffixes(description: str) -> list[str]:
        """Extract explicit file-suffix signals from a description.

        Only dotted extensions (``.pdf``, ``.docx`` …) are admitted as
        keywords. Free-form description prose is deliberately not a keyword
        source — it produced false positives such as a speech-draft message
        matching the pdf/pptx/xlsx skills via generic verbs like 进行/加密.
        """
        if not description:
            return []
        import re

        seen: set[str] = set()
        out: list[str] = []
        for m in re.finditer(r"\.([A-Za-z][A-Za-z0-9]{1,7})", description):
            low = m.group(1).lower()
            if low not in seen:
                seen.add(low)
                out.append(low)
        return out

    def _score_skill(self, message: str, skill_name: str) -> int:
        """Weighted keyword score for one skill.

        Frontmatter-declared triggers count double (S5); description-derived
        keywords count once.  ``triggers.patterns`` are matched as regexes
        here — the channel they were always meant to have; as literal
        keywords they could never fire.
        """
        message_lower = message.lower()
        weights = self._kw_weight.get(skill_name, {})
        score = 0
        for kw, w in weights.items():
            if kw in message_lower:
                score += w
        for pat in self.skill_patterns.get(skill_name, ()):
            try:
                if re.search(pat, message, re.IGNORECASE):
                    score += 2
            except re.error:
                continue
        return score

    def keyword_match_weighted(
        self,
        message: str,
        scene_skills: list[str] | None = None,
    ) -> list[str]:
        """Keyword matching sorted by weighted score (descending).

        Scene-declared skills get a boost so they win ties — this is the
        "scene priority" contract (S1/S2).
        """
        scene_names = list(scene_skills) if scene_skills is not None else self.scene_skills
        scored: dict[str, int] = {}
        for name in self.skill_meta:
            score = self._score_skill(message, name)
            if score > 0:
                scored[name] = score
        if not scored:
            return []
        scene_rank = {n: i for i, n in enumerate(scene_names)}
        ordered = sorted(
            scored.items(),
            key=lambda kv: (-(kv[1] + (10 if kv[0] in scene_rank else 0)),
                            scene_rank.get(kv[0], 99), kv[0]),
        )
        return [n for n, _ in ordered]

    def _keyword_match(self, message: str, scene_skills: list[str] | None = None) -> list[str]:
        """Stage 1: Weighted keyword matching, scene skills boosted."""
        return self.keyword_match_weighted(message, scene_skills)

    def _llm_timeout_s(self) -> float:
        """兜底判超时（秒），来自 ``llm_timeout_ms``，默认 3s。"""
        try:
            return max(0.5, float(self.config.get("llm_timeout_ms", 3000)) / 1000.0)
        except (TypeError, ValueError):
            return 3.0

    def _llm_summaries(
        self,
        candidates: "dict[str, dict] | list[str] | None" = None,
    ) -> dict[str, str]:
        """Build skill summaries for the LLM classifier.

        ``candidates`` restricts the pool to a specific skill set — used for
        scene-priority matching (S2.3) so the LLM only picks among the scene's
        declared skills. Accepts a name list or a metadata dict.
        """
        skill_summaries: dict[str, str] = {}
        if isinstance(candidates, list):
            pool = {n: self.skill_meta[n] for n in candidates if n in self.skill_meta}
        else:
            pool = candidates if candidates is not None else self.skill_meta
        # Only send on-demand skills (non-always_load) to LLM
        for name, meta in pool.items():
            if name in self.always_load_skills:
                continue
            desc = meta.get("description", "")
            hints = meta.get("intent_hints", "")
            if hints:
                skill_summaries[name] = f"{desc} ||| {hints}"
            else:
                skill_summaries[name] = desc
        return skill_summaries

    async def _llm_classify(
        self,
        message: str,
        candidates: "dict[str, dict] | list[str] | None" = None,
    ) -> list[str]:
        """Stage 2 兜底判（异步原生，第0批 F1）。

        超时/异常均返回 ``[]`` 并在日志留痕——不再静默吞掉。
        """
        import asyncio

        skill_summaries = self._llm_summaries(candidates)
        if not skill_summaries:
            logger.debug("LLM classification skipped: no skill summaries")
            return []

        timeout = self._llm_timeout_s()
        try:
            from .intent_classifier import classify_intent_llm

            result = await asyncio.wait_for(
                classify_intent_llm(message, skill_summaries, timeout=timeout),
                timeout=timeout + 1.0,
            )
            if result:
                logger.info("LLM classified skills: %s", result)
            return result or []
        except asyncio.TimeoutError:
            logger.warning("LLM classification timed out (>%.1fs)", timeout)
            return []
        except Exception as e:
            logger.warning("LLM classification failed: %s", e)
            return []

    def _llm_classify_sync(
        self,
        message: str,
        candidates: "dict[str, dict] | list[str] | None" = None,
    ) -> list[str]:
        """Stage 2 兜底判的**同步**入口（仅适用于没有事件循环的上下文）。

        第0批 F1：删除「检测到事件循环就静默 ``return []``」的死分支。
        异步调用链请改用 ``select_async()`` / ``_llm_classify()``；真的落在
        事件循环内时明确 WARNING 留痕，不再无声失效。
        """
        import asyncio

        skill_summaries = self._llm_summaries(candidates)
        if not skill_summaries:
            return []

        try:
            from .intent_classifier import classify_intent_llm

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # No running loop, safe to use asyncio.run()
                timeout = self._llm_timeout_s()
                result = asyncio.run(
                    classify_intent_llm(message, skill_summaries, timeout=timeout)
                )
                if result:
                    logger.info("LLM classified skills: %s", result)
                return result or []

            logger.warning(
                "LLM 兜底判经同步入口调用但当前处于事件循环内，本次跳过；"
                "异步调用链请使用 SkillSelector.select_async()/_llm_classify()。"
            )
            return []

        except Exception as e:
            logger.warning("LLM classification failed: %s", e)
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
