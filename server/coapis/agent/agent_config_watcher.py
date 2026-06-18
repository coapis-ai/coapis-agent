# -*- coding: utf-8 -*-
"""AgentConfigWatcher — 监听 agent.json 变化自动触发 workspace 热重载。

借鉴 CoApis AgentConfigWatcher 模式：
- 轮询 agent.json 的 mtime + channels/heartbeat hash 变化
- 只在有意义的字段变更时触发 reload（忽略 last_dispatch 等运行时写入）
- 通过 MultiAgentManager.reload_agent() 原子式重载 workspace
- 多用户场景下每个 agent 独立 watcher

用法:
    watcher = AgentConfigWatcher(
        agent_id="my_agent",
        workspace_dir=Path("/path/to/workspace"),
        workspace=workspace_instance,
    )
    await watcher.start()
    # ... agent runs ...
    await watcher.stop()
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .workspace import Workspace

logger = logging.getLogger(__name__)

# 轮询间隔（秒）
DEFAULT_POLL_INTERVAL = 3.0


def _hash_section(data: Any) -> str:
    """对配置段做 stable hash，用于变更检测。"""
    if data is None:
        return ""
    try:
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        raw = str(data)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


class AgentConfigWatcher:
    """轮询 agent.json 并触发优雅 workspace 重载。

    只在 channels 或 heartbeat 配置段发生真实变更时触发，
    运行时书写的字段（如 last_dispatch）不会导致误触发。
    """

    def __init__(
        self,
        agent_id: str,
        workspace_dir: Path,
        workspace: "Workspace",
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ):
        self._agent_id = agent_id
        self._workspace_dir = workspace_dir
        self._config_path = workspace_dir / "agent.json"
        self._workspace = workspace
        self._poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None

        self._last_mtime: float = 0.0
        self._last_channels_hash: str = ""
        self._last_heartbeat_hash: str = ""
        self._last_cron_hash: str = ""
        self._disabled: bool = False

    async def start(self) -> None:
        """记录初始快照并启动轮询任务。"""
        self._snapshot()
        self._task = asyncio.create_task(
            self._poll_loop(),
            name=f"agent_config_watcher_{self._agent_id}",
        )
        logger.info(
            "AgentConfigWatcher started: agent=%s poll=%ss path=%s",
            self._agent_id,
            self._poll_interval,
            self._config_path,
        )

    async def stop(self) -> None:
        """停止轮询任务。"""
        if self._disabled:
            return
        self._disabled = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("AgentConfigWatcher stopped: agent=%s", self._agent_id)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _read_mtime(self) -> float:
        """读取 agent.json 的 mtime，文件不存在返回 0。"""
        try:
            return self._config_path.stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def _snapshot(self) -> None:
        """记录当前 mtime 和关键配置段 hash 作为基线。"""
        self._last_mtime = self._read_mtime()
        try:
            with open(self._config_path) as f:
                config = json.load(f)
        except Exception:
            return
        self._last_channels_hash = _hash_section(config.get("channels"))
        self._last_heartbeat_hash = _hash_section(config.get("heartbeat"))
        self._last_cron_hash = _hash_section(config.get("cron"))

    def _resolve_manager(self):
        """从 workspace 获取 MultiAgentManager。"""
        return getattr(self._workspace, "_manager", None)

    async def _poll_loop(self) -> None:
        """主轮询循环。"""
        while not self._disabled:
            try:
                await asyncio.sleep(self._poll_interval)
                if self._disabled:
                    break
                await self._check()
            except Exception:
                logger.exception(
                    "AgentConfigWatcher (%s): poll iteration failed",
                    self._agent_id,
                )

    async def _check(self) -> None:
        """检查配置是否有意义变更，有则触发重载。"""
        mtime = self._read_mtime()
        if mtime == self._last_mtime:
            return
        self._last_mtime = mtime

        try:
            with open(self._config_path) as f:
                config = json.load(f)
        except Exception:
            logger.exception(
                "AgentConfigWatcher (%s): failed to parse agent.json",
                self._agent_id,
            )
            return

        new_channels_hash = _hash_section(config.get("channels"))
        new_heartbeat_hash = _hash_section(config.get("heartbeat"))
        new_cron_hash = _hash_section(config.get("cron"))

        changed = (
            new_channels_hash != self._last_channels_hash
            or new_heartbeat_hash != self._last_heartbeat_hash
            or new_cron_hash != self._last_cron_hash
        )

        # 刷新基线（即使无意义变更也要更新，避免反复读取）
        old_ch = self._last_channels_hash
        old_hb = self._last_heartbeat_hash
        self._last_channels_hash = new_channels_hash
        self._last_heartbeat_hash = new_heartbeat_hash
        self._last_cron_hash = new_cron_hash

        if not changed:
            return

        manager = self._resolve_manager()
        if manager is None:
            logger.warning(
                "AgentConfigWatcher (%s): config changed but "
                "MultiAgentManager not attached; skipping reload",
                self._agent_id,
            )
            return

        # 禁用自身（reload 后会创建新的 watcher）
        self._disabled = True

        logger.info(
            "AgentConfigWatcher (%s): config changed, triggering reload "
            "(channels: %s→%s, heartbeat: %s→%s)",
            self._agent_id,
            old_ch, new_channels_hash,
            old_hb, new_heartbeat_hash,
        )
        try:
            await manager.reload_agent(self._agent_id)
        except Exception:
            logger.exception(
                "AgentConfigWatcher (%s): reload_agent failed",
                self._agent_id,
            )
