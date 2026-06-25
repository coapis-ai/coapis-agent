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

"""User-scoped CronManager registry.

Each user gets their own CronManager instance with isolated storage.
Storage path: workspaces/{username}/crons/jobs.json

Uses @app.middleware("http") pattern for SSE compatibility.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, Request, HTTPException
from starlette.responses import Response

from ...constant import WORKSPACES_DIR
from .manager import CronManager
from .repo.json_repo import JsonJobRepository

logger = logging.getLogger(__name__)


class CronManagerRegistry:
    """Registry that manages per-user CronManager instances.

    Lazy-creates CronManager on first access per user.
    """

    def __init__(self, runner: object, agent_id: str = "default"):
        self._runner = runner
        self._agent_id = agent_id
        self._managers: Dict[str, CronManager] = {}
        self._started: Dict[str, bool] = {}

    def get_or_create(self, username: str) -> CronManager:
        """Get existing CronManager or create new one for user."""
        if username in self._managers:
            return self._managers[username]

        # Create user-specific storage path (unified under workspaces/{username}/)
        user_cron_dir = WORKSPACES_DIR / username / "crons"
        user_cron_dir.mkdir(parents=True, exist_ok=True)
        cron_path = user_cron_dir / "jobs.json"

        # Try to get channel_manager from user's workspace
        channel_mgr = None
        try:
            from ..multi_agent_manager import get_multi_agent_manager
            mam = get_multi_agent_manager()
            if mam:
                ws = mam.get_workspace_for_user(username)
                if ws:
                    channel_mgr = getattr(ws, "channel_manager", None)
        except Exception:
            pass

        repo = JsonJobRepository(cron_path)
        mgr = CronManager(
            repo=repo,
            runner=self._runner,
            channel_manager=channel_mgr,
            agent_id=self._agent_id,
            owner_user_id=username,
        )
        self._managers[username] = mgr
        self._started[username] = False
        return mgr

    async def start_manager(self, username: str) -> None:
        """Start CronManager for a specific user (idempotent)."""
        mgr = self._managers.get(username)
        if mgr is None:
            return
        if self._started.get(username):
            return
        await mgr.start()
        self._started[username] = True

    async def start_all(self) -> None:
        """Start all registered CronManagers."""
        for username in list(self._managers.keys()):
            await self.start_manager(username)

    async def stop_all(self) -> None:
        """Stop all registered CronManagers."""
        for username in list(self._managers.keys()):
            mgr = self._managers.get(username)
            if mgr:
                await mgr.stop()
        self._started.clear()

    def list_users(self) -> list[str]:
        """List all users with CronManagers."""
        return list(self._managers.keys())


async def get_user_cron_manager(request: Request) -> CronManager:
    """Get the CronManager for the current authenticated user.

    Must be async so FastAPI calls it in the event loop context,
    avoiding "no running event loop" errors in Depends().

    Raises 401 if not authenticated, 500 if registry not initialized.
    """
    # Must be called after AuthMiddleware sets request.state.username
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(
            status_code=401,
            detail="Authentication required for cron operations",
        )

    registry: Optional[CronManagerRegistry] = getattr(
        request.app.state, "cron_registry", None
    )
    if registry is None:
        raise HTTPException(
            status_code=500,
            detail="CronManagerRegistry not initialized",
        )

    # Lazy-create on first access
    mgr = registry.get_or_create(username)

    # Start manager lazily (idempotent) - await to ensure jobs are registered
    if not registry._started.get(username):
        await registry.start_manager(username)

    return mgr


# Note: install_cron_middleware is not needed.
# Lazy-creation happens in get_user_cron_manager() which is called
# via Depends() in each cron API endpoint. This avoids the
# "Cannot add middleware after an application has started" error.
