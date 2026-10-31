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

# On-demand skills registry (set by _load_on_demand_skills)
_ON_DEMAND_SKILLS_REGISTRY: dict[str, dict] = {}
_REGISTRY_LOCK = threading.Lock()


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


def _parse_skill_names(raw: str, allowed: dict[str, str]) -> list[str]:
    """判官输出 → 技能名列表。

    只认注册表里真实存在的名字，绝不把模型随口说的名字当技能。一个都认不出
    来不算失败（那是"没命中"），但输出不成 JSON 就算解析失败，交网关降级。
    """
    text = raw.strip()
    match = re.search(r"\[[^\]]*\]", text)
    if match:
        text = match.group(0)
    try:
        names = json.loads(text)
    except Exception as exc:  # noqa: BLE001 - 交给网关记 parse_fail
        raise ValueError(f"判官输出不是 JSON 数组: {raw[:80]!r}") from exc
    if not isinstance(names, list):
        raise ValueError(f"判官输出不是数组: {raw[:80]!r}")
    return [n for n in names if isinstance(n, str) and n in allowed]


async def classify_intent_llm(
    user_message: str,
    skill_summaries: dict[str, str],
    scope: dict | None = None,
) -> list[str]:
    """语义兜底判断走判断网关（v14 §4.4③）。

    超时、缓存、共用熔断、轮内预算、台账都在网关里；本模块只提供提示词与
    解析器。网关降级时返回空列表 = 不预激活（关键词层已经判过，不重复拦）。

    ``scope`` 是 ``{user_id, agent_id, chat_id, turn}``，调用方显式传，
    台账才知道这次判断属于谁的哪一轮。
    """
    from coapis.decision import get_judge_gateway

    reply = await get_judge_gateway().judge(
        purpose="skill_trigger",
        system="",
        user=_build_classify_prompt(user_message, skill_summaries),
        parse=lambda raw: _parse_skill_names(raw, skill_summaries),
        describe=(
            lambda names: ("预激活" + ",".join(names[:3]))
            if names else "无技能命中"
        ),
        scope=scope,
    )
    return list(reply.value or [])



def get_classification_cache_stats() -> dict:
    """Return cache statistics."""
    with _CACHE_LOCK:
        return {
            "size": len(_CLASSIFICATION_CACHE),
            "ttl_seconds": _CACHE_TTL,
        }
