# -*- coding: utf-8 -*-
"""判断熔断（v13 验收标准 5：判断模型不可用自动降级，绝不卡死）。

- 连续失败达到阈值 → 打开熔断，冷却期内直接跳过判断；
- 冷却到期 → 半开，只放一次探测请求；探测失败重新打开，成功则关闭；
- 按 key（岗位 / 岗位+模型）隔离，技能触发挂了不影响计划闸门。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

#: 冷却下限（秒）：下限以下会让半开探测变成高频重试
COOLDOWN_FLOOR_S = 1.0


@dataclass
class _BreakerState:
    failures: int = 0
    opened_at: float = 0.0
    probing: bool = False


class CircuitBreaker:
    """按 key 隔离的熔断器。"""

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_s: float = 120.0,
        cooldown_floor_s: float = COOLDOWN_FLOOR_S,
        enabled: bool = True,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._threshold = max(1, int(failure_threshold))
        self._floor = max(0.0, float(cooldown_floor_s))
        self._cooldown_s = max(self._floor, float(cooldown_s))
        self._enabled = enabled
        self._clock = clock
        self._states: dict[str, _BreakerState] = {}

    def _state(self, key: str) -> _BreakerState:
        return self._states.setdefault(key, _BreakerState())

    @property
    def failure_threshold(self) -> int:
        """连续失败多少次触发熔断（只读）。"""
        return self._threshold

    @property
    def cooldown_s(self) -> float:
        """实际生效的冷却秒数（已抬到地板之上，只读）。"""
        return self._cooldown_s

    @property
    def enabled(self) -> bool:
        return self._enabled

    def allow(self, key: str) -> bool:
        """是否允许本次判断。返回 False 时调用方**必须**走降级路径。"""
        if not self._enabled:
            return True
        state = self._states.get(key)
        if state is None:
            return True
        if state.failures < self._threshold:
            return True
        if self._clock() - state.opened_at >= self._cooldown_s:
            # 冷却到期 → 半开：只放一次探测
            if not state.probing:
                state.probing = True
                return True
            return False
        return False

    def record_failure(self, key: str) -> None:
        if not self._enabled:
            return
        state = self._state(key)
        state.failures += 1
        state.probing = False
        if state.failures >= self._threshold:
            state.opened_at = self._clock()

    def record_success(self, key: str) -> None:
        if not self._enabled:
            return
        state = self._states.get(key)
        if state is not None:
            state.failures = 0
            state.opened_at = 0.0
            state.probing = False

    def state_of(self, key: str) -> str:
        """当前状态：``disabled`` / ``closed`` / ``open`` / ``half_open``。"""
        if not self._enabled:
            return "disabled"
        state = self._states.get(key)
        if state is None or state.failures < self._threshold:
            return "closed"
        if self._clock() - state.opened_at >= self._cooldown_s:
            return "half_open"
        return "open"

    def reset(self, key: Optional[str] = None) -> None:
        """清空熔断状态（测试/运维用）。"""
        if key is None:
            self._states.clear()
        else:
            self._states.pop(key, None)


def make_breaker_from_config(config) -> CircuitBreaker:
    """从判断中枢配置构造熔断器。"""
    return CircuitBreaker(
        failure_threshold=int(getattr(config, "breaker_failure_threshold", 3)),
        cooldown_s=float(getattr(config, "breaker_cooldown_s", 120.0)),
        cooldown_floor_s=float(getattr(config, "breaker_cooldown_floor_s", COOLDOWN_FLOOR_S)),
        enabled=bool(getattr(config, "breaker_enabled", True)),
    )


_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(source: str = "default") -> CircuitBreaker:
    """按岗位取熔断器单例（同岗位同一实例，跨岗位互不影响）。

    ``source`` 省略时取 ``"default"``（调用方未区分岗位的场景）。
    """
    key = str(source or "default")
    breaker = _breakers.get(key)
    if breaker is None:
        from .config import DecisionHubConfig

        breaker = make_breaker_from_config(
            DecisionHubConfig.from_env().normalized(),
        )
        _breakers[key] = breaker
    return breaker


def reset_breakers() -> None:
    """清空进程内熔断器（测试与运维复位用）。"""
    _breakers.clear()


__all__ = [
    "CircuitBreaker",
    "make_breaker_from_config",
    "get_breaker",
    "reset_breakers",
    "COOLDOWN_FLOOR_S",
]
