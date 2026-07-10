# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""CleanupManager - 自动清理过程数据。

v0.5.1 新增。管理 system/ 和 tmp/ 下的过程数据生命周期，
按配置规则自动删除或归档过期文件。

清理规则配置示例 (system/cleanup_config.json):
{
    "enabled": true,
    "schedule": "0 3 * * *",
    "rules": [
        {"path": "tmp/evolution/trajectories", "retention_days": 1, "action": "delete"},
        {"path": "tmp/evolution/experiences", "retention_days": 7, "action": "delete"},
        {"path": "system/reviews", "retention_days": 30, "action": "archive"},
        {"path": "system/audit", "retention_days": 90, "action": "archive"},
        {"path": "tmp/cache", "retention_days": 1, "action": "delete"}
    ]
}
"""

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default cleanup configuration
DEFAULT_CLEANUP_CONFIG = {
    "enabled": True,
    "rules": [
        {"path": "tmp/evolution/trajectories", "retention_days": 1, "action": "delete"},
        {"path": "tmp/evolution/experiences", "retention_days": 7, "action": "delete"},
        {"path": "tmp/cache", "retention_days": 1, "action": "delete"},
        {"path": "tmp/sessions", "retention_days": 1, "action": "delete"},
        {"path": "files/.temp", "retention_days": 1, "action": "delete"},
        {"path": "system/reviews", "retention_days": 30, "action": "archive"},
        {"path": "system/audit", "retention_days": 90, "action": "archive"},
    ],
}


class CleanupManager:
    """系统过程数据清理管理器。

    职责:
    1. 根据配置规则清理过期文件
    2. 归档重要数据（删除前备份）
    3. 监控清理结果并记录日志

    Attributes:
        working_dir: 工作目录根路径
        config: 清理配置
    """

    def __init__(self, working_dir: Path, config_path: Optional[Path] = None):
        self.working_dir = working_dir
        self.config = self._load_config(config_path)
        self._stats = {
            "files_deleted": 0,
            "files_archived": 0,
            "bytes_freed": 0,
            "errors": 0,
        }

    def _load_config(self, config_path: Optional[Path]) -> Dict[str, Any]:
        """加载清理配置，不存在则使用默认配置。"""
        if config_path and config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load cleanup config: {e}, using defaults")
        return DEFAULT_CLEANUP_CONFIG.copy()

    def run_cleanup(self) -> Dict[str, Any]:
        """执行清理任务。

        Returns:
            清理统计结果
        """
        if not self.config.get("enabled", True):
            logger.info("Cleanup is disabled")
            return self._stats

        logger.info("Starting cleanup...")
        self._stats = {
            "files_deleted": 0,
            "files_archived": 0,
            "bytes_freed": 0,
            "errors": 0,
        }

        for rule in self.config.get("rules", []):
            try:
                target = self.working_dir / rule["path"]
                if not target.exists():
                    continue

                action = rule.get("action", "delete")
                retention_days = rule.get("retention_days", 30)

                if action == "delete":
                    self._delete_old_files(target, retention_days)
                elif action == "archive":
                    archive_path = self.working_dir / rule.get(
                        "archive_path", f"{rule['path']}/archive"
                    )
                    self._archive_old_files(target, retention_days, archive_path)

            except Exception as e:
                logger.error(f"Error cleaning {rule.get('path')}: {e}")
                self._stats["errors"] += 1

        logger.info(
            f"Cleanup complete: {self._stats['files_deleted']} deleted, "
            f"{self._stats['files_archived']} archived, "
            f"{self._stats['bytes_freed'] / 1024 / 1024:.2f} MB freed, "
            f"{self._stats['errors']} errors"
        )
        return self._stats

    def _delete_old_files(self, path: Path, retention_days: int) -> None:
        """删除超过指定天数的文件。"""
        cutoff = datetime.now() - timedelta(days=retention_days)
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    mtime = datetime.fromtimestamp(item.stat().st_mtime)
                    if mtime < cutoff:
                        size = item.stat().st_size
                        item.unlink()
                        self._stats["files_deleted"] += 1
                        self._stats["bytes_freed"] += size
                except Exception as e:
                    logger.warning(f"Failed to delete {item}: {e}")
                    self._stats["errors"] += 1

    def _archive_old_files(
        self, path: Path, retention_days: int, archive_path: Path
    ) -> None:
        """归档超过指定天数的文件。"""
        cutoff = datetime.now() - timedelta(days=retention_days)
        archive_path.mkdir(parents=True, exist_ok=True)

        for item in path.rglob("*"):
            if item.is_file():
                try:
                    mtime = datetime.fromtimestamp(item.stat().st_mtime)
                    if mtime < cutoff:
                        date_str = mtime.strftime("%Y-%m-%d")
                        target = archive_path / date_str / item.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(item), str(target))
                        self._stats["files_archived"] += 1
                except Exception as e:
                    logger.warning(f"Failed to archive {item}: {e}")
                    self._stats["errors"] += 1

    def get_size_report(self) -> Dict[str, float]:
        """获取各目录大小报告（MB）。"""
        report = {}
        for subdir in ["tmp", "system/reviews", "system/audit", "system/evolution"]:
            path = self.working_dir / subdir
            if path.exists():
                size = sum(
                    f.stat().st_size for f in path.rglob("*") if f.is_file()
                )
                report[subdir] = size / (1024 * 1024)
        return report

    def cleanup_all(self) -> Dict[str, Any]:
        """执行全量清理（所有临时目录）。"""
        self._stats = {
            "files_deleted": 0,
            "files_archived": 0,
            "bytes_freed": 0,
            "errors": 0,
        }

        # Clean tmp directory completely
        tmp_dir = self.working_dir / "tmp"
        if tmp_dir.exists():
            for item in tmp_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                elif item.is_file():
                    size = item.stat().st_size
                    item.unlink()
                    self._stats["bytes_freed"] += size

        return self._stats
