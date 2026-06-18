# -*- coding: utf-8 -*-
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

"""Admin routers - global management endpoints.

全局管理相关 API，仅管理员可访问：
- /admin/system/* — 系统概览
- /admin/users/* — 用户管理
- /admin/config/* — 全局配置
- /admin/audit/* — 全局审计
- /admin/templates/* — 全局模板管理
- /admin/global-agents/* — 全局智能体管理
- /admin/tools/* — 系统工具（清理/诊断/外部智能体）
"""
from fastapi import APIRouter

from .admin_system import router as admin_system_router
from .admin_users import router as admin_users_router
from .admin_config import router as admin_config_router
from .admin_audit import router as admin_audit_router
from .admin_templates import router as admin_templates_router
from .admin_global_agents import router as admin_global_agents_router
from .admin_tools import router as admin_tools_router

router = APIRouter()

router.include_router(admin_system_router)
router.include_router(admin_users_router)
router.include_router(admin_config_router)
router.include_router(admin_audit_router)
router.include_router(admin_templates_router)
router.include_router(admin_global_agents_router)
router.include_router(admin_tools_router)
