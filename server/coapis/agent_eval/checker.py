# -*- coding: utf-8 -*-
"""Checker suite: deterministic checks + optional LLM-judge for rubrics.

Scoring model (per task):
* Every deterministic check contributes a weighted fraction.
* ``rubric`` (free-text quality bar) is scored 0..1 by the LLM judge.
* Final score = mean of all component scores; verdict thresholds:
  pass >= 0.8, partial >= 0.5, else fail.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

PASS_THRESHOLD = 0.8
PARTIAL_THRESHOLD = 0.5

# weights per check type (sum-normalized per task)
_WEIGHTS = {
    "answer_contains": 1.0,
    "answer_contains_any": 0.8,
    "answer_not_contains": 0.8,
    "min_tool_calls": 1.0,
    "max_tool_calls": 1.0,
    "expected_tool": 1.0,
    "forbidden_tool": 1.0,
    "min_answer_length": 0.6,
    "min_llm_calls": 0.5,
    "rubric": 1.2,
}


class CheckResult:
    def __init__(self, name: str, passed: bool, weight: float, detail: str = "") -> None:
        self.name = name
        self.passed = passed
        self.weight = weight
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.name, "passed": self.passed,
                "weight": self.weight, "detail": self.detail}


class CheckerSuite:
    """Evaluate one run against a task's checks."""

    def __init__(self, judge: Optional[Callable[[str, str], tuple[float, str]]] = None) -> None:
        self.judge = judge  # fn(question, rubric) -> (score 0..1, reason)

    async def evaluate(
        self,
        task: dict[str, Any],
        final_answer: str,
        tool_call_names: list[str],
        llm_calls: int,
    ) -> dict[str, Any]:
        checks: list[CheckResult] = []
        answer = (final_answer or "").strip()

        for kw, val in (task.get("checks") or {}).items():
            fn = getattr(self, f"_check_{kw}", None)
            if fn is None:
                continue
            res = fn(val, answer, tool_call_names, llm_calls)
            if res:
                checks.append(res)

        if task.get("expected_tools"):
            for tool in task["expected_tools"]:
                checks.append(CheckResult(
                    f"expected_tool:{tool}",
                    tool in tool_call_names,
                    _WEIGHTS["expected_tool"],
                    "called" if tool in tool_call_names else "never called",
                ))
        if task.get("forbid_tools"):
            for tool in task["forbid_tools"]:
                checks.append(CheckResult(
                    f"forbidden_tool:{tool}",
                    tool not in tool_call_names,
                    _WEIGHTS["forbidden_tool"],
                    "violated" if tool in tool_call_names else "clean",
                ))

        rubric_res: Optional[CheckResult] = None
        if task.get("rubric") and self.judge is not None:
            try:
                score, reason = await self.judge(final_answer or "", task["rubric"])
                rubric_res = CheckResult("rubric", score >= PARTIAL_THRESHOLD,
                                         _WEIGHTS["rubric"],
                                         f"score={score:.2f}; {reason}")
                checks.append(rubric_res)
            except Exception as exc:  # noqa: BLE001 - judge failure != task failure
                checks.append(CheckResult("rubric", False, _WEIGHTS["rubric"],
                                          f"judge error: {exc}"))

        total_w = sum(c.weight for c in checks) or 1.0
        earned = sum(c.weight for c in checks if c.passed)
        score = round(earned / total_w, 4)
        verdict = "pass" if score >= PASS_THRESHOLD else (
            "partial" if score >= PARTIAL_THRESHOLD else "fail")
        return {
            "score": score,
            "verdict": verdict,
            "success": verdict == "pass",
            "checks": [c.to_dict() for c in checks],
            "rubric_score": (rubric_res.detail.split(";")[0] if rubric_res else None),
        }

    # -------------------------------------------------------------- #
    # individual checkers
    # -------------------------------------------------------------- #
    def _check_answer_contains(self, vals: list[str], answer: str,
                               tools: list[str], llm: int) -> CheckResult:
        missing = [v for v in vals if v not in answer]
        return CheckResult("answer_contains", not missing, _WEIGHTS["answer_contains"],
                           f"missing: {missing}" if missing else "ok")

    def _check_answer_contains_any(self, vals: list[str], answer: str,
                                   tools: list[str], llm: int) -> CheckResult:
        hit = next((v for v in vals if v in answer), None)
        return CheckResult("answer_contains_any", hit is not None,
                           _WEIGHTS["answer_contains_any"],
                           f"hit: {hit}" if hit else f"none of {vals} found")

    def _check_answer_not_contains(self, vals: list[str], answer: str,
                                   tools: list[str], llm: int) -> CheckResult:
        bad = [v for v in vals if v in answer]
        return CheckResult("answer_not_contains", not bad, _WEIGHTS["answer_not_contains"],
                           f"found forbidden: {bad}" if bad else "ok")

    def _check_min_tool_calls(self, val: int, answer: str,
                              tools: list[str], llm: int) -> CheckResult:
        ok = len(tools) >= int(val)
        return CheckResult("min_tool_calls", ok, _WEIGHTS["min_tool_calls"],
                           f"{len(tools)} >= {val}")

    def _check_max_tool_calls(self, val: int, answer: str,
                              tools: list[str], llm: int) -> CheckResult:
        ok = len(tools) <= int(val)
        return CheckResult("max_tool_calls", ok, _WEIGHTS["max_tool_calls"],
                           f"{len(tools)} <= {val}")

    def _check_min_llm_calls(self, val: int, answer: str,
                             tools: list[str], llm: int) -> CheckResult:
        ok = llm >= int(val)
        return CheckResult("min_llm_calls", ok, _WEIGHTS["min_llm_calls"],
                           f"{llm} >= {val}")

    def _check_min_answer_length(self, val: int, answer: str,
                                 tools: list[str], llm: int) -> CheckResult:
        ok = len(answer) >= int(val)
        return CheckResult("min_answer_length", ok, _WEIGHTS["min_answer_length"],
                           f"len={len(answer)} >= {val}")
