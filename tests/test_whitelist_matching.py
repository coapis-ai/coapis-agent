"""Test the improved prefix+args whitelist matching in WorkspaceGuard."""
import fnmatch
import re
import sys
from pathlib import Path

# Minimal stubs so we can import workspace_guard without full app context
sys.modules.setdefault("coapis.config.context", type(sys)("ctx"))
sys.modules["coapis.config.context"].get_current_username = lambda: "test"
sys.modules["coapis.config.context"].get_current_user_role = lambda: "user"
sys.modules["coapis.config.context"].get_current_workspace_dir = lambda: "/tmp"

sys.modules.setdefault("coapis.agents.security.audit_logger", type(sys)("al"))
sys.modules["coapis.agents.security.audit_logger"].AuditLogger = type("AL", (), {"log": staticmethod(lambda e: None)})
sys.modules["coapis.agents.security.audit_logger"].create_audit_event = lambda **kw: None

sys.modules.setdefault("coapis.app.permissions", type(sys)("pm"))
sys.modules["coapis.app.permissions.manager"] = type(sys)("pmm")
sys.modules["coapis.app.permissions.manager"].PermissionManager = type("PM", (), {"get_instance": staticmethod(lambda: None)})

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

from coapis.agents.security.workspace_guard import WorkspaceGuard

g = WorkspaceGuard()

tests = [
    # ── python3 file args → ALLOW ──
    ("python3 script.py", "user", True),
    ("python3 /tmp/test.py", "user", True),
    ("python3 setup.py install", "user", True),
    ("python3 /path/to/app.py --port 8080", "user", True),
    # ── python3 inline flags → BLOCK ──
    ("python3 -c \"import os\"", "user", False),
    ("python3 -e \"print(1)\"", "user", False),
    ("python3 --eval \"print(1)\"", "advanced", False),
    ("python3 -i script.py", "user", False),
    ("python3 -ce \"code\"", "advanced", False),
    ("python3 -E -c \"code\"", "advanced", False),
    # ── node ──
    ("node script.js", "user", True),
    ("node -e \"console.log(1)\"", "user", False),
    ("node --eval \"console.log(1)\"", "user", False),
    # ── base-only commands ──
    ("ls", "user", True),
    ("ls -la", "user", True),
    ("cat file.txt", "user", True),
    ("pwd", "user", True),
    # ── wildcard commands (advanced) ──
    ("docker ps", "advanced", True),
    ("docker rm -f container", "advanced", True),
    ("docker exec -it ctr bash", "advanced", True),
    ("curl -s https://example.com", "user", True),
    ("wget https://example.com/file", "user", True),
    # ── git ──
    ("git status", "user", True),
    ("git push origin main", "advanced", True),
    # ── visitor has no permissions ──
    ("ls", "visitor", False),
    ("cat file.txt", "visitor", False),
    # ── blacklisted commands ──
    ("rm -rf /", "user", False),
    ("shutdown", "user", False),
    # ── no args for base-only → should fail ──
    ("python3", "user", False),
]

passed = 0
failed = 0
for cmd, role, expected in tests:
    result = g._is_command_allowed_fallback(cmd, role)
    ok = result == expected
    passed += ok
    failed += (not ok)
    mark = "✅" if ok else "❌"
    print(f"{mark} {role:10s} | {'ALLOW' if result else 'BLOCK ':5s} | {cmd}")
    if not ok:
        print(f"   ^^^ expected {'ALLOW' if expected else 'BLOCK'}")

print(f"\n{'='*60}")
print(f"Results: {passed}/{len(tests)} passed, {failed} failed")
sys.exit(1 if failed else 0)
