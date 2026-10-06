# -*- coding: utf-8 -*-
"""Rule-based signal extraction from session transcript files.

Part of the integrated memory design (tech_docs/记忆系统整合设计方案.md
§5.2 step 3): the nightly dream scans the user's recent session files and
promotes *signals* — decisions / preferences / goals — into the memory
timeline table so the three layers stay connected.

Deliberately conservative:
- pure stdlib, no LLM (nightly batch cost must stay ~zero);
- keyword heuristics tuned for Chinese business conversations;
- per-file caps (``MAX_PER_FILE`` total, ``MAX_PER_TYPE`` per type) keep a
  chatty session from flooding the timeline;
- dedup happens downstream (timeline ``dedup_key``), so re-scanning the
  same file is safe.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

#: Sentence delimiters used to split message text into candidate units.
_SENTENCE_RE = re.compile(r"[。！？!?；;\n]+")

#: Minimum sentence length (chars) worth promoting — skips fragments.
_MIN_LEN = 6

#: Hard caps per session file.
MAX_PER_FILE = 20
MAX_PER_TYPE = 3

#: Keyword patterns per signal type (compiled once).
_SIGNAL_PATTERNS: Dict[str, "re.Pattern"] = {
    "decision": re.compile(
        r"(决定|拍板|敲定|选定|采纳|采用|就用|就用它|确认使用|按这个方案|"
        r"按.{0,10}(方案|做法|方式|来)|就这么(干|办|定)|同意|定了)"
    ),
    "preference": re.compile(
        r"(更喜欢|偏好|总是|一直都|以后都|今后都|别再|不要再|记住这点|习惯|偏好是|prefer)"
    ),
    "goal": re.compile(
        r"(目标|打算|计划|准备|下周|月底|截止|交付|待办|下一步|里程碑|deadline|todo)"
    ),
}

#: Evaluation order — first matching type wins (decision is most valuable).
_TYPE_ORDER = ("decision", "preference", "goal")

#: signal_type → memories.category mapping (design §6: category=mapping(type)).
SIGNAL_TO_CATEGORY: Dict[str, str] = {
    "decision": "decision",
    "preference": "preference",
    "goal": "goal",
    "conversation": "note",
}


def signal_to_category(signal_type: str | None) -> str:
    """Map a timeline signal type to a memories ledger category."""
    return SIGNAL_TO_CATEGORY.get(signal_type or "conversation", "note")


def _iter_messages(node: Any):
    """Yield ``(role, text)`` pairs from a session file's decoded JSON.

    Handles the observed layout ``{"agent": {"memory": {"content": [[msg,…],…]}}}``
    defensively: any nested list/dict structure is walked, and a message is
    recognized as a dict carrying ``role`` and ``content``.
    """
    stack = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            role = cur.get("role")
            content = cur.get("content")
            if isinstance(role, str) and content is not None:
                texts: List[str] = []
                if isinstance(content, str):
                    texts.append(content)
                elif isinstance(content, list):
                    for blk in content:
                        if isinstance(blk, dict) and isinstance(blk.get("text"), str):
                            texts.append(blk["text"])
                        elif isinstance(blk, str):
                            texts.append(blk)
                if texts:
                    yield role, " ".join(t for t in texts if t)
                continue  # message leaf — do not descend further
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def classify(sentence: str) -> str | None:
    """Return the signal type for a sentence, or None if it matches none."""
    if len(sentence) < _MIN_LEN:
        return None
    for stype in _TYPE_ORDER:
        if _SIGNAL_PATTERNS[stype].search(sentence):
            return stype
    return None


def extract_signals_from_session(path: Path) -> List[Dict[str, str]]:
    """Extract promotable signals from one session file.

    Returns a list of ``{"signal_type": …, "content": …}`` dicts (capped).
    Missing/unparseable files yield an empty list — the dream must never
    crash on a half-written transcript.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    out: List[Dict[str, str]] = []
    per_type: Dict[str, int] = {}
    for role, text in _iter_messages(data):
        if role not in ("user", "assistant"):
            continue
        for sent in _SENTENCE_RE.split(text):
            sent = sent.strip()
            if not sent:
                continue
            stype = classify(sent)
            if stype is None:
                continue
            if len(out) >= MAX_PER_FILE or per_type.get(stype, 0) >= MAX_PER_TYPE:
                return out
            out.append({
                "signal_type": stype,
                "content": sent[:200],
            })
            per_type[stype] = per_type.get(stype, 0) + 1
    return out
