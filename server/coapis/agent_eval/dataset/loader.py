# -*- coding: utf-8 -*-
"""Dataset loader: read task YAMLs from ``tasks/`` into normalized dicts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

TASKS_DIR = Path(__file__).resolve().parent / "tasks"

_CATEGORIES = (
    "tool_collab",
    "planning",
    "memory",
    "skill_trigger",
    "resource_use",
)


def list_categories() -> list[str]:
    return list(_CATEGORIES)


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults so consumers never deal with missing keys."""
    return {
        "uid": raw["uid"],
        "title": raw.get("title", raw["uid"]),
        "category": raw.get("category", ""),
        "difficulty": int(raw.get("difficulty", 1)),
        "user_turns": list(raw.get("user_turns", [])),
        "cross_session": bool(raw.get("cross_session", False)),
        "followup_turns": list(raw.get("followup_turns", [])),
        "expected_tools": list(raw.get("expected_tools", [])),
        "forbid_tools": list(raw.get("forbid_tools", [])),
        "checks": dict(raw.get("checks", {})),
        "rubric": raw.get("rubric"),
        "setup": list(raw.get("setup", [])),
        "teardown": list(raw.get("teardown", [])),
    }


def load_tasks(category: str | None = None) -> list[dict[str, Any]]:
    """Load all tasks (optionally filtered by category).

    Returns a list of normalized task dicts, stably ordered by filename
    then by appearance in the YAML.
    """
    tasks: list[dict[str, Any]] = []
    wanted = {category} if category else set(_CATEGORIES)
    for path in sorted(TASKS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for raw in data.get("tasks", []):
            norm = _normalize(raw)
            norm["category"] = norm["category"] or path.stem
            if norm["category"] in wanted:
                tasks.append(norm)
    return tasks
