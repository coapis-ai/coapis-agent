# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Normalization helpers for provider chat payloads.

The persisted session history remains AgentScope ``Msg`` objects. For
provider requests we build a normalized copy before formatting so
request-time repair and multimodal downgrade logic does not mutate the
stored conversation state.
"""

from __future__ import annotations

import logging
import os
from copy import deepcopy

from agentscope.message import Msg

from ...constant import MEDIA_UNSUPPORTED_PLACEHOLDER
from .tool_message_utils import _sanitize_tool_messages, extract_tool_ids

logger = logging.getLogger(__name__)

_MEDIA_BLOCK_TYPES = {"image", "audio", "video"}


def _compat_mode() -> str:
    """Governance knob for 治理片2 (拍板项：模型兼容先影子观测一周).

    ``COAPIS_MODEL_COMPAT_MODE``:
    - ``shadow`` (default) – compute the rewrite, log what *would* change,
      then send the original list to the provider.  Rewriting message content
      is a behaviour change; a week of shadow data proves it is safe first.
    - ``apply`` – send the rewritten list.
    - ``off`` – skip the pass entirely (escape hatch).
    """
    raw = (os.environ.get("COAPIS_MODEL_COMPAT_MODE") or "shadow").strip().lower()
    return raw if raw in ("shadow", "apply", "off") else "shadow"


def _shape_signature(msgs: list[Msg]) -> list[tuple[str, tuple[str, ...]]]:
    """Compact (role, block-types) signature used to diff shadow rewrites."""
    out = []
    for msg in msgs:
        kinds = [
            block.get("type") if isinstance(block, dict) else "text"
            for block in _blocks_of(msg)
        ]
        out.append((msg.role, tuple(kinds)))
    return out


def _log_shadow_diff(before: list[Msg], after: list[Msg], family: str) -> None:
    """Record a rewrite that shadow mode declined to apply."""
    old = _shape_signature(before)
    new = _shape_signature(after)
    if old == new:
        return
    logger.info(
        "model-compat shadow: family=%s turns %d->%d (net %+d) before=%s after=%s",
        family,
        len(before),
        len(after),
        len(after) - len(before),
        old,
        new,
    )

# Fields that are provider-specific and should not leak across families.
# Gemini: extra_content carries thought_signature.
# AgentScope internal: raw_input is a stream-parsing artefact.
_PROVIDER_ONLY_TOOL_USE_FIELDS = frozenset({"extra_content", "raw_input"})

# The subset that is preserved when the target is its native family.
_GEMINI_NATIVE_FIELDS = frozenset({"extra_content"})


def _clean_provider_specific_fields(
    msgs: list[Msg],
    target_family: str,
) -> None:
    """Remove provider-specific fields that may leak from a previous provider.

    Operates **in-place** on already-cloned messages so the stored
    conversation history is never mutated.

    Current rules
    ~~~~~~~~~~~~~
    * ``extra_content`` – Gemini-specific (``thought_signature``).
      Kept only when *target_family* is ``"gemini"``.
    * ``raw_input`` – AgentScope stream-parsing artefact.
      Stripped unconditionally; some providers reject unknown fields.
    """
    preserve = (
        _GEMINI_NATIVE_FIELDS if target_family == "gemini" else frozenset()
    )
    strip_fields = _PROVIDER_ONLY_TOOL_USE_FIELDS - preserve

    if not strip_fields:
        return

    for msg in msgs:
        if not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            for field in strip_fields:
                block.pop(field, None)


def _clone_msg(msg: Msg) -> Msg:
    """Return a deep copy of an AgentScope message."""
    return Msg.from_dict(deepcopy(msg.to_dict()))


def _clone_messages(msgs: list[Msg]) -> list[Msg]:
    """Return deep-copied messages suitable for request-time normalization."""
    return [_clone_msg(msg) for msg in msgs]


def _strip_media_blocks_in_place(msgs: list[Msg]) -> int:
    """Strip media blocks from copied messages only.

    Mirrors the fallback logic in ``CoApisAgent`` but operates on normalized
    copies so the stored memory remains untouched.
    """
    total_stripped = 0

    for msg in msgs:
        if not isinstance(msg.content, list):
            continue

        new_content = []
        stripped_this_message = 0
        for block in msg.content:
            if (
                isinstance(block, dict)
                and block.get("type") in _MEDIA_BLOCK_TYPES
            ):
                total_stripped += 1
                stripped_this_message += 1
                continue

            if (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and isinstance(block.get("output"), list)
            ):
                original_len = len(block["output"])
                block["output"] = [
                    item
                    for item in block["output"]
                    if not (
                        isinstance(item, dict)
                        and item.get("type") in _MEDIA_BLOCK_TYPES
                    )
                ]
                stripped_count = original_len - len(block["output"])
                total_stripped += stripped_count
                stripped_this_message += stripped_count
                if stripped_count > 0 and not block["output"]:
                    block["output"] = MEDIA_UNSUPPORTED_PLACEHOLDER

            new_content.append(block)

        if not new_content and stripped_this_message > 0:
            new_content.append(
                {"type": "text", "text": MEDIA_UNSUPPORTED_PLACEHOLDER},
            )

        msg.content = new_content

    return total_stripped


def _blocks_of(msg: Msg) -> list:
    """Return *msg*'s content as a list of dict blocks (never mutated)."""
    content = msg.content
    if content is None:
        return []
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return list(content)
    return [content]


def _is_empty_message(msg: Msg) -> bool:
    """True when no provider can accept *msg*: no text, no tool block, no media.

    Whitespace-only text counts as empty — Anthropic rejects an assistant
    message whose content resolves to ``""``, and OpenAI-compatible endpoints
    reject empty ``content`` on ``user`` turns.
    """
    blocks = _blocks_of(msg)
    if not blocks:
        return True
    for block in blocks:
        if not isinstance(block, dict):
            if str(block).strip():
                return False
            continue
        btype = block.get("type")
        if btype == "text":
            if (block.get("text") or "").strip():
                return False
        elif btype in ("tool_use", "tool_result"):
            return False
        elif btype in _MEDIA_BLOCK_TYPES:
            return False
    return True


def _has_tool_blocks(msg: Msg) -> bool:
    for block in _blocks_of(msg):
        if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result"):
            return True
    return False


def _only_tool_results(msg: Msg) -> bool:
    """True when *msg* is purely a tool-result carrier (mergeable run member)."""
    blocks = _blocks_of(msg)
    if not blocks:
        return False
    return all(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks
    )


def _drop_empty_assistant_messages(msgs: list[Msg]) -> list[Msg]:
    """Drop assistant turns that carry nothing a model can read.

    Root cause of "选了文件让分析，有的模型报错、有的没反应": a turn that
    produced only a tool call, or an aborted generation, is stored with empty
    content.  Strict endpoints answer with a 400; permissive ones answer with
    an empty stream, which the UI renders as *no reaction*.
    """
    return [
        msg
        for msg in msgs
        if msg.role != "assistant" or not _is_empty_message(msg)
    ]


def _drop_empty_user_messages(msgs: list[Msg]) -> list[Msg]:
    """Drop user turns with empty content (see ``_drop_empty_assistant``)."""
    return [
        msg for msg in msgs if msg.role != "user" or not _is_empty_message(msg)
    ]


# Only these roles are safe to coalesce.  ``system`` carries tool results in
# this codebase and must stay separated from prose (see
# ``_merge_adjacent_tool_messages``).
_COALESCE_ROLES = frozenset({"user", "assistant"})


def _merge_pair(prev: Msg, cur: Msg) -> Msg:
    """Fuse two adjacent same-role prose turns, preserving text order."""
    merged = _clone_msg(prev)
    blocks: list = []
    for src in (prev, cur):
        for block in _blocks_of(src):
            if not isinstance(block, dict):
                block = {"type": "text", "text": str(block)}
            if (
                blocks
                and block.get("type") == "text"
                and blocks[-1].get("type") == "text"
            ):
                blocks[-1] = {
                    "type": "text",
                    "text": f"{blocks[-1].get('text') or ''}\n{block.get('text') or ''}",
                }
            else:
                blocks.append(dict(block))
    merged.content = blocks
    return merged


def _coalesce_adjacent_roles(msgs: list[Msg]) -> list[Msg]:
    """Fuse consecutive same-role *prose* turns into one.

    Anthropic rejects two consecutive assistant turns; strict OpenAI-compatible
    gateways reject consecutive user turns.  Tool blocks are deliberately
    excluded from merging: fusing a ``tool_use`` turn with the following prose
    turn reorders blocks that providers validate positionally.
    """
    out: list[Msg] = []
    for msg in msgs:
        prev = out[-1] if out else None
        if (
            prev is not None
            and prev.role == msg.role
            and msg.role in _COALESCE_ROLES
            and not _has_tool_blocks(prev)
            and not _has_tool_blocks(msg)
        ):
            out[-1] = _merge_pair(prev, msg)
        else:
            out.append(msg)
    return out


def _merge_adjacent_tool_messages(msgs: list[Msg]) -> list[Msg]:
    """Fuse a run of tool-result-only turns into one turn.

    Parallel tool calls land as one ``system`` turn per result.  Anthropic
    requires every ``tool_result`` for a turn to sit in a *single* following
    user turn, so a run must become one message.
    """
    out: list[Msg] = []
    for msg in msgs:
        prev = out[-1] if out else None
        if (
            prev is not None
            and prev.role == msg.role
            and _only_tool_results(prev)
            and _only_tool_results(msg)
        ):
            merged = _clone_msg(prev)
            merged.content = [
                *([dict(b) for b in _blocks_of(prev)]),
                *([dict(b) for b in _blocks_of(msg)]),
            ]
            out[-1] = merged
        else:
            out.append(msg)
    return out


_UNPAIRED_RESULT_TEXT = (
    "[CoApis] 该工具调用没有留下执行结果（进程中断、用户取消，或结果未落盘）。"
    "请把它视为未执行，不要声称已经执行过。"
)


def _pair_tool_use_ids(msgs: list[Msg]) -> list[Msg]:
    """Give every dangling ``tool_use`` a synthetic ``tool_result``.

    ``_remove_unpaired_tool_messages`` (see ``tool_message_utils``) *deletes*
    the whole assistant turn when its tool call has no result — that erases
    the assistant's intent from history, and the model is left seeing the
    user's request with no trace of the attempt.  Here we keep the turn and
    append a result stating plainly that nothing ran.

    Trailing dangling calls are paired too.  Leaving them unpaired would send
    the request as *prefill*, inviting the model to write its own tool result
    and keep going — the last thing a finished conversation needs.
    """
    seen_results: set[str] = set()
    for msg in msgs:
        _, results = extract_tool_ids(msg)
        seen_results |= results

    out: list[Msg] = []
    for msg in msgs:
        out.append(msg)
        uses, _ = extract_tool_ids(msg)
        if not uses:
            continue
        missing = sorted(uid for uid in uses if uid not in seen_results)
        if not missing:
            continue
        names = {
            block.get("id"): block.get("name") or "tool"
            for block in _blocks_of(msg)
            if isinstance(block, dict) and block.get("type") == "tool_use"
        }
        filler = Msg(
            name="system",
            role="system",
            content=[
                {
                    "type": "tool_result",
                    "id": uid,
                    "name": names.get(uid, "tool"),
                    "output": [{"type": "text", "text": _UNPAIRED_RESULT_TEXT}],
                }
                for uid in missing
            ],
        )
        out.append(filler)
        seen_results |= set(missing)
    return out


def _drop_unpaired_tool_results(msgs: list[Msg]) -> list[Msg]:
    """Drop ``tool_result`` blocks whose ``tool_use`` is not in the history.

    Happens when history is trimmed by compaction: the result survives, its
    call disappears, and the endpoint answers 400 "tool_use_id not found".
    """
    use_ids: set[str] = set()
    for msg in msgs:
        uses, _ = extract_tool_ids(msg)
        use_ids |= uses

    out: list[Msg] = []
    for msg in msgs:
        blocks = _blocks_of(msg)
        kept = [
            block
            for block in blocks
            if not (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and block.get("id") not in use_ids
            )
        ]
        if len(kept) == len(blocks):
            out.append(msg)
            continue
        if not kept:
            continue
        replacement = _clone_msg(msg)
        replacement.content = kept
        out.append(replacement)
    return out


def _apply_compatibility_pass(
    msgs: list[Msg],
    *,
    strict_chain: bool,
) -> list[Msg]:
    """Strict-compatibility governance (治理片2).

    Two tiers, so permissive endpoints are never harmed:

    - **Always on** (every provider): drop empty turns, fuse consecutive
      same-role prose turns.  These shapes are rejected by *all* providers,
      so removing them cannot change meaning.
    - **Strict tier** (``strict_chain=True``: Anthropic, Gemini, strict
      OpenAI-compatible gateways): synthesize missing ``tool_result``s, drop
      orphaned results, fuse tool-result runs.

    Order matters: pair ids before dropping results, merge tool turns last,
    then re-coalesce roles — merging can expose new adjacent same-role turns.
    """
    out = _pair_tool_use_ids(msgs) if strict_chain else list(msgs)
    out = _drop_empty_assistant_messages(out)
    out = _drop_empty_user_messages(out)
    out = _coalesce_adjacent_roles(out)
    if strict_chain:
        out = _drop_unpaired_tool_results(out)
        out = _merge_adjacent_tool_messages(out)
        out = _coalesce_adjacent_roles(out)
    return out


def normalize_messages_for_model_request(
    msgs: list[Msg],
    *,
    supports_multimodal: bool,
    target_family: str = "openai",
    strict_chain: bool = False,
) -> list[Msg]:
    """Return a normalized copy for provider request formatting.

    Args:
        msgs: Source messages (will **not** be mutated).
        supports_multimodal: Whether the target model handles media.
        target_family: Provider family of the *current* model
            (``"openai"`` | ``"anthropic"`` | ``"gemini"``).
            Used to strip fields that belong to other providers.
        strict_chain: Enforce the tool-call chain contract (paired ids,
            no orphan tool results).  Anthropic/Gemini/strict OpenAI-compatible
            endpoints reject unpaired tool messages, so callers targeting
            those families should pass True.
    """
    normalized = _clone_messages(msgs)
    strict = strict_chain or target_family in ("anthropic", "gemini")

    # Pair dangling tool calls *before* sanitizing: `_remove_unpaired_tool_messages`
    # deletes the whole assistant turn when its call has no result, erasing the
    # assistant's intent.  Synthesizing the result first keeps the turn.
    if strict:
        normalized = _pair_tool_use_ids(normalized)

    # Sanitize first: _repair_empty_tool_inputs needs raw_input to fix
    # empty input fields.  _clean_provider_specific_fields runs after so
    # that raw_input (and other provider artefacts) are stripped only once
    # the repair has had its chance.
    normalized = _sanitize_tool_messages(normalized)
    _clean_provider_specific_fields(normalized, target_family)
    if not supports_multimodal:
        _strip_media_blocks_in_place(normalized)

    mode = _compat_mode()
    if mode == "off":
        return normalized

    rewritten = _apply_compatibility_pass(normalized, strict_chain=strict)
    if mode == "shadow":
        # 拍板项：模型兼容先影子观测一周——只记录、不改变发给模型的内容。
        _log_shadow_diff(normalized, rewritten, target_family)
        return normalized
    return rewritten


__all__ = [
    "normalize_messages_for_model_request",
    "_apply_compatibility_pass",
    "_compat_mode",
    "_coalesce_adjacent_roles",
    "_drop_empty_assistant_messages",
    "_drop_empty_user_messages",
    "_drop_unpaired_tool_results",
    "_merge_adjacent_tool_messages",
    "_pair_tool_use_ids",
]
