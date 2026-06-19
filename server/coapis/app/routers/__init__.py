# -*- coding: utf-8 -*-
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

"""API routers with edition-based feature gating.

Community edition: Core features only
Enterprise edition: Core + enterprise features (requires valid license)

Usage:
    Set COAPIS_EDITION=enterprise and COAPIS_LICENSE_KEY to enable enterprise features.
"""

import logging

from fastapi import APIRouter

from ...features import flags

logger = logging.getLogger(__name__)

from .agents import router as agents_router
from .agent import router as agent_router
# Disabled: config.py (CoApis original) depends on get_agent_for_request which fails in CoApis single-agent mode.
# from .config import router as config_router_internal
from .local_models import router as local_models_router
from .providers import router as providers_router
from .skills import router as skills_router
from .skills_stream import router as skills_stream_router
from .workspace import router as workspace_router
from .envs import router as envs_router
from .mcp import router as mcp_router
from .tools import router as tools_router
from ..crons.api import router as cron_router
# runner_router removed: depends on workspace.chat_manager which doesn't exist in CoApis Workspace.
# Our app/routers/chats.py provides the same /chats endpoints with in-memory storage.
# from ..runner.api import router as runner_router
from .console import router as console_router
from .token_usage import router as token_usage_router
from .agent_stats import router as agent_stats_router
from .auth import router as auth_router
from .messages import router as messages_router
from .files import router as files_router
from .settings import router as settings_router
from .plugins import router as plugins_router
from .backup import router as backup_router
from .plan import router as plan_router
from .config_router import router as config_router_ext
from .health import router as health_router
from .chats import router as chats_router
from .websocket import router as websocket_router
from .root import router as root_router
from .commands import router as commands_router
from .agent_stats import router as agent_stats_router
from .local_models import router as local_models_router
from .voice import voice_router
from .approval import router as approval_router
from .user import router as user_router
from .admin import router as admin_router
from ...user_system.routers import users_router, points_router, tokens_router
from .evolution import router as evolution_router
from .growth import router as growth_router
from .foundation import router as foundation_router
from .cross_agent import cross_agent_router
from .multi_layer_evolution import router as multi_layer_evolution_router
from .security import router as security_router
from .permissions import router as permissions_router
from .admin_providers import router as admin_providers_router
from .user_model_prefs import router as user_model_prefs_router
from ..inbox import router as inbox_router
from ..setup import router as setup_router
from ..onboarding import router as onboarding_router
from ..search import router as search_router
from ..i18n import router as i18n_router
from ..config_hot_reload import router as config_reload_router
from ..theme import router as theme_router
from ..monitoring import monitoring_router
from ..sso import sso_router
from .audit import router as audit_router
from ..license_api import router as license_router
from ..cleanup_api import router as cleanup_router
from ..access_control_api import router as access_control_router
from .init import router as init_router

router = APIRouter()

# Core routers
router.include_router(agents_router)
router.include_router(agent_router)  # Agent identity file management
# router.include_router(config_router_internal)  # Disabled: see above
router.include_router(console_router)
router.include_router(cron_router)
router.include_router(local_models_router)
router.include_router(mcp_router)
router.include_router(messages_router)
router.include_router(providers_router)
# runner_router disabled: workspace.chat_manager missing; chats_router covers /chats
# router.include_router(runner_router)
router.include_router(skills_router)
router.include_router(skills_stream_router)
router.include_router(tools_router)
router.include_router(workspace_router)
router.include_router(envs_router)
router.include_router(token_usage_router)
router.include_router(agent_stats_router)
router.include_router(auth_router)
# files_router is included directly in _app.py — skip here to avoid double registration
# router.include_router(files_router)
# router.include_router(files_router)
router.include_router(settings_router)
router.include_router(plugins_router)
router.include_router(backup_router)
router.include_router(plan_router)

# Additional routers (CoApis extensions)
router.include_router(config_router_ext)
router.include_router(health_router)
router.include_router(chats_router)
router.include_router(websocket_router)
router.include_router(root_router)
router.include_router(commands_router)
router.include_router(voice_router)
router.include_router(approval_router)
router.include_router(user_router)
router.include_router(admin_router)
router.include_router(users_router)
router.include_router(points_router)
router.include_router(tokens_router)
router.include_router(evolution_router)
router.include_router(growth_router)
router.include_router(foundation_router)
router.include_router(cross_agent_router)
router.include_router(multi_layer_evolution_router)
router.include_router(security_router)
router.include_router(permissions_router)
router.include_router(inbox_router)
router.include_router(setup_router)
router.include_router(onboarding_router)
router.include_router(search_router)
router.include_router(i18n_router)
router.include_router(config_reload_router)
router.include_router(theme_router)
router.include_router(admin_providers_router)
router.include_router(user_model_prefs_router)
router.include_router(monitoring_router)
router.include_router(audit_router)
router.include_router(sso_router)
router.include_router(init_router)

# ═══════════════════════════════════════════════════════════
# Cleanup, access control, license, files
# ═══════════════════════════════════════════════════════════
router.include_router(cleanup_router)
router.include_router(access_control_router)
router.include_router(license_router)
router.include_router(files_router)

# ═══════════════════════════════════════════════════════════
# Enterprise stubs (always loaded for upgrade prompts)
# ═══════════════════════════════════════════════════════════

# Load enterprise stubs - provides upgrade prompts when enterprise not installed
# Actual enterprise routes are loaded by _load_enterprise_routes() in _app.py
from ..enterprise_stubs import router as enterprise_stubs_router

router.include_router(enterprise_stubs_router)
logger.info("  ✅ Enterprise stub routes loaded (upgrade prompts)")

# Enterprise plugin routes are loaded dynamically in _app.py if enterprise package is installed


def create_agent_scoped_router() -> APIRouter:
    """Create agent-scoped router that wraps existing routers.

    Returns:
        APIRouter with all routers mounted under /agents/{agentId}/
    """
    from .agent_scoped import create_agent_scoped_router as _create

    return _create()


# ═══════════════════════════════════════════════════════════
# Tool & Skill usage statistics
# ═══════════════════════════════════════════════════════════
from fastapi import Query as _Query
from fastapi.responses import JSONResponse as _JSONResponse

@router.get("/usage/stats")
async def get_usage_stats(days: int = _Query(default=7, ge=1, le=90)):
    """Return aggregated tool/skill usage statistics."""
    from ...agents.utils.usage_tracker import get_summary
    return _JSONResponse(get_summary(days))

@router.get("/usage/recent")
async def get_usage_recent(limit: int = _Query(default=100, ge=1, le=1000)):
    """Return recent tool/skill usage entries."""
    from ...agents.utils.usage_tracker import read_recent
    return _JSONResponse(read_recent(limit))

@router.get("/usage/cache")
async def get_cache_stats():
    """Return tool result cache statistics."""
    from ...agents.utils.tool_result_cache import get_cache
    return _JSONResponse(get_cache().stats())

@router.post("/usage/cache/invalidate")
async def invalidate_cache(tool: str = _Query(default="")):
    """Invalidate cached tool results. Empty tool clears all."""
    from ...agents.utils.tool_result_cache import get_cache
    count = get_cache().invalidate(tool or None)
    return _JSONResponse({"invalidated": count})


__all__ = ["router", "create_agent_scoped_router"]
