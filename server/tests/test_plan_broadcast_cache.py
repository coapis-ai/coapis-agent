"""Regression tests for the plan live cache and finished-plan snapshot.

Covers three defects that made the chat plan panel useless:
1. the runtime cached plans under the channel session id while the UI
   queries by the ChatSpec UUID (``session_ids`` aliases fix that);
2. ``finish_plan`` cleared ``current_plan`` and the hook forwarded ``None``,
   so a completed plan vanished (``finished_plan_snapshot`` fixes that);
3. the live cache grew without bound.
"""
from __future__ import annotations

import asyncio

import pytest

from coapis.plan import broadcast as bc
from coapis.plan.lifecycle import finished_plan_snapshot


@pytest.fixture(autouse=True)
def _clear_caches():
    bc._plan_live_cache.clear()
    bc._sse_clients.clear()
    yield
    bc._plan_live_cache.clear()
    bc._sse_clients.clear()


def _plan(name="演练", state="in_progress", substates=("todo", "todo", "todo")):
    return {
        "id": "p1",
        "name": name,
        "state": state,
        "description": "d",
        "expected_outcome": "eo",
        "outcome": None,
        "subtasks": [
            {"name": f"s{i}", "state": st, "description": "", "outcome": None}
            for i, st in enumerate(substates)
        ],
    }


def test_aliases_make_both_ids_hit_the_same_plan():
    """A plan cached under the channel id is found by the chat UUID."""
    plan = _plan()
    bc.broadcast_plan_update(
        "admin",
        {"type": "plan_update", "plan": plan},
        session_id="console:admin",
        session_ids=["console:admin", "a089b560-uuid"],
    )

    found_chan, p_chan = bc.get_live_plan("admin", "console:admin")
    found_uuid, p_uuid = bc.get_live_plan("admin", "a089b560-uuid")

    assert found_chan and found_uuid
    assert p_chan["name"] == "演练"
    assert p_uuid["name"] == "演练"
    assert set(p_uuid["session_ids"]) == {"console:admin", "a089b560-uuid"}


def test_unrelated_session_stays_empty():
    bc.broadcast_plan_update(
        "admin",
        {"type": "plan_update", "plan": _plan()},
        session_id="console:admin",
        session_ids=["console:admin"],
    )
    found, data = bc.get_live_plan("admin", "some-other-chat")
    assert found is False
    assert data is None


def test_no_session_returns_most_recent_plan():
    bc.broadcast_plan_update(
        "admin",
        {"type": "plan_update", "plan": _plan(name="旧计划")},
        session_id="s1",
    )
    bc.broadcast_plan_update(
        "admin",
        {"type": "plan_update", "plan": _plan(name="新计划")},
        session_id="s2",
    )
    found, data = bc.get_live_plan("admin")
    assert found is True
    assert data["name"] == "新计划"


def test_live_cache_is_bounded():
    for i in range(bc._MAX_LIVE_SESSIONS + 25):
        bc.broadcast_plan_update(
            "admin",
            {"type": "plan_update", "plan": _plan(name=f"p{i}")},
            session_id=f"s{i}",
        )
    keys = bc.get_cached_session_keys("admin")
    assert len(keys) == bc._MAX_LIVE_SESSIONS
    assert "s0" not in keys


def test_sse_payload_carries_aliases_for_filtering():
    q = bc.register_sse_client("admin")
    bc.broadcast_plan_update(
        "admin",
        {"type": "plan_update", "plan": _plan()},
        session_id="console:admin",
        session_ids=["console:admin", "uuid-1"],
    )
    payload = q.get_nowait()
    assert payload["session_id"] == "console:admin"
    assert set(payload["session_ids"]) == {"console:admin", "uuid-1"}


class _FakeNotebook:
    def __init__(self, stored=None, last=None):
        self.storage = type("S", (), {"plans": stored or {}})()
        if last is not None:
            self._qp_last_plan_data = last


def test_finished_snapshot_uses_stored_plan_state():
    stored = {"p1": _plan(substates=("done", "done", "done"))}
    snap = finished_plan_snapshot(_FakeNotebook(stored=stored))
    assert snap["finished"] is True
    assert snap["state"] == "done"


def test_finished_snapshot_marks_abandoned_when_nothing_moved():
    stored = {"p1": _plan(substates=("todo", "todo"))}
    snap = finished_plan_snapshot(_FakeNotebook(stored=stored))
    assert snap["state"] == "abandoned"


def test_finished_snapshot_partial_run_is_in_progress():
    stored = {"p1": _plan(substates=("done", "in_progress", "todo"))}
    snap = finished_plan_snapshot(_FakeNotebook(stored=stored))
    assert snap["state"] == "in_progress"


def test_finished_snapshot_falls_back_to_last_live_data():
    last = _plan(substates=("done", "done"))
    snap = finished_plan_snapshot(_FakeNotebook(stored={}, last=last))
    assert snap is not None
    assert snap["finished"] is True
    assert snap["state"] == "done"


def test_finished_snapshot_none_when_nothing_known():
    assert finished_plan_snapshot(_FakeNotebook(stored={})) is None


def test_empty_plan_counts_as_done():
    snap = finished_plan_snapshot(
        _FakeNotebook(stored={"p1": _plan(substates=())}),
    )
    assert snap["state"] == "done"


def test_broadcast_keeps_working_with_single_session_id():
    """Historical single-key callers must keep working unchanged."""
    bc.broadcast_plan_update(
        "admin",
        {"type": "plan_update", "plan": _plan()},
        session_id="only-one",
    )
    found, data = bc.get_live_plan("admin", "only-one")
    assert found is True
    assert data is not None

@pytest.mark.asyncio
async def test_finished_snapshot_with_real_agentscope_plan():
    """Production path: storage holds real ``Plan`` objects, not dicts."""
    from agentscope.plan import InMemoryPlanStorage, Plan, SubTask

    notebook = type("NB", (), {})()
    notebook.storage = InMemoryPlanStorage()
    notebook._qp_last_plan_data = None

    plan = Plan(
        name="真实计划",
        description="d",
        expected_outcome="eo",
        subtasks=[
            SubTask(name="s1", description="d", expected_outcome="e"),
            SubTask(name="s2", description="d", expected_outcome="e"),
        ],
    )
    for st in plan.subtasks:
        st.state = "done"
        st.outcome = "ok"
    plan.state = "done"
    await notebook.storage.add_plan(plan)

    snap = finished_plan_snapshot(notebook)
    assert snap is not None
    assert snap["name"] == "真实计划"
    assert snap["finished"] is True
    assert snap["state"] == "done"
    assert [s["state"] for s in snap["subtasks"]] == ["done", "done"]

@pytest.mark.asyncio
async def test_unregister_removes_client():
    q = bc.register_sse_client("admin")
    bc.unregister_sse_client("admin", q)
    assert bc._sse_clients.get("admin") in (None, set())
