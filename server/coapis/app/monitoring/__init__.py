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

"""
P2-1 监控面板 - 系统指标采集与 API

功能：
- CPU/内存/磁盘/网络实时指标
- 进程信息
- API 调用统计
- 健康状态汇总

开源版：基础监控（psutil）
企业版：扩展监控（Prometheus 集成、历史数据存储、告警规则）
"""

from .collector import SystemMetricsCollector
from .router import router as monitoring_router

__all__ = ["SystemMetricsCollector", "monitoring_router"]
