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
