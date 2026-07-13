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

"""Workspace Monitor - 自动监测并恢复工作空间状态.

定期检查所有工作空间的状态，发现未启动但有启用渠道的智能体会自动启动。
这确保了外部渠道（企业微信、Discord等）始终可以接收消息。
"""
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .multi_agent_manager import MultiAgentManager

logger = logging.getLogger(__name__)


class WorkspaceMonitor:
    """定期检查工作空间状态，发现异常自动恢复.

    监测逻辑：
    1. 每 check_interval 秒检查一次所有工作空间
    2. 发现未启动(status != "running")但有启用渠道的工作空间
    3. 自动启动该工作空间，确保渠道可以接收消息

    使用场景：
    - 工作空间异常退出后自动恢复
    - 外部渠道意外中断后重新启动
    - 确保创建用户后渠道立即可用
    """

    def __init__(self, manager: "MultiAgentManager", check_interval: int = 300):
        """初始化监测器.

        Args:
            manager: MultiAgentManager 实例
            check_interval: 检查间隔（秒），默认 300 秒（5 分钟）
        """
        self.manager = manager
        self.check_interval = check_interval
        self._running = False
        self._task = None

    async def start(self):
        """启动监测器"""
        if self._running:
            logger.warning("WorkspaceMonitor already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"WorkspaceMonitor started (interval: {self.check_interval}s)")

    async def stop(self):
        """停止监测器"""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("WorkspaceMonitor stopped")

    async def _monitor_loop(self):
        """监测循环"""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)
                await self._check_workspaces()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"WorkspaceMonitor error: {e}", exc_info=True)

    async def _check_workspaces(self):
        """检查所有工作空间状态"""
        if not hasattr(self.manager, "_workspaces"):
            return

        checked_count = 0
        recovered_count = 0

        for cache_key, workspace in list(self.manager._workspaces.items()):
            try:
                checked_count += 1
                status = getattr(workspace, "status", "unknown")

                # 检查是否有启用渠道但未启动的工作空间
                if status != "running":
                    # 检查是否有启用的外部渠道（不包括 console）
                    external_channels = ["wecom", "discord", "telegram", "dingtalk", "feishu", "qq", "mattermost", "matrix", "xiaoyi", "weixin", "onebot"]
                    config = getattr(workspace, "config", {}) or {}
                    channels = config.get("channels", {})
                    has_enabled_channels = any(
                        ch_name in external_channels and ch_cfg.get("enabled", False)
                        for ch_name, ch_cfg in channels.items()
                        if isinstance(ch_cfg, dict)
                    )

                    if has_enabled_channels:
                        logger.warning(
                            f"Workspace {cache_key} is not running but has enabled channels. "
                            f"Attempting to recover..."
                        )
                        try:
                            # 从 cache_key 解析 agent_id 和 username
                            if ":" in cache_key:
                                parts = cache_key.split(":", 1)
                                # 处理 user:admin 格式（agent_id 包含冒号）
                                if parts[0] in ["global", "user"]:
                                    # user:admin → username=admin, agent_id=user:admin
                                    username = parts[1] if parts[0] != "global" else None
                                    agent_id = cache_key
                                else:
                                    # admin:user:xxx → username=admin, agent_id=user:xxx
                                    username = parts[0]
                                    agent_id = parts[1]
                            else:
                                agent_id = cache_key
                                username = None

                            await self.manager.get_agent(agent_id, username=username)
                            recovered_count += 1
                            logger.info(f"✓ Workspace {cache_key} recovered successfully")
                        except Exception as e:
                            logger.error(f"✗ Failed to recover workspace {cache_key}: {e}")
            except Exception as e:
                logger.debug(f"Error checking workspace {cache_key}: {e}")

        if recovered_count > 0:
            logger.info(f"WorkspaceMonitor check complete: {checked_count} checked, {recovered_count} recovered")

    async def check_now(self):
        """立即执行一次检查（用于手动触发）"""
        await self._check_workspaces()
