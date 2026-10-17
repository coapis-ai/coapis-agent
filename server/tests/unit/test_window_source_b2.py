"""B2 tests: window truth from providers and from provider refusals.

Every number here comes from a real provider message measured on dev
(2026-10-17), not from a shape we invented.
"""

from __future__ import annotations

import asyncio

import pytest

from coapis.agents.context.window_source import (
    feedback_report,
    model_slot_of,
    parse_window_feedback,
    record_window_feedback,
    resolve_for_model,
    resolve_window,
    window_feedback,
)
from coapis.providers.anthropic_provider import AnthropicProvider
from coapis.providers.gemini_provider import GeminiProvider
from coapis.providers.openai_provider import OpenAIProvider

# ── the refusal texts, verbatim from the field ──────────────────────


LOCAL_VLLM = (
    "Error code: 400 - {'error': {'message': 'The request exceeds the "
    "context window: prompt (114974 tokens) leaves no room to answer in "
    "the context (102400).'"
)

OPENAI_STYLE = (
    "This model's maximum context length is 8192 tokens. However, your "
    "request has 12345 tokens in the messages."
)

ANTHROPIC_STYLE = (
    "Error code: 400 - {'type': 'invalid_request_error', 'message': "
    "'prompt is too long: 210000 tokens > 200000 maximum'}"
)

CLAUDE_COMBINED = (
    "input length and `max_tokens` exceed context limit: 100234 and 25000 "
    "> 128000, decrease input length"
)


def test_parses_the_measured_local_vllm_refusal():
    parsed = parse_window_feedback(LOCAL_VLLM)
    assert parsed == {"window_tokens": 102400, "prompt_tokens": 114974}


def test_parses_openai_style_refusal():
    parsed = parse_window_feedback(OPENAI_STYLE)
    assert parsed["window_tokens"] == 8192
    assert parsed["prompt_tokens"] == 12345


def test_parses_anthropic_style_refusal():
    parsed = parse_window_feedback(ANTHROPIC_STYLE)
    assert parsed["window_tokens"] == 200000
    assert parsed["prompt_tokens"] == 210000


def test_parses_combined_input_and_completion_refusal():
    parsed = parse_window_feedback(CLAUDE_COMBINED)
    assert parsed["window_tokens"] == 128000


def test_plain_400_is_not_a_window_report():
    assert parse_window_feedback("Error code: 400 - invalid api key") is None
    assert parse_window_feedback("") is None
    # A number below the floor is not a context window.
    assert parse_window_feedback("maximum context length is 12") is None


def test_record_pairs_our_measurement_with_their_token_count():
    entry = record_window_feedback(
        "local_vllm",
        "Q3",
        LOCAL_VLLM,
        measured_chars=277598,
    )
    assert entry is not None
    assert entry["window_tokens"] == 102400
    # 277,598 chars measured by the gate against the 114,974 tokens the
    # server counted: the real ratio, which no unit test invented.
    assert entry["observed_chars_per_token"] == pytest.approx(2.415, abs=0.01)
    assert window_feedback("local_vllm", "Q3") is entry
    assert "local_vllm/Q3" in feedback_report()


def test_record_ignores_messages_without_a_window():
    assert record_window_feedback("x", "y", "boom", 100) is None
    assert window_feedback("x", "y") is None


class _Run:
    max_input_length = 131072


class _Model:
    model_key = "local_vllm/Q3"


def test_refusal_outranks_the_configured_window():
    """The whole point: a typed 131072 must not outlive a stated 102400."""
    record_window_feedback("local_vllm", "Q3", LOCAL_VLLM, 277598)
    window = resolve_for_model(_Model(), _Run())
    assert window.source in ("model_self_report", "model_self_report_capped")
    assert window.effective_tokens == int(102400 * 0.7)
    # allowance = 102400 * 0.7 * 3.0 chars
    assert window.to_chars(window.effective_tokens) == 215040


def test_d7_calibration_defaults():
    class _Info:
        max_sequence_length = 102400

    window = resolve_window(_Info(), None)
    assert window.chars_per_token == 3.0
    assert window.effective_tokens == 71680  # 102400 * 0.7
    assert window.to_chars(71680) == 215040


def test_operator_cap_still_wins_when_smaller():
    class _Info:
        max_sequence_length = 102400

    class _Small:
        max_input_length = 65536

    window = resolve_window(_Info(), _Small())
    assert window.source == "model_self_report_capped"
    assert window.effective_tokens == int(65536 * 0.7)


def test_config_fallback_when_nothing_is_reported():
    class _Info:
        max_sequence_length = None

    window = resolve_window(_Info(), _Run())
    assert window.source == "config_fallback"
    assert window.effective_tokens == int(131072 * 0.7)


# ── providers publishing their own window ───────────────────────────


def test_anthropic_normalize_carries_context_window():
    class _Row:
        id = "claude-sonnet-4-5"
        display_name = "Claude Sonnet 4.5"
        max_input_tokens = 200000

    models = AnthropicProvider._normalize_models_payload({"data": [_Row()]})
    assert models[0].max_sequence_length == 200000


def test_anthropic_ignores_junk_windows():
    assert AnthropicProvider._extract_context_length({"max_input_tokens": 9}) is None
    assert AnthropicProvider._extract_context_length({}) is None
    assert (
        AnthropicProvider._extract_context_length({"context_window": 32768})
        == 32768
    )


def test_gemini_normalize_carries_input_token_limit():
    class _Row:
        name = "models/gemini-2.5-pro"
        display_name = "Gemini 2.5 Pro"
        input_token_limit = 1048576

    models = GeminiProvider._normalize_models_payload([_Row()])
    assert models[0].max_sequence_length == 1048576
    assert models[0].id == "gemini-2.5-pro"


def test_openai_carries_vllm_max_model_len():
    class _Row:
        id = "qwen3"
        max_model_len = 32768

    assert OpenAIProvider._extract_context_length(_Row()) == 32768


def test_model_slot_of_walks_known_shapes():
    class _Keyed:
        model_key = "ollama/qwen3:8b"

    assert model_slot_of(_Keyed()) == ("ollama", "qwen3:8b")

    class _Inner:
        _provider_id = "openai"
        model_name = "gpt"

    assert model_slot_of(_Inner()) == ("openai", "gpt")


def test_window_probe_is_throttled_and_needs_a_provider():
    from coapis.providers.provider_manager import ProviderManager

    manager = ProviderManager.get_instance()
    # Unknown provider: nothing to probe, and no exception.
    assert manager.request_window_probe("definitely-not-a-provider") is False

    async def _drive():
        first = manager.request_window_probe("ollama")
        second = manager.request_window_probe("ollama")
        return first, second

    try:
        first, second = asyncio.run(_drive())
    except RuntimeError:  # pragma: no cover - no loop available
        pytest.skip("no event loop for the probe task")
    # At most one probe per provider per interval, whatever the loop state.
    assert second is False
    if first:
        # Let the scheduled probe finish so it cannot leak into other tests.
        async def _drain():
            await asyncio.sleep(0.05)

        asyncio.run(_drain())


def test_discovery_fills_a_missing_window_and_never_clobbers_a_real_one(
    monkeypatch,
):
    """The merge must let ``meta.n_ctx`` land.

    ``fetch_provider_models`` preserves user-set metadata for known models,
    and that loop used to copy ``old.max_sequence_length`` unconditionally —
    so a hand-added model (window ``None``) swallowed every discovered
    ``n_ctx`` and the context budget stayed on ``config_fallback`` forever
    (measured on dev, 2026-10-17: 53/53 sessions on the fallback).
    """
    from coapis.providers import provider_manager as pmod
    from coapis.providers.provider import ModelInfo

    class _FakeProvider:
        id = "fake-win"

        def __init__(self, models):
            self.models = models

        async def fetch_models(self, timeout: float = 5):
            return [
                ModelInfo(id="m1", name="m1", max_sequence_length=102400),
                ModelInfo(id="m2", name="m2", max_sequence_length=204800),
            ]

    manager = pmod.ProviderManager.get_instance()
    provider = _FakeProvider(
        [
            ModelInfo(id="m1", name="m1", max_sequence_length=None),
            ModelInfo(id="m2", name="m2", max_sequence_length=8192),
        ],
    )
    monkeypatch.setattr(manager, "get_provider", lambda _pid: provider)
    monkeypatch.setattr(manager, "_save_provider", lambda *_a, **_k: None)
    monkeypatch.setattr(
        manager,
        "_save_plugin_provider",
        lambda *_a, **_k: None,
    )

    asyncio.run(manager.fetch_provider_models("fake-win", save=True))

    stored = {m.id: m.max_sequence_length for m in provider.models}
    assert stored["m1"] == 102400, "a discovered window must fill the hole"
    assert stored["m2"] == 8192, "an operator-set window must win"
