# -*- coding: utf-8 -*-
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
