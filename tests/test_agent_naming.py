"""Guards for the canonical agent naming (WP0).

These exist because the dual-track naming was invisible for a long time: the
runtime accepted ``"agent:20"`` and ``"user:admin"`` as interchangeable, and
``derive_workspace_dir`` answered a legacy id with a path that never existed.
Every test below pins a rule that, if broken, re-opens that class of bug.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from coapis.constant import (  # noqa: E402
    AGENTS_DIR,
    WORKSPACES_DIR,
    is_user_agent_id,
    is_valid_agent_key,
    legacy_internal_agent_id,
    normalize_agent_key,
    user_agent_id,
    username_from_user_agent_id,
)
from coapis.config.config import derive_workspace_dir  # noqa: E402


# ---------------------------------------------------------------------------
# Key validation
# ---------------------------------------------------------------------------

VALID_KEYS = [
    "admin",
    "zrsz_156",
    "sczrsz_oa",
    "wang-qian",
    "global_default",
    "王小伟",
    "user_10001",
    "a.b",
]

INVALID_KEYS = [
    "zrsz_153(王小伟)",   # display-name pollution that created real dirs
    "user:admin",         # ':' is the id-namespace separator
    "a/b",
    "a\\b",
    "..",
    "../escape",
    ".hidden",
    "",
    "   ",
    "x" * 65,
    "tab\there",
    "nl\nhere",
    "null\x00",
    "quote'a",
    'quote"a',
    "pipe|",
    "star*",
]


@pytest.mark.parametrize("key", VALID_KEYS)
def test_valid_keys_pass_the_gate(key):
    assert is_valid_agent_key(key)
    assert normalize_agent_key(key) == key


@pytest.mark.parametrize("key", INVALID_KEYS)
def test_invalid_keys_are_rejected(key):
    assert not is_valid_agent_key(key)
    with pytest.raises(ValueError):
        normalize_agent_key(key)


def test_normalize_strips_surrounding_whitespace_only():
    assert normalize_agent_key("  admin  ") == "admin"


def test_non_string_key_raises():
    with pytest.raises(ValueError):
        normalize_agent_key(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Semantic id helpers
# ---------------------------------------------------------------------------

def test_user_agent_id_round_trip():
    aid = user_agent_id("zrsz_156")
    assert aid == "user:zrsz_156"
    assert is_user_agent_id(aid)
    assert username_from_user_agent_id(aid) == "zrsz_156"


def test_user_agent_id_validates_the_username():
    with pytest.raises(ValueError):
        user_agent_id("zrsz_153(王小伟)")


def test_legacy_prefix_is_recognised_and_not_producible():
    assert legacy_internal_agent_id("agent:20")
    assert not legacy_internal_agent_id("user:admin")
    assert not legacy_internal_agent_id("global_default")


# ---------------------------------------------------------------------------
# derive_workspace_dir — the routing contract
# ---------------------------------------------------------------------------

def test_user_default_agent_routes_to_user_workspace():
    got = derive_workspace_dir("user:zrsz_156")
    assert got == WORKSPACES_DIR / "zrsz_156"


def test_user_sub_agent_routes_under_owner_agents():
    got = derive_workspace_dir("mybot", username="zrsz_156")
    assert got == WORKSPACES_DIR / "zrsz_156" / "agents" / "mybot"


def test_global_agent_routes_to_agents_dir():
    got = derive_workspace_dir("global_default")
    assert got == AGENTS_DIR / "global_default"


def test_legacy_internal_id_is_not_routable():
    """The old fall-through produced AGENTS_DIR/'agent:20' — a path that
    never exists, which is how a real agent ended up on a synthetic profile."""
    with pytest.raises(ValueError, match="legacy internal id"):
        derive_workspace_dir("agent:20")


def test_empty_id_is_not_routable():
    with pytest.raises(ValueError):
        derive_workspace_dir("")
    with pytest.raises(ValueError):
        derive_workspace_dir(None)  # type: ignore[arg-type]


def test_user_id_and_owner_must_agree():
    with pytest.raises(ValueError, match="names user"):
        derive_workspace_dir("user:alice", username="bob")


def test_polluted_key_cannot_reach_the_disk():
    with pytest.raises(ValueError):
        derive_workspace_dir("global(显示名)")
    with pytest.raises(ValueError):
        derive_workspace_dir("sub", username="zrsz_153(王小伟)")


def test_every_accepted_id_routes_to_exactly_one_path():
    """No accepted id may fall through to a second candidate directory."""
    cases = [
        ("user:admin", None, WORKSPACES_DIR / "admin"),
        ("global_default", None, AGENTS_DIR / "global_default"),
        ("bot1", "admin", WORKSPACES_DIR / "admin" / "agents" / "bot1"),
    ]
    for aid, owner, expected in cases:
        assert derive_workspace_dir(aid, owner) == expected


# ---------------------------------------------------------------------------
# The model must expose ONE identity field
# ---------------------------------------------------------------------------

def test_agent_profile_config_has_no_second_identity_field():
    from coapis.config.config import AgentProfileConfig

    fields = AgentProfileConfig.model_fields
    assert "id" in fields
    assert "agent_id" not in fields, (
        "agent.json must carry exactly one identity field; a second one is "
        "the naming dual-track"
    )


def test_legacy_agent_json_key_is_tolerated_on_read():
    """Old files on disk still contain agent_id; loading must not explode."""
    from coapis.config.config import AgentProfileConfig

    cfg = AgentProfileConfig.model_validate(
        {
            "id": "user:admin",
            "agent_id": "agent:20",  # retired key present in legacy data
            "name": "Admin",
        }
    )
    assert cfg.id == "user:admin"
    assert not hasattr(cfg, "agent_id")


# ---------------------------------------------------------------------------
# Filesystem-safe data keys (no ':' in a directory name)
# ---------------------------------------------------------------------------

def test_agent_data_key_strips_the_user_prefix():
    from coapis.constant import agent_data_key

    assert agent_data_key("user:admin") == "admin"
    assert agent_data_key("user:zrsz_156") == "zrsz_156"
    assert agent_data_key("codeing") == "codeing"
    assert agent_data_key("global_default") == "global_default"


def test_agent_data_key_never_yields_a_colon_name():
    from coapis.constant import agent_data_key

    for aid in ("user:admin", "user:王小伟", "bot1"):
        assert ":" not in agent_data_key(aid)


def test_agent_data_key_rejects_legacy_and_polluted():
    from coapis.constant import agent_data_key

    with pytest.raises(ValueError):
        agent_data_key("agent:20")
    with pytest.raises(ValueError):
        agent_data_key("x(y)")


def test_sub_agent_key_rejects_reserved_and_legacy_forms():
    from coapis.constant import sub_agent_key

    assert sub_agent_key("mybot") == "mybot"
    for bad in ("user:admin", "agent:20", "a/b", "..", "zrsz_153(王小伟)", ""):
        with pytest.raises(ValueError):
            sub_agent_key(bad)


def test_save_agent_config_drops_the_legacy_key(tmp_path, monkeypatch):
    """A rewrite of a legacy agent.json must not leave agent_id behind."""
    from coapis import constant
    from coapis.config.config import AgentProfileConfig, save_agent_config

    ws = tmp_path / "workspaces" / "admin"
    ws.mkdir(parents=True)
    (ws / "agent.json").write_text(
        json.dumps({"id": "user:admin", "agent_id": "agent:20", "name": "Admin"}),
        encoding="utf-8",
    )

    # derive_workspace_dir() imports these at call time, so patching the
    # constant module is what actually takes effect.
    monkeypatch.setattr(constant, "WORKSPACES_DIR", tmp_path / "workspaces")
    monkeypatch.setattr(constant, "AGENTS_DIR", tmp_path / "agents")

    profile = AgentProfileConfig(id="user:admin", name="Admin")
    save_agent_config("user:admin", profile, workspace_dir=ws)

    saved = json.loads((ws / "agent.json").read_text(encoding="utf-8"))
    assert "agent_id" not in saved
    assert saved["id"] == "user:admin"


# ---------------------------------------------------------------------------
# Manager guards: a ``user:`` id may never become a global workspace
# ---------------------------------------------------------------------------


def _patch_agent_dirs(monkeypatch, tmp_path):
    """Point every module-level copy of the two root dirs at tmp_path.

    AGENTS_DIR/WORKSPACES_DIR are imported by name in several modules, so
    patching coapis.constant alone does not reach them.
    """
    from coapis import constant
    from coapis.agents import workspace as workspace_mod
    from coapis.app import multi_agent_manager as mam_mod

    for mod in (constant, mam_mod, workspace_mod):
        monkeypatch.setattr(mod, "AGENTS_DIR", tmp_path / "agents", raising=False)
        monkeypatch.setattr(mod, "WORKSPACES_DIR", tmp_path / "workspaces", raising=False)
    return tmp_path / "agents", tmp_path / "workspaces"


def test_owner_of_reads_the_owner_out_of_the_id():
    from coapis.app.multi_agent_manager import owner_of

    assert owner_of("user:admin") == "admin"
    assert owner_of("user:zrsz_156") == "zrsz_156"
    assert owner_of("global_default") is None
    assert owner_of("default") is None
    # The retired internal id is not a user id and carries no owner.
    assert owner_of("agent:20") is None


def test_create_agent_refuses_the_global_branch_for_a_user_id(tmp_path, monkeypatch):
    """``get/create_agent("user:admin")`` with no username used to be global.

    ``is_global=True`` with no username routes Workspace to
    ``AGENTS_DIR/{agent_id}`` — a second live instance of an agent that
    already runs under ``workspaces/admin``, and the directory
    ``agents/user:admin`` behind it.  The proactive loops and
    POST /api/messages called exactly that.
    """
    import asyncio

    from coapis.app.multi_agent_manager import MultiAgentManager

    agents_dir, workspaces_dir = _patch_agent_dirs(monkeypatch, tmp_path)

    manager = MultiAgentManager(tmp_path)
    ws = asyncio.run(manager.create_agent("user:admin", username=None, is_global=True))

    assert ws.is_global is False
    assert ws.username == "admin"
    assert ws.workspace_dir == workspaces_dir / "admin"
    assert ws.data_dir == workspaces_dir / "admin" / "agents" / "admin"
    # Nothing was written under AGENTS_DIR — that is the duplicate instance.
    assert not (agents_dir / "user:admin").exists()
    assert not (agents_dir / "admin").exists()
    assert "admin:user:admin" in manager._workspaces
    assert "global:user:admin" not in manager._workspaces


def test_discovery_skips_colon_named_dirs_in_agents_dir(tmp_path, monkeypatch):
    """Leftover ``agents/user:x`` data must not be registered as a global agent.

    Registering it keys a workspace ``global:user:x`` and re-creates the
    colon-named directory on every boot, undoing the migration.
    """
    import asyncio

    from coapis.app.multi_agent_manager import MultiAgentManager

    agents_dir, workspaces_dir = _patch_agent_dirs(monkeypatch, tmp_path)

    dirty = agents_dir / "user:admin"
    dirty.mkdir(parents=True)
    (dirty / "agent.json").write_text(
        json.dumps({"id": "user:admin", "name": "Admin"}), encoding="utf-8"
    )
    clean = agents_dir / "global_default"
    clean.mkdir(parents=True)
    (clean / "agent.json").write_text(
        json.dumps({"id": "global_default", "name": "Global"}), encoding="utf-8"
    )

    manager = MultiAgentManager(tmp_path)
    asyncio.run(manager.load_default_agents())

    keys = set(manager._workspaces)
    assert "global:global_default" in keys
    assert "global:user:admin" not in keys
    assert not any(k.startswith("global:user:") for k in keys)


def test_agents_dir_scope_gate_accepts_global_and_scene_only():
    """``AGENTS_DIR`` is the global/scene namespace, nothing else."""
    from coapis.constant import is_agents_dir_scoped

    assert is_agents_dir_scoped("global_default")
    assert is_agents_dir_scoped("scene-meeting-minutes")
    # The two shapes the dual naming actually left behind:
    assert not is_agents_dir_scoped("user:admin")
    assert not is_agents_dir_scoped("user_9b8541")
    # A bare username is a workspace dir, never an AGENTS_DIR entry:
    assert not is_agents_dir_scoped("admin")
    assert not is_agents_dir_scoped("")
    assert not is_agents_dir_scoped(None)


def test_discovery_skips_user_shaped_dirs_in_agents_dir(tmp_path, monkeypatch):
    """A user agent sitting in ``agents/`` must not gain a global identity.

    ``agents/user_9b8541`` is the skeleton a call site built when it omitted
    ``username``.  Registering it keys ``global:user_9b8541`` next to the real
    ``admin:user_9b8541`` — the same agent running twice out of two
    directories, which is the dual-instance bug in its new form.
    """
    import asyncio

    from coapis.app.multi_agent_manager import MultiAgentManager

    agents_dir, workspaces_dir = _patch_agent_dirs(monkeypatch, tmp_path)

    for name in ("user_9b8541", "admin", "user:admin"):
        d = agents_dir / name
        d.mkdir(parents=True)
        (d / "agent.json").write_text(
            json.dumps({"id": name, "name": "Leftover"}), encoding="utf-8"
        )
    keep = agents_dir / "scene-oa"
    keep.mkdir(parents=True)
    (keep / "agent.json").write_text(
        json.dumps({"id": "scene-oa", "name": "OA scene"}), encoding="utf-8"
    )

    manager = MultiAgentManager(tmp_path)
    asyncio.run(manager.load_default_agents())

    keys = set(manager._workspaces)
    assert "global:scene-oa" in keys
    assert not any(k.startswith("global:user") for k in keys)
    assert "global:admin" not in keys


def test_messages_send_binds_the_agent_id_to_the_authenticated_caller():
    """``X-Agent-Id`` may not name another user's agent.

    The endpoint used to call ``get_agent(agent_id)`` with no ``username``, so
    a ``user:`` id resolved through the id's own owner and the send ran inside
    that person's workspace.  Binding the caller makes the ownership check run
    and refuses the cross-user case outright.
    """
    import asyncio

    from fastapi import HTTPException
    from starlette.datastructures import State
    from starlette.requests import Request

    from coapis.app.routers.messages import SendMessageRequest, send_message

    class FakeManager:
        def __init__(self):
            self.calls = []

        async def get_agent(self, agent_id, username=None):
            self.calls.append((agent_id, username))
            raise ValueError("probe stop after the call")

    def probe(x_agent_id, caller):
        mgr = FakeManager()
        app = type("App", (), {})()
        app.state = State()
        app.state.multi_agent_manager = mgr
        req = Request({"type": "http", "app": app, "headers": []})
        req.state.username = caller
        payload = SendMessageRequest(
            channel="console",
            target_user=caller or "x",
            target_session=f"console:{caller}",
            text="probe",
        )
        with pytest.raises(HTTPException):
            asyncio.run(send_message(payload, req, x_agent_id))
        return mgr.calls

    # Own agent: caller is passed through, so the ownership check runs.
    assert probe("user:alice", "alice") == [("user:alice", "alice")]
    # Someone else's agent: refused before the workspace is touched.
    assert probe("user:admin", "alice") == []
    # Retired "default" resolves to the caller's own agent, not a global one.
    assert probe("default", "alice") == [("user:alice", "alice")]
    # Global agents stay shared (no username), as designed.
    assert probe("global_default", "alice") == [("global_default", None)]
