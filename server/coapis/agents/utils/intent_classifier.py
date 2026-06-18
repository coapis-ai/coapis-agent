"""LLM-based intent classifier for on-demand skill triggering.

Uses a lightweight LLM call to classify user intent and match
to available on-demand skills. Falls back to keyword matching
if the LLM call fails or is unavailable.

Design:
- Fast: single short prompt, max_tokens=50, no streaming
- Cheap: uses the same LLM provider as the main agent
- Fallback: keyword matching always available as backup
- Cache: caches results for repeated similar queries
"""

from __future__ import annotations

import json
import logging
import os
import hashlib
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


def _get_provider_config() -> dict | None:
    """Read LLM provider config from system settings."""
    global _PROVIDER_CONFIG
    if _PROVIDER_CONFIG is not None:
        return _PROVIDER_CONFIG

    config_paths = [
        Path("/apps/ai/coapis/system/providers.json"),
        Path(os.environ.get("COAPIS_SYSTEM_DIR", "")) / "providers.json" if os.environ.get("COAPIS_SYSTEM_DIR") else None,
    ]

    for p in config_paths:
        if p and p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    providers = json.load(f)
                # Use the first available provider
                for name, cfg in providers.items():
                    api_base = cfg.get("api_base", "")
                    api_key = cfg.get("api_key", "none")
                    models = cfg.get("models", {})
                    if models:
                        model_id = next(iter(models.keys()))
                        _PROVIDER_CONFIG = {
                            "api_base": api_base.rstrip("/"),
                            "api_key": api_key,
                            "model": model_id,
                        }
                        logger.debug("Intent classifier using provider: %s/%s", name, model_id)
                        return _PROVIDER_CONFIG
            except Exception as e:
                logger.debug("Failed to read provider config from %s: %s", p, e)
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


async def classify_intent_llm(
    user_message: str,
    skill_summaries: dict[str, str],
    timeout: float = 5.0,
) -> list[str] | None:
    """Use LLM to classify user intent and return matching skill names.

    Args:
        user_message: The user's input message.
        skill_summaries: Dict of skill_name -> short description.
        timeout: Max seconds to wait for LLM response.

    Returns:
        List of matching skill names, or None if classification failed.
    """
    if not skill_summaries:
        return []

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
