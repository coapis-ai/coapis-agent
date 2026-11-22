"""P1 and P2 of the context budget: measured evidence, and a refusal that pays.

P1 asks a question the selection gate could not ask before. Not "is the
declared window big enough" -- the declaration is a claim -- but "can it hold
what our own prompts cost on it". The gate measures that cost every turn;
these tests check the measurement reaches the gate that chooses models, and
that a slot nobody has measured is left exactly as it was.

P2 is the fallback. A provider that refuses with a stated cap has corrected
our view of the window; filing that correction and letting the turn die spends
a fact on a log line.
"""

import asyncio

import pytest

from coapis.agents.context.context_budget import (
    ContextBudgetGuard,
    ContextOverflowError,
)
from coapis.agents.context.window_source import (
    MIN_USABLE_WINDOW_TOKENS,
    WindowInfo,
    _MEASURED_FIXED,
    _apply_measured_evidence,
    check_model_window,
    measured_usability,
    parse_window_feedback,
    record_measured_fixed,
    record_window_feedback,
    window_usability,
)

PROVIDER = "selfcheck-provider"

REFUSAL = (
    "This model's maximum context length is %d tokens. "
    "Received prompt with 9000 tokens of text."
)


@pytest.fixture(autouse=True)
def _clear_window_evidence():
    """Window evidence is process-global.

    A guard budgets against it before sending, so a refusal recorded by
    one test would otherwise tighten the window of the next one and make
    it fail for a reason that has nothing to do with it.
    """
    from coapis.agents.context import window_source as ws

    ws._FEEDBACK.clear()
    yield
    ws._FEEDBACK.clear()


@pytest.fixture(autouse=True)
def _clean_measured_registry():
    _MEASURED_FIXED.clear()
    yield
    _MEASURED_FIXED.clear()


def _window(tokens, chars_per_token=4.0):
    return WindowInfo(
        reported_tokens=tokens,
        effective_tokens=tokens,
        source="declared",
        chars_per_token=chars_per_token,
    )


def _history(turns, size=400):
    rows = []
    for i in range(turns):
        rows.append({"role": "user", "content": "q%d %s" % (i, "x" * size)})
        rows.append({"role": "assistant", "content": "a%d %s" % (i, "y" * size)})
    return rows


class _RefusalModel:
    """A model that refuses with a provider context error, then recovers."""

    model_key = "%s/m-retry" % PROVIDER

    def __init__(self, refusals=1, cap=4000):
        self.refusals = refusals
        self.cap = cap
        self.calls = 0

    async def __call__(self, messages, tools=None, **kwargs):
        self.calls += 1
        if self.calls <= self.refusals:
            raise RuntimeError(REFUSAL % self.cap)
        return {"ok": True}


# ── P1: the selection gate may use what the runtime measured ─────────────────


def test_declaration_alone_passes_a_window_the_fixed_part_cannot_fill():
    """20k tokens looks usable. That judgement has no idea what we spend."""
    assert window_usability(20000)["usable"] is True


def test_measured_fixed_overhead_vetoes_that_same_declaration():
    record_measured_fixed(PROVIDER, "m-fixed", 19000)

    verdict = _apply_measured_evidence(window_usability(20000), PROVIDER, "m-fixed")

    assert verdict["usable"] is False
    assert verdict["measured"]["fixed_tokens"] == 19000
    assert "fixed part" in verdict["reason"]


def test_a_window_far_above_the_measured_fixed_part_still_passes():
    record_measured_fixed(PROVIDER, "m-big", 19000)

    verdict = _apply_measured_evidence(window_usability(200000), PROVIDER, "m-big")

    assert verdict["usable"] is True


def test_unmeasured_slot_keeps_the_verdict_it_was_given():
    declared = window_usability(131072)

    out = _apply_measured_evidence(declared, PROVIDER, "never-measured")

    assert out["usable"] == declared["usable"]
    assert out["measured"]["usable"] is None


def test_nothing_measured_never_reports_a_verdict():
    assert measured_usability(PROVIDER, "never-measured")["usable"] is None


def test_a_refusal_below_the_floor_vetoes_a_generous_declaration():
    record_window_feedback(PROVIDER, "m-cap", REFUSAL % 4000, 36000, 4.0)

    verdict = _apply_measured_evidence(window_usability(131072), PROVIDER, "m-cap")

    assert verdict["usable"] is False
    assert verdict["measured"]["proven_tokens"] == 4000
    assert MIN_USABLE_WINDOW_TOKENS > 4000


def test_selection_gate_carries_the_measured_veto_end_to_end():
    """The function the model screen actually calls, unchanged by its callers."""
    record_window_feedback(PROVIDER, "m-live", REFUSAL % 4000, 36000, 4.0)

    verdict = check_model_window(PROVIDER, "m-live")

    assert verdict["usable"] is False


# ── P2: a refusal that states a smaller window is re-enforced, not fatal ─────


def test_a_refusal_stating_a_smaller_window_is_enforced_again_and_retried():
    model = _RefusalModel()
    guard = ContextBudgetGuard(model, window=_window(100000), agent_name="selfcheck")
    messages = [{"role": "system", "content": "be brief"}] + _history(5)

    result = asyncio.run(guard(messages, tools=None))

    assert result == {"ok": True}
    assert model.calls == 2
    assert guard.window.effective_tokens == 4000
    assert guard.window.source == "observed"


def test_a_second_refusal_is_not_retried_again():
    model = _RefusalModel(refusals=99)
    guard = ContextBudgetGuard(model, window=_window(100000), agent_name="selfcheck")
    messages = [{"role": "system", "content": "be brief"}] + _history(5)

    with pytest.raises(RuntimeError):
        asyncio.run(guard(messages, tools=None))

    assert model.calls == 2


def test_a_refusal_stating_a_cap_and_a_prompt_size_is_taken_as_stated():
    """Both numbers in the refusal are read: the cap and what we sent.

    This is the wording an Anthropic-compatible endpoint actually returns.
    """
    report = parse_window_feedback("prompt is too long: 9000 tokens > 4000 maximum")
    assert report["window_tokens"] == 4000
    assert report["prompt_tokens"] == 9000


def test_retry_gives_up_when_even_the_tightened_window_cannot_hold_the_prompt():
    """512 tokens is a 2048-char window: our fixed part alone is far over it.

    The gate must then stop rather than send a second doomed request, and let
    the provider's own refusal stand as the answer.
    """
    model = _RefusalModel(cap=512)
    guard = ContextBudgetGuard(model, window=_window(100000), agent_name="selfcheck")
    messages = [{"role": "system", "content": "z" * 200000}] + _history(3)

    with pytest.raises(RuntimeError):
        asyncio.run(guard(messages, tools=None))

    # One call: re-enforcing against the stated cap found no way to fit, so no
    # second request went out.
    assert model.calls == 1


def test_a_tightened_window_still_answers_when_a_degraded_cut_can_reach_it():
    """Where a cut can reach, the turn is saved rather than lost.

    4000 tokens cannot hold a 200k-char system prompt as it stands, but the
    gate can shed the tool catalogue and cut the system prompt down to the
    window. That is a degraded answer, not a silent success: it has to be
    marked as such on the snapshot.
    """
    model = _RefusalModel(cap=4000)
    guard = ContextBudgetGuard(model, window=_window(100000), agent_name="selfcheck")
    messages = [{"role": "system", "content": "z" * 200000}] + _history(3)

    result = asyncio.run(guard(messages, tools=None))

    assert result == {"ok": True}
    assert model.calls == 2
    assert guard.degrade_mode



def test_a_refusal_that_teaches_nothing_smaller_is_not_retried():
    model = _RefusalModel(cap=200000)
    guard = ContextBudgetGuard(model, window=_window(100000), agent_name="selfcheck")
    messages = [{"role": "system", "content": "be brief"}] + _history(5)

    with pytest.raises(RuntimeError):
        asyncio.run(guard(messages, tools=None))

    assert model.calls == 1



def test_a_measured_ceiling_is_adopted_before_the_first_request():
    """Evidence on record must change the *next* request, not just the verdict.

    The operator declares 1000000 tokens for a slot whose provider has already
    refused everything above 404. Budgeting against the declared number sends a
    request we know will be refused; the gate has to spend the measured ceiling
    instead and refuse it locally, without touching the network.
    """
    provider_id, model_name = "measured-first-provider", "m-404"
    record_window_feedback(
        provider_id,
        model_name,
        REFUSAL % 404,
        measured_chars=202652,
        chars_per_token=4.0,
    )

    class Slot(_RefusalModel):
        model_key = provider_id + "/" + model_name

    model = Slot(cap=404)
    guard = ContextBudgetGuard(model, window=_window(1000000), agent_name="measured-first")
    messages = [{"role": "system", "content": "z" * 200000}] + _history(3)

    with pytest.raises(ContextOverflowError):
        asyncio.run(guard(messages, tools=None))

    # Refused locally: the provider was never asked.
    assert model.calls == 0


def test_a_stated_cap_below_the_parsing_floor_is_still_the_cap_we_believe():
    """A small stated cap is the pathology, not noise, and beats a guess.

    404 tokens is below our parsing floor, so it used to be discarded and the
    window was invented from the size of the prompt that failed -- which came
    out *bigger* than the cap the provider had just told us, and the slot read
    as usable for a whole day.
    """
    record_window_feedback(
        PROVIDER,
        "tiny-slot",
        REFUSAL % 404,
        measured_chars=202652,
        chars_per_token=4.0,
    )
    verdict = measured_usability(PROVIDER, "tiny-slot", declared_tokens=1000000)
    assert verdict["usable"] is False
    assert verdict["proven_tokens"] == 404


def test_an_upper_bound_from_a_refusal_never_certifies_a_usable_slot():
    """A refusal proves the window is *under* a number, never that it reaches it.

    So the bound may tighten the gate, but it cannot hand out a pass to a slot
    that has never served anything. The verdict is withheld with a reason, not
    answered with a yes.
    """
    record_window_feedback(
        PROVIDER,
        "never-served",
        "the prompt is too long for this deployment",
        measured_chars=100000,
        chars_per_token=4.0,
    )
    verdict = measured_usability(PROVIDER, "never-served", declared_tokens=131072)
    assert verdict["usable"] is None
    assert "upper bound" in verdict["reason"]


def test_an_inferred_bound_never_lifts_a_tiny_slot_to_a_floor():
    """Inference is a ceiling: a smaller failed prompt gives a smaller bound."""
    record_window_feedback(
        PROVIDER,
        "small-refusal",
        "context length exceeded",
        measured_chars=800,
        chars_per_token=4.0,
    )
    verdict = measured_usability(PROVIDER, "small-refusal", declared_tokens=131072)
    assert verdict["usable"] is False
    assert 0 < verdict["proven_tokens"] < MIN_USABLE_WINDOW_TOKENS
