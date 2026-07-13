#!/usr/bin/env python3
"""
Migrate legacy config.agents.profiles registry to workspace-based storage.

This script:
1. Reads existing config.agents.profiles from system/config.json
2. For each user workspace, creates config.json if missing
3. For users with workspace dir but no agent.json, creates a default one
4. Verifies each agent.json is in the correct location
5. Removes profiles from system/config.json
6. Generates a migration report

Usage:
    python migrate_profiles_to_workspaces.py [--dry-run] [--data-dir /path/to/coapis]

    --dry-run   Show what would be done without making changes
    --data-dir  Path to CoApis data directory (default: auto-detect)
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def find_data_dir() -> Path:
    """Auto-detect CoApis data directory."""
    candidates = [
        Path("/apps/ai/coapis"),
        Path.home() / ".coapis",
        Path("/opt/coapis"),
    ]
    for p in candidates:
        if (p / "system" / "config.json").exists():
            return p
    print("ERROR: Cannot find CoApis data directory. Use --data-dir to specify.")
    sys.exit(1)


def read_json(path: Path):
    """Read JSON file, return None on error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  WARNING: Cannot read {path}: {e}")
        return None


def write_json(path: Path, data: dict, dry_run: bool) -> None:
    """Write JSON file (skip in dry-run mode)."""
    if dry_run:
        print(f"  [DRY-RUN] Would write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def make_default_agent_json(agent_id: str, name: str, username: str = "") -> dict:
    """Create a minimal agent.json structure."""
    return {
        "id": agent_id,
        "name": name,
        "description": "",
        "owner": username,
        "channels": {},
        "mcp": {"clients": {}},
    }


def make_user_config_json(username: str) -> dict:
    """Create a default user config.json."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "username": username,
        "display_name": "",
        "language": "zh",
        "timezone": "Asia/Shanghai",
        "default_agent_id": f"user:{username}",
        "created_at": now,
    }


def migrate(data_dir: Path, dry_run: bool) -> dict:
    """Run the migration. Returns a report dict."""
    report = {
        "data_dir": str(data_dir),
        "dry_run": dry_run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profiles_found": 0,
        "profiles_migrated": 0,
        "agent_json_created": 0,
        "config_json_created": 0,
        "config_json_cleaned": False,
        "errors": [],
        "details": [],
    }

    config_path = data_dir / "system" / "config.json"
    workspaces_dir = data_dir / "workspaces"
    agents_dir = data_dir / "agents"

    # --- Step 1: Read existing profiles ---
    config_data = read_json(config_path)
    if config_data is None:
        report["errors"].append(f"Cannot read {config_path}")
        return report

    profiles = config_data.get("agents", {}).get("profiles", {})
    report["profiles_found"] = len(profiles)
    print(f"\n📋 Found {len(profiles)} profile(s) in config.agents.profiles")

    # --- Step 2: Check each profile ---
    for agent_id, profile in profiles.items():
        ws_dir = profile.get("workspace_dir", "")
        print(f"\n🔍 Profile: {agent_id}")
        print(f"   workspace_dir: {ws_dir}")

        if ws_dir and Path(ws_dir).exists():
            agent_json = Path(ws_dir) / "agent.json"
            if agent_json.exists():
                print(f"   ✅ agent.json exists at {agent_json}")
                report["profiles_migrated"] += 1
                report["details"].append({
                    "agent_id": agent_id,
                    "status": "already_exists",
                    "path": str(agent_json),
                })
            else:
                print(f"   ⚠️  workspace exists but no agent.json")
                report["details"].append({
                    "agent_id": agent_id,
                    "status": "workspace_exists_no_agent_json",
                    "path": ws_dir,
                })
        else:
            print(f"   ⚠️  workspace not found at {ws_dir}")
            report["details"].append({
                "agent_id": agent_id,
                "status": "workspace_not_found",
                "path": ws_dir,
            })

    # --- Step 3: Scan all user workspaces ---
    print(f"\n📂 Scanning workspaces in {workspaces_dir}")
    if not workspaces_dir.exists():
        report["errors"].append(f"Workspaces dir not found: {workspaces_dir}")
        return report

    user_dirs = sorted([d for d in workspaces_dir.iterdir() if d.is_dir()])
    print(f"   Found {len(user_dirs)} user workspace(s)")

    for user_dir in user_dirs:
        username = user_dir.name
        agent_json_path = user_dir / "agent.json"
        config_json_path = user_dir / "config.json"
        actions = []

        # Create agent.json if missing
        if not agent_json_path.exists():
            agent_id = f"user:{username}"
            name = f"Default ({username})"
            data = make_default_agent_json(agent_id, name, username)
            write_json(agent_json_path, data, dry_run)
            report["agent_json_created"] += 1
            actions.append("created agent.json")
        else:
            actions.append("agent.json exists")

        # Create config.json if missing
        if not config_json_path.exists():
            data = make_user_config_json(username)
            write_json(config_json_path, data, dry_run)
            report["config_json_created"] += 1
            actions.append("created config.json")
        else:
            actions.append("config.json exists")

        detail = {"username": username, "action": " + ".join(actions)}
        report["details"].append(detail)
        if "created" in detail["action"]:
            print(f"   📝 {username}: {detail['action']}")

    # --- Step 4: Clean profiles from config.json ---
    if profiles:
        print(f"\n🧹 Removing profiles from system/config.json")
        if not dry_run:
            if "agents" in config_data and "profiles" in config_data["agents"]:
                del config_data["agents"]["profiles"]
                config_path.write_text(
                    json.dumps(config_data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                report["config_json_cleaned"] = True
                print("   ✅ Removed config.agents.profiles from config.json")
        else:
            print("   [DRY-RUN] Would remove config.agents.profiles from config.json")
            report["config_json_cleaned"] = True

    # --- Step 5: Verify global agents ---
    print(f"\n🌐 Checking global agents in {agents_dir}")
    if agents_dir.exists():
        global_agents = sorted([d for d in agents_dir.iterdir() if d.is_dir()])
        for ga_dir in global_agents:
            agent_json = ga_dir / "agent.json"
            if agent_json.exists():
                meta = read_json(agent_json)
                aid = meta.get("id", ga_dir.name) if meta else ga_dir.name
                print(f"   ✅ {aid}: {agent_json}")
            else:
                print(f"   ⚠️  {ga_dir.name}: no agent.json")
                report["errors"].append(f"Global agent {ga_dir.name} has no agent.json")
    else:
        print(f"   ℹ️  No global agents directory")

    return report


def main():
    parser = argparse.ArgumentParser(description="Migrate profiles to workspace-based storage")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--data-dir", type=str, default="", help="Path to CoApis data directory")
    args = parser.parse_args()

    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        data_dir = find_data_dir()

    print("=" * 60)
    print(f"CoApis Profiles Migration Script")
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}Data dir: {data_dir}")
    print("=" * 60)

    report = migrate(data_dir, args.dry_run)

    # Print summary
    print("\n" + "=" * 60)
    print("📊 Migration Report")
    print("=" * 60)
    print(f"  Profiles found:            {report['profiles_found']}")
    print(f"  Profiles already migrated: {report['profiles_migrated']}")
    print(f"  agent.json created:        {report['agent_json_created']}")
    print(f"  config.json created:       {report['config_json_created']}")
    print(f"  config.json cleaned:       {report['config_json_cleaned']}")
    print(f"  Errors:                    {len(report['errors'])}")

    if report["errors"]:
        print("\n⚠️  Errors:")
        for e in report["errors"]:
            print(f"    - {e}")

    # Save report
    report_path = data_dir / "system" / "migration_report.json"
    if not args.dry_run:
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\n📄 Report saved to {report_path}")
    else:
        print(f"\n📄 [DRY-RUN] Would save report to {report_path}")

    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
