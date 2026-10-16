# -*- coding: utf-8 -*-
"""C3 lock: one route, one handler, one source.

Defect being locked (measured on dev 2026-10-15):
  ``GET /api/config/security/tool-guard/builtin-rules`` existed twice in the
  source tree (``config.py`` and ``tool_guard.py``).  ``routers/__init__.py``
  does not mount ``config.py`` (line 37: "Disabled: config.py … depends on
  get_agent_for_request"), so the live duplicate is the always-empty
  ``builtin-rules`` handler inside ``tool_guard.py`` reading a ``rules`` key
  the unified YAML never had → the console's "built-in rules" panel was
  permanently empty.

C3 removes the dead handlers from ``config.py``, deletes the always-empty
rule endpoints, and moves file-guard onto the single YAML source.  This test
locks: no path is registered twice in the router the app actually mounts,
the removed endpoints answer 404, and every guard route reads the same YAML.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from coapis.security.tool_guard.unified_engine import (
    get_unified_engine,
    reset_engine,
)

REPO = Path(__file__).resolve().parents[3]
SERVER = REPO / "server"
SHIPPED_YAML = SERVER / "coapis" / "system" / "tool_guard.yaml"


@pytest.fixture(autouse=True)
def isolated_yaml(tmp_path, monkeypatch):
    """Point the single source at a throwaway copy for the whole test.

    These tests PUT to the guard endpoints; without the override they would
    rewrite the operator's live tool_guard.yaml.
    """
    dst = tmp_path / "tool_guard.yaml"
    dst.write_bytes(SHIPPED_YAML.read_bytes())
    monkeypatch.setenv("COAPIS_TOOL_GUARD_YAML", str(dst))
    # The engine resolves its path once at import, so the env override alone
    # would not move it; point the module constant at the copy as well.
    import coapis.security.tool_guard.unified_engine as ue

    monkeypatch.setattr(ue, "_CONFIG_PATH", dst)
    reset_engine()
    yield dst
    reset_engine()

GUARD_PATHS = (
    "/config/security/tool-guard",
    "/config/security/tool-guard/builtin-rules",
    "/config/security/file-guard",
    "/config/security/shell-guard/rules",
    "/config/security/shell-guard/evasion-checks",
    "/config/security/shell-guard/config",
)

#: Endpoints removed by C3 (dead or duplicated).
REMOVED_PATHS = (
    "/config/security/tool-guard/builtin-rules",
    "/config/security/shell-guard/rules",
    "/config/security/shell-guard/config",
)


def _build_app() -> FastAPI:
    """Mount the guard routers exactly the way the real app does.

    The real app mounts ``coapis.app.routers.router`` (``_app.py``:
    ``app.include_router(api_router, prefix="/api")``).  Note that
    ``routers/__init__.py`` deliberately does **not** mount ``config.py``
    ("Disabled: config.py depends on get_agent_for_request"), so the live
    guard surface is ``tool_guard.py`` only — the duplicate-handler defect
    lived in the unmounted file.  Mounting the real router is what makes
    this a statement about the running service.
    """
    from coapis.app.permissions import decorators as perm_dec
    from coapis.app.routers import router as api_router

    # Route-shape test: neutralise the auth gate so we can inspect the
    # routing table and hit the handlers without a login session.
    perm_dec._perform_permission_check = lambda request, permission: None

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    return app


def _routes(app: FastAPI):
    out = []
    for r in app.routes:
        path = getattr(r, "path", None)
        if path and any(path == "/api" + p for p in GUARD_PATHS):
            out.append((path, getattr(r, "methods", set()), r.endpoint.__name__))
    return out


def test_no_duplicate_guard_routes():
    dup = [
        p for p in GUARD_PATHS
        if len([m for m in _routes(_build_app()) if m[0] == "/api" + p]) > 1
    ]
    assert not dup, f"routes registered more than once: {dup}"


def test_removed_endpoints_answer_404():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    for path in REMOVED_PATHS:
        r = client.get(f"/api{path}")
        assert r.status_code == 404, f"{path} should be gone, got {r.status_code}"


def test_file_guard_is_served_from_the_yaml_source():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    r = client.get("/api/config/security/file-guard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "enabled" in body and "paths" in body


def test_tool_guard_switch_reads_writes_the_single_source():
    """GET/PUT of the master switch must hit the YAML the engine reads."""
    from coapis.security.tool_guard import config_store as cs
    from coapis.security.tool_guard.unified_engine import get_unified_engine, reset_engine

    client = TestClient(_build_app(), raise_server_exceptions=False)
    original = cs.load_raw()
    try:
        r = client.put(
            "/api/config/security/tool-guard",
            json={"enabled": False},
        )
        assert r.status_code == 200, r.text
        reset_engine()
        assert cs.load_raw()["access_control"]["enabled"] is False
        assert get_unified_engine().enabled is False
        g = client.get("/api/config/security/tool-guard")
        assert g.json()["enabled"] is False
    finally:
        data = dict(original)
        cs.save_raw(data)
        reset_engine()


def test_console_write_reloads_the_running_engine(isolated_yaml):
    """A console write must change the engine the sessions are using.

    The engine is a process-wide singleton holding a parsed copy of the YAML.
    Measured on dev 2026-10-15: all nine guard PUT handlers wrote the file and
    none reloaded the engine, so flipping the master switch only took effect
    after a service restart.
    """
    client = TestClient(_build_app(), raise_server_exceptions=False)
    base = "/api/config/security/tool-guard"

    assert get_unified_engine().enabled is True
    r = client.put(base, json={"enabled": False})
    assert r.status_code == 200
    assert get_unified_engine().enabled is False, (
        "engine kept the old config after the console turned it off"
    )
    r = client.put(base, json={"enabled": True})
    assert r.status_code == 200
    assert get_unified_engine().enabled is True


def test_master_switch_off_bypasses_the_mixin_gate(isolated_yaml):
    """Console switch off → the mixin must not gate tool calls any more.

    Locks the last link of the chain the C2 fix is about:
    console PUT → single YAML → ``engine.reload()`` → ``engine.enabled`` →
    ``ToolGuardMixin._decide_guard_action``.
    """
    import asyncio

    from coapis.agents.tool_guard_mixin import ToolGuardMixin
    from coapis.security.tool_guard.execution_level import ToolExecutionLevel

    client = TestClient(_build_app(), raise_server_exceptions=False)
    tool_call = {
        "name": "execute_shell_command",
        "input": {"command": "rm -rf /tmp/x"},
    }
    class _Stub:
        """Minimal stand-in for the mixin host (engine resolved per call)."""

        _agent_config = None

        @property
        def _tool_guard_engine(self):
            return get_unified_engine()

        def _get_tool_execution_level(self):
            return ToolExecutionLevel.AUTO

        def _get_current_user_role(self):
            return "admin"

        def _plan_scope_covers(self, tool_name, tool_call):
            return False

    stub = _Stub()

    assert get_unified_engine().enabled is True
    r = client.put("/api/config/security/tool-guard", json={"enabled": False})
    assert r.status_code == 200
    assert get_unified_engine().enabled is False
    off = asyncio.run(ToolGuardMixin._decide_guard_action(stub, tool_call))
    assert off is None, "guard must be bypassed when the master switch is off"


def test_config_router_has_no_guard_handlers():
    """C3: config.py must not implement guard routes any more.

    Checked on the source, not by importing: ``routers/__init__.py`` does not
    mount this module, and importing it drags in ``agents.acp`` (which is
    broken against agent-client-protocol 0.12.x — see the acp finding).
    """
    src = (SERVER / "coapis" / "app" / "routers" / "config.py").read_text(
        encoding="utf-8",
    )
    offenders = [
        line.strip()
        for line in src.splitlines()
        if re.search(r"@router\.(get|post|put|delete)\(", line)
        and any(
            k in line for k in ("tool-guard", "file-guard", "shell-guard")
        )
    ]
    assert not offenders, f"config.py still serves guard routes: {offenders}"
