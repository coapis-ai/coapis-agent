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

"""Workspace routers - user-level resource management.

Each user manages their own agents, models, skills, etc.
All endpoints require authentication.
"""
from fastapi import APIRouter

from .workspace_agents import router as workspace_agents_router
from .workspace_models import router as workspace_models_router
from .workspace_skills import router as workspace_skills_router
from .workspace_security import router as workspace_security_router
from .workspace_backups import router as workspace_backups_router
from .workspace_audit import router as workspace_audit_router

# Import workspace config routes (running-config, language, audio-mode, etc.)
# This was previously in workspace.py which was shadowed by the workspace/ package
from ..workspace_config import router as workspace_config_router

router = APIRouter()

router.include_router(workspace_agents_router)
router.include_router(workspace_models_router)
router.include_router(workspace_skills_router)
router.include_router(workspace_security_router)
router.include_router(workspace_backups_router)
router.include_router(workspace_audit_router)
router.include_router(workspace_config_router)
