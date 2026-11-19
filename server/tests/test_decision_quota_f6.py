"""v20 F6 决策模型配额护栏测试。

覆盖三件事，都是本轮实测逼出来的：
  1. 默认值 0/0 时护栏必须完全沉默（既有部署行为逐字不变）；
  2. 在途数与当日 token 越界时给出正确码位（限流 / 配额），且计数不漂负；
  3. 台账查询失败时按"放行"处理 —— 配额是刹车，不能变成闸死。
"""
from __future__ import annotations

import time

import pytest

from coapis.decision import judge_reasons as jr
from coapis.decision.config import DEFAULTS
from coapis.decision.gateway import LAYER_QUOTA, JudgeGateway


class _Cfg:
    """最小决策模型配置：只给护栏用到的两个旋钮。"""

    judge_max_in_flight = 0
    judge_daily_token_budget = 0


@pytest.fixture()
def gateway() -> JudgeGateway:
    # 用真实类实例，不碰进程级单例，避免污染其它用例
    return JudgeGateway()


def test_new_defaults_are_off(gateway):
    """旋钮默认 0 = 不限：老部署不配任何环境变量时，行为必须不变。"""
    assert DEFAULTS["judge_daily_token_budget"] == 0
    assert DEFAULTS["judge_max_in_flight"] == 0
    assert gateway._quota_code(_Cfg()) is None


def test_quota_codes_on_breach(gateway):
    """在途满 → 限流码；token 到顶 → 配额码；未越界 → None。"""
    cfg = _Cfg()
    cfg.judge_max_in_flight = 3
    gateway._in_flight = 3
    assert gateway._quota_code(cfg) == jr.RATE_LIMITED
    gateway._in_flight = 2
    assert gateway._quota_code(cfg) is None

    cfg.judge_max_in_flight = 0
    gateway._quota_cache = {
        "day": time.strftime("%Y-%m-%d"), "tokens": 5000, "ts": time.time(),
    }
    cfg.judge_daily_token_budget = 4000
    assert gateway._quota_code(cfg) == jr.QUOTA_EXHAUSTED
    cfg.judge_daily_token_budget = 6000
    assert gateway._quota_code(cfg) is None


def test_release_never_goes_negative(gateway):
    """释放回调可能被多次触发（异常路径），计数不能漂成负数。"""
    gateway._in_flight = 1
    gateway._release_in_flight()
    gateway._release_in_flight()
    assert gateway._in_flight == 0


def test_quota_note_carries_live_numbers(gateway):
    """降级台账要能还原现场：在途/配额四个数都得写进去。"""
    cfg = _Cfg()
    cfg.judge_max_in_flight = 4
    cfg.judge_daily_token_budget = 1000
    gateway._in_flight = 2
    gateway._quota_cache = {"day": "x", "tokens": 900, "ts": 0}
    note = gateway._quota_note(cfg)
    assert "2/4" in note and "900/1000" in note


def test_daily_tokens_falls_back_on_db_failure(gateway, monkeypatch):
    """台账读不到时按放行处理：不能因为一次查询失败让决策模型链整条停摆。"""

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(gateway, "_quota_cache", {"day": "", "tokens": 777, "ts": 0.0})
    monkeypatch.setattr(gateway, "_daily_tokens_live", boom)
    assert gateway._daily_tokens() == 777


def test_quota_layer_is_distinct_from_budget():
    """配额档位独立于逐轮预算档位 —— 台账上必须分得开。"""
    assert LAYER_QUOTA == "quota_cap"
    assert LAYER_QUOTA != "budget_cap"
    assert "quota_exhausted" in jr.ALL_CODES
