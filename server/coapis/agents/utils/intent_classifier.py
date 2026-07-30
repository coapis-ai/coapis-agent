"""Intent classifier for on-demand skill triggering.

Two-tier strategy:
1. Keyword matching (fast, zero cost, no LLM dependency)
2. LLM classification (richer semantics, higher cost)

Keyword matching is the primary method. LLM fallback only
runs when the keyword index returns no matches. This eliminates
the 5-second LLM latency for the majority of skill triggers.
"""

from __future__ import annotations

import json
import logging
import os
import hashlib
import re
import time
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cache for classification results (query_hash -> (skills, timestamp))
_CLASSIFICATION_CACHE: dict[str, tuple[list[str], float]] = {}
_CACHE_TTL = 300  # 5 minutes
_CACHE_LOCK = threading.Lock()

# Provider config cache
_PROVIDER_CONFIG: dict | None = None

# On-demand skills registry (set by _load_on_demand_skills)
_ON_DEMAND_SKILLS_REGISTRY: dict[str, dict] = {}
_REGISTRY_LOCK = threading.Lock()


def _get_provider_config() -> dict | None:
    """Read LLM provider config from ProviderManager."""
    global _PROVIDER_CONFIG
    if _PROVIDER_CONFIG is not None:
        return _PROVIDER_CONFIG

    try:
        from coapis.providers.provider_manager import ProviderManager
        pm = ProviderManager.get_instance()
        # 优先使用 active model
        active = pm.get_active_model()
        if active:
            provider = pm.get_provider(active.provider_id)
            if provider and provider.base_url:
                _PROVIDER_CONFIG = {
                    "api_base": provider.base_url.rstrip("/"),
                    "api_key": provider.api_key or "none",
                    "model": active.model,
                }
                logger.debug("Intent classifier using active model: %s/%s", active.provider_id, active.model)
                return _PROVIDER_CONFIG
        # 回退：找第一个有模型且配置好的 provider
        for pid, provider in {**pm.builtin_providers, **pm.custom_providers}.items():
            if provider.models and provider.base_url:
                _PROVIDER_CONFIG = {
                    "api_base": provider.base_url.rstrip("/"),
                    "api_key": provider.api_key or "none",
                    "model": provider.models[0].id,
                }
                logger.debug("Intent classifier using provider: %s/%s", pid, provider.models[0].id)
                return _PROVIDER_CONFIG
    except Exception as e:
        logger.debug("Failed to read provider config from ProviderManager: %s", e)
    return None


def _build_classify_prompt(
    user_message: str,
    skill_summaries: dict[str, str],
) -> str:
    """Build a classification prompt with full descriptions and few-shot examples.

    Uses complete skill descriptions (not truncated) and includes
    intent_hints if available for better classification accuracy.
    """
    # 构建技能列表，使用完整描述
    skill_entries = []
    for name, desc in skill_summaries.items():
        # desc 可能是 "description ||| intent_hints" 格式
        if " ||| " in desc:
            main_desc, hints = desc.split(" ||| ", 1)
            skill_entries.append(f"- {name}: {main_desc}\n  意图提示: {hints}")
        else:
            skill_entries.append(f"- {name}: {desc}")
    skill_list = "\n".join(skill_entries)

    # few-shot 示例
    examples = """示例:
- "帮我写个报告" → ["axu-report-writing"]
- "把这个PDF转成图片" → ["pdf"]
- "创建一个Excel表格" → ["xlsx"]
- "做个演示文稿" → ["pptx"]
- "帮我写个Word文档" → ["docx"]
- "分析一下这些数据" → ["axu-data-analysis"]
- "帮我看看这个政策" → ["axu-policy-interpretation"]
- "润色一下这段文字" → ["axu-text-polishing"]"""

    return f"""你是一个技能分类器。根据用户消息和可用技能列表，判断哪些技能与用户意图相关。

可用技能:
{skill_list}

{examples}

用户消息: {user_message}

请返回与用户意图相关的技能名称 JSON 数组。只返回 JSON 数组，不要其他内容。
如果没有技能匹配，返回空数组 []。

相关技能 (仅 JSON 数组):"""


def classify_intent_keywords(
    user_message: str,
    skill_summaries: dict[str, str],
) -> list[str]:
    """Keyword-based intent classification as primary method.

    Matches user message against registered on-demand skill trigger
    keywords and descriptions. Fast, free, and available without
    an LLM provider.

    Args:
        user_message: The user's input message.
        skill_summaries: Dict of skill_name -> short description.

    Returns:
        List of matching skill names, or empty list if no match.
    """
    if not user_message or not skill_summaries:
        return []

    msg_lower = user_message.lower()
    matched: list[str] = []

    with _REGISTRY_LOCK:
        for skill_name, skill_data in _ON_DEMAND_SKILLS_REGISTRY.items():
            trigger_keywords = skill_data.get("trigger_keywords", [])
            summary = skill_summaries.get(skill_name, "")
            all_keywords = trigger_keywords + [summary.lower()]

            for kw in all_keywords:
                kw_lower = kw.lower().strip()
                if not kw_lower:
                    continue
                if kw_lower in msg_lower:
                    matched.append(skill_name)
                    break

    return matched


def register_on_demand_skills(skills: dict[str, dict]) -> None:
    """Register on-demand skills in the keyword classifier registry.

    Called during skill registration to populate the keyword index.
    Idempotent — safe to call repeatedly.

    Args:
        skills: Dict of skill_name -> {"trigger_keywords": [...], "description": "..."}
    """
    with _REGISTRY_LOCK:
        for skill_name, data in skills.items():
            _ON_DEMAND_SKILLS_REGISTRY[skill_name] = data


async def classify_intent_llm(
    user_message: str,
    skill_summaries: dict[str, str],
    timeout: float = 5.0,
) -> list[str] | None:
    """Classify user intent and return matching skill names.

    Primary: keyword matching (instant, no LLM cost).
    Fallback: LLM classification (richer semantics).

    Returns:
        List of matching skill names, or None if both methods failed.
    """
    if not skill_summaries:
        return []

    # Phase 1: keyword matching (cheap, instant)
    keyword_matches = classify_intent_keywords(user_message, skill_summaries)
    if keyword_matches:
        logger.debug(
            "Intent classifier: keyword match: user_msg=%s -> skills=%s",
            user_message[:50], keyword_matches,
        )
        return keyword_matches

    # Phase 2: no keyword matches, try LLM classification
    config = _get_provider_config()
    if not config:
        logger.debug("No LLM provider configured for intent classification")
        return None

    # Check cache
    cache_key = hashlib.md5(
        user_message.lower().strip().encode()
    ).hexdigest()[:16]
    with _CACHE_LOCK:
        cached = _CLASSIFICATION_CACHE.get(cache_key)
        if cached and time.monotonic() - cached[1] < _CACHE_TTL:
            logger.debug("Intent classifier cache hit")
            return cached[0]

    try:
        import httpx

        prompt = _build_classify_prompt(user_message, skill_summaries)
        payload = {
            "model": config["model"],
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 512,  # Thinking models need space for reasoning chain
            "temperature": 0.0,
        }
        headers = {
            "Content-Type": "application/json",
        }
        if config["api_key"] and config["api_key"] != "none":
            headers["Authorization"] = f"Bearer {config['api_key']}"

        url = f"{config['api_base']}/chat/completions"

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # Extract response text — handle thinking models (reasoning field)
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = (message.get("content") or "").strip()

        # Fallback: extract JSON array from reasoning field (thinking models)
        if not content:
            reasoning = (message.get("reasoning") or "").strip()
            if reasoning:
                import re
                match = re.search(r'\[[\s\S]*?\]', reasoning)
                if match:
                    content = match.group()

        if not content:
            logger.debug(
                "LLM returned empty content (finish_reason=%s)",
                choice.get("finish_reason"),
            )
            return None

        # Parse JSON array from response
        # Handle markdown code blocks
        if "```" in content:
            import re
            match = re.search(r'\[.*?\]', content, re.DOTALL)
            if match:
                content = match.group()

        skills = json.loads(content)
        if not isinstance(skills, list):
            return None

        # Validate skill names exist in the summaries
        valid_skills = [s for s in skills if s in skill_summaries]

        # Cache result
        with _CACHE_LOCK:
            _CLASSIFICATION_CACHE[cache_key] = (valid_skills, time.monotonic())
            # Evict old entries
            if len(_CLASSIFICATION_CACHE) > 500:
                cutoff = time.monotonic() - _CACHE_TTL
                expired = [k for k, (_, ts) in _CLASSIFICATION_CACHE.items() if ts < cutoff]
                for k in expired:
                    del _CLASSIFICATION_CACHE[k]

        logger.info(
            "LLM intent classification: user_msg=%s -> skills=%s",
            user_message[:50], valid_skills,
        )
        return valid_skills

    except Exception as e:
        logger.debug("LLM intent classification failed: %s", e)
        return None


def get_classification_cache_stats() -> dict:
    """Return cache statistics."""
    with _CACHE_LOCK:
        return {
            "size": len(_CLASSIFICATION_CACHE),
            "ttl_seconds": _CACHE_TTL,
        }
