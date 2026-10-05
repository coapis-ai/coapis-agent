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

"""User-scoped CronManager registry.

Each user gets their own CronManager instance with isolated storage.
Storage path: workspaces/{username}/crons/jobs.json

Uses @app.middleware("http") pattern for SSE compatibility.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Request, HTTPException
from starlette.responses import Response

from ...constant import WORKSPACES_DIR
from .manager import CronManager
from .repo.json_repo import JsonJobRepository

logger = logging.getLogger(__name__)


# Module-level singleton for CronManagerRegistry
_registry_instance: Optional["CronManagerRegistry"] = None


def set_registry(registry: "CronManagerRegistry") -> None:
    """Set the global CronManagerRegistry singleton."""
    global _registry_instance
    _registry_instance = registry


def get_registry() -> Optional["CronManagerRegistry"]:
    """Get the global CronManagerRegistry singleton."""
    return _registry_instance


class CronManagerRegistry:
    """Registry that manages per-user CronManager instances.

    Lazy-creates CronManager on first access per user.
    Workspace CronManagers can register themselves via register_manager(),
    which takes priority over lazy-created instances.
    """

    def __init__(self, runner: object, agent_id: str = "default"):
        self._runner = runner
        self._agent_id = agent_id
        self._managers: Dict[str, CronManager] = {}
        self._started: Dict[str, bool] = {}
        # Superseded managers awaiting graceful stop (drained best-effort).
        self._retired: List[CronManager] = []

    def register_manager(self, username: str, manager: CronManager) -> None:
        """Register a workspace CronManager for a user.

        This overwrites any lazy-created CronManager, ensuring the API
        always uses the workspace's CronManager (which has the real runner,
        channel_manager, memory_manager, heartbeat, and dream).

        A superseded manager is gracefully stopped (best-effort) so two
        schedulers never run over the same jobs.json simultaneously.
        """
        old = self._managers.get(username)
        if old is not None and old is not manager:
            self._retire(old)
        self._managers[username] = manager
        self._started[username] = True
        logger.info(f"Registered workspace CronManager for {username}")

    def _retire(self, old: CronManager) -> None:
        """Schedule a graceful stop for a superseded manager.

        Async-safe: if an event loop is running the stop is scheduled as a
        task; otherwise the manager stays in ``_retired`` and is drained by
        ``start_all()`` / ``stop_all()``.
        """
        self._retired.append(old)
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._stop_retired(old))
            task.add_done_callback(self._discard_retired_task)
        except RuntimeError:
            # No running loop — will be drained later.
            logger.debug("Retired CronManager queued (no running loop)")

    @staticmethod
    def _discard_retired_task(task: "asyncio.Task") -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.warning(
                f"Retired CronManager stop error: {task.exception()}"
            )

    async def _stop_retired(self, old: CronManager) -> None:
        try:
            await old.stop()
            logger.info("Stopped superseded CronManager")
        except Exception as e:
            logger.warning(f"Superseded CronManager stop failed: {e}")
        finally:
            if old in self._retired:
                self._retired.remove(old)

    def get(self, username: str) -> Optional[CronManager]:
        """Return the registered manager for a user, or None."""
        return self._managers.get(username)

    def get_or_create(self, username: str) -> CronManager:
        """Get existing CronManager or create new one for user."""
        if username in self._managers:
            return self._managers[username]

        # Create user-specific storage path (unified under workspaces/{username}/)
        user_cron_dir = WORKSPACES_DIR / username / "crons"
        user_cron_dir.mkdir(parents=True, exist_ok=True)
        cron_path = user_cron_dir / "jobs.json"

        repo = JsonJobRepository(cron_path)
        mgr = CronManager(
            repo=repo,
            runner=self._runner,
            channel_manager=None,
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
        """Stop all registered CronManagers (incl. retired backlog)."""
        # Drain any superseded managers that were never stopped (e.g.
        # retired while no event loop was running).
        for old in list(self._retired):
            try:
                await old.stop()
            except Exception as e:
                logger.warning(f"Retired CronManager stop failed: {e}")
        self._retired.clear()
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

    Uses the CronManagerRegistry (module-level singleton).
    Workspace CronManagers register themselves into the registry on startup.
    If the workspace hasn't been loaded yet, triggers loading so the
    workspace's CronManager (with real runner/channel_manager/memory_manager)
    gets registered.

    Raises 401 if not authenticated.
    """
    username = getattr(request.state, "username", None)
    if not username:
        raise HTTPException(
            status_code=401,
            detail="Authentication required for cron operations",
        )

    registry = get_registry()
    if registry is None:
        registry = getattr(request.app.state, "cron_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=500,
            detail="No CronManager available: registry not initialized",
        )

    # If registry has no started manager for this user, try loading the
    # workspace first — this triggers workspace.start() which registers
    # the workspace's CronManager into the registry.
    if username not in registry._managers or not registry._started.get(username):
        try:
            mam = getattr(request.app.state, "multi_agent_manager", None)
            if mam:
                # User workspaces are keyed "user:{username}" — passing
                # "default" looks up a non-existent global agent and the
                # ownership check rejects it, so the workspace's
                # CronManager never got registered (silent cron failure).
                ws = await mam.get_agent(f"user:{username}", username=username)
                if ws and not ws._started:
                    await ws.start()
        except Exception as e:
            logger.warning(f"Could not trigger workspace load for {username}: {e}")

    mgr = registry.get_or_create(username)
    if not registry._started.get(username):
        await registry.start_manager(username)
    return mgr
