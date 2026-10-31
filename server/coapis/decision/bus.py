# -*- coding: utf-8 -*-
"""判断台账写入（v13 第 15 章 D6：判断日志进台账）。

台账是**旁路观测面**，不是主流程的一部分，因此：

- **fire-and-forget**：``emit`` 吞掉一切异常，绝不把异常抛回消息路径。
- **全字段显式列举**：表结构红线是全字段非空 + 服务端默认值，写入方逐字段
  给值，避免"字段丢失"类回归（系统内已有三起先例）。
- **一键关闭**：总开关 / 台账开关关闭时直接返回，不碰数据库。
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from .config import DecisionHubConfig
from .types import DecisionResult

logger = logging.getLogger(__name__)

#: 台账表列（逐字段显式列举，配合全字段非空红线）
_LEDGER_COLUMNS = (
    "event_id",
    "source",
    "complexity",
    "action",
    "reason",
    "hit_layer",
    "model",
    "latency_ms",
    "cost",
    "tokens",
    "user_id",
    "agent_id",
    "chat_id",
    "outcome",
    "created_at",
    # v14 §4.3 台账补列（迁移 0020）
    "input_hash",
    "judgment",
    "turn",
    "rating",
)


class DecisionBus:
    """判断台账写入器。"""

    # 清理节流：每个进程最多每小时清一次。台账写入是对话热路径，
    # 不能每条都跑一次全表删除。
    _PURGE_INTERVAL_S = 3600.0

    def __init__(self, config: DecisionHubConfig | None = None) -> None:
        self._config = config or DecisionHubConfig.from_env()
        self._purged_at = 0.0

    @property
    def config(self) -> DecisionHubConfig:
        return self._config

    def emit(
        self,
        event: DecisionResult,
        *,
        user_id: str = "",
        agent_id: str = "",
        chat_id: str = "",
    ) -> bool:
        """把一次判断落台账。**永不抛异常**，返回是否写入。

        作用域（user_id/agent_id/chat_id）既可作为关键字参数传入，也可
        预先写在事件对象上——关键字参数只补空，不覆盖已有值。
        """
        cfg = self._config
        if not cfg.enabled or not cfg.ledger_enabled:
            return False
        try:
            if not event.event_id:
                event.event_id = str(uuid.uuid4())
            if not event.created_at:
                event.created_at = time.time()
            if user_id:
                event.user_id = user_id
            if agent_id:
                event.agent_id = agent_id
            if chat_id:
                event.chat_id = chat_id
            row = event.to_row()
        except Exception as exc:  # 构造畸形 → 丢弃
            logger.warning("[DecisionHub] 台账行构造失败（丢弃）: %s", exc)
            return False
        try:
            self._insert(row)
            self._purge()
            return True
        except Exception as exc:
            logger.warning("[DecisionHub] 台账写入失败（忽略）: %s", exc)
            return False

    def _purge(self) -> None:
        """按保留期清掉超期的台账行（v13 验收 15.3 之三：90 天清理）。

        判断日志只进台账、不进记忆管道，因此**必须**有出口，否则详单表
        无限增长。清理由写入顺带触发，并按进程节流（一小时一次）——
        台账写入是对话热路径，不能每条都做一次全表删除。异常由调用方
        统一吞掉：清理失败不影响判断写入本身。
        """
        now = time.time()
        if now - self._purged_at < self._PURGE_INTERVAL_S:
            return
        self._purged_at = now
        days = int(getattr(self._config, "ledger_retention_days", 90) or 90)
        cutoff = now - float(days) * 86400.0
        from ..foundation.db.engine import get_session
        from sqlalchemy import text

        with get_session() as session:
            session.execute(
                text("DELETE FROM decision_events WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )

    def _insert(self, row: dict[str, Any]) -> None:
        from ..foundation.db.engine import get_session
        from sqlalchemy import text

        columns = ", ".join(_LEDGER_COLUMNS)
        placeholders = ", ".join(f":{name}" for name in _LEDGER_COLUMNS)
        sql = text(f"INSERT INTO decision_events ({columns}) VALUES ({placeholders})")
        payload = {name: row[name] for name in _LEDGER_COLUMNS}
        with get_session() as session:
            session.execute(sql, payload)


_bus: Optional[DecisionBus] = None


def get_bus() -> DecisionBus:
    """进程内单例总线。"""
    global _bus
    if _bus is None:
        _bus = DecisionBus(DecisionHubConfig.from_env())
    return _bus


def set_bus(bus: DecisionBus) -> None:
    """注入总线（测试/运行期开关用）。"""
    global _bus
    _bus = bus


__all__ = ["DecisionBus", "get_bus", "set_bus"]
