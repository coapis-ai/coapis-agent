# -*- coding: utf-8 -*-
"""判断中枢配置（v13 第 15 章 D5：判据不入库，这里只有开关与阈值）。

来源优先级：**智能体 running_config.decision_hub > 环境变量 > 默认值**
（与既有配置优先级约定一致）。

开关粒度：一个总开关 ``enabled`` + 每岗位一个开关。一期只接了技能触发与
计划闸门两个岗位，岗位开关就是「一键关闭回到今天」的落点。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping

ENV_PREFIX = "COAPIS_DECISION_"

#: 一期接入的岗位（岗位开关 = 总开关之下的细粒度闸门）
POSTS = (
    "intent",
    "skill_trigger",
    "plan_gate",
    "tool_guard",
    "verify",
    "context",
)

DEFAULTS = {
    "enabled": True,
    "ledger_enabled": True,
    "cache_enabled": True,
    "breaker_enabled": True,
    "cache_ttl_s": 300.0,
    "cache_max_entries": 512,
    "breaker_failure_threshold": 3,
    "breaker_cooldown_s": 120.0,
    "breaker_cooldown_floor_s": 1.0,
    # 判断模型要跑在"会话激活模型"上；推理型模型（Q3 这类）光思考就要
    # 几百 token、两三秒，1.5s/60token 的预算等于"判官必败、静默退回规则"。
    "llm_timeout_ms": 3000.0,
    "llm_max_tokens": 512,
}


def _env(name: str) -> str | None:
    return os.environ.get(ENV_PREFIX + name)


def _as_bool(val: Any, default: bool) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() not in ("false", "0", "no", "off")


def _as_float(val: Any, default: float) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _as_int(val: Any, default: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


@dataclass
class DecisionHubConfig:
    """判断中枢运行参数（开关 + 阈值）。"""

    enabled: bool = True
    ledger_enabled: bool = True
    cache_enabled: bool = True
    breaker_enabled: bool = True
    cache_ttl_s: float = 300.0
    cache_max_entries: int = 512
    breaker_failure_threshold: int = 3
    breaker_cooldown_s: float = 120.0
    breaker_cooldown_floor_s: float = 1.0
    llm_timeout_ms: float = 3000.0
    # 判断模型的输出预算。推理型模型（Q3 这类）先思考后作答，
    # 60 token 连思考都出不完，判官必败、静默退回规则层。
    llm_max_tokens: int = 512
    posts: dict = field(default_factory=dict)

    # ---- 构造 ----

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "DecisionHubConfig":
        """从智能体 running_config 的 decision_hub 段构造，并叠加 env 覆盖。

        优先级：智能体配置 > 环境变量 > 默认值。
        """
        raw = dict(raw or {})
        merged: dict[str, Any] = {}
        for key, default in DEFAULTS.items():
            env_name = key.upper()
            # 优先级：智能体配置 > 环境变量 > 默认值
            val = raw.get(key)
            if val is None:
                val = _env(env_name)
            if val is None:
                val = default
            merged[key] = (
                _as_bool(val, default)
                if isinstance(default, bool)
                else (_as_int(val, default) if isinstance(default, int) and not isinstance(default, bool) else _as_float(val, default))
            )
        posts = {p: _as_bool(raw.get(f"{p}_enabled"), merged["enabled"]) for p in POSTS}
        # 构造即夹取安全区间：调用方漏调 normalized() 也不会把判断环节配成拖死主链路
        return cls(posts=posts, **merged).normalized()

    @classmethod
    def from_env(cls) -> "DecisionHubConfig":
        """纯环境变量来源（无智能体配置时）。"""
        return cls.from_dict(None)

    def normalized(self) -> "DecisionHubConfig":
        """把越界参数夹回安全区间（防配置写错把判断环节拖死）。"""
        self.cache_ttl_s = min(max(float(self.cache_ttl_s), 1.0), 3600.0)
        self.cache_max_entries = min(max(int(self.cache_max_entries), 16), 4096)
        self.breaker_failure_threshold = min(max(int(self.breaker_failure_threshold), 1), 100)
        self.breaker_cooldown_s = min(max(float(self.breaker_cooldown_s), 1.0), 3600.0)
        self.breaker_cooldown_floor_s = min(
            max(float(self.breaker_cooldown_floor_s), 1.0),
            300.0,
        )
        self.llm_timeout_ms = min(max(float(self.llm_timeout_ms), 100.0), 8000.0)
        self.llm_max_tokens = min(max(int(self.llm_max_tokens), 64), 4096)
        return self

    # ---- 开关 ----

    def post_enabled(self, source: str) -> bool:
        """某岗位是否启用（总开关压过岗位开关）。"""
        if not self.enabled:
            return False
        return bool(self.posts.get(source, True))

    @property
    def llm_timeout_s(self) -> float:
        """判断模型超时（秒）。"""
        return self.llm_timeout_ms / 1000.0

    @property
    def cache_ttl(self) -> float:
        """结论缓存 TTL（秒）。"""
        return self.cache_ttl_s

    @property
    def cache_max(self) -> int:
        """结论缓存容量。"""
        return self.cache_max_entries


__all__ = ["DecisionHubConfig", "POSTS", "ENV_PREFIX"]
