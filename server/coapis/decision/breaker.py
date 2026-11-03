# -*- coding: utf-8 -*-
"""判断熔断（v13 验收标准 5：判断模型不可用自动降级，绝不卡死）。

- 连续失败达到阈值 → 打开熔断，冷却期内直接跳过判断；
- 冷却到期 → 半开，只放一次探测请求；探测失败重新打开，成功则关闭；
- 按 key 隔离。判官三处（计划闸门 / 技能触发 / 验收）共用同一个键
  ``judge-model``，任一连续失败就一起降级（v14 §4.3①）。
- 半开探测失败 → 冷却翻倍，封顶 4×基准；探测成功 → 回到基准。
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
    #: 上一次失败的时刻，用于按窗口切段（见 CircuitBreaker.window_s）
    last_failure_at: float = 0.0
    #: 半开探测开始的时刻，用于探测超时放行（见 CircuitBreaker.probe_s）
    probe_started_at: float = 0.0


class CircuitBreaker:
    """按 key 隔离的熔断器。"""

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_s: float = 120.0,
        cooldown_floor_s: float = COOLDOWN_FLOOR_S,
        enabled: bool = True,
        clock: Callable[[], float] = time.time,
        window_s: float = 60.0,
        probe_s: float = 3.0,
    ) -> None:
        self._threshold = max(1, int(failure_threshold))
        self._floor = max(0.0, float(cooldown_floor_s))
        self._cooldown_s = max(self._floor, float(cooldown_s))
        #: 基准冷却：半开探测失败会翻倍，探测成功回到这里
        self._base_cooldown_s = self._cooldown_s
        #: 失败计数的时间窗口（秒）。窗口外的失败不再累计——否则进程长期运行中
        #: 偶发的零星失败会一路累加到阈值，把健康模型误判成熔断。0 = 不衰减。
        self._window_s = max(0.0, float(window_s))
        #: 半开探测超时（秒）。探测那颗请求失联（进程被杀、回调没跑到）时，
        #: 探测权必须按时释放，否则这个源永远不再有第二次探测。
        self._probe_s = max(0.0, float(probe_s))
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
        if state.probing and self._probe_s > 0:
            # 探测那颗请求失联（进程被杀、回调没跑到）时按时把探测权释放。
            # 不释放的话这个源只有一颗探测且永不落账，熔断从此再也不被观测。
            started = state.probe_started_at
            if started and self._clock() - started > self._probe_s:
                state.probing = False
                state.probe_started_at = 0.0
        if state.probing:
            # 半开期的探测权只有一颗。放过一次之后，在这颗探测落账
            # （record_success / record_failure）之前，其余请求一律降级——
            # 熔断要的是"只放一次探测"，不是"半开期全放行"。
            return False
        if state.failures < self._threshold:
            return True
        if self._clock() - state.opened_at >= self._cooldown_s:
            # 冷却到期 → 半开：只放一次探测
            if not state.probing:
                state.probing = True
                # 冷却在放探测这一刻结束：之后所有计时都从这次探测算。
                # 用 opened_at 计时的话，cooldown_s=60 + probe_s=6 时冷却
                # （60s）先于探测超时（66s）到期，每次到期都再放一颗新探测，
                # 60~66s 这段被持续消耗——dev 熔断器 21 次 consumed 的来历。
                state.probe_started_at = self._clock()
                return True
            return False
        return False

    def record_failure(self, key: str) -> None:
        if not self._enabled:
            return
        state = self._state(key)
        was_probing = state.probing
        now = self._clock()
        if (
            self._window_s > 0
            and state.last_failure_at
            and now - state.last_failure_at > self._window_s
        ):
            # 窗口外的旧失败清账。长期运行的进程里偶发零星失败若永不清算，
            # 累加到阈值就会把健康模型误判成熔断。
            state.failures = 0
        state.last_failure_at = now
        state.failures += 1
        state.probing = False
        state.probe_started_at = 0.0
        if state.failures >= self._threshold:
            state.opened_at = self._clock()
            if was_probing:
                # 半开探测失败 → 冷却翻倍，封顶 4×基准。判官模型一直不可用
                # 就别每次都重新撞一次超时（v14 §4.3②）。
                self._cooldown_s = min(
                    self._cooldown_s * 2.0,
                    self._base_cooldown_s * 4.0,
                )

    def record_success(self, key: str) -> None:
        if not self._enabled:
            return
        state = self._states.get(key)
        if state is not None:
            state.failures = 0
            state.opened_at = 0.0
            state.probing = False
            state.probe_started_at = 0.0
            self._cooldown_s = self._base_cooldown_s

    def sync_thresholds(
        self,
        threshold: int,
        cooldown_s: float,
        window_s: float | None = None,
        probe_s: float | None = None,
    ) -> None:
        """让在途配置说话算数（v15 F6）。

        闸门是按问句/模型惰性建的：第一次用到就按当时的配置定下阈值。
        若那一刻中枢配置还没装载（拿到的是默认 3 次 / 120 秒），之后
        配置改成 5 次也不会回头更新——于是「配置说 5 次才熔断、实际
        3 次就熔断」，判官被记成故障、整条判断被跳过，台账里全是
        skipped_backend，运维看到的永远是「模型坏了」。

        窗口与探测超时传 None 表示沿用闸门现值：调用方没有这两项时，
        不要把已经生效的窗口悄悄清零（窗口清零等于失败永不清算）。
        """
        self._threshold = max(1, int(threshold))
        self._cooldown_s = max(float(cooldown_s), self._floor)
        self._base_cooldown_s = self._cooldown_s
        if window_s is not None:
            self._window_s = max(0.0, float(window_s))
        if probe_s is not None:
            self._probe_s = max(0.0, float(probe_s))

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

    def failures_of(self, key: str) -> int:
        """当前累计的连续失败次数（未熔断时也在计数）。"""
        state = self._states.get(key)
        return 0 if state is None else int(state.failures)

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
        window_s=float(getattr(config, "breaker_window_seconds", 60.0)),
        probe_s=float(getattr(config, "breaker_probe_timeout_s", 3.0)),
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
