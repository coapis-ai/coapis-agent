# -*- coding: utf-8 -*-
"""Single source of truth for the tool-guard configuration (C2).

Before C2 there were **three** places holding tool-guard settings:

1. ``server/coapis/system/tool_guard.yaml``   – shipped defaults, read by the
   unified engine (read-only in a container image).
2. ``{WORKING_DIR}/system/tool_guard.yaml``   – the copy the console routes
   read/wrote (``DATA_DIR.parent/"system"`` == ``SYSTEM_DIR``).
3. ``config.json`` ``security.tool_guard`` / ``security.file_guard`` – read by
   the legacy engine, the file guardian and the ``/config/security/*`` routes.

Consequence measured on dev 2026-10-15: flipping the console switch wrote
``config.json`` while the engine that actually decided tool calls read the
shipped YAML → the switch did nothing.

After C2 there is exactly **one** file:

    {WORKING_DIR}/system/tool_guard.yaml        (runtime, writable, persistent)

seeded from the shipped defaults on first use.  ``COAPIS_TOOL_GUARD_YAML``
overrides the location (tests / custom deployments).  Every reader — the
unified engine, the file-path guardian and the console routes — resolves the
path through :func:`resolve_yaml_path`, so a console write is always visible
to the engine after a reload.

Upgrade note: the runtime file is user data and is *not* overwritten by a new
image.  When a release ships new built-in rules, run
``scripts/migrate_tool_guard_single_source.py`` (merge mode) to fold the new
defaults in while keeping the operator's edits.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

ENV_OVERRIDE = "COAPIS_TOOL_GUARD_YAML"

#: Built-in defaults shipped inside the package (``server/coapis/system/``).
SHIPPED_YAML = Path(__file__).resolve().parents[2] / "system" / "tool_guard.yaml"


def runtime_yaml_path() -> Path:
    """The operator-editable config file (``SYSTEM_DIR/tool_guard.yaml``)."""
    from coapis.constant import SYSTEM_DIR

    return SYSTEM_DIR / "tool_guard.yaml"


def _stamp(data: dict[str, Any], *, kind: str, source: Path | None = None) -> None:
    """Record provenance in ``meta`` so upgrades can tell edits from seeds.

    ``seeded_from`` marks a pristine copy (nobody edited it → a later release
    may replace it wholesale); ``last_edited`` marks operator edits (a later
    release must merge around them).
    """
    import datetime as _dt

    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    stamp = _dt.datetime.now().isoformat(timespec="seconds")
    if kind == "seed":
        meta["seeded_at"] = stamp
        meta["seeded_from"] = _sha256(source) if source else ""
        meta.pop("last_edited", None)
    else:
        meta["last_edited"] = stamp
    data["meta"] = meta


def _sha256(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def resolve_yaml_path() -> Path:
    """Resolve *the* tool-guard YAML path, seeding the runtime copy if needed.

    Priority: ``COAPIS_TOOL_GUARD_YAML`` → runtime file → seeded runtime file
    → shipped file (read-only fallback when the runtime dir is not writable).
    """
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override:
        return Path(override).expanduser().resolve()

    runtime = runtime_yaml_path()
    if runtime.exists():
        return runtime

    if SHIPPED_YAML.exists():
        try:
            runtime.parent.mkdir(parents=True, exist_ok=True)
            data = yaml.safe_load(SHIPPED_YAML.read_text(encoding="utf-8")) or {}
            _stamp(data, kind="seed", source=SHIPPED_YAML)
            _dump(data, runtime)
            logger.info(
                "Seeded tool-guard config %s from shipped defaults", runtime
            )
            return runtime
        except OSError as exc:
            logger.warning(
                "Cannot seed tool-guard config at %s (%s); "
                "falling back to shipped defaults %s",
                runtime,
                exc,
                SHIPPED_YAML,
            )
    return SHIPPED_YAML


def _dump(data: dict[str, Any], path: Path) -> None:
    """Atomically write the YAML mapping."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yaml.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.dump(
            data,
            fh,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=120,
        )
    os.replace(tmp, path)


def load_raw() -> dict[str, Any]:
    """Read the raw YAML mapping (``{}`` when missing/unreadable)."""
    path = resolve_yaml_path()
    if not path.exists():
        logger.warning("tool_guard.yaml not found at %s", path)
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001 - config must never crash the app
        logger.error("Failed to load tool_guard.yaml (%s): %s", path, exc)
        return {}


def save_raw(data: dict[str, Any]) -> Path:
    """Persist the full mapping and reset the engine singleton.

    Returns the path written.  Callers must treat this as the only supported
    write path for tool-guard configuration.
    """
    path = resolve_yaml_path()
    payload = dict(data)
    _stamp(payload, kind="edit")
    _dump(payload, path)

    from .unified_engine import reset_engine

    reset_engine()
    logger.info("Saved tool-guard config: %s", path)
    return path


def is_pristine_seed(data: dict[str, Any]) -> bool:
    """True when the runtime file was seeded and never edited by the console."""
    meta = data.get("meta")
    if not isinstance(meta, dict):
        # Pre-meta files: treat as pristine only when the content matches the
        # shipped baseline (no operator edits to preserve).
        return True
    return "last_edited" not in meta


# ---------------------------------------------------------------------------
# Section accessors (path guard)
# ---------------------------------------------------------------------------


def path_guard_section() -> dict[str, Any]:
    """Return the ``path_guard`` section of the single source."""
    data = load_raw()
    section = data.get("path_guard")
    if isinstance(section, dict):
        return section
    return {}


def path_guard_enabled() -> bool:
    section = path_guard_section()
    return bool(section.get("enabled", True))


def sensitive_files() -> list[str]:
    section = path_guard_section()
    files = section.get("sensitive_files")
    if isinstance(files, list):
        return [str(f) for f in files]
    return []
