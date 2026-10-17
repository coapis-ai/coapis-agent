"""Utilities for discovering and loading template-type global agents."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def get_template_agents() -> List[Path]:
    """Return all enabled global baseline agent directories, sorted by priority.

    Global baseline agents (id starting with 'global_') are the base layer
    that all other agents inherit from.  Lower priority number = outermost layer.
    Agents without a priority field default to 100.

    Returns:
        Sorted list of Paths to global agent directories (global_*).
    """
    from ..constant import AGENTS_DIR

    results: list[tuple[int, Path]] = []
    if not AGENTS_DIR.exists():
        return []

    for agent_dir in AGENTS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        # Only global baseline agents (global_*) serve as inheritance source
        if not agent_dir.name.startswith("global_"):
            continue
        agent_json = agent_dir / "agent.json"
        if not agent_json.exists():
            continue
        try:
            with open(agent_json, encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            continue

        if config.get("enabled", True):
            priority = config.get("priority", 100)
            results.append((int(priority) if priority is not None else 100, agent_dir))

    # Sort by priority ascending (lower number = outermost layer)
    results.sort(key=lambda x: x[0])
    return [path for _, path in results]


def get_service_agents() -> List[Path]:
    """Return all enabled service-type global agent directories."""
    from ..constant import AGENTS_DIR

    results: list[Path] = []
    if not AGENTS_DIR.exists():
        return []

    for agent_dir in AGENTS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        agent_json = agent_dir / "agent.json"
        if not agent_json.exists():
            continue
        try:
            with open(agent_json, encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            continue

        if config.get("role") in ("service", "hybrid") and config.get("enabled", True):
            results.append(agent_dir)

    return results
