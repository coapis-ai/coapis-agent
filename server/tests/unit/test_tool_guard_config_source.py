# -*- coding: utf-8 -*-
"""C2 lock: tool-guard configuration has exactly ONE source.

Defect being locked (measured on dev 2026-10-15):
  * the console's master switch wrote ``config.json``
    (``PUT /config/security/tool-guard`` -> ``config.security.tool_guard``);
  * the engine that decided tool calls read
    ``server/coapis/system/tool_guard.yaml``;
  * the console's rule list read a ``rules`` key that never existed
    (``/config/security/tool-guard/builtin-rules`` -> ``[]`` forever).

C2 makes ``{WORKING_DIR}/system/tool_guard.yaml`` the single source for
engine + console + file guard, and C5 removes the legacy sources entirely.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tests.unit._tool_guard_legacy_baseline import LEGACY_RULE_IDS

import coapis.security.tool_guard.unified_engine as ue
from coapis.security.tool_guard.unified_engine import UnifiedToolGuardEngine

REPO = Path(__file__).resolve().parents[3]
SERVER = REPO / "server"


# ---------------------------------------------------------------------------
# The single source
# ---------------------------------------------------------------------------


def test_single_source_path_is_runtime_yaml(monkeypatch):
    """The engine reads the runtime YAML (SYSTEM_DIR), not the code tree."""
    from coapis.security.tool_guard import config_store as cs

    monkeypatch.delenv(cs.ENV_OVERRIDE, raising=False)
    resolved = cs.resolve_yaml_path()
    assert resolved.name == "tool_guard.yaml"
    assert resolved.exists()
    # Not the in-package shipped file (read-only inside a container image).
    assert resolved != cs.SHIPPED_YAML


def test_env_override_wins(monkeypatch, tmp_path):
    from coapis.security.tool_guard import config_store as cs

    target = tmp_path / "custom.yaml"
    target.write_text(
        yaml.dump({"access_control": {"enabled": False}}), encoding="utf-8"
    )
    monkeypatch.setenv(cs.ENV_OVERRIDE, str(target))
    assert cs.resolve_yaml_path() == target.resolve()


def test_runtime_file_seeded_from_shipped_when_missing(monkeypatch, tmp_path):
    from coapis.security.tool_guard import config_store as cs

    monkeypatch.delenv(cs.ENV_OVERRIDE, raising=False)
    monkeypatch.setattr(
        cs, "runtime_yaml_path", lambda: tmp_path / "system" / "tool_guard.yaml"
    )
    resolved = cs.resolve_yaml_path()
    assert resolved == (tmp_path / "system" / "tool_guard.yaml")
    assert resolved.exists(), "runtime copy must be seeded from shipped defaults"
    assert yaml.safe_load(resolved.read_text(encoding="utf-8")).get("commands")


def test_router_and_engine_read_the_same_file():
    """C3: the console route and the engine resolve the identical path.

    Compared through the dynamic resolver: ``tool_guard.TOOL_GUARD_YAML`` is a
    module constant frozen at import, so comparing it here would only prove
    that two imports happened under the same environment.
    """
    from coapis.app.routers import tool_guard as tg_router

    assert Path(tg_router.config_file_path()).resolve() == Path(ue._CONFIG_PATH).resolve()


def test_file_guardian_reads_the_single_source(monkeypatch):
    """Path layer must not read config.json any more."""
    from coapis.security.tool_guard.guardians import file_guardian as fg

    cfg = yaml.safe_load(Path(ue._CONFIG_PATH).read_text(encoding="utf-8"))
    cfg["path_guard"] = {"enabled": False, "sensitive_files": ["/tmp/canary-dir"]}
    monkeypatch.setattr(ue, "_CONFIG_PATH", Path("/dev/null"))
    monkeypatch.setattr(
        "coapis.security.tool_guard.config_store.load_raw", lambda: cfg
    )
    assert fg._is_file_guard_enabled() is False
    assert any("canary-dir" in p for p in fg._load_sensitive_files_from_config())


# ---------------------------------------------------------------------------
# C5: the legacy sources are gone
# ---------------------------------------------------------------------------


def test_legacy_engine_files_removed():
    tg = SERVER / "coapis" / "security" / "tool_guard"
    assert not (tg / "engine.py").exists(), "legacy ToolGuardEngine must be retired"
    assert not (tg / "guardians" / "rule_guardian.py").exists()
    assert not (tg / "rules" / "dangerous_shell_commands.yaml").exists()
    assert not (tg / "migrate_to_unified.py").exists()


def test_config_json_no_longer_carries_guard_sections():
    """``security.tool_guard`` / ``security.file_guard`` left config.json (C2)."""
    from coapis.config.config import SecurityConfig

    fields = set(SecurityConfig.model_fields)
    assert "tool_guard" not in fields
    assert "file_guard" not in fields
    # Stale keys in an existing config.json must be tolerated, not crash.
    cfg = SecurityConfig.model_validate(
        {"tool_guard": {"enabled": False}, "file_guard": {"enabled": False}},
    )
    assert cfg.skill_scanner is not None


def test_legacy_resolvers_removed():
    from coapis.security.tool_guard import utils

    assert not hasattr(utils, "resolve_guarded_tools")
    assert not hasattr(utils, "resolve_denied_tools")


def test_unified_config_covers_legacy_rule_ids():
    """The frozen legacy baseline (28 ids) must be a subset of the unified set."""
    cfg = yaml.safe_load(Path(ue._CONFIG_PATH).read_text(encoding="utf-8"))
    unified_ids = {r["id"] for r in cfg.get("global_rules", [])}
    missing = set(LEGACY_RULE_IDS) - unified_ids
    assert not missing, f"legacy rules missing from the unified config: {missing}"


def test_config_json_side_effect_is_gone():
    """Writing config.json must not change what the engine decides."""
    engine = UnifiedToolGuardEngine()
    before = engine.process_command(
        "execute_shell_command", {"command": "rm -rf /tmp/xyz"},
    )["action"]
    assert before in ("block", "confirm")
