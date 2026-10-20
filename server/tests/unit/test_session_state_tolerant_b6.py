# -*- coding: utf-8 -*-
"""B6: an old session file must restore, not be thrown away.

Measured on prod 2026-10-19: 10 occurrences of
``Key 'toolkit' not found in state_dict`` in 24 hours -- one per chat start --
and the runner's handler answered by discarding the saved history.
"""

import json

import pytest

from coapis.app.runner.session import SafeJSONSession, _load_state_tolerant


class _Module:
    """Minimal StateModule stand-in: declares modules, restores what it gets."""

    def __init__(self) -> None:
        self._module_dict = {"memory": self, "toolkit": self}
        self._attribute_dict: dict = {}
        self.loaded = None
        self.strict_seen = None

    def state_dict(self):
        return {"memory": {"content": []}}

    def load_state_dict(self, state_dict, strict=True):
        self.strict_seen = strict
        if strict:
            for key in self._module_dict:
                if key not in state_dict:
                    raise KeyError(f"Key '{key}' not found in state_dict")
        self.loaded = state_dict


class _LegacyModule(_Module):
    """A module predating the ``strict`` keyword."""

    def load_state_dict(self, state_dict, strict=True):  # noqa: ARG002
        del strict
        for key in self._module_dict:
            if key not in state_dict:
                raise KeyError(f"Key '{key}' not found in state_dict")
        self.loaded = state_dict


def test_tolerant_load_skips_missing_module_and_keeps_the_rest():
    module = _Module()
    saved = {"memory": {"content": [["hi"]]}}

    missing = _load_state_tolerant(module, saved)

    assert missing == ["toolkit"]
    assert module.strict_seen is False
    assert module.loaded == saved


def test_tolerant_load_reports_nothing_when_file_is_complete():
    module = _Module()
    saved = {"memory": {"content": []}, "toolkit": {}}

    assert _load_state_tolerant(module, saved) == []
    assert module.loaded == saved


def test_tolerant_load_keeps_strict_behaviour_for_legacy_modules():
    module = _LegacyModule()
    saved = {"memory": {"content": []}}

    with pytest.raises(KeyError):
        _load_state_tolerant(module, saved)


@pytest.mark.asyncio
async def test_load_session_state_restores_old_file(tmp_path):
    """The regression: a file without ``toolkit`` must load, not raise."""
    session = SafeJSONSession(save_dir=str(tmp_path))
    agent = _Module()
    # Write an old record by hand: it predates the toolkit module.
    path = session._get_save_path("chat-1", user_id="u1")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"agent": {"memory": {"content": [["old", "dialog"]]}}}, fh)

    await session.load_session_state(
        session_id="chat-1",
        user_id="u1",
        agent=agent,
    )

    assert agent.loaded == {"memory": {"content": [["old", "dialog"]]}}


@pytest.mark.asyncio
async def test_load_session_state_survives_missing_top_module(tmp_path):
    session = SafeJSONSession(save_dir=str(tmp_path))
    agent = _Module()
    path = session._get_save_path("chat-2", user_id="u1")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"other": {"whatever": 1}}, fh)

    await session.load_session_state(
        session_id="chat-2",
        user_id="u1",
        agent=agent,
    )
    assert agent.loaded is None
