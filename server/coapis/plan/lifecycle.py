"""Plan lifecycle helpers shared by the runner and the API layer.

``finish_plan`` in AgentScope moves the plan into ``notebook.storage`` and
sets ``current_plan`` to ``None``. A hook that naively forwards ``None``
makes a finished plan vanish from the UI the moment it completes, so the
final snapshot has to be reconstructed here.
"""
from __future__ import annotations

import logging
from typing import Any

from .schemas import plan_to_response

logger = logging.getLogger(__name__)


def finished_plan_snapshot(notebook: Any) -> dict[str, Any] | None:
    """Rebuild the final snapshot of a plan whose ``current_plan`` is gone.

    Preference order:
    1. the most recent plan in ``notebook.storage`` (agentscope parks
       finished plans there, with their true final state),
    2. the last snapshot the hook saw while the plan was live.

    The returned dict is marked ``finished=True`` and its ``state`` is
    normalised so the UI can render a truthful completion.
    """
    snapshot: dict[str, Any] | None = None

    stored: list[Any] = []
    try:
        plans = getattr(getattr(notebook, "storage", None), "plans", None)
        if isinstance(plans, dict):
            stored = list(plans.values())
        elif isinstance(plans, list):
            stored = list(plans)
    except Exception:  # pragma: no cover - defensive
        stored = []

    for item in reversed(stored):
        if isinstance(item, dict):
            # Already-serialized plan (e.g. restored from session state).
            snapshot = dict(item)
            break
        try:
            snapshot = plan_to_response(item).model_dump()
            break
        except Exception:
            logger.debug(
                "Could not serialize stored plan; trying the next one",
                exc_info=True,
            )
            snapshot = None

    if snapshot is None:
        last = getattr(notebook, "_qp_last_plan_data", None)
        if isinstance(last, dict):
            snapshot = dict(last)

    if snapshot is None:
        return None

    snapshot = dict(snapshot)
    states = [
        s.get("state")
        for s in (snapshot.get("subtasks") or [])
        if isinstance(s, dict)
    ]
    if not states:
        snapshot["state"] = "done"
    elif all(s == "done" for s in states):
        snapshot["state"] = "done"
    elif all(s == "todo" for s in states):
        snapshot["state"] = "abandoned"
    else:
        snapshot["state"] = "in_progress"
    snapshot["finished"] = True
    try:
        notebook._qp_last_plan_data = snapshot
    except Exception:  # pragma: no cover - defensive
        pass
    return snapshot
