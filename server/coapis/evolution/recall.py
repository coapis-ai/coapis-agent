# -*- coding: utf-8 -*-
"""经验召回的可见性与新鲜度尺子（单一实现）。

## 为什么存在

注入侧历史上只有一条作用域判断：

    if _exp_agent and agent_id and _exp_agent != agent_id: continue

它要求经验的 ``source_agent`` 必须等于当前 agent，于是被标记为
``is_generalizable=true`` 的**全局通用经验也一律被杀掉**（实测生产账本
1913 条的 ``source_agent`` 是 ``CoPaw`` / ``aEMams`` 等，与当前会话 agent
大多不等）。同时排序只看 ``confidence``，完全不看时间 —— 一条两年前的
经验和昨天的经验同权重竞争 15 个注入名额，这正是"老记忆变成噪音"的
机制成因。

本模块把两把尺子收敛为一份可测的纯函数：

- **可见性**：显式 global / 可泛化 → 跨 agent 可见；否则限本 agent。
- **新鲜度**：指数衰减，半衰期默认 180 天（用户拍板 D1）。

## 设计约束

- 纯函数、无 IO、无 pydantic：便于单测，也避免注入链路依赖模型解析。
- 缺时间戳的存量记录给**中性新鲜度** ``NEUTRAL_FRESHNESS``，既不被永久
  置顶，也不被判死（用户 D4：历史数据不做迁移，只建后续机制）。
- 不做硬删除：超龄只降权，迁移/归档属于另一件事，需单独授权。
"""

from __future__ import annotations

import datetime
import math
import os
from typing import Any, Iterable

# 用户拍板 D1：半衰期 180 天。可用环境变量覆盖，便于灰度调参。
DEFAULT_HALF_LIFE_DAYS = 180.0

# 缺时间戳的存量经验给中性权重（半衰期的等效"半个世代"）。
NEUTRAL_FRESHNESS = 0.5

# 注入渲染时用于提示模型的时间戳字段，按优先级排列。
_TIMESTAMP_KEYS = ("saved_at", "created_at", "updated_at", "approved_at")


def half_life_days() -> float:
    """半衰期（天），支持 ``COAPIS_EVO_HALF_LIFE_DAYS`` 覆盖。"""
    raw = (os.environ.get("COAPIS_EVO_HALF_LIFE_DAYS") or "").strip()
    if not raw:
        return DEFAULT_HALF_LIFE_DAYS
    try:
        v = float(raw)
    except ValueError:
        return DEFAULT_HALF_LIFE_DAYS
    return v if v > 0 else DEFAULT_HALF_LIFE_DAYS


def parse_timestamp(exp: dict, now: datetime.datetime | None = None):
    """取经验里第一个可解析的时间戳（aware/naive 都接受）。"""
    for key in _TIMESTAMP_KEYS:
        raw = exp.get(key)
        if not raw or not isinstance(raw, str):
            continue
        text = raw.strip().replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(text)
        except ValueError:
            continue
        ref = now or datetime.datetime.now(dt.tzinfo)
        # 统一时区，避免 aware 与 naive 相减抛 TypeError。
        if (dt.tzinfo is not None) != (ref.tzinfo is not None):
            dt = dt.replace(tzinfo=ref.tzinfo)
        return dt
    return None


def age_days(exp: dict, now: datetime.datetime | None = None):
    """经验年龄（天），无时间戳返回 None。未来时间戳按 0 处理。"""
    dt = parse_timestamp(exp, now=now)
    if dt is None:
        return None
    ref = now or datetime.datetime.now(dt.tzinfo)
    return max(0.0, (ref - dt).total_seconds() / 86400.0)


def freshness(exp: dict, now: datetime.datetime | None = None, hl: float | None = None) -> float:
    """指数衰减权重：半衰期处为 0.5，越新越接近 1。"""
    if hl is None:
        hl = half_life_days()
    age = age_days(exp, now=now)
    if age is None:
        return NEUTRAL_FRESHNESS
    return math.pow(0.5, age / hl)


def is_global(exp: dict) -> bool:
    """是否属于"跨 agent 可见"的全局经验。"""
    if str(exp.get("applicable_scope") or "").lower() == "global":
        return True
    if bool(exp.get("is_generalizable")):
        return True
    return False


def is_visible(exp: dict, agent_id: str = "", user_id: str = "") -> bool:
    """可见性判定。

    - 全局/可泛化经验：任何 agent 可见。
    - 否则要求来源 agent 与当前 agent 一致（来源缺失时放行，
      因为缺来源的旧数据没有归属信息，杀掉会误伤）。
    """
    if is_global(exp):
        return True
    source = str(exp.get("source_agent") or exp.get("source_agent_id") or "")
    if not source or not agent_id:
        return True
    return source == agent_id


def relevance_score(
    exp: dict,
    now: datetime.datetime | None = None,
    hl: float | None = None,
) -> float:
    """综合权重 = 置信度 × 新鲜度 × 轻微重要度。

    importance_score 只给 0.8~1.2 的窄带调制，避免它压过时间与置信度。
    """
    try:
        conf = float(exp.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    try:
        imp = float(exp.get("importance_score") or exp.get("score") or 0.5)
    except (TypeError, ValueError):
        imp = 0.5
    imp_factor = 0.8 + min(max(imp, 0.0), 1.0) * 0.4
    return max(conf, 0.01) * freshness(exp, now=now, hl=hl) * imp_factor


def cluster_key(exp: dict[str, Any]) -> str:
    """同主题指纹：``experience_type`` + 标题归一化（只留字母数字）。

    两个用途共用同一把尺子：
      1. 注入前去重 —— 同一主题（如"沙箱拒绝"被记了 8 次）只占一个席位；
      2. 固化门槛 —— 同一主题被**独立记录多次**，说明它是反复出现的
         重要事项，才配写进 AGENTS.md（见 evolution/sediment.py）。
    """
    title = str(exp.get("title") or "").strip()
    if not title:
        title = str(exp.get("content") or "").strip()
    norm = "".join(ch for ch in title.lower() if ch.isalnum())
    etype = str(exp.get("experience_type") or "misc").strip().lower()
    return etype + "|" + norm[:48]


def dedupe(experiences: Iterable[dict], *, now: datetime.datetime | None = None,
           hl: float | None = None) -> tuple[list[dict], dict[str, int]]:
    """同主题簇只保留综合权重最高的一条。

    Returns:
        ``(保留列表, 合并计数>1 的簇)``；簇数与多出的行数用于观测霸榜是否治住。
    """
    best: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        key = cluster_key(exp)
        counts[key] = counts.get(key, 0) + 1
        cur = best.get(key)
        if cur is None or relevance_score(cur, now=now, hl=hl) < relevance_score(exp, now=now, hl=hl):
            best[key] = exp
    merged = {k: v for k, v in counts.items() if v > 1}
    return list(best.values()), merged

def rank(
    experiences: Iterable[dict],
    agent_id: str = "",
    limit: int = 15,
    now: datetime.datetime | None = None,
    hl: float | None = None,
    dedupe_topic: bool = True,
    stats: dict[str, int] | None = None,
) -> list[dict]:
    """过滤不可见 → 同主题聚合 → 按综合权重排序 → 截断。

    ``dedupe_topic=True``（默认）先做同主题聚合：同一 :func:`cluster_key` 只留
    综合权重最高的一条。旧行为让单主题霸占席位（实测 sandbox 主题占 8/15
    席），新话题经验永远挤不进来；合并明细写进 ``stats`` 供调用方观测。
    返回原 dict 引用，不改写入参。"""
    pool = [e for e in experiences if isinstance(e, dict) and is_visible(e, agent_id=agent_id)]
    scanned = len(pool)
    merged_clusters = 0
    merged_rows = 0
    if dedupe_topic:
        pool, merged = dedupe(pool, now=now, hl=hl)
        merged_clusters = len(merged)
        merged_rows = sum(v - 1 for v in merged.values())
    if stats is not None:
        # scanned = 扫过的可见条数。少了这个键，注入日志里的 scanned 恒为 0，
        # "扫了多少、留下多少"就无从对账（实测 2026-11-27）。
        stats["scanned"] = scanned
        stats["after_dedupe"] = len(pool)
        stats["merged_clusters"] = merged_clusters
        stats["merged_rows"] = merged_rows
    pool.sort(key=lambda e: relevance_score(e, now=now, hl=hl), reverse=True)
    if limit and limit > 0:
        return pool[:limit]
    return pool


def human_age(exp: dict, now: datetime.datetime | None = None) -> str:
    """给模型看的新旧线索，如 ``3天前`` / ``8个月前`` / ``时间未知``。

    注入文本里带上这个，模型才能自己判断"这条老经验是否还适用于当前
    问题"——这是缓解答非所问的关键一环。
    """
    age = age_days(exp, now=now)
    if age is None:
        return "时间未知"
    if age < 1:
        return "今天"
    if age < 31:
        # 必须四舍五入：int() 截断会把 4.99 天显示成"4天前"。
        return f"{round(age)}天前"
    if age < 365:
        return f"{round(age / 31)}个月前"
    return f"{age / 365:.1f}年前"


# ---------------------------------------------------------------------------
# 意图过滤（P5）：问什么注入什么
# ---------------------------------------------------------------------------
#
# 尺子的取值必须来自数据里真有的字段值，不能自己发明词。
# approved.jsonl 实测取值（2026-11-27，1913 条）：
#   category        = general/preference/template/coding/skill/style/
#                     workflow/tool_usage/design/domain
#   experience_type = lesson/pattern/preference/skill
# 历史上这里拿 experience_type 去比 {code_error, best_practice, decision_record,
# operational_failure, operational_pattern}，这五个词在上述两个字段里都 0 命中，
# 过滤永远落空（只有"配置"类靠 preference 侥幸命中），"问什么注入什么"形同虚设。

INTENT_CATEGORIES: dict[str, tuple[str, ...]] = {
    "code": ("coding", "tool_usage", "skill", "domain", "general"),
    "ops": ("workflow", "tool_usage", "skill", "general"),
    "config": ("preference", "workflow", "domain", "template", "general"),
}

INTENT_HINTS: dict[str, tuple[str, ...]] = {
    "code": ("代码", "写法", "报错", "调试", "修复", "函数", "接口", "bug",
             "debug", "coding", "code", "exception", "traceback"),
    "ops": ("部署", "发布", "上线", "容器", "重启", "环境", "命令", "构建",
            "运维", "deploy", "docker", "nginx", "restart"),
    "config": ("配置", "设置", "参数", "端口", "变量", "开关", "环境变量",
               "config", "setting", "port"),
}


def filter_by_intent(exps: Iterable[dict], query: str,
                     limit: int = 10) -> tuple[list[dict], set[str]]:
    """按提问意图把候选经验收窄到相关类别。

    返回 ``(保留的经验, 命中的类别集合)``；类别集合为空表示"这次没过滤"。

    两种情况**不会比不过滤更差**：问题没命中任何意图、或收窄后一条不剩，
    都原样返回候选 —— 宁可多注入，不可把该用的经验筛没了。
    """
    candidates = [e for e in (exps or []) if isinstance(e, dict)]
    q = str(query or "").lower()
    if not candidates or not q:
        return candidates[:limit], set()

    matched: set[str] = set()
    for intent, hints in INTENT_HINTS.items():
        if any(h in q for h in hints):
            matched.update(INTENT_CATEGORIES[intent])
    if not matched:
        return candidates[:limit], set()

    kept = [
        e for e in candidates
        if str(e.get("category") or "").strip().lower() in matched
    ]
    if not kept:
        return candidates[:limit], matched
    return kept[:limit], matched
