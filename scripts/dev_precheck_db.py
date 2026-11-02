#!/usr/bin/env python3
"""判断中枢 dev 预检尺子（v14 §批次0 尺子对齐 / §批次5 治理）。

设计约束（写死在代码里，改脚本等于改尺子，必须说清楚为什么）：

* **档位尺子直接 import 代码里的 ``LEVELS``**（唯一真源
  :mod:`coapis.agents.plan_gate`）。之前脚本里硬编码「trivial/light/standard/
  complex」四档，代码是三档——同一份数据两次体检给出「档位全非法」和
  「Simple 占 65%」两个结论，体检当场作废。尺子和代码必须是同一把。
* **KPI 口径带 ``origin`` 过滤**：测试造数（``origin='test'``）不进真判率/损耗
  分布；origin 列为空的历史行按「web」处理（迁移 0021 之前的存量）。
* **方言自适应**：dev 主线是 SQLite，企业版 dev 是 PostgreSQL，同一条命令必须
  都能跑通。所以脚本里不用 ``->>``、``split_part`` 这类单方言语法：指标 4
  直接读 ``complexity`` 列（写入侧契约已保证是档位，台账里也没有 ``purpose``
  列），动词分布在 Python 里切分。
* 指标固定、顺序固定：改前/改后各跑一次，差值就是这批改动的真实收益。
* 只读：脚本不写库、不改配置，跑一万次也不影响 dev。

跑法::

    python scripts/dev_precheck_db.py --url "sqlite:////apps/ai/coapis-dev/system/coapis.db"
    python scripts/dev_precheck_db.py --url "$COAPIS_DATABASE_URL"   # PG 同一条命令
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

import sqlalchemy as sa

# 岗位名显示成中文，和台账治理文档一致；未知岗位原样显示（不许静默漏岗）。
_LABELS = {
    "plan_gate": "判岗(ComplexityClassifier)",
    "skill_router": "技能岗(预激活+意图)",
    "skill_trigger": "技能岗(预激活)",
    "skill_intent": "意图岗(并入技能岗)",
    "tool_gate": "工具闸(v14 新岗)",
    "tool_profile": "工具闸(v14 新岗)",
    "advisor": "改道岗(事中纠察)",
    "acceptance": "验收岗(收尾判官)",
}


def _levels() -> tuple:
    """档位尺子 = 代码里的词表，本脚本绝不自带第二把尺子。

    判岗写台账用的就是 :mod:`coapis.agents.plan_gate` 的 ``LEVELS``，尺子取同
    一个来源；取不到（部署包里没这份代码）就退到 rubric，两处都取不到直接
    报错——尺子缺失比跑出一份假体检好。
    """
    try:
        from coapis.agents.plan_gate import LEVELS  # 唯一真源（三档）

        return tuple(LEVELS)
    except Exception:  # noqa: BLE001
        from coapis.decision.rubric import LEVELS

        return tuple(LEVELS)


def _origin_is_web() -> str:
    """KPI 口径：测试造数不算数；origin 为空的历史行算真实流量。

    SQLite 里 ``origin=''`` 和 ``origin IS NULL`` 都要放过，PG 同理——所以
    条件写成「不是 test」，比「等于 web」更稳（历史行没有 origin 值）。
    """
    return "(origin IS NULL OR origin <> 'test')"


def _rows(conn, sql):
    return [tuple(r) for r in conn.execute(sa.text(sql)).fetchall()]


def _pct(n, d):
    return 0.0 if not d else 100.0 * n / d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="COAPIS_DATABASE_URL")
    args = ap.parse_args()

    levels = _levels()
    band_sql = ", ".join(f"'{b}'" for b in levels)
    engine = sa.create_engine(args.url)
    dialect = engine.dialect.name
    kpi = _origin_is_web()
    with engine.connect() as _boot:
        total = int(_rows(_boot, "SELECT count(*) FROM decision_events")[0][0])
    print("=" * 68)
    print(f"判断中枢 dev 预检 · 台账行数 {total} · 档位尺子 LEVELS={levels} · 方言 {dialect}")
    print("=" * 68)
    with engine.connect() as conn:
        # ── 0 台账行数：KPI 分母（剔除测试造数）+ 岗位构成 ────────────
        kpi_total = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE {kpi}")[0][0])
        comp = _rows(
            conn,
            "SELECT coalesce(source,'(空)'), count(*) FROM decision_events "
            f"WHERE {kpi} GROUP BY 1 ORDER BY 2 DESC",
        )
        print("0 台账行数(KPI)  :  %d 行（总 %d，剔除 origin='test' 造数 %d）" % (
            kpi_total, total, total - kpi_total))
        for r in comp:
            lab = _LABELS.get(str(r[0]), "其他/未分类")
            print(f"     {str(r[0]):14s} {lab:26s} {int(r[1]):5d}  {_pct(int(r[1]), kpi_total):5.1f}%")
        extra = [str(r[0]) for r in comp if str(r[0]) not in _LABELS]
        if extra:
            print(f"     ⚠ 未知岗位 {extra} —— 台账写入侧绕过了契约，先查是谁在写")

        # ── 1 五岗是否都有数据（接线体检，不是效果）──────────────────
        print("1 五岗接线      :")
        for key, label in [
            ("plan_gate", "判岗(ComplexityClassifier)"),
            ("skill_trigger", "技能岗(预激活)"),
            ("skill_intent", "意图岗(并入技能岗)"),
            ("tool_gate", "工具闸(v14 新岗)"),
            ("advisor", "改道岗(事中纠察)"),
            ("acceptance", "验收岗(收尾判官)"),
        ]:
            n = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE source='{key}'")[0][0])
            print(f"     {label:30s} {n:5d}")

        # ── 2 真判率（KPI 口径：模型真判 / 全部）─────────────────────
        llm_n = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE hit_layer='llm' AND {kpi}")[0][0])
        print(f"2 真判率(KPI)    :  {_pct(llm_n, kpi_total):5.1f}%  = {llm_n}/{kpi_total}"
              "   目标 >60%（一期）")

        # ── 3 损耗分布：熔断/超时/规则/解析失败/设计不判/失败 ────────
        keys = [
            ("熔断", "reason LIKE '%circuit_break%' OR hit_layer='circuit_break'"),
            ("超时", "reason LIKE '%超时%' OR hit_layer='timeout'"),
            ("解析失败", "reason LIKE '%无有效判断%' OR reason LIKE '%JSON 解析%' OR hit_layer='json_parse'"),
            ("模型调用失败", "reason LIKE '%调用失败%'"),
            ("规则兜底", "reason LIKE '%规则兜底%' OR hit_layer='rule_fallback'"),
            ("规则快判", "reason LIKE '%rule_fast%' OR hit_layer='rule_fast'"),
            ("规则(设计不判)", "reason LIKE '%不经判官%'"),
            ("判官给出判断", "reason LIKE '%判官判定%'"),
            ("事中改道", "hit_layer='advisory' OR source='advisor'"),
            ("判官关闭", "reason LIKE '%判官关闭%'"),
        ]
        print("3 损耗分布(KPI)  :")
        for label, where in keys:
            n = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE ({where}) AND {kpi}")[0][0])
            print(f"     {label:16s} {n:5d}  {_pct(n, kpi_total):5.1f}%")
        covered = sum(
            int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE ({w}) AND {kpi}")[0][0])
            for _, w in keys
        )
        print(f"     未归类(重叠后)  {kpi_total - covered:5d}")

        # ── 4 档位合法率（尺子=代码 LEVELS；读 complexity 列）────────
        pg_all = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE source='plan_gate'")[0][0])
        pg = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE source='plan_gate' AND {kpi}")[0][0])
        legal = int(_rows(
            conn,
            f"SELECT count(*) FROM decision_events WHERE source='plan_gate' AND {kpi} "
            f"AND lower(coalesce(complexity,'')) IN ({band_sql})",
        )[0][0])
        print(f"4 档位合法率      :  {_pct(legal, pg):5.1f}%  = {legal}/{pg}"
              f"   判岗行 {pg_all} 行（含测试造数）")
        band = _rows(
            conn,
            "SELECT coalesce(complexity,'(空)') b, count(*) FROM decision_events "
            f"WHERE source='plan_gate' AND {kpi} GROUP BY 1 ORDER BY 2 DESC",
        )
        for r in band:
            tag = "合法" if str(r[0]).lower() in [b.lower() for b in levels] else "非法/空"
            print(f"     {str(r[0]):22s} {int(r[1]):5d}  {tag}")
        dirty = _rows(
            conn,
            "SELECT coalesce(complexity,'(空)') b, count(*) FROM decision_events "
            f"WHERE source='plan_gate' AND coalesce(complexity,'')<>'' "
            f"AND lower(complexity) NOT IN ({band_sql}) GROUP BY 1 ORDER BY 2 DESC LIMIT 6",
        )
        if dirty:
            print(f"   脏带（含测试行，全量 {pg_all - pg} 行里的历史脏值）: {dirty}")

        # ── 5 Simple 占比（主判据：消耗/轮次；无表则只报占比）────────
        n_simple = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE source='plan_gate' AND {kpi} AND lower(coalesce(complexity,''))='simple'")[0][0])
        print(f"5 Simple 占比     :  {_pct(n_simple, pg):5.1f}%  = {n_simple}/{pg}")
        try:
            r = _rows(conn,
                      "SELECT count(*), coalesce(sum(iter_count),0), coalesce(sum(cost),0) FROM chat_runs")[0]
            print(f"   消耗/轮次(全 agent) : 轮次 {int(r[0])} · iter {int(r[1])} · 成本 {float(r[2]):.4f}"
                  " 元 · 每轮 iter %.2f · 每轮成本 %.4f 元" % (
                      (int(r[1]) / int(r[0]) if int(r[0]) else 0),
                      (float(r[2]) / int(r[0]) if int(r[0]) else 0)))
            print("   ⚠ chat_runs 无复杂度字段 → 按档位的消耗/轮次需 v13 批次1 的 complexity 落列")
        except Exception as exc:  # noqa: BLE001
            print(f"   消耗/轮次: 跳过（chat_runs: {type(exc).__name__}）")

        # ── 6 判官开销：真判的时延/成本 + 超时占预算 ────────────────
        r = _rows(conn,
                  "SELECT count(*), coalesce(avg(latency_ms),0), coalesce(avg(cost),0),"
                  " coalesce(avg(tokens),0) FROM decision_events WHERE hit_layer='llm'")[0]
        print(f"6 判官开销        :  真判 {int(r[0])} 行 · 平均 {int(r[1])}ms · 成本 {float(r[2]):.4f} 元"
              " · tokens %.0f" % float(r[3]))
        mx = int(_rows(conn,
                       "SELECT coalesce(max(latency_ms),0) FROM decision_events WHERE hit_layer='llm'")[0][0])
        print(f"   最慢真判 {mx}ms")
        lat = _rows(conn,
                    "SELECT coalesce(hit_layer,'(空)'), count(*), coalesce(avg(latency_ms),0),"
                    " coalesce(max(latency_ms),0) FROM decision_events GROUP BY 1 ORDER BY 3 DESC")
        print("   按层时延:")
        for x in lat:
            print(f"     {str(x[0]):14s} {int(x[1]):5d}  均 {int(x[2]):5d}ms  峰 {int(x[3]):6d}ms")

        # ── 7 缓存命中（rule_fast 是规则快判，与缓存层分开）─────────
        cache = int(_rows(conn, "SELECT count(*) FROM decision_events WHERE hit_layer='cache'")[0][0])
        rf = int(_rows(conn, "SELECT count(*) FROM decision_events WHERE hit_layer='rule_fast'")[0][0])
        print(f"7 缓存命中        :  缓存 {cache} 行 · 规则快判 {rf} 行 · 合计 {_pct(cache + rf, total):5.1f}%   目标 >30%（一期）")

        # ── 8 判官预算：单轮调用上限/熔断/超时（自适应）─────────────
        try:
            from coapis.decision.config import get_config

            cfg = get_config()
            print(f"8 判官预算        :  单轮上限 {cfg.judge_max_calls_per_turn} 次"
                  f" · 熔断 {cfg.breaker_failure_threshold} 连败/{cfg.breaker_cooldown_s:.0f}s 冷却"
                  f" · 硬超时 {cfg.llm_timeout_ms:.0f}ms(0=按模型自适应)"
                  f" · 软超时 {cfg.judge_soft_ms:.0f}ms · 事中每 {cfg.advisor_every_iters} iter 改道")
            for kind, ms in (("local", cfg.effective_timeout_ms("local")),
                             ("api", cfg.effective_timeout_ms("api"))):
                print(f"   {kind} 生效超时 {ms:.0f}ms · 事中单轮预算 {cfg.advisor_budget_ms:.0f}ms")
        except Exception as exc:  # noqa: BLE001
            print(f"8 判官预算        :  跳过（{type(exc).__name__}: {exc}）")

        # ── 9 台账卫生：身份/成本/闭环/档位（全部 KPI 口径）─────────
        n_nochat = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE coalesce(chat_id,'')='' AND {kpi}")[0][0])
        n_noturn = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE coalesce(turn,0)<=0 AND {kpi}")[0][0])
        n_noagent = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE coalesce(agent_id,'')='' AND {kpi}")[0][0])
        n_nocost = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE coalesce(cost,0)<=0 AND hit_layer='llm' AND {kpi}")[0][0])
        n_llm = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE hit_layer='llm' AND {kpi}")[0][0])
        n_out = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE source='plan_gate' AND {kpi}")[0][0])
        n_closed = int(_rows(conn, f"SELECT count(*) FROM decision_events WHERE source='plan_gate' AND {kpi} AND coalesce(outcome,'pending')<>'pending'")[0][0])
        print(f"9 台账卫生(KPI)   :  无 chat_id {n_nochat} · 无 turn {n_noturn} · 无 agent {n_noagent}"
              f" · llm 行成本 0 {n_nocost}/{n_llm}")
        print(f"   plan_gate 闭环:  {n_closed}/{n_out} 行 outcome 非 pending")
        print(f"   成本 0 占比    :  {_pct(n_nocost, n_llm):5.1f}%")

        # ── 10 意图岗判率（并岗后应为 0；0 = 省下一次调用）──────────
        n_intent = int(_rows(conn, "SELECT count(*) FROM decision_events WHERE source='skill_intent'")[0][0])
        n_ig = int(_rows(conn, "SELECT count(*) FROM decision_events WHERE source='skill_intent' AND hit_layer='llm'")[0][0])
        print(f"10 意图岗判率      :  真判 {_pct(n_ig, n_intent):5.1f}%  = {n_ig}/{n_intent}   一期目标 0%（并岗）")

        # ── 11 判岗输出落档情况（真判行里 band/effort/verb 各占多少）─
        raw = [str(r[0]) for r in _rows(
            conn,
            f"SELECT coalesce(action,'(空)') FROM decision_events WHERE hit_layer='llm' AND {kpi} LIMIT 1000",
        )]
        verbs = Counter(x.split(":", 1)[0].strip() or "(空)" for x in raw)
        eff = Counter()
        for x in raw:
            for e in ("light", "standard", "deep"):
                if f"thinking:{e}" in x:
                    eff[e] += 1
                    break
        has_verb = sum(v for k, v in verbs.items() if k in ("read", "write", "analyze", "create"))
        print(f"11 判岗落档(真判)  :  {len(raw)} 行里 effort 标注 {sum(eff.values())} 行 · verb 标注 {has_verb} 行")
        for k, v in eff.most_common():
            print(f"     effort {k:10s} {v:4d}")
        for k, v in verbs.most_common(6):
            print(f"     action 前缀 {k:18s} {v:4d}")
        if has_verb == 0:
            print("     ⚠ verb 未落台账（v13 批次4 待做）——指标只报事实，不粉饰")

        # ── 12 advisor（改道岗）：有没有数据、有多少是建议 ──────────
        n_adv = int(_rows(conn, "SELECT count(*) FROM decision_events WHERE hit_layer='advisory' OR action LIKE 'advisor:%'")[0][0])
        n_advice = int(_rows(conn, "SELECT count(*) FROM decision_events WHERE action LIKE 'advisor:advice:%'")[0][0])
        n_block = int(_rows(conn, "SELECT count(*) FROM decision_events WHERE action LIKE 'advisor:block:%'")[0][0])
        print(f"12 advisor         :  {n_adv} 行（advice {n_advice} / block {n_block}）")

        print("=" * 68)
    engine.dispose()


if __name__ == "__main__":
    main()
