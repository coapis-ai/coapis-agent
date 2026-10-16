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
    reported = reported_window_for(provider_id, model_name)

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
            0.5,
        )
    if chars_per_token is None:
        chars_per_token = getattr(
            running_config,
            "formatted_chars_per_token",
            1.1,
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