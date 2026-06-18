"""Standalone test for prefix+args whitelist matching logic.

Tests the semantic matching logic directly without importing workspace_guard,
to avoid the relative import issue outside the package context.
"""
import fnmatch
import re


# ── Copy of the matching logic from WorkspaceGuard ──

INTERPRETER_INLINE_FLAGS = frozenset({
    "-c", "-e", "-E", "-i", "-I",
    "--command", "--eval", "--execute", "--interactive",
})

FALLBACK_SHELL_WHITELIST = {
    "visitor": [],
    "user": [
        "ls *",
        "cat *", "head *", "tail *", "wc *", "grep *", "find *",
        "pwd", "date", "whoami",
        "echo *", "printf *",
        "mkdir *",
        "touch *",
        "cp *",
        "mv *",
        "tree",
        "sort *", "uniq *", "cut *", "tr *", "sed *", "awk *",
        "python3 *.py", "python *.py",
        "node *.js", "npm *", "pip3 *", "pip *",
        "git *",
        "curl -s *", "curl --head *", "wget *",
    ],
    "advanced": [
        "ls *",
        "cat *", "head *", "tail *", "wc *", "grep *", "find *",
        "pwd", "date", "whoami", "id",
        "echo *", "printf *",
        "mkdir *",
        "touch *",
        "rm *", "rm -r", "rm -f",
        "cp *",
        "mv *",
        "tree",
        "sort *", "uniq *", "cut *", "tr *", "sed *", "awk *",
        "python3 *.py", "python *.py",
        "node *.js", "npm *", "pip3 *", "pip *",
        "git *",
        "curl *", "wget *",
        "chmod *", "chown *",
        "docker", "docker *",
        "systemctl *", "service *",
        "apt *", "apt-get *", "yum *", "dnf *",
        "kill *", "pkill *",
        "tar *", "zip *", "unzip *",
        "crontab *",
    ],
    "admin": [
        "ls *",
        "cat *", "head *", "tail *", "wc *", "grep *", "find *",
        "pwd", "date", "whoami", "id",
        "echo *", "printf *",
        "mkdir *",
        "touch *",
        "rm *", "rm -r", "rm -f",
        "cp *",
        "mv *",
        "tree",
        "sort *", "uniq *", "cut *", "tr *", "sed *", "awk *",
        "python3 *.py", "python *.py",
        "node *.js", "npm *", "pip3 *", "pip *",
        "git *",
        "curl *", "wget *",
        "chmod *", "chown *",
        "docker", "docker *",
        "systemctl *", "service *",
        "apt *", "apt-get *", "yum *", "dnf *",
        "kill *", "pkill *",
        "tar *", "zip *", "unzip *",
        "crontab *",
    ],
}

FALLBACK_BLACKLIST = [
    "rm -rf /", "rm -rf /*", "rm -rf ~",
    "mkfs.*", "dd if=", "shutdown", "reboot", "halt",
    "poweroff", "fdisk", "parted", "iptables", "nft",
]

DANGEROUS_PATTERNS = [
    r"rm\s+-[a-zA-Z]*f[a-zA-Z]*\s+(/|\~|/home|/root|/etc|/usr|/bin|/sbin)",
    r">\s*(/dev/|/etc/|/usr/|/bin/|/sbin/)",
    r"(python3?|node|ruby|perl|php)\s+(-c|--eval|-e)\s",
    r"python3?\s+-m\s+(subprocess|os|pty|shutil)",
    r"socket\.socket\s*\(",
    r"subprocess\.(call|run|Popen)\s*\(",
    r"os\.system\s*\(",
    r"os\.popen\s*\(",
]


def _is_file_pattern_entry(allowed_tail):
    if len(allowed_tail) == 1:
        pat = allowed_tail[0]
        if pat.startswith("*") and "." in pat:
            return True
    return False


def _args_are_files_only(args):
    if not args:
        return True
    for arg in args:
        if arg in ("|", ">", ">>", "<", "&&", "||"):
            return False
        if arg.startswith("-"):
            if arg.startswith("--"):
                flag_name = arg.split("=", 1)[0]
                if flag_name in INTERPRETER_INLINE_FLAGS:
                    return False
            else:
                flag_chars = arg[1:].split("=", 1)[0]
                for ch in flag_chars:
                    if ch in ("c", "e", "E", "i", "I"):
                        return False
    return True


def is_command_allowed(command, role):
    cmd = command.strip()
    if not cmd:
        return False

    # Blacklist
    for bp in FALLBACK_BLACKLIST:
        if fnmatch.fnmatch(cmd, bp):
            return False

    # Dangerous patterns
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, cmd):
            return False

    tokens = cmd.split()
    base_cmd = tokens[0]
    args = tokens[1:] if len(tokens) > 1 else []

    allowed_commands = FALLBACK_SHELL_WHITELIST.get(role, [])

    for allowed in allowed_commands:
        allowed_tokens = allowed.split()
        allowed_base = allowed_tokens[0]

        if not fnmatch.fnmatch(base_cmd, allowed_base):
            continue

        allowed_tail = allowed_tokens[1:]

        if not allowed_tail:
            if not args:
                return True
            continue

        if allowed_tail == ["*"]:
            return True

        if _is_file_pattern_entry(allowed_tail):
            if args and _args_are_files_only(args):
                return True
            continue

        if fnmatch.fnmatch(cmd, allowed):
            return True

    return False


# ── Test cases ──

tests = [
    # python3 file args → ALLOW
    ("python3 script.py", "user", True),
    ("python3 /tmp/test.py", "user", True),
    ("python3 setup.py install", "user", True),
    ("python3 /path/to/app.py --port 8080", "user", True),
    # python3 inline flags → BLOCK
    ("python3 -c \"import os\"", "user", False),
    ("python3 -e \"print(1)\"", "user", False),
    ("python3 --eval \"print(1)\"", "advanced", False),
    ("python3 -i script.py", "user", False),
    ("python3 -ce \"code\"", "advanced", False),
    ("python3 -E -c \"code\"", "advanced", False),
    # node
    ("node script.js", "user", True),
    ("node -e \"console.log(1)\"", "user", False),
    ("node --eval \"console.log(1)\"", "user", False),
    # base-only commands
    ("ls", "user", True),
    ("ls -la", "user", True),
    ("cat file.txt", "user", True),
    ("pwd", "user", True),
    # wildcard commands (advanced)
    ("docker ps", "advanced", True),
    ("docker rm -f container", "advanced", True),
    ("docker exec -it ctr bash", "advanced", True),
    ("curl -s https://example.com", "user", True),
    ("wget https://example.com/file", "user", True),
    # git
    ("git status", "user", True),
    ("git push origin main", "advanced", True),
    # visitor has no permissions
    ("ls", "visitor", False),
    ("cat file.txt", "visitor", False),
    # blacklisted commands
    ("rm -rf /", "user", False),
    ("shutdown", "user", False),
    # no args for base-only → should fail (python3 alone)
    ("python3", "user", False),
    # python3 with pipe → BLOCK
    ("python3 script.py | tee out.log", "user", False),
    # python3 advanced with file args → ALLOW
    ("python3 test.py --verbose", "advanced", True),
    # docker not in user role → BLOCK
    ("docker ps", "user", False),
    # user cannot rm
    ("rm -f file.txt", "user", False),
]

passed = 0
failed = 0
for cmd, role, expected in tests:
    result = is_command_allowed(cmd, role)
    ok = result == expected
    passed += ok
    failed += (not ok)
    mark = "✅" if ok else "❌"
    print(f"{mark} {role:10s} | {'ALLOW' if result else 'BLOCK ':5s} | {cmd}")
    if not ok:
        print(f"   ^^^ expected {'ALLOW' if expected else 'BLOCK'}")

print(f"\n{'='*60}")
print(f"Results: {passed}/{len(tests)} passed, {failed} failed")

import sys
sys.exit(1 if failed else 0)
