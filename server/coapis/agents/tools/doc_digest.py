"""B4: the digest layer — read a document *for a goal*, not in full.
(2026-10-17, 片4-6 施工单 B4)

B3 made a document addressable; this module spends that address book.  A
digest is produced by the compaction model (the session model when no
compaction model is configured) walking the block index in chunks, and what
comes back is a summary **plus pointers into the original** — never the
document itself.  The ledger records the digest and the pointers, so a
session can talk about a 1.2MB document without ever carrying it.

Hard caps, because this is the one path that calls a model on purpose:
``DIGEST_MAX_CALLS`` model calls and ``DIGEST_MAX_INPUT_CHARS`` characters
of input, both reported in the result (``calls_used``) so a caller can tell
a complete digest from a digest that ran out of budget.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .doc_pages import (
    ParsedDoc,
    _cache_dir,
    parse_document,
)

logger = logging.getLogger(__name__)

#: Model calls one digest may spend.
DIGEST_MAX_CALLS = 12
#: Characters of document text one digest may read.
DIGEST_MAX_INPUT_CHARS = 120_000
#: Document characters handed to the model per call (拍板 §7-1: ≤6,000).
DIGEST_CHUNK_CHARS = 6000
#: Characters the digest answer is asked to stay under.
DIGEST_OUT_CHARS = 4000

_INSTRUCTION = (
    "你在为一个小目标阅读一份长文档的片段。只输出与目标有关的内容。\n"
    "sections：本片段涉及的主题与要点，每行一条，格式「主题: 要点」。\n"
    "facts：本片段中的关键数字、名称、结论，每行一条，带出处页/章。\n"
    "pointers：值得回看原文的位置，格式「起始-结束 主题」，取自片段标题。\n"
    "没有内容的字段给一个短说明（如「无」），不要编造，不要复述原文长句。"
)


def _digest_path(key: str, cache_dir: Path) -> Path:
    return cache_dir / f"{key}.digest.json"


def _load_digest(key: str, cache_dir: Path) -> dict[str, Any] | None:
    path = _digest_path(key, cache_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError) as exc:
        logger.debug("digest cache read failed for %s: %s", key, exc)
        return None


def _save_digest(
    key: str,
    cache_dir: Path,
    payload: dict[str, Any],
) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        _digest_path(key, cache_dir).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.debug("digest cache write failed for %s: %s", key, exc)


def _goal_terms(goal: str) -> list[str]:
    return [t for t in re.split(r"[\s,，、;；.。]+", str(goal or "")) if len(t) >= 2]


def _digest_chunks(
    doc: ParsedDoc,
    goal: str,
    max_calls: int,
    max_input_chars: int,
) -> list[dict[str, Any]]:
    """Group the block index into model-sized chunks under the hard caps.

    Blocks are ordered by how many goal terms they contain (拍板 §7-1), so
    the 12-call budget is spent where the answer is most likely to be;
    ties keep document order, and the leftovers are reported as
    ``uncovered``.
    """
    terms = _goal_terms(goal)
    scored = []
    for block in doc.blocks:
        body = doc.text[block.start : block.end].lower()
        score = sum(body.count(term.lower()) for term in terms)
        scored.append((score, block))
    hits = [b for score, b in scored if score > 0]
    rest = [b for score, b in scored if score == 0]
    ordered = hits + rest

    chunks: list[dict[str, Any]] = []
    current: dict[str, Any] = {"ranges": [], "chars": 0, "titles": []}
    spent = 0
    for block in ordered:
        if spent + block.chars > max_input_chars:
            break
        if current["ranges"] and (
            current["chars"] + block.chars > DIGEST_CHUNK_CHARS
            or len(chunks) + 1 >= max_calls
        ):
            chunks.append(current)
            current = {"ranges": [], "chars": 0, "titles": []}
        current["ranges"].append((block.start, block.end))
        current["chars"] += block.chars
        current["titles"].append(block.title)
        spent += block.chars
    if current["ranges"] and len(chunks) < max_calls:
        chunks.append(current)
    return chunks


def _uncovered(covered: list[tuple[int, int]], total: int) -> list[str]:
    """Character ranges the digest never read."""
    gaps: list[str] = []
    cursor = 0
    for start, end in sorted(covered):
        if start > cursor:
            gaps.append(f"{cursor}-{start}")
        cursor = max(cursor, end)
    if cursor < total:
        gaps.append(f"{cursor}-{total}")
    return gaps


def _digest_model() -> tuple[Any, Any]:
    """The compaction model when configured, else the session model."""
    from ...app.agent_context import get_current_agent_id
    from ..model_factory import (
        create_model_and_formatter,
        create_model_and_formatter_from_ref,
    )

    agent_id = None
    try:
        agent_id = get_current_agent_id()
    except Exception:  # pragma: no cover - context optional
        agent_id = None

    ref = ""
    try:
        from ...config.config import get_config

        cfg = get_config(agent_id)
        ccc = (
            cfg.running.light_context_config.context_compact_config
        )
        ref = (getattr(ccc, "compaction_model_id", "") or "").strip()
    except Exception:  # pragma: no cover - config optional
        ref = ""

    if ref:
        model, formatter = create_model_and_formatter_from_ref(ref)
        if model is not None:
            return model, formatter
    model, formatter = create_model_and_formatter(agent_id)
    if model is None:
        raise RuntimeError("没有可用的模型，无法生成文档摘要")
    return model, formatter


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in str(value or "").split("\n") if line.strip()]


async def read_doc_digest(
    doc: ParsedDoc,
    goal: str,
    max_calls: int = DIGEST_MAX_CALLS,
    max_input_chars: int = DIGEST_MAX_INPUT_CHARS,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Summarize *doc* for *goal* and return pointers into the original."""
    goal = str(goal or "").strip()
    if not goal:
        return {
            "mode": "digest",
            "error": "digest 需要 goal（要回答的问题）。",
        }
    directory = cache_dir if cache_dir is not None else _cache_dir()
    cached = _load_digest(doc.key, directory)
    if cached is not None and cached.get("goal") == goal:
        return {**cached, "mode": "digest", "cached": True}

    try:
        model, formatter = _digest_model()
    except Exception as exc:
        return {
            "mode": "digest",
            "error": f"摘要模型不可用：{type(exc).__name__}: {exc}",
        }

    from agentscope.message import Msg

    chunks = _digest_chunks(doc, goal, max_calls, max_input_chars)
    sections: list[str] = []
    facts: list[str] = []
    pointers: list[str] = []
    covered: list[tuple[int, int]] = []
    calls = 0
    input_chars = 0
    last_error = ""

    for chunk in chunks:
        if calls >= max_calls or input_chars >= max_input_chars:
            break
        parts: list[str] = []
        for start, end in chunk["ranges"]:
            room = max_input_chars - input_chars
            if room <= 0:
                break
            piece = doc.text[start : min(end, start + room)]
            if piece.strip():
                parts.append(piece)
                input_chars += len(piece)
        text = "\n\n".join(parts)
        if not text.strip():
            continue
        calls += 1
        span = chunk["ranges"][0]
        try:
            prompt = await formatter.format(
                [
                    Msg("system", _INSTRUCTION, "system"),
                    Msg(
                        "user",
                        f"目标：{goal}\n\n片段位置：{span[0]}-{chunk['ranges'][-1][1]}"
                        f"（{chunk['titles'][0]} 起）\n\n{text}",
                        "user",
                    ),
                ],
            )
            res = await model(prompt)
            body = res.get_text_content() if hasattr(res, "get_text_content") else ""
            meta = getattr(res, "metadata", None) or {}
            sections.extend(_split_lines(meta.get("sections") or ""))
            facts.extend(_split_lines(meta.get("facts") or ""))
            pointers.extend(_split_lines(meta.get("pointers") or ""))
            if not (sections or facts) and body:
                # Structured output unavailable: keep what the model said.
                sections.extend(_split_lines(body)[:8])
            covered.extend(chunk["ranges"])
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "digest call %d failed for %s: %s",
                calls,
                doc.path,
                exc,
            )
            break

    if not covered:
        return {
            "mode": "digest",
            "error": f"摘要生成失败：{last_error or '模型没有返回内容'}",
            "calls_used": calls,
        }

    read_to = max(end for _, end in covered)
    payload: dict[str, Any] = {
        "mode": "digest",
        "goal": goal,
        "format": doc.fmt,
        "path": doc.path,
        "total_chars": doc.chars,
        "sections": sections[:60],
        "facts": facts[:60],
        "pointers": pointers[:60],
        "uncovered": _uncovered(covered, doc.chars),
        "next_start": read_to,
        "calls_used": calls,
        "input_chars": input_chars,
        "budget": {
            "max_calls": max_calls,
            "max_input_chars": max_input_chars,
        },
        "hint": (
            "需要原文细节时用 mode=range 配 pointers/next_start 取用；"
            "摘要未覆盖的区间见 uncovered。"
        ),
        "cached": False,
    }
    if last_error:
        payload["warning"] = f"摘要在 {calls} 次调用后中断：{last_error}"
    if read_to < doc.chars:
        payload["warning"] = (
            payload.get("warning", "")
            + f" 文档共 {doc.chars} 字符，本次摘要读到 {read_to} 字符"
            f"（{calls} 次调用，上限 {max_calls} 次 / {max_input_chars} 字符）。"
        ).strip()
    _save_digest(doc.key, directory, payload)
    return payload


async def digest_document(
    abs_path: str,
    fmt: str,
    goal: str,
    max_calls: int = DIGEST_MAX_CALLS,
    max_input_chars: int = DIGEST_MAX_INPUT_CHARS,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Parse (cached) then digest for *goal*."""
    parsed = parse_document(abs_path, fmt, cache_dir=cache_dir)
    if "error" in parsed:
        return {"mode": "digest", "error": parsed["error"]}
    return await read_doc_digest(
        parsed["doc"],
        goal,
        max_calls=max_calls,
        max_input_chars=max_input_chars,
        cache_dir=cache_dir,
    )
