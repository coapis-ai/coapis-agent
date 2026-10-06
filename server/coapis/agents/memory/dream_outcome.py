# -*- coding: utf-8 -*-
"""Pure outcome computation for the nightly dream consolidation.

Given the per-level results of :meth:`ReMeLightMemoryManager.dream`,
derive a 3-state outcome (``success`` / ``partial`` / ``failed``) plus a
machine-readable ``reason`` and a human-readable ``summary``. Kept as a
pure function so it is trivially unit-testable.

States (tech_docs/记忆能力升级-社区版可执行方案_v1.md §4.2):
- ``skipped``  — no input at all (no daily notes / empty memory md);
- ``success``  — every attempted level consolidated cleanly;
- ``partial``  — some levels succeeded, some errored;
- ``failed``   — every attempted level errored.
"""

from __future__ import annotations

from typing import Dict, Tuple

STATUS_SKIPPED = "skipped"
STATUS_SUCCESS = "success"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"

RESULT_OK = "ok"
RESULT_SKIPPED = "skipped"
RESULT_ERROR = "error"


def compute_dream_outcome(results: Dict[str, str]) -> Tuple[str, str, str]:
    """Compute (status, reason, summary) from per-level dream results.

    Args:
        results: mapping of level name (e.g. "L3") to one of
            ``RESULT_OK`` / ``RESULT_SKIPPED`` / ``RESULT_ERROR``.

    Returns:
        (status, reason, summary) — status is one of STATUS_*, reason is
        a snake_case machine token (``no_input`` / ``llm_error`` /
        ``mixed_levels``), summary lists ``level=result`` pairs.
    """
    if not results:
        return STATUS_SKIPPED, "no_input", "(no levels run)"

    oks = [lv for lv, r in results.items() if r == RESULT_OK]
    errs = [lv for lv, r in results.items() if r == RESULT_ERROR]
    skips = [lv for lv, r in results.items() if r == RESULT_SKIPPED]

    summary = ",".join(f"{lv}={r}" for lv, r in sorted(results.items()))

    if not oks and not errs:
        return STATUS_SKIPPED, "no_input", summary
    if not errs:
        return STATUS_SUCCESS, "consolidated", summary
    if not oks:
        return STATUS_FAILED, "llm_error", summary
    return STATUS_PARTIAL, "mixed_levels", summary
