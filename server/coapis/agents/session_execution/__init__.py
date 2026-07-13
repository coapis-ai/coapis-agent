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

"""Session Execution Manager (SEM) - 会话执行全生命周期管理。

默认关闭，通过配置开关控制是否启用。不影响现有功能。
"""

from .config import SessionExecutionConfig
from .manager import SessionExecutionManager
from .state import SessionState, InterventionLevel, ToolCallRecord

__all__ = [
    "SessionExecutionConfig",
    "SessionExecutionManager",
    "SessionState",
    "InterventionLevel",
    "ToolCallRecord",
]
