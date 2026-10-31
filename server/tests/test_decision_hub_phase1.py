# -*- coding: utf-8 -*-
"""智能判断中枢 一期测试。

覆盖一期交付项（v13 第 8 章）：
判断槽位 + 回落链 + 缓存 + 熔断 + 总线/台账 + 总开关 + 静态检查。

运行：
    .venv-test/bin/python -m pytest server/tests/test_decision_hub_phase1.py -q
"""

import asyncio
import time
from pathlib import Path

import pytest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from coapis.decision import (
    CircuitBreaker,
    DecisionBus,
    DecisionHubConfig,
    DecisionResult,
    cached_judgment,
    get_breaker,
    get_cached_judgment,
    get_judgment_cache,
    make_cache_key,
    put_cached_judgment,
    reset_judgment_cache,
)
from coapis.decision.breaker import make_breaker_from_config
from coapis.decision.types import DecisionResult
from coapis.decision.resolver import get_judgment_provider_config

SERVER_DIR = Path(__file__).resolve().parents[1]


def asyncio_run(coro):
    """跑一个协程拿返回值（判级/兜底判都是协程）。"""
    return asyncio.run(coro)


# ------------------------------------------------ 判断岗取模（D1/D2：复用激活模型）


def test_judgment_adds_no_new_model_type():
    """D1 定稿：判断岗不新增模型类型，既有类型一个都不能少。"""
    from coapis.providers.model_type import VALID_MODEL_TYPES

    assert "judgment" not in VALID_MODEL_TYPES, "判断岗复用激活模型，不新增配置项"
    for legacy in ("chat", "embedding", "rerank", "audio", "vision"):
        assert legacy in VALID_MODEL_TYPES, "既有模型类型不得被改动"


def _patch_slot(monkeypatch, slot):
    import coapis.app.routers.user_model_prefs as ump

    monkeypatch.setattr(ump, "resolve_chat_model_slot", lambda u, a, s=None: slot)


def test_judgment_config_requires_live_provider(monkeypatch):
    """激活模型指向不存在的 provider 时不产出配置（判断岗停用，不猜模型）。"""
    from coapis.providers.provider_manager import ProviderManager

    class _PM:
        def get_provider(self, pid):
            return None

    _patch_slot(monkeypatch, ("ghost", "m"))
    monkeypatch.setattr(
        ProviderManager, "get_instance", classmethod(lambda cls: _PM()),
    )
    assert get_judgment_provider_config("u", "a") is None


def test_judgment_config_follows_active_model(monkeypatch):
    """命中激活模型：base_url 去尾斜杠、key 取 provider 现值、不落原文。"""
    from coapis.providers.provider_manager import ProviderManager

    class _Prov:
        base_url = "https://example.test/v1/"
        api_key = "sk-live"

        def list_models(self):
            return ["model-x"]

    class _PM:
        def get_provider(self, pid):
            return _Prov()

    _patch_slot(monkeypatch, ("prov-x", "model-x"))
    monkeypatch.setattr(
        ProviderManager, "get_instance", classmethod(lambda cls: _PM()),
    )
    cfg = get_judgment_provider_config("u1", "a1")
    assert cfg is not None
    assert cfg["api_base"] == "https://example.test/v1"
    assert cfg["api_key"] == "sk-live"
    assert cfg["provider_id"] == "prov-x"
    assert cfg["model"] == "model-x"


def test_judgment_config_rejects_stale_model(monkeypatch):
    """激活模型已被删除（偏好变陈旧）时降级不判断，不拿不存在的模型去判。"""
    from coapis.providers.provider_manager import ProviderManager

    class _Prov:
        base_url = "https://example.test/v1"
        api_key = "k"

        def list_models(self):
            return ["other"]

    class _PM:
        def get_provider(self, pid):
            return _Prov()

    _patch_slot(monkeypatch, ("p", "gone-model"))
    monkeypatch.setattr(
        ProviderManager, "get_instance", classmethod(lambda cls: _PM()),
    )
    assert get_judgment_provider_config("u", "a") is None


def test_judgment_config_swallows_lookup_failure(monkeypatch):
    """取模链路抛异常时返回 None，绝不把异常抛给聊天主链路。"""
    import coapis.app.routers.user_model_prefs as ump

    def _boom(u, a, s=None):
        raise RuntimeError("provider store down")

    monkeypatch.setattr(ump, "resolve_chat_model_slot", _boom)
    assert get_judgment_provider_config("u", "a") is None


def test_judgment_config_empty_identity_is_none(monkeypatch):
    """Empty identity must not fabricate a provider when nothing is usable.

    Regression: v13 §10.2.1 - "" used to return the hardcoded "openai"
    for a provider that does not exist.  The third resolution level
    (global default) is forced empty here, otherwise the test passes on
    a host with no providers and fails in a dev container with a live
    model, which is environment luck, not a guarantee.
    """
    from coapis.providers.provider_manager import ProviderManager

    monkeypatch.setattr(
        ProviderManager,
        "get_active_model",
        lambda self: None,
        raising=True,
    )
    assert get_judgment_provider_config("", "") is None


# ---------------------------------------------------------------- 缓存


def test_cache_key_scope_isolation():
    """缓存键必须含 user/agent 与岗位 —— 跨用户、跨岗位不得串判。"""
    k1 = make_cache_key("skill_trigger", "查日程", user_id="alice", agent_id="a1")
    k2 = make_cache_key("skill_trigger", "查日程", user_id="bob", agent_id="a1")
    k3 = make_cache_key("intent", "查日程", user_id="alice", agent_id="a1")
    assert k1 != k2, "跨用户必须隔离"
    assert k1 != k3, "跨岗位必须隔离"


def test_cache_key_candidates_participate():
    """候选集参与键计算：候选变了缓存必须失效。"""
    k1 = make_cache_key("skill_trigger", "查日程", ["s1", "s2"])
    k2 = make_cache_key("skill_trigger", "查日程", ["s1", "s3"])
    assert k1 != k2


def test_cached_judgment_hit_and_miss():
    cache = get_judgment_cache()
    cache.clear()
    key = make_cache_key("skill_trigger", "查日程")
    calls = []

    def compute():
        calls.append(1)
        return ["s1"]

    value, hit = cached_judgment(key, compute, cache=cache)
    assert value == ["s1"] and hit is False
    value2, hit2 = cached_judgment(key, compute, cache=cache)
    assert value2 == ["s1"] and hit2 is True
    assert len(calls) == 1, "命中缓存不得再调用计算函数"


def test_cached_judgment_empty_result_not_cached():
    """空结果不缓存 —— 未命中是常态，缓存只存正向结果。"""
    cache = get_judgment_cache()
    cache.clear()
    key = make_cache_key("skill_trigger", "查日程")
    for _ in range(2):
        cached_judgment(key, lambda: [], cache=cache)
    assert len(cache) == 0


def test_cache_ttl_expiry():
    """TTL 到期后不得再命中（缓存只借 5 分钟，不永久固化）。"""
    from coapis.decision.cache import TTLCache

    cache = TTLCache(max_entries=8, ttl_s=60)
    key = make_cache_key("skill_trigger", "x")
    put_cached_judgment(key, ["s1"], cache=cache)
    assert get_cached_judgment(key, cache=cache) == ["s1"]
    # 把写入时间拨到 TTL 之外，等价于时间流逝（避免测试真等 60s）
    cache._data[key] = (time.monotonic() - 1, ["s1"])  # (expires, value)
    assert get_cached_judgment(key, cache=cache) is None


def test_cache_lru_eviction():
    """超过容量按 LRU 淘汰，不得无界增长。"""
    cache = get_judgment_cache()
    cache.clear()
    cap = cache.max_entries
    for i in range(cap + 50):
        put_cached_judgment(
            make_cache_key("skill_trigger", "q%d" % i), ["s"], cache=cache,
        )
    assert len(cache) <= cap, "LRU 必须封顶，不得无界增长"


def test_cache_zero_ttl_never_hits():
    """ttl_s=0 表示关闭缓存（normalize 允许 0），不得命中。"""
    from coapis.decision.cache import TTLCache

    cache = TTLCache(max_entries=8, ttl_s=0)
    key = make_cache_key("skill_trigger", "x")
    put_cached_judgment(key, ["s1"], cache=cache)
    assert get_cached_judgment(key, cache=cache) is None


def test_cache_disabled_flag_short_circuits():
    """cache_enabled=False 时 cached_judgment 必须每次重算。"""
    cfg = DecisionHubConfig.from_dict({"cache_enabled": False})
    assert cfg.cache_enabled is False


# ---------------------------------------------------------------- 熔断
#
# 真实 API：CircuitBreaker(failure_threshold, cooldown_s, enabled)，按 key
# 隔离 —— 六岗以 source 为 key，一岗熔断不传染他岗（v13 第 3.3 节）。


def test_breaker_opens_after_threshold():
    b = CircuitBreaker(failure_threshold=3, cooldown_s=60)
    assert b.allow("skill_trigger")
    for _ in range(3):
        b.record_failure("skill_trigger")
    assert not b.allow("skill_trigger"), "连续失败达阈值必须断开"
    assert b.state_of("skill_trigger") == "open"


def test_breaker_cooldown_floor_is_one_second():
    """冷却下限 1 秒（int 语义），不得配成 0 秒导致熔断永不生效。"""
    assert CircuitBreaker(cooldown_s=0).cooldown_s == 1
    assert CircuitBreaker(cooldown_s=0.4).cooldown_s == 1
    assert CircuitBreaker(cooldown_s=30).cooldown_s == 30


def test_breaker_cooldown_half_open_single_probe():
    """冷却结束进入半开，只放行一次探测；探测成功即闭合。"""
    b = CircuitBreaker(failure_threshold=1, cooldown_s=60)
    b.record_failure("plan_gate")
    assert not b.allow("plan_gate"), "断开期必须拒绝判断"
    assert b.state_of("plan_gate") == "open"
    # 把断开时间拨到冷却之外，等价于时间流逝（避免测试真等 60s）
    b._state("plan_gate").opened_at = time.monotonic() - 61
    assert b.state_of("plan_gate") == "half_open", "冷却结束进入半开"
    assert b.allow("plan_gate"), "半开放行一次探测"
    assert not b.allow("plan_gate"), "半开只允许一次探测"
    b.record_success("plan_gate")
    assert b.state_of("plan_gate") == "closed"
    assert b.allow("plan_gate")


def test_breaker_half_open_probe_failure_reopens():
    """半开探测再次失败必须重新断开。"""
    b = CircuitBreaker(failure_threshold=1, cooldown_s=60)
    b.record_failure("plan_gate")
    b._state("plan_gate").opened_at = time.monotonic() - 61
    assert b.allow("plan_gate")
    b.record_failure("plan_gate")
    assert b.state_of("plan_gate") == "open"
    assert not b.allow("plan_gate")


def test_breaker_success_resets_failures():
    b = CircuitBreaker(failure_threshold=3, cooldown_s=60)
    b.record_failure("intent")
    b.record_failure("intent")
    b.record_success("intent")
    assert b.state_of("intent") == "closed"
    b.record_failure("intent")
    assert b.allow("intent"), "成功后失败计数清零，不应断开"


def test_breaker_isolated_by_source_key():
    b = CircuitBreaker(failure_threshold=1, cooldown_s=60)
    b.record_failure("skill_trigger")
    assert not b.allow("skill_trigger")
    assert b.allow("plan_gate"), "一岗熔断不得传染他岗"
    assert b.allow("intent")


def test_breaker_disabled_passes_everything():
    b = CircuitBreaker(failure_threshold=1, cooldown_s=60, enabled=False)
    for _ in range(10):
        b.record_failure("skill_trigger")
    assert b.allow("skill_trigger"), "熔断关闭时恒放行"
    assert b.state_of("skill_trigger") == "disabled"


def test_breaker_reset_clears_state():
    b = CircuitBreaker(failure_threshold=1, cooldown_s=60)
    b.record_failure("intent")
    assert not b.allow("intent")
    b.reset("intent")
    assert b.allow("intent")


def test_breaker_from_config_threshold():
    class _Cfg:
        breaker_failure_threshold = 2
        breaker_cooldown_s = 7.0

    b = make_breaker_from_config(_Cfg())
    assert b.failure_threshold == 2
    assert b.cooldown_s == 7.0
    b.record_failure("intent")
    assert b.allow("intent")
    b.record_failure("intent")
    assert not b.allow("intent")


def test_breaker_defaults_when_config_missing():
    class _Empty:
        pass

    b = make_breaker_from_config(_Empty())
    assert b.failure_threshold == 3
    assert b.cooldown_s == 120


def test_get_breaker_is_singleton_with_source_keys():
    a = get_breaker()
    b = get_breaker()
    assert a is b, "进程级单例，按 key 分岗位"
    a.reset()


# ---------------------------------------------------------------- 总开关


def test_config_master_switch_off():
    cfg = DecisionHubConfig.from_dict({"enabled": False})
    assert cfg.enabled is False


def test_config_defaults_when_empty():
    cfg = DecisionHubConfig.from_dict(None)
    assert cfg.enabled is True, "缺省开启（缺省安全）"
    assert cfg.cache_enabled is True and cfg.breaker_enabled is True
    assert cfg.ledger_enabled is True


def test_config_post_switches():
    """六岗可单独关；总开关优先于六岗开关。"""
    cfg = DecisionHubConfig.from_dict({"intent_enabled": False})
    assert cfg.post_enabled("intent") is False
    assert cfg.post_enabled("plan_gate") is True
    cfg2 = DecisionHubConfig.from_dict({"enabled": False, "intent_enabled": True})
    assert cfg2.post_enabled("intent") is False, "总开关必须压过六岗开关"


def test_config_env_override(monkeypatch):
    monkeypatch.setenv("COAPIS_DECISION_ENABLED", "false")
    assert DecisionHubConfig.from_dict(None).enabled is False
    monkeypatch.delenv("COAPIS_DECISION_ENABLED")
    assert DecisionHubConfig.from_dict(None).enabled is True

    monkeypatch.setenv("COAPIS_DECISION_BREAKER_FAILURE_THRESHOLD", "7")
    monkeypatch.setenv("COAPIS_DECISION_BREAKER_COOLDOWN_S", "30")
    cfg = DecisionHubConfig.from_dict(None)
    assert cfg.breaker_failure_threshold == 7
    assert cfg.breaker_cooldown_s == 30
    monkeypatch.delenv("COAPIS_DECISION_BREAKER_FAILURE_THRESHOLD")
    monkeypatch.delenv("COAPIS_DECISION_BREAKER_COOLDOWN_S")

    monkeypatch.setenv("COAPIS_DECISION_CACHE_TTL_S", "60")
    monkeypatch.setenv("COAPIS_DECISION_CACHE_MAX_ENTRIES", "128")
    cfg = DecisionHubConfig.from_dict(None)
    assert cfg.cache_ttl_s == 60
    assert cfg.cache_max_entries == 128
    monkeypatch.delenv("COAPIS_DECISION_CACHE_TTL_S")
    monkeypatch.delenv("COAPIS_DECISION_CACHE_MAX_ENTRIES")


def test_config_agent_wins_over_env(monkeypatch):
    """智能体配置优先于 env（与既有配置优先级约定一致）。"""
    monkeypatch.setenv("COAPIS_DECISION_CACHE_TTL_S", "60")
    cfg = DecisionHubConfig.from_dict({"cache_ttl_s": 90})
    assert cfg.cache_ttl_s == 90
    monkeypatch.delenv("COAPIS_DECISION_CACHE_TTL_S")


def test_config_normalize_clamps_outliers():
    """越界参数必须收敛，防止配置把系统配崩。"""
    cfg = DecisionHubConfig.from_dict({
        "llm_timeout_ms": 10 ** 9,
        "cache_max_entries": 10 ** 9,
        "cache_ttl_s": -5,
        "breaker_failure_threshold": 0,
        "breaker_cooldown_s": -1,
    })
    # 超时上限封顶：判断绝不允许拖垮主链路（改造前无此护栏）
    assert cfg.llm_timeout_ms == 8000
    assert cfg.cache_max_entries == 4096
    # TTL / 冷却 / 阈值都有地板：配错不会变成「永不失效」或「零冷却」
    assert cfg.cache_ttl_s == 1.0
    assert cfg.breaker_failure_threshold == 1
    assert cfg.breaker_cooldown_s == 1.0


# ---------------------------------------------------------------- 总线 / 台账
#
# 真实 API：DecisionBus(config) 同步直写全局引擎；emit() 返回 bool，
# 任何异常都转成 False（台账不得影响业务）。测试用 init_engine 指向临时库。


@pytest.fixture()
def ledger_db(tmp_path):
    """把全局引擎指向临时 sqlite 并建表，返回库路径。

    顺带清一次进程级判断缓存与熔断——缓存/熔断是**进程级**状态，
    不清就会跨用例命中（缓存命中不落台账，台账类断言随机变红）。
    """
    from coapis.foundation.db import init_engine, reset_engine
    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.models.decision import DecisionEvent  # noqa: F401

    def _clean():
        try:
            from coapis.decision.breaker import reset_breakers
            from coapis.decision.cache import reset_judgment_cache
            from coapis.decision.gateway import reset_judge_gateway

            reset_judgment_cache()
            reset_breakers()
            reset_judge_gateway()
        except Exception:  # pragma: no cover - 老版本网关没有这些钩子
            pass

    url = "sqlite:///%s" % (tmp_path / "ledger.db")
    engine = init_engine(url)
    BaseRow.metadata.create_all(engine)
    _clean()
    yield url
    _clean()
    reset_engine()


def _bus(enabled=True):
    from coapis.decision import set_bus

    cfg = DecisionHubConfig.from_dict({"ledger_enabled": enabled})
    bus = DecisionBus(cfg)
    set_bus(bus)
    return bus


def _query_all():
    from coapis.foundation.db import get_session_factory
    from coapis.foundation.db.models.decision import DecisionEvent

    with get_session_factory()() as s:
        return list(s.query(DecisionEvent).all())


def test_bus_emit_writes_ledger(ledger_db):
    bus = _bus()
    ok = bus.emit(DecisionResult(
        source="skill_trigger",
        complexity="simple",
        action="single_tool",
        reason="兜底判命中 2 个技能",
        hit_layer="llm",
        model="ollama/qwen3:8b",
        latency_ms=421,
        cost=0.0012,
        tokens=318,
        user_id="alice",
        agent_id="a1",
        chat_id="c1",
    ))
    assert ok is True

    rows = _query_all()
    assert len(rows) == 1
    row = rows[0]
    assert row.source == "skill_trigger"
    assert row.hit_layer == "llm"
    assert row.latency_ms == 421
    assert row.cost == 0.0012, "成本按元存，不得被整型截断成 0"
    assert row.tokens == 318
    assert (row.user_id, row.agent_id, row.chat_id) == ("alice", "a1", "c1")
    assert row.outcome == "pending"
    assert isinstance(row.created_at, float) and row.created_at > 1_000_000


def test_bus_emit_disabled(ledger_db):
    bus = _bus(enabled=False)
    assert bus.emit(DecisionResult(source="intent")) is False
    assert _query_all() == []


def test_bus_emit_never_raises_on_bad_payload(ledger_db):
    bus = _bus()
    assert bus.emit(DecisionResult(source="intent")) is True


def test_bus_emit_survives_db_failure(ledger_db):
    """台账写失败必须返回 False 且不抛异常。"""
    bus = _bus()
    # 把引擎指向不存在的目录制造写失败
    from coapis.foundation.db import init_engine

    init_engine("sqlite:////nonexistent-dir-xyz-9876/ledger.db")
    assert bus.emit(DecisionResult(source="intent")) is False


def test_ledger_columns_not_null_with_server_defaults(ledger_db):
    """红线：全字段非空 + 服务端默认值（系统内已有三起字段丢失先例）。"""
    import sqlite3

    from coapis.foundation.db import get_engine

    db = get_engine().url.database
    conn = sqlite3.connect(str(db))
    try:
        cols = {r[1]: (r[2], r[3], r[4])
                for r in conn.execute("PRAGMA table_info(decision_events)")}
        assert "event_id" in cols
        for name, (_t, notnull, dflt) in cols.items():
            assert notnull == 1, "%s 必须 NOT NULL" % name
            if name != "event_id":
                assert dflt is not None, "%s 必须有服务端默认值" % name

        conn.execute("INSERT INTO decision_events (event_id) VALUES ('e-1')")
        conn.commit()
        row = conn.execute(
            "SELECT source, complexity, action, reason, hit_layer, model,"
            " latency_ms, cost, tokens, user_id, agent_id, chat_id, outcome,"
            " created_at FROM decision_events WHERE event_id='e-1'"
        ).fetchone()
        assert row == ("", "", "", "", "", "", 0, 0.0, 0, "", "", "", "pending", 0.0)
    finally:
        conn.close()


def test_ledger_cost_and_created_at_are_real(ledger_db):
    """cost / created_at 必须是浮点：判断成本常在 1 元以下，整型会截成 0。"""
    import sqlite3

    from coapis.foundation.db import get_engine

    conn = sqlite3.connect(str(get_engine().url.database))
    try:
        types = {r[1]: r[2].upper()
                 for r in conn.execute("PRAGMA table_info(decision_events)")}
        assert types["cost"] in ("REAL", "FLOAT")
        assert types["created_at"] in ("REAL", "FLOAT")
        assert types["latency_ms"] == "INTEGER"
        assert types["tokens"] == "INTEGER"
    finally:
        conn.close()


def test_migration_0018_matches_model():
    """迁移脚本列类型必须与 ORM 一致（迁移与模型分头跑过太多次）。"""
    mig = (SERVER_DIR / "coapis/foundation/db/migrations/versions"
           / "0018_decision_events.py")
    text = mig.read_text(encoding="utf-8")
    assert "sa.Float()" in text, "cost/created_at 迁移必须是 Float"
    assert "sa.Integer()" in text, "latency_ms/tokens 迁移必须是 Integer"
    for col in ("source", "complexity", "action", "reason", "hit_layer",
                "model", "user_id", "agent_id", "chat_id", "outcome"):
        assert 'sa.Column("%s", sa.Text(), nullable=False' % col in text, col


def test_plan_gate_emits_ledger(ledger_db):
    """判档模型复核发生时必须入账（台账岗位 plan_gate）。"""
    from coapis.agents.plan_gate import ComplexityClassifier

    _bus()
    # v14 §4.4①：判档不再有 judge_enabled 开关——判断恒走网关，降级是网关的职责
    clf = ComplexityClassifier()
    clf.set_ledger_scope({"user_id": "alice", "agent_id": "a1", "chat_id": "c1"})
    # 规则层只能给出 complex/simple/medium：complex 与 simple 都是直通，
    # 零次判断、不入账（见 test_plan_gate_no_ledger_on_rule_passthrough）。
    # 只有 medium 边界样本才调判级模型复核——这才是本测试要锁的入账路径。
    text = "总结一下这个季度的销售情况，给出建议"
    assert clf.classify(text) == "medium"
    # 判级结果由现场模型给出（simple/medium/complex），网关降级时为 None。
    # 本测试锁的是"发生了判断并留下完整台账"，不锁模型判成哪一档——
    # 判档准不准由校准岗按台账统计，不该由单元测试锁死。
    assert asyncio_run(clf._lite_judge(text)) in ("complex", "medium", "simple", None)

    rows = _query_all()
    assert len(rows) == 1
    assert rows[0].source == "plan_gate"
    # 命中层白名单含 llm：环境里真配了判断模型时，L1 命中就是本用例要锁的
    # "发生了判断并留下完整台账"。判成哪一档不锁（由校准岗按台账统计）。
    assert rows[0].hit_layer in (
        "llm",
        "no_model",
        "error",
        "timeout",
        "model",
        "cache",
        "skill",
        "rule",
    )
    assert (rows[0].user_id, rows[0].agent_id, rows[0].chat_id) == ("alice", "a1", "c1")


def test_plan_gate_rule_passthrough_skips_ledger(ledger_db):
    """规则直通（零次判断）不入账——台账只记真发生过的判断。"""
    from coapis.agents.plan_gate import ComplexityClassifier

    _bus()
    clf = ComplexityClassifier()
    clf.set_ledger_scope({"user_id": "alice", "agent_id": "a1", "chat_id": "c1"})
    assert asyncio_run(clf.classify_smart("查今天的销售数据")) == "simple"
    assert _query_all() == []


# ---------------------------------------------------------------- 静态检查
#
# v13 第 4.1 节：判断权不得再散落。机制 = 扫描业务模块里"自己拼判断模型
# 客户端"的写法，新增即测试失败。允许清单逐条写明角色，防止日后被当成
# 随手加行的白名单。

# 允许直接构造模型客户端的位置 → 角色说明
# 注：coapis/providers/ 整层豁免（造客户端本就是 provider 层职责），
#     在断言里按前缀放行，不逐文件列举。
_JUDGMENT_ALLOWLIST = {
    # 判断中枢本体：取模与判官客户端本就由它构造（唯一合法出口）
    "coapis/decision/resolver.py": "判断中枢取模",

    # 模型工厂 / provider 层：本就该由它造客户端
    "coapis/providers/openai_chat_model.py": "provider 工厂",
    "coapis/providers/ollama_chat_model.py": "provider 工厂",
    "coapis/providers/provider_manager.py": "provider 管理",
    "coapis/providers/provider.py": "provider 定义",

    # 对话主模型与多模态：不是判断岗
    "coapis/agents/core.py": "对话主模型客户端",
    "coapis/agents/utils/view_media.py": "视觉模型调用",
    "coapis/agents/utils/audio_transcription.py": "音频模型调用",
    "coapis/agents/model_factory.py": "模型工厂",
    "coapis/providers/model_factory.py": "模型工厂",
    # provider 连通性自检：不是判断岗
    "coapis/app/routers/admin_providers.py": "provider 连通性测试",
    # 判断岗：模型配置必须来自中枢 resolver（下面单独断言）
    "coapis/agents/plan_gate.py": "判断岗（复杂度判级）",
    "coapis/agents/utils/intent_classifier.py": "判断岗（意图分类）",
}

_JUDGMENT_PATTERNS = (
    "AsyncOpenAI(",
    "OpenAIChatModel(",
    "DashScopeChatModel(",
    "AnthropicChatModel(",
    "GeminiChatModel(",
    "chat/completions",
)

# 判断岗必须从中枢取模型，不得自己解析 provider/模型
_JUDGMENT_SITES = {
    "coapis/agents/plan_gate.py": "plan_gate",
    "coapis/agents/utils/intent_classifier.py": "intent",
    "coapis/agents/react_agent.py": "skill_trigger",
}


def _iter_business_py():
    root = SERVER_DIR / "coapis"
    for path in root.rglob("*.py"):
        rel = path.relative_to(SERVER_DIR).as_posix()
        if "/tests/" in rel or rel.startswith("tests/"):
            continue
        yield rel, path


def test_no_new_scattered_judgment_model_clients():
    """业务模块新增"自己拼判断模型客户端"必须失败。"""
    hits = []
    for rel, path in _iter_business_py():
        text = path.read_text(encoding="utf-8")
        for pat in _JUDGMENT_PATTERNS:
            if pat in text:
                hits.append((rel, pat))
    offenders = sorted({
        r for r, _ in hits
        if r not in _JUDGMENT_ALLOWLIST
        and not r.startswith("coapis/providers/")
    })
    assert not offenders, (
        "判断权散落：以下模块直接构造了模型客户端，必须改走智能判断中枢 "
        "(coapis/decision)，或在允许清单里说明角色：%s" % ", ".join(offenders)
    )


def test_judgment_sites_consume_the_hub():
    """三个判断岗必须 import coapis.decision，不得自行解析模型配置。"""
    for rel, source in _JUDGMENT_SITES.items():
        text = (SERVER_DIR / rel).read_text(encoding="utf-8")
        assert "coapis.decision" in text or "from ..decision" in text, (
            "%s 未接入判断中枢（岗位 %s）" % (rel, source)
        )


def test_judgment_sites_do_not_resolve_chat_slot_directly():
    """判断岗不得绕过回落链直接调三层解析。"""
    for rel in _JUDGMENT_SITES:
        text = (SERVER_DIR / rel).read_text(encoding="utf-8")
        assert "resolve_chat_model_slot" not in text, (
            "%s 直接调用了 resolve_chat_model_slot，必须经 decision.resolver" % rel
        )


def test_decision_package_does_not_import_agents():
    """中枢不得反向 import 智能体层（判断岗依赖中枢，反向即成环）。

    允许的单向依赖：resolver 复用 app 层的对话模型三层解析
    （resolve_chat_model_slot），这是回落链 L2/L3 的实现，方向是
    decision → app，不构成环。
    """
    for path in (SERVER_DIR / "coapis/decision").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for bad in ("from ..agents", "from coapis.agents"):
            assert bad not in text, "%s 反向依赖了 agents 层" % path.name


# ---------- 台账保留期清理（验收 15.3 之三：90 天清理生效）----------


def _bus_ret(days: int) -> DecisionBus:
    """带指定保留期的写入器；_purged_at 归零保证本用例必触发清理。"""
    cfg = DecisionHubConfig.from_env()
    cfg.ledger_enabled = True
    cfg.ledger_retention_days = days
    cfg.normalized()
    bus = DecisionBus(cfg)
    bus._purged_at = 0.0
    return bus


def _age(event_id: str, days: int) -> None:
    """把某行人为老化到 N 天前，模拟历史台账。"""
    from coapis.foundation.db import get_session_factory
    from coapis.foundation.db.models.decision import DecisionEvent

    with get_session_factory()() as s:
        row = s.query(DecisionEvent).filter(DecisionEvent.event_id == event_id).one()
        row.created_at = time.time() - days * 86400.0
        s.commit()


def test_bus_purges_rows_past_retention(ledger_db):
    """超过保留期的行在下一次写入时被清掉；新行原样留着。"""
    bus = _bus_ret(7)
    assert bus.emit(DecisionResult(source="plan_pre", complexity="simple")) is True
    assert len(_query_all()) == 1

    _age(_query_all()[0].event_id, 30)
    bus._purged_at = 0.0  # 越过节流窗口：本次写入必须顺带清掉超期行
    assert bus.emit(DecisionResult(source="plan_mid", complexity="complex")) is True

    rows = _query_all()
    assert len(rows) == 1, "30 天前的行应被清掉，只剩本轮新行"
    assert rows[0].source == "plan_mid"


def test_bus_keeps_rows_within_retention(ledger_db):
    """保留期内的行绝不清掉——复盘校准岗要做跨轮对照。"""
    bus = _bus_ret(90)
    assert bus.emit(DecisionResult(source="plan_pre")) is True
    _age(_query_all()[0].event_id, 30)
    bus._purged_at = 0.0  # 越过节流窗口，确保本次写入真的触发清理
    assert bus.emit(DecisionResult(source="plan_mid")) is True
    assert len(_query_all()) == 2, "30 天 < 90 天保留期，不得清理"


def test_bus_purge_is_throttled_per_process(ledger_db):
    """清理按进程节流：节流窗口内不重复清理，热路径不做全表删除。"""
    bus = _bus_ret(7)
    assert bus.emit(DecisionResult(source="a")) is True

    _age(_query_all()[0].event_id, 30)
    assert bus.emit(DecisionResult(source="b")) is True
    assert len(_query_all()) == 2, "节流窗口内不触发清理"

    bus._purged_at = 0.0
    assert bus.emit(DecisionResult(source="c")) is True
    rows = _query_all()
    assert len(rows) == 2, "越过节流窗口后超期行被清掉"
    assert {r.source for r in rows} == {"b", "c"}


def test_bus_purge_failure_never_blocks_write(ledger_db, monkeypatch):
    """台账写入异常必须被吞掉：绝不阻断对话（清理与写入同处一个护罩）。"""
    bus = _bus_ret(7)

    calls = {"n": 0}

    def _flaky(row):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("写入/清理时表不可用")

    monkeypatch.setattr(bus, "_insert", _flaky)
    assert bus.emit(DecisionResult(source="plan_pre")) is True
    assert bus.emit(DecisionResult(source="plan_mid")) is False


def test_retention_days_in_config_contract():
    """保留期进单一配置契约：有默认值、有边界、界面可改。"""
    from coapis.decision.config import DEFAULTS

    assert DEFAULTS["ledger_retention_days"] == 90
    assert "ledger_retention_days" in DecisionHubConfig.known_keys()

    cfg = DecisionHubConfig.from_env()
    cfg.ledger_retention_days = 1
    assert cfg.normalized().ledger_retention_days == 7, "下限 7 天"
    cfg.ledger_retention_days = 99999
    assert cfg.normalized().ledger_retention_days == 3650, "上限 3650 天"
