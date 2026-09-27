# -*- coding: utf-8 -*-
"""LLM-as-a-Judge: score free-text rubrics 0..1 with a strict prompt."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

JUDGE_PROMPT = """你是一名严格的智能体评测裁判。请依据评分细则给智能体的最终回答打分。

【用户任务】{question}
【智能体最终回答】
{answer}

【评分细则】
{rubric}

评分规则：
- 满分 1.0，最低 0.0，允许两位小数。
- 只依据回答本身与细则的吻合度打分，不要奖励客套话。
- 编造事实、偏离细则核心要求应显著扣分。

请严格按以下 JSON 输出（不要输出任何其他文字）：
{{"score": 0.0, "reason": "一句话理由"}}
"""


class LLMJudge:
    """Calls a chat-completion callable and parses the structured verdict.

    ``model_fn`` signature: ``async (system_prompt: str, user_prompt: str) -> str``
    (returns raw assistant text). Kept transport-agnostic so tests can inject
    a fake; production wires it to the eval agent's own model client.
    """

    def __init__(self, model_fn: Any, temperature: float = 0.0) -> None:
        self.model_fn = model_fn
        self.temperature = temperature

    async def score(self, question: str, answer: str,
                    rubric: str) -> tuple[float, str]:
        prompt = JUDGE_PROMPT.format(question=question, answer=answer[:4000],
                                     rubric=rubric)
        raw = await self.model_fn("", prompt)
        return parse_judge_output(raw)


def parse_judge_output(raw: str) -> tuple[float, str]:
    """Robustly extract (score, reason) from judge output."""
    text = (raw or "").strip()
    # strip markdown fences if present
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    brace = re.search(r"\{.*\}", text, re.S)
    if brace:
        text = brace.group(0)
    try:
        obj = json.loads(text)
        score = float(obj.get("score", 0.0))
        return max(0.0, min(1.0, score)), str(obj.get("reason", ""))[:500]
    except (ValueError, TypeError, AttributeError):
        m = re.search(r"score[\"']?\s*[:=]\s*([01](?:\.\d+)?)", text)
        if m:
            return max(0.0, min(1.0, float(m.group(1)))), "parsed from text"
        return 0.0, "unparseable judge output"
