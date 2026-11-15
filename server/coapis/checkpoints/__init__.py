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

"""检查点（B5-A 最小版）：工作区文件的内容寻址只读快照 + 可预览回滚。

**默认关闭。** 开关读环境变量 ``COAPIS_CHECKPOINTS_ENABLED``
（写法参照 ``governance.visibility.visibility_enabled``，但默认值相反——
这里是 fail-closed：没配 = 关）。开启需显式设 ``true/1/yes/on``。

关闭时端点不静默：列表 404、动作类 503，都带中文说明怎么开启。

这一版明确**不做**的三件事：
* 不建数据表、不写 alembic 迁移（清单与索引都是 JSON 文件）；
* 不做全量备份——整包备份归 ``coapis.backup`` / ``workspace_backups``，
  这里只管工作区文件的**逐文件指纹与差异**；
* 不自动创建检查点（创建由调用方触发；只有恢复前那一次是自动留底）。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_ENV_FLAG = "COAPIS_CHECKPOINTS_ENABLED"

#: 显式开启的取值（其他一律按关处理）
_ON_VALUES = frozenset({"1", "true", "yes", "on", "enable", "enabled"})


def checkpoints_enabled() -> bool:
    """检查点功能开关（**默认关**）。

    读环境变量 ``COAPIS_CHECKPOINTS_ENABLED``：只有显式写了
    ``1/true/yes/on/enable/enabled`` 才算开。取不到、写歪了、空串
    一律按"关"处理——恢复是破坏性能力，默认不开门。
    """
    raw = os.getenv(_ENV_FLAG, "")
    return raw.strip().lower() in _ON_VALUES


def checkpoints_flag() -> str:
    """给前端/运维看的开关状态（含环境变量名，便于照着设）。"""
    return (
        "COAPIS_CHECKPOINTS_ENABLED=%s -> %s"
        % (
            os.getenv(_ENV_FLAG, "(未设置)"),
            "已启用" if checkpoints_enabled() else "未启用",
        )
    )


# ── 对外导出 ──────────────────────────────────────────────────────────────
from .models import (  # noqa: E402  (开关函数先定义，导出靠后)
    KIND_MANUAL,
    KIND_PRE_RESTORE,
    Checkpoint,
    DiffResult,
    RestoreOutcome,
    RestorePlan,
)
from .paths import (
    CheckpointPathError,
    FileEntry,
    PathEscapeError,
    ScopeForbiddenError,
    is_excluded,
    is_secret_path,
    scan_entries,
    workspace_files_root,
)
from .service import (
    BlobMissingError,
    CheckpointIntegrityError,
    CheckpointNotFoundError,
    CheckpointService,
    ConfirmRequiredError,
    TooManyFilesError,
)
from .storage import CheckpointStore

__all__ = [
    # 开关
    "checkpoints_enabled",
    "checkpoints_flag",
    # 模型
    "Checkpoint",
    "DiffResult",
    "RestorePlan",
    "RestoreOutcome",
    "KIND_MANUAL",
    "KIND_PRE_RESTORE",
    # 服务
    "CheckpointService",
    "CheckpointStore",
    # 作用域
    "workspace_files_root",
    "scan_entries",
    "is_excluded",
    "is_secret_path",
    "FileEntry",
    # 异常
    "CheckpointPathError",
    "PathEscapeError",
    "ScopeForbiddenError",
    "ConfirmRequiredError",
    "CheckpointNotFoundError",
    "CheckpointIntegrityError",
    "BlobMissingError",
    "TooManyFilesError",
]
