# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
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

"""DiskMonitor - 监控磁盘空间使用。

v0.5.1 新增。监控 CoApis 各目录的磁盘使用情况，
在空间不足时发出告警，支持目录大小报告。
"""

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default monitored directories
DEFAULT_MONITORED_DIRS = [
    "tmp",
    "system/evolution",
    "system/reviews",
    "system/audit",
    "workspaces",
    "agents",
]


class DiskMonitor:
    """磁盘空间监控器。

    职责:
    1. 监控各目录的磁盘使用情况
    2. 在空间不足时发出告警
    3. 提供目录大小报告

    Attributes:
        working_dir: 工作目录根路径
        threshold_gb: 磁盘空间告警阈值（GB）
    """

    def __init__(
        self,
        working_dir: Path,
        threshold_gb: float = 10.0,
        monitored_dirs: Optional[List[str]] = None,
    ):
        self.working_dir = working_dir
        self.threshold_gb = threshold_gb
        self.monitored_dirs = monitored_dirs or DEFAULT_MONITORED_DIRS

    def check_disk_space(self) -> Dict[str, Any]:
        """检查磁盘空间。"""
        total, used, free = shutil.disk_usage(self.working_dir)
        free_gb = free / (1024**3)
        return {
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free_gb, 2),
            "warning": free_gb < self.threshold_gb,
            "threshold_gb": self.threshold_gb,
        }

    def get_size_report(self) -> Dict[str, float]:
        """获取各目录大小报告（MB）。"""
        report = {}
        for subdir in self.monitored_dirs:
            path = self.working_dir / subdir
            if path.exists():
                try:
                    size = sum(
                        f.stat().st_size
                        for f in path.rglob("*")
                        if f.is_file()
                    )
                    report[subdir] = round(size / (1024 * 1024), 2)
                except Exception:
                    report[subdir] = -1
            else:
                report[subdir] = 0
        return report

    def get_full_report(self) -> Dict[str, Any]:
        """获取完整磁盘报告。"""
        disk = self.check_disk_space()
        dirs = self.get_size_report()
        return {
            "disk": disk,
            "directories": dirs,
            "summary": {
                "total_dir_size_mb": round(sum(v for v in dirs.values() if v > 0), 2),
                "warning": disk["warning"],
            },
        }

    def print_report(self) -> str:
        """打印可读的磁盘报告。"""
        report = self.get_full_report()
        lines = ["=== CoApis 磁盘报告 ===", ""]

        disk = report["disk"]
        lines.append(f"磁盘: {disk['free_gb']}GB 可用 / {disk['total_gb']}GB 总量")
        if disk["warning"]:
            lines.append(f"⚠️  警告: 剩余空间低于 {disk['threshold_gb']}GB 阈值!")
        lines.append("")

        lines.append("目录大小:")
        for name, size_mb in report["directories"].items():
            if size_mb > 0:
                lines.append(f"  {name}: {size_mb:.2f} MB")
            elif size_mb == 0:
                lines.append(f"  {name}: (空)")
            else:
                lines.append(f"  {name}: (读取失败)")

        lines.append("")
        lines.append(f"总计: {report['summary']['total_dir_size_mb']:.2f} MB")
        return "\n".join(lines)
