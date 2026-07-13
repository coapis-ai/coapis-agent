#!/usr/bin/env python3
"""Migrate agent.json to slim format.

Removes global-inherited fields, fixes workspace_dir to ".", and sets owner.

Usage:
    python3 migrate_agent_json_slim.py [--data-dir DIR] [--dry-run]

Default data-dir: /apps/ai/coapis
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Fields to remove (global-inherited)
REMOVE_FIELDS = {
    "mcp", "acp", "security", "running", "llm_routing",
    "heartbeat", "plan", "approval_level", "language",
    "system_prompt_files",
}


def derive_owner(agent_id: str, agent_json_path: Path) -> str:
    """Infer owner from agent_id or filesystem path."""
    # user:admin → admin
    if agent_id.startswith("user:"):
        return agent_id.split(":", 1)[1]
    # workspaces/{username}/agents/{id} → username
    parts = str(agent_json_path).split("/")
    if "workspaces" in parts:
        idx = parts.index("workspaces")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    # global agents → empty
    return ""


def migrate_file(path: Path, dry_run: bool = False) -> dict:
    """Migrate a single agent.json. Returns summary dict."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    original = json.dumps(data, ensure_ascii=False)
    agent_id = data.get("id", path.parent.name)
    changes = []

    # 1. Remove global-inherited fields
    for field in REMOVE_FIELDS:
        if field in data:
            del data[field]
            changes.append(f"-{field}")

    # 2. Fix workspace_dir to "."
    old_wd = data.get("workspace_dir", "")
    if old_wd != ".":
        data["workspace_dir"] = "."
        changes.append(f"workspace_dir: {old_wd!r} → '.'")

    # 3. Fix owner
    old_owner = data.get("owner", "")
    correct_owner = derive_owner(agent_id, path)
    if old_owner != correct_owner:
        data["owner"] = correct_owner
        changes.append(f"owner: {old_owner!r} → {correct_owner!r}")

    # 4. Remove 'tools' field if present (managed by global config)
    if "tools" in data:
        del data["tools"]
        changes.append("-tools")

    # 5. Remove empty description placeholder
    if data.get("description") == f"{agent_id} agent":
        data["description"] = ""
        changes.append("description: removed placeholder")

    # Write back
    new_json = json.dumps(data, ensure_ascii=False)
    modified = original != new_json

    if modified and not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return {
        "path": str(path),
        "agent_id": agent_id,
        "modified": modified,
        "changes": changes,
        "fields_before": len(json.loads(original)),
        "fields_after": len(data),
    }


def main():
    parser = argparse.ArgumentParser(description="Migrate agent.json to slim format")
    parser.add_argument("--data-dir", default="/apps/ai/coapis", help="Data directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"ERROR: {data_dir} does not exist")
        sys.exit(1)

    # Find all agent.json files
    agent_jsons = []

    # 1. User sub-agents: workspaces/{username}/agents/{id}/agent.json
    for f in sorted(data_dir.glob("workspaces/*/agents/*/agent.json")):
        agent_jsons.append(f)

    # 2. User default agents: workspaces/{username}/agent.json
    for f in sorted(data_dir.glob("workspaces/*/agent.json")):
        agent_jsons.append(f)

    # 3. Global agents: agents/{id}/agent.json
    for f in sorted(data_dir.glob("agents/*/agent.json")):
        agent_jsons.append(f)

    if not agent_jsons:
        print(f"No agent.json found under {data_dir}")
        sys.exit(0)

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"\n{'='*60}")
    print(f"  Agent.json Slim Migration ({mode})")
    print(f"  Data dir: {data_dir}")
    print(f"  Found: {len(agent_jsons)} agent.json files")
    print(f"{'='*60}\n")

    modified_count = 0
    for path in agent_jsons:
        result = migrate_file(path, dry_run=args.dry_run)
        status = "✏️  MODIFIED" if result["modified"] else "✅ unchanged"
        print(f"  {status}  {result['agent_id']}")
        print(f"    path: {result['path']}")
        print(f"    fields: {result['fields_before']} → {result['fields_after']}")
        if result["changes"]:
            for ch in result["changes"]:
                print(f"    • {ch}")
        print()
        if result["modified"]:
            modified_count += 1

    print(f"\n{'='*60}")
    print(f"  Summary: {modified_count}/{len(agent_jsons)} files modified")
    if args.dry_run:
        print(f"  (DRY-RUN — no files were actually changed)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
