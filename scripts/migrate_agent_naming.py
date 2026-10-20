#!/usr/bin/env python3
# Pyright config for the standalone script:
# pythonVersion: 3.11
# pythonPlatform: Linux
"""Normalise the agent naming dual-track.

The runtime used to carry TWO identities for one agent:

    id        = "user:{username}"   semantic, used by the registry and
                                    derive_workspace_dir()
    agent_id  = "agent:{user.id}"   ASCII-safe, written into agent.json and
                                    used as the MultiAgentManager cache key

Consequences this script removes:
  * ``get_agent("user:xxx")`` missed the workspace registered under
    ``"agent:20"`` and built a SECOND Workspace over the same directory.
  * ``derive_workspace_dir("agent:20")`` fell through to
    ``AGENTS_DIR/agent:20`` — a directory that never exists — so a user's
    real agent silently ran on a synthetic profile.
  * Display names leaked into directory names (``workspaces/zrsz_153(王小伟)``).

What it does, in order:
  1. Back up every file it is about to touch under ``backups/agent_naming_<ts>/``.
  2. File layer — for every ``agent.json``:
       - drop the retired ``agent_id`` key
       - rewrite ``id`` to the canonical form for that directory
       - sync the owner's registry entry (``config.json`` agents) to the same id
  3. DB layer — for every table with an ``agent_id`` column, rewrite
     ``agent:{n}`` to ``user:{username}`` using the users table.

Idempotent: a second run reports "nothing to do".

Usage:
    python scripts/migrate_agent_naming.py --working-dir /app/workdir --dry-run
    python scripts/migrate_agent_naming.py --working-dir /app/workdir --apply
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

USER_PREFIX = "user:"
LEGACY_PREFIX = "agent:"

#: The only namespaces allowed to occupy ``agents/`` — mirrors
#: coapis.constant.AGENTS_DIR_ID_PREFIXES.  Anything else sitting there is
#: leftover data from the dual naming.
AGENTS_DIR_PREFIXES = ("global_", "scene-")

# Characters that must never appear in a username / agent key.  Mirrors
# coapis.constant._FORBIDDEN_KEY_CHARS; duplicated here on purpose so this
# script runs standalone inside a container without importing the package.
FORBIDDEN = set(
    '/\\:()[]{}|<>\'"`'
    " \t\n\r\v\f"
    "?*;&=%#~!@$^,"
)


def key_is_safe(key: str) -> bool:
    if not key or len(key) > 64:
        return False
    if key.startswith(".") or ".." in key:
        return False
    return all(c not in FORBIDDEN and ord(c) >= 0x20 for c in key)


class Report:
    def __init__(self) -> None:
        self.changed: list[str] = []
        self.skipped: list[str] = []
        self.errors: list[str] = []
        self.legacy_key_dirs: list[str] = []


def load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def atomic_write(path: Path, data: dict[str, Any], report_dir: Path,
                 rel: str, apply: bool) -> None:
    """Write *data* to *path*, snapshotting the previous bytes first."""
    if not apply:
        return
    snapshot = report_dir / rel
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if not snapshot.exists():
        shutil.copy2(path, snapshot)
    tmp = path.with_suffix(path.suffix + ".migrating")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)


def migrate_agent_json(
    agent_json: Path,
    expected_id: str,
    report: Report,
    report_dir: Path,
    rel: str,
    apply: bool,
) -> None:
    """Drop the legacy key and force ``id`` to *expected_id*."""
    try:
        data = load_json(agent_json)
    except (json.JSONDecodeError, OSError) as exc:
        report.errors.append(f"{rel}: unreadable agent.json ({exc})")
        return

    fixes: list[str] = []
    legacy = data.get("agent_id")
    if legacy is not None:
        data.pop("agent_id")
        fixes.append(f"dropped agent_id={legacy!r}")
        report.legacy_key_dirs.append(rel)

    current = data.get("id")
    if current != expected_id:
        data["id"] = expected_id
        fixes.append(f"id {current!r} -> {expected_id!r}")

    if not fixes:
        report.skipped.append(rel)
        return

    report.changed.append(f"{rel}: " + "; ".join(fixes))
    atomic_write(agent_json, data, report_dir, rel, apply)


def sync_registry(user_dir: Path, canonical_id: str, report: Report,
                  report_dir: Path, apply: bool) -> None:
    """Point the owner's registry default entry at *canonical_id*."""
    cfg = user_dir / "config.json"
    if not cfg.exists():
        return
    try:
        data = load_json(cfg)
    except (json.JSONDecodeError, OSError) as exc:
        report.errors.append(f"{cfg}: unreadable ({exc})")
        return
    # user config.json keeps the registry as a bare list under "agents";
    # tolerate the {"agents": {"entries": [...]}} shape as well.
    raw = data.get("agents")
    if isinstance(raw, dict):
        agents = raw.get("entries")
    else:
        agents = raw
    if not isinstance(agents, list):
        return

    touched = False
    for entry in agents:
        if not isinstance(entry, dict):
            continue
        if entry.get("is_default") and entry.get("id") != canonical_id:
            report.changed.append(
                f"{user_dir.name}/config.json: registry default "
                f"{entry.get('id')!r} -> {canonical_id!r}"
            )
            entry["id"] = canonical_id
            touched = True

    # The top-level pointer must agree with the registry entry.
    if data.get("default_agent_id") not in (None, canonical_id):
        report.changed.append(
            f"{user_dir.name}/config.json: default_agent_id "
            f"{data.get('default_agent_id')!r} -> {canonical_id!r}"
        )
        data["default_agent_id"] = canonical_id
        touched = True

    if touched:
        atomic_write(cfg, data, report_dir, f"{user_dir.name}/config.json", apply)


def migrate_files(working_dir: Path, report: Report, report_dir: Path,
                  apply: bool) -> None:
    """Normalise every agent.json under workspaces/ and agents/."""
    workspaces = working_dir / "workspaces"
    agents_dir = working_dir / "agents"

    # 1. User default agents: workspaces/{username}/agent.json
    if workspaces.is_dir():
        for user_dir in sorted(p for p in workspaces.iterdir()
                               if p.is_dir() and not p.name.startswith(".")):
            username = user_dir.name
            if not key_is_safe(username):
                report.errors.append(
                    f"workspaces/{username}: username is not a safe key "
                    "(rename the user before migrating)"
                )
                continue
            agent_json = user_dir / "agent.json"
            if agent_json.exists():
                # A workspace whose agent.json has no owner is a GLOBAL
                # agent's workspace (e.g. workspaces/global_default), not a
                # user's — its canonical id is the directory name.
                try:
                    owner = load_json(agent_json).get("owner")
                except (json.JSONDecodeError, OSError):
                    owner = username
                if owner in (None, "", 0):
                    expected = username
                    registry_id = None
                else:
                    expected = f"{USER_PREFIX}{username}"
                    registry_id = expected
                migrate_agent_json(
                    agent_json, expected, report,
                    report_dir, f"{username}/agent.json", apply,
                )
                if registry_id:
                    sync_registry(user_dir, registry_id, report,
                                  report_dir, apply)

            # 2. User sub-agents: workspaces/{username}/agents/{key}/agent.json
            sub_root = user_dir / "agents"
            if sub_root.is_dir():
                for sub in sorted(p for p in sub_root.iterdir() if p.is_dir()):
                    if ":" in sub.name:
                        # rename_colon_dirs() owns these; flagging them here
                        # would double-count one finding as an error.
                        continue
                    if not key_is_safe(sub.name):
                        report.errors.append(
                            f"workspaces/{username}/agents/{sub.name}: "
                            "agent key is not a safe directory name"
                        )
                        continue
                    aj = sub / "agent.json"
                    if aj.exists():
                        migrate_agent_json(
                            aj, sub.name, report, report_dir,
                            f"{username}/agents/{sub.name}/agent.json", apply,
                        )

    # 3. Global agents: agents/{agent_id}/agent.json
    if agents_dir.is_dir():
        for agent_dir in sorted(p for p in agents_dir.iterdir() if p.is_dir()):
            if ":" in agent_dir.name:
                # Handled by rename_colon_dirs().
                continue
            if not key_is_safe(agent_dir.name):
                report.errors.append(
                    f"agents/{agent_dir.name}: agent key is not a safe "
                    "directory name"
                )
                continue
            aj = agent_dir / "agent.json"
            if aj.exists():
                migrate_agent_json(
                    aj, agent_dir.name, report, report_dir,
                    f"agents/{agent_dir.name}/agent.json", apply,
                )


def merge_into(src: Path, dst: Path, report: Report, apply: bool,
               depth: int = 0) -> tuple[int, int]:
    """Move *src*'s entries into *dst*, never overwriting.

    Returns ``(moved, conflicts)``.  Byte-identical files are dropped from
    *src* (duplicate template copies, not user data); real directories
    recurse.  Symlinks are atomic entries and are NEVER traversed:
    ``workspaces/global_default/.../files`` is a symlink into another tree,
    and following it would move files that do not belong to this agent.
    Anything genuinely different is reported as a conflict and left for a
    human.
    """
    moved = conflicts = 0
    for entry in sorted(src.iterdir()):
        dest = dst / entry.name
        is_link = entry.is_symlink()

        if not dest.exists() and not dest.is_symlink():
            if apply:
                entry.rename(dest)
            moved += 1
            continue

        if is_link:
            # Compare resolved targets: relative and absolute spellings of
            # the same directory are the same data.
            if dest.is_symlink() and entry.resolve() == dest.resolve():
                if apply:
                    entry.unlink()
                moved += 1
                continue
            conflicts += 1
            report.errors.append(
                f"{entry}: symlink target differs from {dest} - merge by hand"
            )
            continue

        if entry.is_dir() and dest.is_dir() and depth < 6:
            m, c = merge_into(entry, dest, report, apply, depth + 1)
            moved += m
            conflicts += c
            if apply and c == 0 and entry.is_dir() and not any(entry.iterdir()):
                entry.rmdir()
        elif entry.is_file() and dest.is_file():
            if entry.read_bytes() == dest.read_bytes():
                if apply:
                    entry.unlink()
                moved += 1
            else:
                conflicts += 1
                report.errors.append(
                    f"{entry}: differs from {dest} - merge by hand"
                )
        else:
            conflicts += 1
            report.errors.append(f"{entry}: cannot merge into {dest}")
    return moved, conflicts


def rename_colon_dirs(working_dir: Path, report: Report, apply: bool) -> None:
    """Rename ``user:{name}`` data/skills dirs to ``{name}``.

    Runtime data and skills used to be keyed by the raw semantic id, producing
    ``workspaces/admin/agents/user:admin`` and ``workspaces/admin/skills/user:admin``
    — directory names carrying the id namespace separator.  The runtime now
    writes ``agents/admin`` / ``skills/admin``; this moves the existing data
    onto those names so nothing is orphaned.
    """
    roots = [working_dir / "workspaces", working_dir / "agents"]
    for root in roots:
        if not root.is_dir():
            continue
        targets: list[Path] = []
        if root.name == "workspaces":
            for user_dir in sorted(p for p in root.iterdir()
                                   if p.is_dir() and not p.name.startswith(".")):
                # Runtime data lives under agents/, skills under skills/.
                # Both used to be keyed by the raw semantic id, so both carry
                # colon-named directories.
                for sub_name in ("agents", "skills"):
                    sub = user_dir / sub_name
                    if sub.is_dir():
                        targets.extend(p for p in sub.iterdir() if p.is_dir())
        else:
            targets.extend(p for p in root.iterdir() if p.is_dir())

        for path in targets:
            if ":" not in path.name:
                continue
            try:
                entries = list(path.iterdir())
            except OSError as exc:
                report.errors.append(f"{path}: not listable ({exc})")
                continue
            if not entries:
                # Empty leftover from an older keying scheme (e.g.
                # "scene-x:admin"); nothing to preserve.
                report.changed.append(f"remove empty colon dir {path}")
                if apply:
                    if path.is_symlink():
                        path.unlink()
                    else:
                        path.rmdir()
                continue
            if not path.name.startswith(USER_PREFIX):
                report.errors.append(
                    f"{path}: colon in directory name but not a 'user:' id — "
                    "rename by hand"
                )
                continue
            new_name = path.name[len(USER_PREFIX):]
            if not key_is_safe(new_name):
                report.errors.append(
                    f"{path}: target name {new_name!r} is not a safe key"
                )
                continue
            new_path = path.with_name(new_name)
            if new_path.exists():
                # Both names exist for the same agent (the colon dir written
                # before the fix plus the clean dir after).  Merge without
                # overwriting.
                moved, conflicts = merge_into(path, new_path, report, apply)
                report.changed.append(
                    f"merge {path} -> {new_path} ({moved} entries moved, "
                    f"{conflicts} conflicting)"
                )
                if apply and conflicts == 0 and not any(path.iterdir()):
                    path.rmdir()
                continue
            report.changed.append(f"{path} -> {new_path}")
            if apply:
                path.rename(new_path)


def migrate_db(working_dir: Path, report: Report, apply: bool) -> None:
    """Rewrite ``agent:{n}`` agent_id values to ``user:{username}``."""
    try:
        from sqlalchemy import create_engine, inspect, text
    except ImportError:
        report.errors.append("sqlalchemy unavailable; skipped DB migration")
        return

    engines: list[tuple[str, Any]] = []

    # Preferred: reuse the project's own URL builder so enterprise (PG) and
    # community (sqlite) deployments are handled by the same rules the app
    # uses, including COAPIS_DATABASE_URL precedence.
    try:
        server_dir = Path(__file__).resolve().parents[1] / "server"
        if str(server_dir) not in sys.path:
            sys.path.insert(0, str(server_dir))
        from coapis.foundation.db.engine import build_database_url

        url = build_database_url()
        engines.append((url, create_engine(url)))
    except Exception as exc:  # noqa: BLE001 - standalone fallback below
        report.skipped.append(f"db: package engine unavailable ({exc})")

    if not engines:
        env_url = os.environ.get("COAPIS_DATABASE_URL")
        if env_url:
            try:
                engines.append((env_url, create_engine(env_url)))
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"cannot open {env_url}: {exc}")

    if not engines:
        for db in (working_dir / "coapis.db", working_dir / "auth.db"):
            if db.exists() and db.stat().st_size > 0:
                try:
                    engines.append((str(db), create_engine(f"sqlite:///{db}")))
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"cannot open {db}: {exc}")

    if not engines:
        report.skipped.append("db: no database found")
        return

    for label, engine in engines:
        try:
            insp = inspect(engine)
            tables = insp.get_table_names()
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"{label}: inspect failed ({exc})")
            continue

        # Build the agent:{n} -> user:{username} map from the users table.
        mapping: dict[str, str] = {}
        if "users" in tables:
            with engine.connect() as conn:
                try:
                    rows = conn.execute(
                        text("SELECT id, username FROM users")
                    ).fetchall()
                    for uid, uname in rows:
                        mapping[f"{LEGACY_PREFIX}{uid}"] = f"{USER_PREFIX}{uname}"
                except Exception:  # noqa: BLE001
                    pass

        for table in tables:
            try:
                cols = [c["name"] for c in insp.get_columns(table)]
            except Exception:  # noqa: BLE001
                continue
            if "agent_id" not in cols:
                continue
            with engine.connect() as conn:
                try:
                    found = conn.execute(
                        text(
                            f'SELECT agent_id, COUNT(*) FROM "{table}" '
                            f"WHERE agent_id LIKE '{LEGACY_PREFIX}%' "
                            "GROUP BY agent_id"
                        )
                    ).fetchall()
                except Exception:  # noqa: BLE001
                    continue
                for legacy, count in found:
                    target = mapping.get(legacy)
                    if target is None:
                        report.errors.append(
                            f"{label}:{table}: {count} rows carry agent_id="
                            f"{legacy!r} with no user to map it to"
                        )
                        continue
                    report.changed.append(
                        f"{label}:{table}: {count} rows {legacy!r} -> {target!r}"
                    )
                    if apply:
                        conn.execute(
                            text(
                                f'UPDATE "{table}" SET agent_id = :t '
                                "WHERE agent_id = :l"
                            ),
                            {"t": target, "l": legacy},
                        )
                if apply:
                    conn.commit()
        engine.dispose()


def sweep_agents_dir(working_dir: Path, report_dir: Path, report: Report,
                     apply: bool) -> None:
    """Move out-of-convention directories out of ``agents/``.

    ``agents/`` is the global/scene namespace.  A directory there that is
    neither ``global_*`` nor ``scene-*`` is dual-naming leftover: the colon
    form (``user:admin``), a bare username (``admin``), or the template
    skeleton a call site built when it omitted ``username`` (``user_9b8541``).
    Discovery refuses to register them, so they are dead weight that re-appears
    in every listing of "global agents".  Moved to the report dir, never
    deleted.
    """
    agents_dir = working_dir / "agents"
    if not agents_dir.is_dir():
        return
    for agent_dir in sorted(p for p in agents_dir.iterdir() if p.is_dir()):
        name = agent_dir.name
        if name.startswith(".") or name.startswith(AGENTS_DIR_PREFIXES):
            continue
        target = report_dir / f"agents_{name}"
        report.changed.append(
            f"agents/{name}: not a global ('global_*') or scene ('scene-*') "
            f"agent -> moved to {target}"
        )
        if apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(agent_dir), str(target))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--working-dir",
        default=None,
        help="CoApis working dir (the one containing workspaces/ and agents/)",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Write changes. Without it the run is a dry run.")
    args = parser.parse_args()

    working_dir = args.working_dir
    if not working_dir:
        import os
        working_dir = os.environ.get("COAPIS_WORKING_DIR")
    if not working_dir:
        print("ERROR: --working-dir (or COAPIS_WORKING_DIR) is required",
              file=sys.stderr)
        return 2

    wd = Path(working_dir).expanduser().resolve()
    if not wd.is_dir():
        print(f"ERROR: working dir {wd} does not exist", file=sys.stderr)
        return 2

    apply = bool(args.apply)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    report_dir = wd / "backups" / f"agent_naming_{stamp}"
    report = Report()

    print(f"working dir : {wd}")
    print(f"mode        : {'APPLY' if apply else 'DRY RUN'}")
    print(f"backup dir  : {report_dir}")
    print("-" * 68)

    migrate_files(wd, report, report_dir, apply)
    rename_colon_dirs(wd, report, apply)
    sweep_agents_dir(wd, report_dir, report, apply)
    migrate_db(wd, report, apply)

    print(f"changed : {len(report.changed)}")
    for line in report.changed:
        print(f"  - {line}")
    print(f"clean   : {len(report.skipped)}")
    print(f"errors  : {len(report.errors)}")
    for line in report.errors:
        print(f"  ! {line}")

    if not apply and report.changed:
        print("-" * 68)
        print("Dry run only. Re-run with --apply to write these changes.")
    if report.errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
