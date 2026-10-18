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

"""The single source of truth for "how big is this model's window".

Why this module exists
----------------------
Every consumer used to answer that question on its own, and every one of
them was wrong in a different way:

- ``RunningConfig.max_input_length`` was a user-entered number, shipped as
  102400 for a model whose own window is 32768.
- ``agent_context._get_context_limit`` kept a hardcoded table of model-name
  patterns (gpt-4o 128000, claude 200000, gemini 1000000, ollama 8192) and
  matched by substring.  It never matched the deployment's model, so it
  always returned the 128000 default.
- ``agentscope_context_manager`` read ``model.context_window``, an attribute
  no model object in this codebase has ever set.
- The governance layer published a window nobody consumed.

One number, computed once, from the model's own report.  Callers that need
a *character* budget convert with the calibrated chars/token ratio; callers
that need a *token* budget use it directly.  Nothing else may invent a
window.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Floor so a bogus 0/None from a provider cannot produce a 0-token budget.
_MIN_WINDOW_TOKENS = 512


@dataclass(frozen=True)
class WindowInfo:
    """Resolved context window for one model.

    Attributes:
        reported_tokens: What the model/provider itself publishes, or None.
        effective_tokens: ``reported_tokens * safety_factor`` — the number
            every budget calculation must use.
        source: ``"model_self_report"`` / ``"config_fallback"`` /
            ``"model_self_report_capped"`` when the configured value was
            lower than the reported one.
        chars_per_token: Calibrated formatted-prompt chars per token, used
            for the token<->char conversions upstream measures in chars.
    """

    reported_tokens: int | None
    effective_tokens: int
    source: str
    chars_per_token: float = 1.1

    def to_chars(self, tokens: float) -> int:
        """Convert a token budget into the character budget upstream measures."""
        return int(tokens * self.chars_per_token)

    def to_tokens(self, chars: float) -> int:
        """Inverse of ``to_chars``."""
        return int(chars / self.chars_per_token) if self.chars_per_token else 0


def model_slot_of(model: Any) -> tuple[str | None, str | None]:
    """Best-effort ``(provider_id, model_name)`` of a live chat model object.

    The model wrappers we use expose the pair in different places
    (``model_key`` on the retry wrapper, ``_provider_id``/``model_name`` on
    the OpenAI-compatible inner model), so this walks the known shapes.
    Returns ``(None, None)`` rather than guessing.
    """
    key = getattr(model, "model_key", None)
    if isinstance(key, str) and "/" in key:
        provider_id, _, name = key.partition("/")
        return provider_id.strip() or None, name.strip() or None

    inner = getattr(model, "_inner", None) or model
    provider_id = getattr(inner, "_provider_id", None) or getattr(
        inner,
        "provider_id",
        None,
    )
    name = getattr(inner, "model_name", None)
    return (
        str(provider_id).strip() if provider_id else None,
        str(name).strip() if name else None,
    )


def reported_window_for(
    provider_id: str | None,
    model_name: str | None,
) -> int | None:
    """Ask the provider registry what this model says its window is."""
    if not provider_id or not model_name:
        return None
    try:
        from ...providers.provider_manager import ProviderManager

        provider = ProviderManager.get_instance().get_provider(provider_id)
    except Exception as exc:  # registry unavailable -> caller falls back
        logger.debug("Provider lookup failed for %s: %s", provider_id, exc)
        return None
    if provider is None:
        return None
    for model_info in getattr(provider, "models", []) or []:
        if model_info.id == model_name:
            return model_info.max_sequence_length
    return None


def provider_slots() -> list[tuple[str, Any]]:
    """Every ``(provider_id, provider)`` the registry currently knows."""
    try:
        from ...providers.provider_manager import ProviderManager

        manager = ProviderManager.get_instance()
    except Exception as exc:  # registry unavailable -> caller falls back
        logger.debug("Provider registry lookup failed: %s", exc)
        return []
    slots: list[tuple[str, Any]] = []
    for provider_id, provider in (
        list(manager.builtin_providers.items())
        + list(manager.custom_providers.items())
    ):
        slots.append((provider_id, provider))
    for provider_id, plugin in (manager.plugin_providers or {}).items():
        info = plugin.get("info") if isinstance(plugin, dict) else None
        if info is not None:
            slots.append((provider_id, info))
    return slots


def reported_window_for_model_name(
    model_name: str | None,
    base_url: str | None = None,
) -> tuple[str | None, int | None]:
    """Find ``(provider_id, window)`` for a model named by string alone.

    Callers holding a raw provider client -- the experience extractor builds
    its own ``AsyncOpenAI`` client from ``AgentCore`` -- have a model *name*
    and an endpoint, and no provider id, so :func:`reported_window_for`
    cannot identify them.  Matching the name alone is unsafe (the same model
    can be served twice with different windows), so when ``base_url`` is
    known it must match: a wrong window is worse than no window.

    Returns ``(None, None)`` when nothing matches, never raises.
    """
    if not model_name:
        return None, None
    name = str(model_name).strip()
    wanted_url = _normalize_base_url(base_url)
    for provider_id, provider in provider_slots():
        if str(getattr(provider, "id", provider_id)).strip() != provider_id:
            continue
        if wanted_url:
            provider_url = _normalize_base_url(
                getattr(provider, "base_url", "") or "",
            )
            if provider_url and provider_url != wanted_url:
                continue
        for model_info in getattr(provider, "models", []) or []:
            if getattr(model_info, "id", None) == name:
                return provider_id, getattr(
                    model_info,
                    "max_sequence_length",
                    None,
                )
    return None, None


def _normalize_base_url(value: str | None) -> str:
    """Compare two endpoints: scheme-insensitive, trailing-slash-insensitive."""
    if not value:
        return ""
    url = str(value).strip().rstrip("/").lower()
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix) :]
    return url


def merge_window_feedback(
    provider_id: str | None,
    model_name: str | None,
    reported: int | None,
) -> int | None:
    """Rank a provider's refusal above its static ``/models`` number."""
    observed = window_feedback(provider_id, model_name)
    if not observed:
        return reported
    # A refusal is the most recent thing the provider has told us about
    # this model, so it outranks a static /models number.
    return (
        observed["window_tokens"]
        if reported is None
        else min(reported, observed["window_tokens"])
    )


def resolve_for_model(
    model: Any,
    running_config: Any = None,
    **kwargs: Any,
) -> WindowInfo:
    """Resolve the window for a live model object.

    Convenience wrapper around :func:`resolve_window` that looks up the
    model's self-reported window from the provider registry.  Never raises.
    """
    provider_id, model_name = model_slot_of(model)
    reported = merge_window_feedback(
        provider_id,
        model_name,
        reported_window_for(provider_id, model_name),
    )

    class _Stub:
        pass

    info = _Stub()
    info.max_sequence_length = reported
    result = resolve_window(info, running_config, **kwargs)
    if result.source != "model_self_report" and provider_id:
        logger.info(
            "Model %s/%s reports no context window; falling back to "
            "configured max_input_length (%s)",
            provider_id,
            model_name,
            result.source,
        )
        # Ask the provider for its own number in the background, so the
        # next session budgets against the truth and not the typed value.
        try:
            from ...providers.provider_manager import ProviderManager

            ProviderManager.get_instance().request_window_probe(provider_id)
        except Exception:  # the probe is an optimisation, never fatal
            logger.debug(
                "context-window probe request failed for %s",
                provider_id,
                exc_info=True,
            )
    return result


async def compute_keep_recent(
    memory: Any,
    budget_tokens: int,
    chars_per_token: float,
    keep_recent_min: int,
    keep_recent_max: int,
) -> int:
    """How many recent messages fit inside *budget_tokens*.

    The single tail-sizing rule in Coapis.  Upstream counts a tool-use /
    tool-result pair as one group when it applies ``keep_recent``; counting
    plain messages is therefore conservative — it keeps fewer groups, never
    more.  Clamped so a session is never squeezed below the configured floor
    nor kept uncompressed past the ceiling.

    Anyone with a budget to size (the reasoning hook, the evolution engine,
    offline evaluation) calls this rather than writing its own loop — the
    evolution engine used to invent its own constant and disagreed with the
    agent it was evolving.
    """
    messages = await memory.get_memory(prepend_summary=False)
    budget_chars = budget_tokens * chars_per_token
    used = 0.0
    kept = 0
    for msg in reversed(messages):
        used += len(str(msg.content))
        kept += 1
        if used >= budget_chars and kept >= keep_recent_min:
            break
    return max(keep_recent_min, min(keep_recent_max, kept))


def resolve_window(
    model_info: Any = None,
    running_config: Any = None,
    *,
    safety_factor: float | None = None,
    chars_per_token: float | None = None,
) -> WindowInfo:
    """Resolve the effective context window.

    Args:
        model_info: ``ModelInfo`` of the model in use; its
            ``max_sequence_length`` is the model's self-reported window.
        running_config: ``RunningConfig`` providing the fallback
            ``max_input_length`` and, when not passed explicitly, the
            safety factor and chars/token calibration.
        safety_factor: Override for tests.
        chars_per_token: Override for tests.

    Returns:
        ``WindowInfo``.  Never raises: a provider that reports nothing
        falls back to configuration.
    """
    reported = getattr(model_info, "max_sequence_length", None)
    try:
        reported = int(reported) if reported is not None else None
    except (TypeError, ValueError):
        reported = None
    if reported is not None and reported < _MIN_WINDOW_TOKENS:
        reported = None

    configured = getattr(running_config, "max_input_length", None)
    try:
        configured = int(configured) if configured is not None else None
    except (TypeError, ValueError):
        configured = None

    if safety_factor is None:
        safety_factor = getattr(
            running_config,
            "context_window_safety_factor",
            0.7,
        )
    if chars_per_token is None:
        chars_per_token = getattr(
            running_config,
            "formatted_chars_per_token",
            3.0,
        )
    # A factor of 0 (or a nonsense calibration) would silently disable
    # compaction, which is the failure mode this whole module exists to fix.
    safety_factor = max(0.05, min(1.0, float(safety_factor)))
    chars_per_token = max(0.5, min(8.0, float(chars_per_token)))

    if reported is not None:
        base, source = reported, "model_self_report"
        if configured is not None and configured < reported:
            # The operator deliberately capped this model (e.g. to leave
            # room for a proxy); respect the lower value.
            base, source = configured, "model_self_report_capped"
    elif configured is not None:
        base, source = configured, "config_fallback"
    else:
        base, source = _MIN_WINDOW_TOKENS, "hard_floor"

    effective = max(_MIN_WINDOW_TOKENS, int(base * safety_factor))
    info = WindowInfo(
        reported_tokens=reported,
        effective_tokens=effective,
        source=source,
        chars_per_token=chars_per_token,
    )
    logger.debug(
        "Context window resolved: reported=%s configured=%s effective=%s (%s)",
        reported,
        configured,
        effective,
        source,
    )
    return info

# Providers that publish no window in /models still tell us the number when
# they refuse a request: "prompt (114974 tokens) leaves no room to answer in
# the context (102400)" (measured on dev, 2026-10-17, local_vllm/Q3).  That
# refusal is the model self-reporting its window under load, so we keep it:
# the next resolution caps against it, and the observed chars/token ratio is
# recorded next to the configured one.  This is how a fabricated
# ``max_input_length`` stops being the number the whole system budgets
# against.

_FEEDBACK: dict[tuple[str | None, str | None], dict[str, Any]] = {}
_FEEDBACK_MAX = 64

# How long a refusal-derived window stays authoritative.  A refusal is a fact
# about the server *as it was loaded that minute*; keeping it forever would let
# one bad peak define the budget for the life of the process.  24 h (拍板 D1).
_FEEDBACK_TTL_SECONDS: float = float(
    os.getenv("COAPIS_CONTEXT_FEEDBACK_TTL_SECONDS", "86400"),
)

# Refusals that say "too big" and give no number.  "Context size has been
# exceeded" (dev provider a3, measured 2026-10-18) is the whole response body:
# no digits, so ``parse_window_feedback`` finds nothing and the fabricated
# self-reported window keeps defining every budget.  These markers let the
# refusal still mean something: the prompt we measured did **not** fit, so the
# real window is below that measurement.
_CONTEXT_REFUSAL_MARKERS: tuple[str, ...] = (
    "context size has been exceeded",
    "context size exceeded",
    "context length exceeded",
    "context window exceeded",
    "context limit exceeded",
    "maximum context",
    "prompt is too long",
    "no room to answer",
    "insufficient space for the prompt",
    "context overflow",
)

# The refused prompt is an upper bound, not the window: the server refused
# *at least* that much, so the cap sits a margin below it.
_INFERRED_CAP_MARGIN = 0.9
# A second numberless refusal of a prompt that already fits under the current
# cap means the cap is still too generous: shrink it, never grow it.
_INFERRED_SHRINK_STEP = 0.75

_WINDOW_PATTERNS: tuple[str, ...] = (
    r"context \(\s*(\d+)\s*\)",
    r"maximum context length(?: is|:)?\s*(\d+)",
    r"context length of\s*(\d+)",
    r"exceed(?:s)? (?:the )?context limit:?\s*\d+\s+and\s+\d+\s*>\s*(\d+)",
    r">\s*(\d+)\s*(?:tokens?\s*)?maximum",
    r"context[_ ]window(?: size)?(?: is|:)?\s*(\d+)",
    r"max(?:imum)? (?:context )?tokens:?\s*(\d+)",
)

_PROMPT_PATTERNS: tuple[str, ...] = (
    r"prompt \(\s*(\d+)(?:\s*tokens?)?\)",
    r"prompt is too long:\s*(\d+)",
    r"(\d+)\s*tokens?\s*>",
    r"(\d+)\s+tokens? (?:in the messages|were sent|in prompt)",
    r"prompt(?: tokens)?[:=]?\s*(\d+)\s*tokens?",
    r"total tokens:\s*(\d+)",
)


def parse_window_feedback(message: str) -> dict[str, Any] | None:
    """Pull ``(window_tokens, prompt_tokens)`` out of a refusal.

    Returns None when the text carries no window number, so a plain 400
    never becomes a "fact".
    """
    if not message:
        return None
    text = message.replace("\n", " ")
    window = None
    for pattern in _WINDOW_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                window = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if window >= _MIN_WINDOW_TOKENS:
                break
            window = None
    if window is None:
        return None
    prompt = None
    for pattern in _PROMPT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                prompt = int(match.group(1))
            except (TypeError, ValueError):
                continue
            break
    return {"window_tokens": window, "prompt_tokens": prompt}


def is_context_refusal(message: str | None) -> bool:
    """True when this response body says "too big", with or without numbers."""
    text = (message or "").lower()
    return any(marker in text for marker in _CONTEXT_REFUSAL_MARKERS)


def _inferred_window_from_refusal(
    provider_id: str | None,
    model_name: str | None,
    message: str,
    measured_chars: int | None,
    chars_per_token: float | None,
) -> int | None:
    """Upper bound on the window from a refusal that names no number.

    ``measured_chars`` is our own measurement of the prompt that got refused,
    so the bound is "strictly less than what we just sent".  Repeated refusals
    ratchet the cap down; nothing here ever raises a window.
    """
    if not is_context_refusal(message):
        return None
    if not measured_chars or measured_chars <= 0:
        return None
    ratio = (
        chars_per_token
        if chars_per_token and chars_per_token > 0
        else _FALLBACK_CHARS_PER_TOKEN
    )
    cap = int(measured_chars / ratio * _INFERRED_CAP_MARGIN)
    previous = _FEEDBACK.get((provider_id, model_name))
    if previous and previous.get("inferred"):
        cap = min(cap, int(previous["window_tokens"] * _INFERRED_SHRINK_STEP))
    return max(_MIN_WINDOW_TOKENS, cap)


def record_window_feedback(
    provider_id: str | None,
    model_name: str | None,
    message: str,
    measured_chars: int | None = None,
    chars_per_token: float | None = None,
) -> dict[str, Any] | None:
    """Remember what a refusal taught us about this model's window.

    ``measured_chars`` is the gate's own measurement of the prompt that was
    refused, which turns the provider's token count into the *observed*
    chars-per-token ratio — the number the calibration constants are
    supposed to approximate.

    A refusal with no number in it is still a refusal: when we have our own
    measurement of the prompt that failed, it becomes an inferred cap on the
    window (see :func:`_inferred_window_from_refusal`).  Plain 400s with no
    context wording and no number still record nothing.
    """
    parsed = parse_window_feedback(message)
    inferred = False
    if parsed is None:
        window = _inferred_window_from_refusal(
            provider_id,
            model_name,
            message,
            measured_chars,
            chars_per_token,
        )
        if window is None:
            return None
        parsed = {"window_tokens": window, "prompt_tokens": None}
        inferred = True
    entry: dict[str, Any] = {
        "window_tokens": parsed["window_tokens"],
        "prompt_tokens": parsed["prompt_tokens"],
        "measured_chars": measured_chars,
        "inferred": inferred,
        "recorded_at": time.monotonic(),
        "raw": (message or "")[:400],
    }
    if measured_chars and parsed["prompt_tokens"]:
        entry["observed_chars_per_token"] = round(
            measured_chars / parsed["prompt_tokens"],
            3,
        )
    if len(_FEEDBACK) >= _FEEDBACK_MAX:
        _FEEDBACK.pop(next(iter(_FEEDBACK)))
    _FEEDBACK[(provider_id, model_name)] = entry
    logger.warning(
        "Provider refusal caps the window for %s/%s at %d tokens (%s; "
        "prompt %s tokens, our measurement %s chars%s). The context budget "
        "uses this from now on, for %.0f h.",
        provider_id,
        model_name,
        entry["window_tokens"],
        "inferred from our own measurement"
        if inferred
        else "the provider stated it",
        entry["prompt_tokens"],
        measured_chars,
        (
            f", observed {entry['observed_chars_per_token']} chars/token"
            if entry.get("observed_chars_per_token")
            else ""
        ),
        _FEEDBACK_TTL_SECONDS / 3600,
    )
    return entry


def window_feedback(
    provider_id: str | None,
    model_name: str | None,
) -> dict[str, Any] | None:
    """The last refusal-derived window we learned for this model slot.

    Returns None once the entry is older than ``_FEEDBACK_TTL_SECONDS`` and
    drops it, so a stale peak stops defining the budget and the next refusal
    re-measures the server as it is now.
    """
    key = (provider_id, model_name)
    entry = _FEEDBACK.get(key)
    if entry is None:
        return None
    age = time.monotonic() - entry.get("recorded_at", 0.0)
    if age > _FEEDBACK_TTL_SECONDS:
        _FEEDBACK.pop(key, None)
        logger.info(
            "Refusal-derived window for %s/%s expired after %.1f h; "
            "the budget goes back to the provider's self-report until the "
            "next refusal.",
            provider_id,
            model_name,
            age / 3600,
        )
        return None
    return entry


def feedback_report() -> dict[str, dict[str, Any]]:
    """All refusal-derived windows, keyed ``provider/model`` (diagnostics)."""
    out: dict[str, dict[str, Any]] = {}
    for (provider_id, model_name), entry in _FEEDBACK.items():
        out[f"{provider_id}/{model_name}"] = dict(entry)
    return out
