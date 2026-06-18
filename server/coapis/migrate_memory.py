# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""migrate_memory.py - v0.5.1 数据迁移脚本。

将旧版目录结构迁移到新版：
1. workspaces/{user}/evolution/ → system/evolution/ (数据保留，目录不再重复)
2. workspaces/{user}/evolution/trajectories/ → tmp/evolution/trajectories/ (临时数据)
3. workspaces/{user}/evolution/experiences/ → tmp/evolution/experiences/ (临时数据)
4. workspaces/{user}/evolution/reviews/ → system/reviews/ (归档)
5. 用户级 workflows/ 目录清理
6. 确保 MEMORY.md 存在

使用方法：
    python -m coapis.migrate_memory [--dry-run] [--backup-dir /path/to/backup]

安全措施：
- 自动备份旧数据
- --dry-run 模式预览变更
- 验证迁移结果
"""

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryMigration:
    """v0.5.1 数据迁移管理器。

    迁移规则：
    - evolution/trajectories/* → tmp/evolution/trajectories/
    - evolution/experiences/* → tmp/evolution/experiences/
    - evolution/reviews/* → system/reviews/
    - workflows/ → 删除 (已废弃)
    - 确保 MEMORY.md 存在
    """

    def __init__(
        self,
        working_dir: Path,
        backup_dir: Optional[Path] = None,
        dry_run: bool = False,
    ):
        self.working_dir = working_dir
        self.backup_dir = backup_dir or working_dir / ".migration_backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dry_run = dry_run
        self._stats = {
            "users_migrated": 0,
            "files_moved": 0,
            "files_backed_up": 0,
            "dirs_created": 0,
            "dirs_removed": 0,
            "errors": 0,
        }

    def run(self) -> Dict[str, Any]:
        """执行迁移。"""
        logger.info(f"Starting v0.5.1 migration (dry_run={self.dry_run})")

        if not self.dry_run:
            self.backup_dir.mkdir(parents=True, exist_ok=True)

        workspaces_dir = self.working_dir / "workspaces"
        if not workspaces_dir.exists():
            logger.warning(f"Workspaces directory not found: {workspaces_dir}")
            return self._stats

        for user_dir in workspaces_dir.iterdir():
            if not user_dir.is_dir() or user_dir.name.startswith("."):
                continue
            try:
                self._migrate_user(user_dir)
                self._stats["users_migrated"] += 1
            except Exception as e:
                logger.error(f"Failed to migrate {user_dir.name}: {e}")
                self._stats["errors"] += 1

        logger.info(f"Migration complete: {self._stats}")
        return self._stats

    def _migrate_user(self, user_dir: Path) -> None:
        """迁移单个用户的数据。"""
        username = user_dir.name
        logger.info(f"Migrating user: {username}")

        # 1. Migrate evolution/trajectories/ → tmp/evolution/trajectories/
        src_traj = user_dir / "evolution" / "trajectories"
        dst_traj = self.working_dir / "tmp" / "evolution" / "trajectories"
        self._migrate_directory(src_traj, dst_traj, f"{username}/trajectories")

        # 2. Migrate evolution/experiences/ → tmp/evolution/experiences/
        src_exp = user_dir / "evolution" / "experiences"
        dst_exp = self.working_dir / "tmp" / "evolution" / "experiences"
        self._migrate_directory(src_exp, dst_exp, f"{username}/experiences")

        # 3. Migrate evolution/reviews/ → system/reviews/
        src_reviews = user_dir / "evolution" / "reviews"
        dst_reviews = self.working_dir / "system" / "reviews"
        self._migrate_directory(src_reviews, dst_reviews, f"{username}/reviews")

        # 4. Remove evolution/ directory (now empty or only has leftover files)
        evo_dir = user_dir / "evolution"
        if evo_dir.exists():
            if not self.dry_run:
                shutil.rmtree(evo_dir, ignore_errors=True)
                self._stats["dirs_removed"] += 1
            logger.info(f"  Removed evolution/ directory")

        # 5. Remove workflows/ directory (deprecated)
        workflows_dir = user_dir / "workflows"
        if workflows_dir.exists():
            if not self.dry_run:
                shutil.rmtree(workflows_dir, ignore_errors=True)
                self._stats["dirs_removed"] += 1
            logger.info(f"  Removed workflows/ directory")

        # 6. Ensure memory/ directory exists
        memory_dir = user_dir / "memory"
        if not memory_dir.exists():
            if not self.dry_run:
                memory_dir.mkdir(parents=True, exist_ok=True)
                self._stats["dirs_created"] += 1
            logger.info(f"  Created memory/ directory")

        # 7. Ensure MEMORY.md exists
        memory_md = user_dir / "MEMORY.md"
        if not memory_md.exists():
            if not self.dry_run:
                memory_md.write_text(
                    f"# {username} 的记忆\n\n> 由 v0.5.1 迁移脚本自动创建。\n",
                    encoding="utf-8",
                )
                self._stats["dirs_created"] += 1
            logger.info(f"  Created MEMORY.md")

    def _migrate_directory(self, src: Path, dst: Path, label: str) -> None:
        """迁移目录内容。"""
        if not src.exists():
            return

        if not self.dry_run:
            # Backup first
            backup_path = self.backup_dir / label
            if src.exists():
                shutil.copytree(src, backup_path, dirs_exist_ok=True)
                self._stats["files_backed_up"] += 1

            # Move files
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                target = dst / item.name
                if item.is_file():
                    shutil.move(str(item), str(target))
                    self._stats["files_moved"] += 1
                elif item.is_dir():
                    if not target.exists():
                        shutil.move(str(item), str(target))
                    else:
                        # Merge contents
                        for sub_item in item.rglob("*"):
                            if sub_item.is_file():
                                rel = sub_item.relative_to(item)
                                sub_target = target / rel
                                sub_target.parent.mkdir(parents=True, exist_ok=True)
                                shutil.move(str(sub_item), str(sub_target))
                                self._stats["files_moved"] += 1

        logger.info(f"  Migrated {label}: {src} → {dst}")

    def verify(self) -> bool:
        """验证迁移结果。"""
        workspaces_dir = self.workspaces_dir
        if not workspaces_dir.exists():
            return True

        all_ok = True
        for user_dir in workspaces_dir.iterdir():
            if not user_dir.is_dir() or user_dir.name.startswith("."):
                continue

            # Check evolution/ is removed
            evo_dir = user_dir / "evolution"
            if evo_dir.exists():
                logger.error(f"{user_dir.name}: evolution/ still exists!")
                all_ok = False

            # Check MEMORY.md exists
            memory_md = user_dir / "MEMORY.md"
            if not memory_md.exists():
                logger.error(f"{user_dir.name}: MEMORY.md missing!")
                all_ok = False

            # Check memory/ exists
            memory_dir = user_dir / "memory"
            if not memory_dir.exists():
                logger.error(f"{user_dir.name}: memory/ missing!")
                all_ok = False

        return all_ok

    def get_stats(self) -> Dict[str, Any]:
        return self._stats.copy()


def main():
    parser = argparse.ArgumentParser(description="CoApis v0.5.1 数据迁移")
    parser.add_argument(
        "--working-dir",
        type=str,
        default="/apps/ai/coapis",
        help="CoApis working directory",
    )
    parser.add_argument(
        "--backup-dir",
        type=str,
        default=None,
        help="Backup directory for old data",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without executing",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify migration results after migration",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    migration = MemoryMigration(
        working_dir=Path(args.working_dir),
        backup_dir=Path(args.backup_dir) if args.backup_dir else None,
        dry_run=args.dry_run,
    )

    if args.verify:
        if migration.verify():
            print("✅ Migration verification passed!")
        else:
            print("❌ Migration verification failed! Check logs above.")
            sys.exit(1)
    else:
        stats = migration.run()
        print(f"\nMigration results:")
        for k, v in stats.items():
            print(f"  {k}: {v}")

        if not args.dry_run:
            print(f"\nBackups saved to: {migration.backup_dir}")


if __name__ == "__main__":
    main()
