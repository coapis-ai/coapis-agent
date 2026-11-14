# -*- coding: utf-8 -*-
"""按 (provider, model) 的可用性台账（B1 · 借鉴 QwenPaw ``provider_model_availability.py``）。

**与熔断器的分工（实施方案 §5-B1 拍板）**：

- ``decision/breaker.py`` = **计数与冷却**（连续失败阈值 → 打开 → 冷却）。
- 本模块 = **原因与可见性**：把"为什么不可用"写下来、留给 API 与人看。
- 熔断打开时由 ``gateway`` 读本模块 :func:`reason_of` 把原因带进判官台账。

键固定为 ``(provider_id, model)``（D9：不引入 workspace 维度）。
进程内单例 + TTL；台账是**运维观测数据**，不是计费依据。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "STATUS_OK",
    "STATUS_UNAVAILABLE",
    "AVAILABILITY_STATUSES",
    "ProviderModelAvailabilityRecord",
    "ProviderModelAvailabilityView",
    "ProviderModelAvailabilityStore",
    "get_availability_store",
    "reason_of",
    "record_model_result",
    "record_model_result_safe",
    "reset_availability_store",
]

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"
# 允许的状态集合（借鉴上游口径，我方多一个 auth）
AVAILABILITY_STATUSES = frozenset(
    {"ok", "rate_limited", "timeout", "auth", "unsupported", "network"},
)

_DEFAULT_TTL_SECONDS = 3600.0
_UNSAFE = ("\x00", "\n", "\r", "\t")


def _safe_key(value: Any, limit: int = 128) -> str:
    """键清洗：落库/做字典键前的最小消毒（借鉴上游 _safe_text 思路）。"""
    text = str(value if value is not None else "").strip()
    for ch in _UNSAFE:
        text = text.replace(ch, " ")
    return text[:limit]


def _ttl_seconds() -> float:
    """记录存活时间（秒）。环境变量可覆盖，非法值回默认。"""
    raw = os.environ.get("COAPIS_AVAILABILITY_TTL", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_SECONDS
    if value <= 0:
        return _DEFAULT_TTL_SECONDS
    return value


def _now() -> float:
    return time.time()


@dataclass(frozen=True)
class ProviderModelAvailabilityRecord:
    provider_id: str
    model: str
    status: str = STATUS_OK
    detail: str = ""
    checked_at: float = field(default_factory=_now)
    cooldown_until: float | None = None
    consecutive_failures: int = 0

    @property
    def is_cooling_down(self) -> bool:
        return self.cooldown_until is not None and self.cooldown_until > _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "model": self.model,
            "status": self.status,
            "detail": self.detail,
            "checked_at": self.checked_at,
            "cooldown_until": self.cooldown_until,
            "consecutive_failures": self.consecutive_failures,
            "cooling_down": self.is_cooling_down,
        }


@dataclass(frozen=True)
class ProviderModelAvailabilityView:
    """``GET /api/providers/availability`` 的响应形状。"""

    items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": self.items,
            "count": len(self.items),
            "ttl_seconds": _ttl_seconds(),
        }


class ProviderModelAvailabilityStore:
    """进程内单例存储（TTL 过期自动剔除；不自己落库）。

    持久化说明：判官/聊天侧的观测台账要长期留痕时，由调用方显式调用
    :func:`persist_to_decision_ledger`（判官侧已有 ``decision_events`` 通路），
    本模块**不自己写库**——避免与熔断器形成两本账。
    """

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], ProviderModelAvailabilityRecord] = {}

    # ------------------------------------------------------------- 内部工具
    @staticmethod
    def _key(provider_id: str, model: str) -> tuple[str, str]:
        return (_safe_key(provider_id, 64), _safe_key(model, 128))

    def _purge_expired(self) -> None:
        ttl = _ttl_seconds()
        now = _now()
        expired = [
            key
            for key, rec in self._records.items()
            if now - rec.checked_at > ttl and not rec.is_cooling_down
        ]
        for key in expired:
            self._records.pop(key, None)

    # ---------------------------------------------------------------- 写入
    def record(
        self,
        provider_id: str,
        model: str,
        status: str,
        detail: str = "",
        *,
        cooldown_until: float | None = None,
    ) -> ProviderModelAvailabilityRecord:
        """记录一次结果。``status`` 必须在 :data:`AVAILABILITY_STATUSES` 内。"""
        key = self._key(provider_id, model)
        clean = _safe_key(status, 32)
        if clean not in AVAILABILITY_STATUSES:
            # 状态越界不抛异常（台账不能反噬主链），归入 unsupported 并留原话
            detail = f"{detail} (status={clean})".strip()
            clean = "unsupported"
        previous = self._records.get(key)
        failures = 0 if clean == STATUS_OK else int(
            (previous.consecutive_failures if previous else 0) + 1,
        )
        record = ProviderModelAvailabilityRecord(
            provider_id=key[0],
            model=key[1],
            status=clean,
            detail=_safe_key(detail, 400),
            checked_at=_now(),
            cooldown_until=cooldown_until,
            consecutive_failures=failures,
        )
        self._records[key] = record
        self._purge_expired()
        return record

    # ---------------------------------------------------------------- 读取
    def get(self, provider_id: str, model: str) -> ProviderModelAvailabilityRecord | None:
        self._purge_expired()
        return self._records.get(self._key(provider_id, model))

    def snapshot(
        self,
        provider_ids: Iterable[str] | None = None,
    ) -> ProviderModelAvailabilityView:
        self._purge_expired()
        wanted = (
            None
            if provider_ids is None
            else {_safe_key(pid, 64) for pid in provider_ids}
        )
        items = [
            rec.to_dict()
            for (pid, _m), rec in sorted(self._records.items())
            if wanted is None or pid in wanted
        ]
        return ProviderModelAvailabilityView(items=items)

    def reason_of(self, provider_id: str, model: str) -> str:
        """给熔断器/判官台账用的"为什么不可用"。

        无记录 → ``ok``（**没观测过就等于没证据说它坏**，不猜坏）。
        """
        rec = self.get(provider_id, model)
        if rec is None:
            return STATUS_OK
        if rec.status == STATUS_OK:
            return STATUS_OK
        bits = [rec.status]
        if rec.detail:
            bits.append(rec.detail)
        if rec.is_cooling_down:
            bits.append(f"cooling_down_until={rec.cooldown_until:.0f}")
        bits.append(f"fails={rec.consecutive_failures}")
        return " ".join(bits)[:400]

    def clear(self) -> None:
        self._records.clear()


_STORE: ProviderModelAvailabilityStore | None = None


def get_availability_store() -> ProviderModelAvailabilityStore:
    global _STORE
    if _STORE is None:
        _STORE = ProviderModelAvailabilityStore()
    return _STORE


def reset_availability_store() -> None:
    """测试用：清掉单例（别在生产调）。"""
    global _STORE
    _STORE = None


def reason_of(provider_id: str, model: str) -> str:
    return get_availability_store().reason_of(provider_id, model)


def record_model_result(
    provider_id: str,
    model: str,
    status: str,
    detail: str = "",
    *,
    cooldown_until: float | None = None,
) -> ProviderModelAvailabilityRecord:
    return get_availability_store().record(
        provider_id,
        model,
        status,
        detail,
        cooldown_until=cooldown_until,
    )


def record_model_result_safe(
    provider_id: str,
    model: str,
    status: str,
    detail: str = "",
    *,
    cooldown_until: float | None = None,
) -> None:
    """记账**绝不反噬主链**：任何异常都吞掉（台账是观测物，不是关键路径）。"""
    try:
        record_model_result(
            provider_id,
            model,
            status,
            detail,
            cooldown_until=cooldown_until,
        )
    except Exception:  # noqa: BLE001 - 观测面不能把聊天请求带崩
        return
