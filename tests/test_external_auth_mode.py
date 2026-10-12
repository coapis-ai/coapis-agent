"""Tests for the system-level ``auth_mode`` two-state in outbound identity.

``required`` has been removed: identity injection is always *degrading* —
inject when an identity is available, pass through (no identity) when not.
Whether the request is ultimately allowed is decided by the external business
system, not CoApis.

    auth_mode    valid identity   missing identity / no token
    optional     inject           pass through ({})           [default]
    none         no inject        pass through ({})

``required`` (legacy value) is treated as ``optional`` (degrades the same way).

``_load_systems`` / ``get_identity_username`` / ``find_binding`` are patched so
the test is hermetic (no config files, no network).
"""
import asyncio
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from coapis.app import external_identity as ei
from coapis.app.external_identity import outbound_headers, resolve_auth_mode

HEAD_IDENTITY = "X-CoApis-Identity"

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"✅ {name}")
    else:
        failed += 1
        print(f"❌ {name}  {detail}")


def make_system(auth_mode=None, **extra):
    s = {
        "provider_id": "oa",
        "name": "OA",
        "base_urls": ["https://oa.corp.com"],
        "status": 1,
        "shared_secret": "testsecret",
        "credential": {},
    }
    if auth_mode is not None:
        s["auth_mode"] = auth_mode
    s.update(extra)
    return s


BINDING = {"external_id": "ext123", "user_id": "alice", "provider": "oa", "status": 1}


def run_outbound(system, has_binding=True, username="alice", url="https://oa.corp.com/api/x"):
    async def _run():
        with mock.patch.object(ei, "_load_systems", return_value=[system] if system else []), \
             mock.patch.object(ei, "get_identity_username", return_value=username), \
             mock.patch.object(ei, "find_binding", return_value=BINDING if has_binding else None):
            return await outbound_headers(url, source="mcp")
    return asyncio.run(_run())


# ── resolve_auth_mode unit cases ──
check("resolve: missing → optional", resolve_auth_mode(make_system(None)) == "optional")
check("resolve: legacy required → optional", resolve_auth_mode(make_system("required")) == "optional")
check("resolve: optional", resolve_auth_mode(make_system("optional")) == "optional")
check("resolve: none", resolve_auth_mode(make_system("none")) == "none")
check("resolve: invalid → optional", resolve_auth_mode(make_system("bogus")) == "optional")
check("resolve: None system → optional", resolve_auth_mode(None) == "optional")
check("resolve: case-insensitive", resolve_auth_mode(make_system("OPTIONAL")) == "optional")

# ── outbound_headers two-state (signature mode) ──
h = run_outbound(make_system("none"), has_binding=True)
check("none → {} (no inject, even with identity)", h == {}, f"got {h}")

h = run_outbound(make_system("optional"), has_binding=True)
check("optional + bound → inject", h.get(HEAD_IDENTITY) == "alice", f"got {h}")

h = run_outbound(make_system("optional"), has_binding=False)
check("optional + unbound → pass ({})", h == {}, f"got {h}")

h = run_outbound(make_system("optional"), has_binding=True, username=None)
check("optional + no user → pass ({})", h == {}, f"got {h}")

# default (no auth_mode field) → optional → degrades
h = run_outbound(make_system(None), has_binding=False)
check("default(no field) + unbound → pass ({})", h == {}, f"got {h}")

# legacy required → treated as optional → degrades when no identity
h = run_outbound(make_system("required"), has_binding=False)
check("legacy required + unbound → pass ({}) (degrade)", h == {}, f"got {h}")
h = run_outbound(make_system("required"), has_binding=True)
check("legacy required + bound → inject", h.get(HEAD_IDENTITY) == "alice", f"got {h}")

# non-matching URL → {} regardless of auth_mode
h = run_outbound(make_system("optional"), url="https://unrelated.example.com/x")
check("non-matching URL → {} (pass)", h == {}, f"got {h}")

# optional wraps the pass_through path too (fault tolerance)
pt = make_system("optional", credential={"external_token": {"mode": "pass_through"}})
h = run_outbound(pt, has_binding=True, username=None)
check("optional + pass_through + no user → pass ({})", h == {}, f"got {h}")

print(f"\n{'='*60}")
print(f"Results: {passed}/{passed + failed} passed, {failed} failed")
sys.exit(1 if failed else 0)
