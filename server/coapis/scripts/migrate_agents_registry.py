#!/usr/bin/env python3
"""Migrate existing agents from directory scanning to user config.json registry.

Scans workspaces/{username}/agent.json and workspaces/{username}/agents/*/agent.json,
writes entries into workspaces/{username}/config.json agents[] field.

Supports --data-dir, --dry-run, and --fix-defaults flags.
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def fix_default_agents(user_ws_dir: Path, dry_run: bool = False) -> int:
    """Update existing registry entries: set is_default=True for user:{username} agents."""
    cfg_path = user_ws_dir / "config.json"
    if not cfg_path.exists():
        return 0

    try:
        cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    agents = cfg_data.get("agents", [])
    updated = 0
    for entry in agents:
        if entry.get("id", "").startswith("user:") and not entry.get("is_default", False):
            entry["is_default"] = True
            updated += 1
            logger.info(f"  Marked {entry['id']} as is_default=True")

    if updated and not dry_run:
        cfg_data["agents"] = agents
        cfg_path.write_text(
            json.dumps(cfg_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return updated


def migrate_user(username: str, user_ws_dir: Path, dry_run: bool = False) -> int:
    """Migrate agents for one user. Returns count of agents registered."""
    cfg_path = user_ws_dir / "config.json"
    
    # Load existing config.json
    if cfg_path.exists():
        try:
            cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg_data = {"username": username}
    else:
        cfg_data = {"username": username}
    
    existing_agents = cfg_data.get("agents", [])
    existing_ids = {e["id"] for e in existing_agents}
    added = []
    
    # 1. Default agent: workspaces/{username}/agent.json
    default_json = user_ws_dir / "agent.json"
    if default_json.exists():
        try:
            meta = json.loads(default_json.read_text(encoding="utf-8"))
            agent_id = meta.get("id", f"user:{username}")
            if agent_id not in existing_ids:
                added.append({
                    "id": agent_id,
                    "name": meta.get("name", agent_id),
                    "description": meta.get("description", ""),
                    "workspace_dir": "",
                    "created_at": meta.get("created_at", datetime.now(timezone.utc).isoformat()),
                    "enabled": meta.get("enabled", True),
                    "is_default": True,
                })
                logger.info(f"  [{username}] default agent: {agent_id}")
            else:
                logger.info(f"  [{username}] default agent {agent_id} already in registry, skip")
        except Exception as e:
            logger.warning(f"  [{username}] failed to read default agent.json: {e}")
    
    # 2. Sub-agents: workspaces/{username}/agents/*/agent.json
    agents_dir = user_ws_dir / "agents"
    if agents_dir.exists():
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            agent_json = agent_dir / "agent.json"
            if not agent_json.exists():
                continue
            try:
                meta = json.loads(agent_json.read_text(encoding="utf-8"))
                agent_id = meta.get("id", agent_dir.name)
                if agent_id in existing_ids:
                    logger.info(f"  [{username}] sub-agent {agent_id} already in registry, skip")
                    continue
                rel_ws = str(agent_dir.relative_to(user_ws_dir))
                added.append({
                    "id": agent_id,
                    "name": meta.get("name", agent_id),
                    "description": meta.get("description", ""),
                    "workspace_dir": rel_ws,
                    "created_at": meta.get("created_at", datetime.now(timezone.utc).isoformat()),
                    "enabled": meta.get("enabled", True),
                })
                logger.info(f"  [{username}] sub-agent: {agent_id} (ws={rel_ws})")
            except Exception as e:
                logger.warning(f"  [{username}] failed to read {agent_json}: {e}")
    
    if not added:
        logger.info(f"  [{username}] no new agents to register")
        return 0
    
    if dry_run:
        logger.info(f"  [{username}] DRY RUN: would add {len(added)} agents")
        return len(added)
    
    # Write to config.json
    existing_agents.extend(added)
    cfg_data["agents"] = existing_agents
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps(cfg_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info(f"  [{username}] wrote {len(added)} agents to config.json")
    return len(added)


def main():
    parser = argparse.ArgumentParser(description="Migrate agents to registry")
    parser.add_argument("--data-dir", type=str, required=True,
                        help="Data directory (e.g. /apps/ai/coapis-dev)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing")
    parser.add_argument("--fix-defaults", action="store_true",
                        help="Mark existing user:{username} agents as is_default=True")
    args = parser.parse_args()
    
    data_dir = Path(args.data_dir)
    ws_base = data_dir / "workspaces"
    if not ws_base.exists():
        logger.error(f"Workspaces dir not found: {ws_base}")
        sys.exit(1)
    
    if args.fix_defaults:
        # Only fix is_default flag on existing registry entries
        total_fixed = 0
        for user_dir in sorted(ws_base.iterdir()):
            if not user_dir.is_dir() or user_dir.name == "global_default":
                continue
            count = fix_default_agents(user_dir, dry_run=args.dry_run)
            total_fixed += count
        mode = "DRY RUN" if args.dry_run else "DONE"
        logger.info(f"\n{mode}: fixed {total_fixed} default agents")
        return
    
    total_users = 0
    total_agents = 0
    
    for user_dir in sorted(ws_base.iterdir()):
        if not user_dir.is_dir():
            continue
        username = user_dir.name
        # Skip global_default (not a real user)
        if username == "global_default":
            continue
        total_users += 1
        count = migrate_user(username, user_dir, dry_run=args.dry_run)
        total_agents += count
    
    mode = "DRY RUN" if args.dry_run else "DONE"
    logger.info(f"\n{mode}: migrated {total_agents} agents across {total_users} users")


if __name__ == "__main__":
    main()
