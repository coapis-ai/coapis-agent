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
