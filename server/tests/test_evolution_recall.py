# -*- coding: utf-8 -*-
"""evolution.recall 尺子测试：可见性 + 新鲜度衰减 + 排序。

治的病：注入侧曾要求 ``source_agent == 当前agent``，把标记为可泛化的
全局经验一律杀掉；排序只看 confidence，两年前的经验和昨天的同权重。
"""

import datetime

import pytest

from coapis.evolution import recall


def _iso(days_ago, tz=None):
    return (datetime.datetime.now(tz) - datetime.timedelta(days=days_ago)).isoformat()


def test_default_half_life_is_180_days():
    assert recall.DEFAULT_HALF_LIFE_DAYS == 180.0
    assert recall.half_life_days() == 180.0


def test_half_life_env_override(monkeypatch):
    monkeypatch.setenv("COAPIS_EVO_HALF_LIFE_DAYS", "30")
    assert recall.half_life_days() == 30.0
    monkeypatch.setenv("COAPIS_EVO_HALF_LIFE_DAYS", "abc")
    assert recall.half_life_days() == 180.0
    monkeypatch.setenv("COAPIS_EVO_HALF_LIFE_DAYS", "-5")
    assert recall.half_life_days() == 180.0


def test_freshness_decays_and_halves_at_half_life():
    now = datetime.datetime.now()
    fresh = {"saved_at": _iso(0, now.tzinfo)}
    half = {"saved_at": _iso(180, now.tzinfo)}
    old = {"saved_at": _iso(540, now.tzinfo)}
    assert recall.freshness(fresh, now=now) == pytest.approx(1.0, abs=0.01)
    assert recall.freshness(half, now=now) == pytest.approx(0.5, abs=0.01)
    assert recall.freshness(old, now=now) < 0.15
    assert recall.freshness(fresh, now=now) > recall.freshness(half, now=now) > \
        recall.freshness(old, now=now)


def test_missing_timestamp_gets_neutral_freshness():
    assert recall.freshness({}) == recall.NEUTRAL_FRESHNESS
    assert recall.freshness({"saved_at": "not-a-date"}) == recall.NEUTRAL_FRESHNESS


def test_future_timestamp_clamped_to_zero_age():
    now = datetime.datetime.now()
    exp = {"saved_at": _iso(-10, now.tzinfo)}
    assert recall.age_days(exp, now=now) == 0.0


def test_global_or_generalizable_visible_everywhere():
    assert recall.is_visible({"is_generalizable": True}, agent_id="A") is True
    assert recall.is_visible({"applicable_scope": "global"}, agent_id="A") is True
    assert recall.is_global({"is_generalizable": True}) is True


def test_private_experience_stays_with_owner():
    exp = {"is_generalizable": False, "source_agent": "A"}
    assert recall.is_visible(exp, agent_id="A") is True
    assert recall.is_visible(exp, agent_id="B") is False


def test_missing_owner_is_not_killed():
    """缺归属信息的存量数据没有资格被误杀。"""
    assert recall.is_visible({"title": "x"}, agent_id="A") is True


def test_rank_drops_private_of_other_agent():
    now = datetime.datetime.now()
    pool = [
        {"title": "mine", "confidence": 0.9, "source_agent": "B",
         "is_generalizable": False, "saved_at": _iso(1, now.tzinfo)},
        {"title": "shared", "confidence": 0.6, "source_agent": "B",
         "is_generalizable": True, "saved_at": _iso(1, now.tzinfo)},
    ]
    titles = [e["title"] for e in recall.rank(pool, agent_id="A", now=now)]
    assert titles == ["shared"]


def test_rank_prefers_recent_over_stale_same_confidence():
    now = datetime.datetime.now()
    pool = [
        {"title": "ancient", "confidence": 0.95, "is_generalizable": True,
         "saved_at": _iso(720, now.tzinfo)},
        {"title": "recent", "confidence": 0.90, "is_generalizable": True,
         "saved_at": _iso(3, now.tzinfo)},
    ]
    got = recall.rank(pool, agent_id="A", now=now)
    assert got[0]["title"] == "recent"


def test_rank_limit_and_no_mutation_of_input():
    now = datetime.datetime.now()
    pool = [
        {"title": f"e{i}", "confidence": 0.8, "is_generalizable": True,
         "saved_at": _iso(i, now.tzinfo)} for i in range(20)
    ]
    original = [e["title"] for e in pool]
    got = recall.rank(pool, agent_id="A", limit=15, now=now)
    assert len(got) == 15
    assert [e["title"] for e in pool] == original


def test_human_age_buckets():
    now = datetime.datetime.now()
    assert recall.human_age({"saved_at": _iso(0, now.tzinfo)}, now=now) == "今天"
    assert recall.human_age({"saved_at": _iso(5, now.tzinfo)}, now=now) == "5天前"
    # 90 天 ≈ 3 个月（截断会算成 2 个月）
    assert recall.human_age({"saved_at": _iso(90, now.tzinfo)}, now=now) == "3个月前"
    assert recall.human_age({"saved_at": _iso(800, now.tzinfo)}, now=now).endswith("年前")
    assert recall.human_age({}, now=now) == "时间未知"


def test_broken_scores_do_not_crash():
    """脏数据（confidence 为字符串）不能让注入链路炸掉。"""
    pool = [{"title": "x", "confidence": "N/A", "importance_score": None,
             "saved_at": "garbage", "is_generalizable": True}]
    got = recall.rank(pool, agent_id="A")
    assert len(got) == 1


# ══════════════ 同主题聚合去重（M2：治「单主题霸榜」）══════════════
def _exp(title, content, *, conf=0.9, days=0, etype="lesson"):
    return {
        "id": title + "|" + content,
        "title": title,
        "content": content,
        "confidence": conf,
        "experience_type": etype,
        "agent_ids": ["a1"],
        "created_at": _iso(days),
    }


def _stale_flood(n=10):
    # 老引擎反复报的同一个错：同主题被记了 n 次，条条权重都差不多
    return [_exp("沙箱执行被拒", "沙箱里跑不了这条命令", conf=1.0, days=i)
            for i in range(n)]


def test_rank_without_dedupe_lets_one_topic_hog_every_slot():
    fresh = _exp("前端构建入口", "产物在 client/dist", conf=0.8)
    got = recall.rank(_stale_flood() + [fresh], limit=3, dedupe_topic=False)
    titles = [r["title"] for r in got]
    assert titles == ["沙箱执行被拒"] * 3, titles
    assert "前端构建入口" not in titles


def test_rank_dedupe_lets_new_topic_in():
    fresh = _exp("前端构建入口", "产物在 client/dist", conf=0.8)
    got = recall.rank(_stale_flood() + [fresh], limit=3)
    titles = [r["title"] for r in got]
    assert "前端构建入口" in titles, titles
    assert len(set(titles)) == len(titles), "同主题不应再占多个席位"


def test_rank_stats_report_merge_amount():
    fresh = _exp("前端构建入口", "产物在 client/dist", conf=0.8)
    stats = {}
    recall.rank(_stale_flood(10) + [fresh], limit=3, stats=stats)
    assert stats["merged_clusters"] == 1
    assert stats["merged_rows"] == 9
    assert stats["after_dedupe"] == 2


def test_dedupe_representative_is_the_freshest():
    rows = [
        _exp("端口", "开发入口是 4200", days=300),
        _exp("端口", "开发入口是 4300", days=1),
        _exp("端口", "开发入口是 4300", days=1),
    ]
    kept, merged = recall.dedupe(rows)
    assert len(kept) == 1
    assert "4300" in kept[0]["content"], "同主题里该留最新的那条"
    assert list(merged.values()) == [3]


def test_cluster_key_ignores_case_and_punctuation_but_not_type():
    a = recall.cluster_key({"title": "Language Preference",
                            "experience_type": "preference"})
    b = recall.cluster_key({"title": "language, preference!",
                            "experience_type": "preference"})
    c = recall.cluster_key({"title": "language preference",
                            "experience_type": "lesson"})
    assert a == b
    assert a != c


def test_rank_dedupe_does_not_mutate_input():
    rows = _stale_flood(4)
    before = [dict(r) for r in rows]
    recall.rank(rows, limit=2)
    assert rows == before


# ===========================================================================
# P5 意图过滤：问什么注入什么
# ===========================================================================
#
# 治的病：过滤尺子历史上比的是 {code_error, best_practice, decision_record,
# operational_failure, operational_pattern}，这些词在 approved.jsonl 的
# category / experience_type 两个字段里 **0 命中**（实测 2026-11-27），
# 收窄永远落空，"问什么注入什么"形同虚设。


# approved.jsonl 实测取值（1913 条）。尺子只能用这里的词，
# 谁再往里塞自发明的类型词，这条测试就拦谁。
REAL_CATEGORIES = {
    "general", "preference", "template", "coding", "skill", "style",
    "workflow", "tool_usage", "design", "domain",
}


def _iexp(title, category, exp_type="lesson"):
    return {"title": title, "content": "x", "category": category,
            "experience_type": exp_type}


def test_intent_vocabulary_must_exist_in_data():
    """尺子里的每个取值都必须是库里真出现过的 category。"""
    invented = set()
    for cats in recall.INTENT_CATEGORIES.values():
        invented |= set(cats) - REAL_CATEGORIES
    assert not invented, f"过滤器用了数据里不存在的类型词: {sorted(invented)}"


def test_code_question_keeps_lessons_not_only_preference():
    rows = [_iexp("语言偏好", "preference", "preference"),
            _iexp("空指针排查", "coding"),
            _iexp("工具用法", "tool_usage", "pattern")]
    kept, matched = recall.filter_by_intent(rows, "帮我修复这个报错")
    assert matched, "中文提问必须命中意图（历史上只有英文键，永不命中）"
    titles = [r["title"] for r in kept]
    assert "空指针排查" in titles
    assert "工具用法" in titles


def test_config_question_narrows_away_unrelated_domain():
    rows = [_iexp("端口配置", "preference", "preference"),
            _iexp("无关的领域知识", "style")]
    kept, matched = recall.filter_by_intent(rows, "改一下端口配置")
    assert matched
    assert [r["title"] for r in kept] == ["端口配置"]


def test_unrelated_question_does_not_filter():
    rows = [_iexp("语言偏好", "preference", "preference"),
            _iexp("空指针排查", "coding")]
    kept, matched = recall.filter_by_intent(rows, "今天天气怎么样")
    assert matched == set()
    assert len(kept) == len(rows)


def test_narrowing_to_empty_falls_back_to_unfiltered():
    """收窄为空时必须回退：宁可多注入，不能把该用的筛没。"""
    rows = [_iexp("设计规范", "design"), _iexp("风格约定", "style")]
    kept, matched = recall.filter_by_intent(rows, "部署一下容器")
    assert matched, "意图是命中的"
    assert [r["title"] for r in kept] == ["设计规范", "风格约定"]


def test_limit_applied_after_filter():
    rows = [_iexp(f"编码规范{i}", "coding") for i in range(12)]
    kept, matched = recall.filter_by_intent(rows, "这段代码写法对吗", limit=10)
    assert matched and len(kept) == 10


def test_category_missing_or_padded_is_tolerated():
    rows = [{"title": "无类别", "content": "x"},
            {"title": "带空格", "content": "y", "category": "  Coding  "},
            {"title": "空类别", "content": "z", "category": None}]
    kept, matched = recall.filter_by_intent(rows, "修复代码报错")
    assert [r["title"] for r in kept] == ["带空格"]


def test_filter_never_mutates_input_rows():
    rows = [_iexp("空指针排查", "coding")]
    before = [dict(r) for r in rows]
    recall.filter_by_intent(rows, "修复报错")
    assert rows == before


def test_empty_inputs_are_safe():
    assert recall.filter_by_intent([], "代码") == ([], set())
    rows = [_iexp("语言偏好", "preference", "preference")]
    assert recall.filter_by_intent(rows, "")[1] == set()
