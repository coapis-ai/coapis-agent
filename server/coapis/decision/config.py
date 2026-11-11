# -*- coding: utf-8 -*-
"""判断中枢配置（v13 第 15 章 D5：判据不入库，这里只有开关与阈值）。

来源优先级：**智能体 running_config.decision_hub > 环境变量 > 默认值**
（与既有配置优先级约定一致）。

开关粒度：一个总开关 ``enabled`` + 每岗位一个开关。一期只接了技能触发与
计划闸门两个岗位，岗位开关就是「一键关闭回到今天」的落点。
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

#: 探针超时 vs 岗位软阈值口径分裂只告警一次（配置装载很频繁）。
_PROBE_SOFT_WARNED = False

ENV_PREFIX = "COAPIS_DECISION_"

#: 接入的岗位（岗位开关 = 总开关之下的细粒度闸门）
#:
#: ``acceptance``（v14 §3.5 环4/5 验收回灌）与 ``advisor``（v14 §3.4 环1
#: 事中改道）是判断中枢补上的两个岗位：它们的判断对象是**整轮任务**，
#: 不是轮里的某一条消息，所以除岗位开关外还受 ``judge_hub`` 的预算闸门管。
POSTS = (
    "intent",
    "skill_trigger",
    "plan_gate",
    "plan_review",
    "tool_gate",
    "tool_guard",
    "verify",
    "context",
    "acceptance",
    "advisor",
)

DEFAULTS = {
    "enabled": True,
    "ledger_enabled": True,
    "cache_enabled": True,
    "breaker_enabled": True,
    "cache_ttl_s": 300.0,
    "cache_max_entries": 512,
    "breaker_failure_threshold": 5,
    "breaker_cooldown_s": 60.0,
    "breaker_cooldown_floor_s": 1.0,
    # v19 P0-3：探针超时必须 ≥ 最慢岗位的判断软阈值（技能岗 12s）。探针 3s 就
    # 判失败=「判官还在正常判，熔断先把它判死」，半开永远合不上；自检会直说。
    "breaker_probe_timeout_s": 15.0,
    "breaker_probe_max_in_flight": 1,
    "breaker_window_seconds": 60.0,
    "breaker_half_open_cooldown_s": 60.0,
    # v19 P0-2 ①：连续**软超时**几次才按失败触发熔断。软阈值到点=主链等不起，
    # 判官还在跑，不是判官坏——单次软超时不记失败；连续到这个数才冷却。
    "breaker_soft_streak": 5,
    "budget_total_seconds": 600.0,
    "max_call_budget_s": 300.0,
    # 判断模型要跑在"会话激活模型"上；推理型模型（Q3 这类）光思考就要
    # 几百 token、两三秒，1.5s/60token 的预算等于"判官必败、静默退回规则"。
    # ``0`` = 按链路自适应（本地取 ``llm_timeout_ms_local``，远端 API 取
    # ``llm_timeout_ms_api``）：判官是同步调用，本地 vLLM 跑思考模型实测
    # 5~15 秒，固定 3000ms 对本地链路必然全灭（台账 timeout 层的真因）。
    "llm_timeout_ms": 0.0,
    "llm_timeout_ms_local": 8000.0,
    "llm_timeout_ms_api": 5000.0,
    # 判官固定模型槽：两者都非空时判官固定用该模型（建议轻量非思考模型），
    # 任一为空则回落"会话激活模型"链——会话模型差，判官跟着差。
    "judge_provider_id": "",
    "judge_model": "",
    "llm_max_tokens": 512,
    # 每轮判官 LLM 调用上限（v14 §4.1 第 4 条）。判官是辅助判断，
    # 一轮里判档 + 技能触发 + 验收加起来就该封顶，不能把整轮预算
    # 吃在判断上——这是"重复/循环判断"的根治闸门。
    # 判档 1 次 + 事中改道 1 次 + 收尾验收 1 次 = 3。低于 3 时后到的岗位
    # 只会记下 budget_cap 台账（可见但不生效），等于关掉改道与验收。
    "judge_max_calls_per_turn": 7,
    # v15 §M2 软超时：**全局兜底值**（毫秒）。主链最多等判官这么久，超时
    # 先返回降级、判官后台跑完补写台账。
    # v19 P2-2：2000 → 5000。判官 p50=5997ms、91% 超过 2000ms——拿 2 秒的
    # 尺子量它，主链几乎每次都先走、判官永远"迟到"。真正的口径按岗位取
    # （judge_soft_ms_post），唯一入口 soft_ms_for()。
    "judge_soft_ms": 5000.0,
    # v19 P1-2（D4 拍板）：**按岗位**的软阈值（毫秒），一把尺子量五岗是
    # 真判率 30% 的成因之一。口径：有消费者在等的岗位吃小预算（判档在计划
    # 生成前，4s）；幕后岗吃大预算（技能触发/工具闸/验收在整轮里，6-12s）。
    # 台账里的 timeout 行因此是"按岗位预算的诚实结果"，不是被 2s 统一绞杀。
    "judge_soft_ms_post": {
        "plan_gate": 4000.0,
        "plan_review": 4000.0,
        "skill_trigger": 6000.0,
        "tool_gate": 6000.0,
        "tool_guard": 6000.0,
        "advisor": 6000.0,
        "acceptance": 12000.0,
    },
    # 验收岗单独的软阈值（毫秒）。验收在整轮交付跑完才触发，是**幕后岗**——
    # 没有任何人等它的结论。拿主链那 4 秒量它，等于让唯一能判交付的岗位恒
    # 弃权；验收 verdict 是判档行 outcome 的唯一来源，弃权 = 闭环 0 行
    # （dev 实测 182 行台账 180 行停在 pending 的直接成因）。
    "judge_soft_ms_acceptance": 12000.0,
    # 预算分池（v14 §4.3）：一轮 7 格判官额度原先是五岗抢一个池——tool_gate
    # 一次工具调用抢一格，池吃光后判档岗与验收岗全数落 budget_cap
    # （dev 实测 budget_cap 38 行：plan_gate 21 / tool_gate 9 / acceptance 4）。
    # 验收是闭环的回执岗，它抢不到预算，判档行就永远对不上账（闭环 5/39）；
    # 判档岗抢不到，档位只能靠规则兜底。故验收按岗位预留，其余四岗共享余额，
    # 且每岗位各有上限——抢池这件事不该由台账来兜。
    "judge_reserve_acceptance": 2,
    # 每岗位每轮上限（tool_gate 天生调用多，靠它把单轮调用次数压下来）。
    "judge_post_limit_default": 2,
    "judge_post_limits": {
        "plan_gate": 2,
        "skill_trigger": 2,
        "tool_gate": 2,
        "advisor": 2,
        "acceptance": 2,
    },
    # 判官默认关思考（v14 D1）：判断要的是结论，不是推理过程。
    "judge_thinking_enabled": False,
    # v19 P2-3 审计位：技能清单被改动时记一条治理台账（谁在什么时候把哪个
    # 技能启用/停用/保存/删除）。技能清单决定"哪些技能会进每轮提示"，现在
    # 人人可改且零审计——改一次，触发行为变了，台账上什么痕迹都没有。
    "skill_gate_audit": True,
    # v19 P2-2 门槛配置化：技能触发 Tier2（写死关键词表）是否参与打分。
    # 这张表是触发链里唯一没人能维护的部分（50+ 条指向池外技能）。
    "skill_tier2_enabled": True,
    # v19 P2-2 门槛配置化：无命中兜底最多注入几个技能名（装载层会灌全文）。
    "skill_fallback_cap": 1,
    # ── 判官设置项 API 的两处配置位（v14 §5.2）─────────────────────
    # 事中改道：每 N 个迭代让判官插话一次；**0 = 关闭事中改道**。
    "advisor_every_iters": 6,
    # 前 N 个迭代不判改道：动作太少，判了也看不出来，只产噪声台账。
    "advisor_min_iters": 3,
    # 验收喂给判官的交付文本上限（字）。交付越长越贵，摘要足够判。
    "acceptance_max_chars": 4000,
    # ── 自检验收（v27 · 拍板 D3）──────────────────────────────────
    # dev 七天台账：验收 0 行真判、outcome 全票 pending——判官岗位离线时，
    # 「本轮算不算交付」这件事在台账里是空白。自检验收补这块空白：让**本轮的
    # 主模型**按同一张验收清单自评，结论只进台账 + 回填档位，不改回答、不拦
    # 动作、不加动作。自评不是判官，别拿它当外部验收用（自己给自己打分，
    # 只能看趋势，不能当闸）。false = 整条熄火。
    "selfcheck_enabled": True,
    # 自评在轮尾后台跑，不占主链时间、不占判官轮内预算，所以用独立尺子：
    # 会话模型调用超过这个毫秒数就放弃这一判（宁缺不拖）。
    "selfcheck_timeout_ms": 20000,
    # 回答短于这个字数不自评：寒暄/确认类交付判了只产垃圾行。
    "selfcheck_min_answer_chars": 80,
    # 预算豁免轮数：前 N 轮不吃思考预算降级。
    "budget_exempt_turns": 5,
    # 台账保留天数：判断日志只进台账、不进记忆管道，因此**必须**有出口，
    # 否则详单表无限增长。总线在写入时顺带清掉超期的行。
    "ledger_retention_days": 90,
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


def _as_str(val: Any, default: str) -> str:
    """字符串项归一化。

    模型槽（``judge_provider_id``/``judge_model``）是字符串——以前没有
    字符串分支，非数值配置一律被 ``_as_float`` 吞回默认值，判官固定模型槽
    会永远读成空（等于该功能恒不生效）。
    """
    if val is None:
        return default
    if isinstance(val, str):
        return val.strip()
    return str(val).strip()


#: 管理端可用的短名键（写盘时按原样保留，读取时收敛成全名）。
HUB_KEY_ALIASES = frozenset({"timeout_ms", "max_calls_per_turn", "advisor_enabled"})


def normalize_hub_keys(raw: Any) -> dict:
    """把管理端短名收敛成中枢全名（键名只在这一处映射）。

    管理端与既有接口习惯用短名（``timeout_ms`` / ``max_calls_per_turn`` /
    ``advisor_enabled``），中枢内部用带岗位前缀的全名。两处各写一套键名
    迟早对不上，所以映射只留这一份：配置写入、读取校验、路由过滤都调它。

    只在短名出现且对应全名缺席时生效，避免同一份配置里两个键名互相覆盖。
    """
    out = dict(raw or {})
    for alias, full in (
        ("timeout_ms", "llm_timeout_ms"),
        ("max_calls_per_turn", "judge_max_calls_per_turn"),
    ):
        if alias in out and full not in out:
            out[full] = out[alias]
    if "advisor_enabled" in out and "advisor_every_iters" not in out:
        out["advisor_every_iters"] = (
            int(DEFAULTS["advisor_every_iters"])
            if _as_bool(out["advisor_enabled"], True)
            else 0
        )
    return out


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
    breaker_failure_threshold: int = 5
    breaker_cooldown_s: float = 60.0
    breaker_cooldown_floor_s: float = 1.0
    # 熔断探测与统计窗口。缺这三件时熔断只有"打开→冷却→全开"，没有任何一次
    # 受控探测来判断模型是否恢复；窗口缺失时失败计数永不清零，偶发的历史失败
    # 会让熔断被反复误触发。半开冷却必须大于探针超时，否则上次探测还在飞、
    # 下一颗请求又放行，探测并发失控。
    # v19 P0-3：探针超时必须 **≥ 最慢岗位的软阈值**（技能岗 12s）——探针 3s 就
    # 判失败等于"判官还在正常判，熔断先把它判死"，半开永远合不上（自检会直说）。
    breaker_probe_timeout_s: float = 15.0
    breaker_probe_max_in_flight: int = 1
    breaker_window_seconds: float = 60.0
    breaker_half_open_cooldown_s: float = 60.0
    # v19 P0-2 ①：连续软超时达到这个次数才按失败触发岗位熔断（软超时本身
    # 是中性事件——判官还在跑，主链只是等不起）。真判成功即清零。
    breaker_soft_streak: int = 5
    # 整轮判断预算池与单次调用硬上限：池总量必须容得下单次上限，否则一次调用
    # 就能把整轮额度吃空，后续判断岗位全部直接判死。
    budget_total_seconds: float = 600.0
    max_call_budget_s: float = 300.0
    llm_timeout_ms: float = 0.0
    llm_timeout_ms_local: float = 8000.0
    llm_timeout_ms_api: float = 5000.0
    # 判断模型的输出预算。推理型模型（Q3 这类）先思考后作答，
    # 60 token 连思考都出不完，判官必败、静默退回规则层。
    llm_max_tokens: int = 512
    ledger_retention_days: int = 90

    # -------------------------------------------------------------- #
    # 管理端契约别名（v14 §5.2）
    #
    # 中枢内部统一用带岗位前缀的全名（llm_timeout_ms /
    # judge_max_calls_per_turn / advisor_every_iters）；管理端与既有接口
    # 习惯用短名下发布。键名只在 from_dict 一处收敛，两处各写一套迟早对不上。
    # -------------------------------------------------------------- #
    @property
    def timeout_ms(self) -> float:
        """整次判断的毫秒预算（API 契约名，与 llm_timeout_ms 同值）。"""
        return self.llm_timeout_ms

    @property
    def max_calls_per_turn(self) -> int:
        """单轮判断调用上限（API 契约名）。"""
        return self.judge_max_calls_per_turn

    def effective_timeout_ms(self, is_local: bool) -> float:
        """按链路类型取本次判断的毫秒预算（F1 自适应超时）。

        ``llm_timeout_ms > 0`` 视为人工显式指定，最高优先；``0`` 时本地链路
        取 ``llm_timeout_ms_local``，远端 API 取 ``llm_timeout_ms_api``。
        """
        fixed = float(self.llm_timeout_ms)
        if fixed > 0:
            return fixed
        return float(
            self.llm_timeout_ms_local if is_local else self.llm_timeout_ms_api,
        )

    def soft_ms_for(self, purpose: str) -> float:
        """取某个岗位的**软阈值**（主链为这一判最多等多久）。

        口径（v19 P1-2 拍板）：
        - ``acceptance``（验收）吃 ``judge_soft_ms_acceptance``——它是幕后岗，
          没有任何人等它的结论，拿主链预算量它 = 把闭环判成恒弃权。
        - 其余岗位吃 ``judge_soft_ms_post`` 表里的值，表里没写的岗位
          （以及空表）回落全局 ``judge_soft_ms``。
        - 硬超时（``effective_timeout_ms``）不受影响，它是"这一判最多活
          多久"的保险丝；软阈值只管"主链等多久就先走、判官后台补判"。
        """
        key = str(purpose or "").strip()
        if key == "acceptance":
            val = float(self.judge_soft_ms_acceptance)
        else:
            table = self.judge_soft_ms_post or {}
            raw = table.get(key)
            global_ms = float(self.judge_soft_ms)
            if raw is None:
                val = global_ms
            else:
                # **全局值是主链等待上限**（小蜜蜂 2026-11-04 定案：主链一句话
                # 等 4 秒不可接受）：岗位表只能在这个上限内**收紧**某个岗位，
                # 不能放宽。要更宽预算的只有幕后岗（验收），它走
                # judge_soft_ms_acceptance 这条独立通道。
                val = min(float(raw), global_ms)
        return min(max(val, 200.0), 20000.0)

    @property
    def advisor_enabled(self) -> bool:
        """事中改道是否开启（API 契约名 = 每 N 轮复核，N>0 即开启）。"""
        return self.advisor_every_iters > 0

    # 每轮判官 LLM 调用上限。判档 + 技能触发 + 验收加起来就该封顶，
    # 不能把整轮预算吃在判断上——这是"重复/循环判断"的根治闸门。
    judge_max_calls_per_turn: int = 7
    # v14 §批次3 软超时（毫秒）：**全局兜底值**（岗位口径见
    # judge_soft_ms_post / soft_ms_for）。超过即主链先返回降级、判官后台
    # 跑完补写台账；硬超时 effective_timeout_ms 退居保险丝。
    judge_soft_ms: float = 5000.0
    # 验收岗单独的软阈值（毫秒）。验收是幕后岗：整轮交付跑完才触发，
    # 没有任何消费者在等它的结论，所以不该吃主链那 4 秒的预算。
    # 它的 verdict 是判档行 outcome 的唯一来源——验收弃权 = 闭环恒 0。
    judge_soft_ms_acceptance: float = 12000.0
    # v19 P1-2：**按岗位**软阈值表（毫秒）。一把 2 秒的尺子量七岗是"真判率
    # 被绞肉机绞掉"的成因：判档岗在计划生成前（有人在等），技能/工具/改道/
    # 验收在整轮里（幕后）。**必须是数据类字段**——只写进 DEFAULTS 时
    # ``from_dict`` 把它当 kwargs 传给 ``cls(...)``，构造直接 TypeError，
    # 整个中枢配置读取链崩（2026-11-07 实测复现）。
    judge_soft_ms_post: dict = field(
        default_factory=lambda: dict(DEFAULTS["judge_soft_ms_post"]),
    )
    # 预算分池（v14 §4.3）：验收岗每轮预留额度 + 每岗位每轮上限。
    # 依据：dev 实测 budget_cap 38 行（plan_gate 21 / tool_gate 9 / acceptance 4）
    # ——五岗抢一个 7 格池，抢不到预算的恰是要把闭环合上的那两个岗。
    judge_reserve_acceptance: int = 2
    judge_post_limit_default: int = 2
    judge_post_limits: dict = field(
        default_factory=lambda: dict(DEFAULTS["judge_post_limits"]),
    )
    judge_provider_id: str = ""
    judge_model: str = ""
    # 判官是否开思考（默认关）。推理型模型一开思考，光思考就吃掉
    # 大几百 token，判断这种"要一个字母结论"的调用纯属浪费。
    judge_thinking_enabled: bool = False
    # v19 P2-3 审计位：技能清单被改动（建/改/删/启用/停用/保存）时记一条
    # 治理台账。技能清单决定"哪些技能会进每轮提示"，改动零审计 = 触发行为
    # 变了没有任何痕迹可对账。
    skill_gate_audit: bool = True
    # v19 P2-2 门槛：Tier2 写死关键词表是否参与技能打分（默认开）。
    skill_tier2_enabled: bool = True
    # v19 P2-2 门槛：无命中兜底最多注入几个技能名（装载层灌全文，1=最省）。
    skill_fallback_cap: int = 1

    # ── 判官设置项 API 的两处配置位（v14 §5.2）─────────────────────
    # 事中改道：每 N 个迭代让判官插话一次；**0 = 关闭事中改道**。
    advisor_every_iters: int = 6
    advisor_min_iters: int = 3
    acceptance_max_chars: int = 4000
    # 自检验收（v27 · 拍板 D3）——见 DEFAULTS 同名字段的注释。
    selfcheck_enabled: bool = True
    selfcheck_timeout_ms: int = 20000
    selfcheck_min_answer_chars: int = 80
    # v19 P2-2 接线（消费点：decision/gateway.py 轮内池子闸）：启动期前 N 轮，
    # 每个岗位**本轮第一格**判断不吃轮内池子闸——判档/计划门禁/计划审查/技能触发
    # 全落在前几轮，池子默认 6 格，工具门禁一多就把启动期判断整批砍掉
    # （实测 budget_cap 落点大半在 turn=0/1：任务从第一步就没判断）。
    # 同一岗位本轮第二次起照旧受闸（防打转的初衷不让），0 = 关闭这个口子。
    budget_exempt_turns: int = 5

    posts: dict = field(default_factory=dict)

    # ---- 构造 ----

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "DecisionHubConfig":
        """从智能体 running_config 的 decision_hub 段构造，并叠加 env 覆盖。

        优先级：智能体配置 > 环境变量 > 默认值。
        """
        raw = normalize_hub_keys(raw)
        merged: dict[str, Any] = {}
        for key, default in DEFAULTS.items():
            env_name = key.upper()
            # 优先级：智能体配置 > 环境变量 > 默认值
            val = raw.get(key)
            if val is None:
                val = _env(env_name)
            if val is None:
                val = default
            if isinstance(default, dict):
                # 表型配置（v14 §4.3 岗位上限表 / v19 P1-2 按岗位软阈值）。
                # 值类型跟着默认值走：整数表夹整数，浮点表夹浮点——原先
                # 一律 ``_as_int`` 会把 4000.0ms 的软阈值压成 4000 再按
                # "岗位上限"语义处理，缺项还回落到 ``judge_post_limit_default``
                # 这个八竿子打不着的默认值。
                got = val if isinstance(val, dict) else {}
                dvals = dict(default)
                is_float_table = all(isinstance(dv, float) for dv in dvals.values())
                floor = 200.0 if is_float_table else 0
                table: dict[str, Any] = {}
                for name, dv in dvals.items():
                    raw_v = got.get(name, dv)
                    table[name] = (
                        max(_as_float(raw_v, float(dv)), floor)
                        if is_float_table
                        else max(_as_int(raw_v, int(dv)), floor)
                    )
                for name, v in got.items():
                    if name not in table:
                        table[name] = (
                            max(_as_float(v, float(cls.judge_soft_ms)), floor)
                            if is_float_table
                            else max(
                                _as_int(v, int(DEFAULTS["judge_post_limit_default"])),
                                floor,
                            )
                        )
                merged[key] = table
            elif isinstance(default, bool):
                merged[key] = _as_bool(val, default)
            elif isinstance(default, int):
                merged[key] = _as_int(val, default)
            elif isinstance(default, str):
                merged[key] = _as_str(val, default)
            else:
                merged[key] = _as_float(val, default)
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
        # 熔断三件新参数同样夹取：探针超时写 0 等于永久放行探测，写 600 等于
        # 每次探测都拖满整轮预算；半开冷却小于探针超时时，上一次探测还在飞
        # 下一颗就放行，探测并发会失控 → 冷却下限锁探针超时。
        self.breaker_probe_timeout_s = min(
            max(float(self.breaker_probe_timeout_s), 0.2), 30.0,
        )
        self.breaker_probe_max_in_flight = min(
            max(int(self.breaker_probe_max_in_flight), 1), 16,
        )
        self.breaker_window_seconds = min(
            max(float(self.breaker_window_seconds), 5.0), 3600.0,
        )
        self.breaker_half_open_cooldown_s = min(
            max(float(self.breaker_half_open_cooldown_s), self.breaker_probe_timeout_s),
            3600.0,
        )
        self.breaker_soft_streak = min(max(int(self.breaker_soft_streak), 1), 50)
        # v19 P2-2 校验：**探针超时必须量得住最宽的岗位软阈值**，否则半开探测
        # 必然"超时失败"→ 熔断永远合不上（判官明明能用也被长期排除）。
        # 口径分裂时只告警不改数：自动抬探针超时会把主链的等待窗口一起撑大，
        # 那是行为决策，不是夹取，必须由配置的人知道。
        try:
            _soft_max = max(
                [float(self.judge_soft_ms), float(self.judge_soft_ms_acceptance)]
                + [float(v) for v in (self.judge_soft_ms_post or {}).values()]
            )
            if float(self.breaker_probe_timeout_s) * 1000.0 < _soft_max:
                # 只说一次：配置装载很频繁（每次判断都读），每条都喊会淹掉日志。
                global _PROBE_SOFT_WARNED
                if not _PROBE_SOFT_WARNED:
                    _PROBE_SOFT_WARNED = True
                    logger.warning(
                        "[决策中枢] 配置口径分裂：熔断探针超时 %.1fs 小于最大岗位"
                        "软阈值 %.1fs——半开探测会在判官正常判完之前判它失败，"
                        "熔断合不上。建议 BREAKER_PROBE_TIMEOUT_S >= %.1f",
                        float(self.breaker_probe_timeout_s),
                        _soft_max / 1000.0,
                        _soft_max / 1000.0,
                    )
        except Exception:  # noqa: BLE001 - 校验本身绝不阻断配置装载
            logger.debug("[决策中枢] 软阈值校验跳过", exc_info=True)
        # 整轮硬墙必须容得下单次调用上限，否则一次调用就能把整轮预算吃空；
        # 夹取顺序：先把单次上限压进整轮额度内，再夹整轮额度本身。
        self.max_call_budget_s = min(
            max(float(self.max_call_budget_s), 1.0),
            max(float(self.budget_total_seconds), 1.0),
        )
        self.budget_total_seconds = min(
            max(float(self.budget_total_seconds), self.max_call_budget_s),
            7200.0,
        )
        self.llm_timeout_ms = min(max(float(self.llm_timeout_ms), 0.0), 20000.0)
        self.llm_timeout_ms_local = min(max(float(self.llm_timeout_ms_local), 200.0), 20000.0)
        self.llm_timeout_ms_api = min(max(float(self.llm_timeout_ms_api), 200.0), 20000.0)
        self.llm_max_tokens = min(max(int(self.llm_max_tokens), 64), 4096)
        self.judge_soft_ms = min(max(float(self.judge_soft_ms), 200.0), 20000.0)
        # 验收在幕后，允许比主链阈值更长；下限不得低于主链阈值，否则
        # "给验收松绑"这件事被一个手滑的配置值悄悄撤销。
        self.judge_soft_ms_acceptance = min(
            max(float(self.judge_soft_ms_acceptance), self.judge_soft_ms),
            20000.0,
        )
        # 按岗位软阈值（v19 P1-2）：逐岗位夹进 [200ms, 20s]，非数值项丢掉，
        # 空表由 soft_ms_for 回落全局阈值。验收阈值只放宽不收紧（幕后岗）。
        _soft_table: dict[str, float] = {}
        for _k, _v in dict(self.judge_soft_ms_post or {}).items():
            try:
                _fv = float(_v)
            except (TypeError, ValueError):
                continue
            _soft_table[str(_k).strip()] = min(max(_fv, 200.0), 20000.0)
        _soft_table["acceptance"] = min(
            max(
                float(_soft_table.get("acceptance", self.judge_soft_ms_acceptance)),
                self.judge_soft_ms_acceptance,
            ),
            20000.0,
        )
        self.judge_soft_ms_post = _soft_table
        self.judge_max_calls_per_turn = min(
            max(int(self.judge_max_calls_per_turn), 1), 8,
        )
        # 兜底技能条数（v19 P2-2 门槛配置化）：0 允许（完全不注入），上限 10
        # 防止回到"灌一桌菜"——每个兜底技能都会被装载层灌进每轮提示。
        self.skill_fallback_cap = min(max(int(self.skill_fallback_cap), 0), 10)
        # 预算分池（v14 §4.3）：验收预留不能吃满全局额度（吃满了其余四岗就
        # 永远抢不到），每岗位上限非负、封顶 8（与全局同量级，0=该岗不限）。
        self.judge_reserve_acceptance = min(
            max(int(self.judge_reserve_acceptance), 0),
            max(int(self.judge_max_calls_per_turn) - 1, 0),
        )
        self.judge_post_limit_default = min(max(int(self.judge_post_limit_default), 0), 8)
        self.judge_post_limits = {
            str(k): min(max(int(v), 0), 8)
            for k, v in dict(self.judge_post_limits).items()
        }
        self.advisor_every_iters = min(max(int(self.advisor_every_iters), 0), 64)
        self.advisor_min_iters = min(max(int(self.advisor_min_iters), 1), 32)
        self.acceptance_max_chars = min(
            max(int(self.acceptance_max_chars), 500), 40000,
        )
        # 自评尺子夹取（v27 · 拍板 D3）：低于 2s 的自评基本判不出东西（模型还
        # 没开始想就超时），高于 60s 会在轮尾拖出一长串后台调用。宁缺不拖。
        self.selfcheck_timeout_ms = min(
            max(int(self.selfcheck_timeout_ms), 2000), 60000,
        )
        self.selfcheck_min_answer_chars = min(
            max(int(self.selfcheck_min_answer_chars), 20), 2000,
        )
        self.budget_exempt_turns = min(max(int(self.budget_exempt_turns), 0), 64)
        # 保留期下限 7 天：低于一周的判断日志撑不住复盘校准岗的对照。
        self.ledger_retention_days = min(max(int(self.ledger_retention_days), 7), 3650)
        return self

    @classmethod
    def known_keys(cls) -> list[str]:
        """配置段里被认识的键名——配置 API 只收这些，防止死字段再生。"""
        return [f.name for f in fields(cls)]

    def full_view(self) -> dict[str, Any]:
        """全字段视图（落盘与管理页读取用）。

        与 :meth:`as_dict` 的区别：这里不换算单位、不改名，读写同名，
        落盘再读回不会丢值；页面要显示"当前生效的每一项"也用这个。
        """
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def as_dict(self) -> dict[str, Any]:
        """判官设置项 API 的字典视图（v14 §5.2 的契约字段名）。

        字段名按 API 契约拼：``max_calls_per_turn`` 是本类
        ``judge_max_calls_per_turn`` 的契约名，``timeout_s`` 由
        ``llm_timeout_ms`` 换算成秒。其余同名直出。
        """
        return {
            "enabled": bool(self.enabled),
            "max_calls_per_turn": int(self.judge_max_calls_per_turn),
            "advisor_every_iters": int(self.advisor_every_iters),
            "advisor_min_iters": int(self.advisor_min_iters),
            "acceptance_max_chars": int(self.acceptance_max_chars),
            "selfcheck_enabled": bool(self.selfcheck_enabled),
            "selfcheck_timeout_ms": int(self.selfcheck_timeout_ms),
            "selfcheck_min_answer_chars": int(self.selfcheck_min_answer_chars),
            "timeout_s": float(self.llm_timeout_ms) / 1000.0,
            "timeout_ms_local": float(self.llm_timeout_ms_local),
            "timeout_ms_api": float(self.llm_timeout_ms_api),
            "judge_provider_id": str(self.judge_provider_id),
            "judge_model": str(self.judge_model),
            "budget_exempt_turns": int(self.budget_exempt_turns),
        }

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


# ---------------------------------------------------------------------
# 进程内单例配置（改了环境变量要重启才生效，与其余部件一致）
# ---------------------------------------------------------------------

_hub_cache: "DecisionHubConfig | None" = None
_merged_cache: "dict[tuple, DecisionHubConfig]" = {}

#: 管理页落盘的配置段多久重读一次（秒）。写入口会主动失效，这里只是兜底。
_SAVED_TTL_SECONDS = 30.0
_saved_cache: dict[str, Any] = {"at": 0.0, "data": {}}


def hub_config_path() -> Path:
    """管理页保存的中枢配置落盘位置（部署级单一真相）。"""
    from ..constant import WORKING_DIR

    return Path(WORKING_DIR) / "config" / "decision_hub.json"


def saved_hub_section() -> dict[str, Any]:
    """读管理页已保存的配置段。文件缺失、损坏一律当空，不影响主流程。"""
    now = time.monotonic()
    if _saved_cache["data"] is not None and (now - _saved_cache["at"]) < _SAVED_TTL_SECONDS:
        return _saved_cache["data"]
    data: dict[str, Any] = {}
    try:
        path = hub_config_path()
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, Mapping):
                data = dict(raw)
    except Exception:  # 配置读不到就退回环境变量，绝不把对话带崩
        data = {}
    _saved_cache["at"] = now
    _saved_cache["data"] = data
    return data


def save_hub_section(patch: Mapping[str, Any]) -> DecisionHubConfig:
    """管理页保存入口：别名归一 → 夹取 → 落盘 → 立刻生效。

    只写一个文件、只认一份真相；写盘用全字段视图（读写同名，不换算单位），
    因此"写进去的"和"读出来的"永远一致。
    """
    accepted = normalize_hub_keys(patch)
    merged = {k: v for k, v in saved_hub_section().items() if k not in accepted}
    merged.update(accepted)
    cfg = DecisionHubConfig.from_dict(merged).normalized()
    cfg = DecisionHubConfig.from_dict(cfg.full_view()).normalized()

    path = hub_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(json.dumps(cfg.full_view(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    reset_hub_config()
    return cfg


def get_hub_config() -> "DecisionHubConfig":
    """当前生效的中枢配置：**管理页保存值 > 环境变量 > 默认值**，进程内缓存。

    环境变量是出厂值，管理页保存的值压在它上面。页面写完会调用
    :func:`reset_hub_config`，因此「页面改了立刻生效」不需要重启。
    """
    global _hub_cache
    if _hub_cache is None:
        cfg = DecisionHubConfig.from_env().normalized()
        saved = saved_hub_section()
        if saved:
            cfg = DecisionHubConfig.from_dict(
                {**cfg.full_view(), **normalize_hub_keys(saved)}
            ).normalized()
        _hub_cache = cfg
    return _hub_cache


def _saved_file_section_safe() -> dict:
    """读数据根 ``config/decision_hub.json``（管理台保存的那份），失败给空。

    优先级：智能体段 > 环境变量 > 这份文件 > 默认值。界面改了预算要能
    真的落到判官身上，运行时就必须读它（带 5 秒缓存，改配置不必重启）。
    """
    try:
        sec = saved_hub_section()
        return dict(sec) if isinstance(sec, Mapping) else {}
    except Exception:  # 读不到就退回原有优先级，绝不影响启动
        return {}


def merge_hub_config(raw: Mapping[str, Any] | None) -> "DecisionHubConfig":
    """智能体 ``decision_hub`` 段叠加在 env 配置之上，**进程内缓存**。

    优先级仍是「智能体配置 > 环境变量 > 默认值」（复用 :meth:`from_dict`），
    这里只是把结果按配置内容缓存起来：判断中枢每轮都会取配置，
    不能每次都重新解析一遍（v14 §4.1 第 2 条）。改了环境变量要重启才生效。
    """
    file_sec = _saved_file_section_safe()
    key = tuple(sorted(
        (str(k), str(v)) for k, v in {**file_sec, **(raw or {})}.items()
    ))
    cfg = _merged_cache.get(key)
    if cfg is None:
        cfg = DecisionHubConfig.from_dict({**file_sec, **(raw or {})}).normalized()
        _merged_cache[key] = cfg
    return cfg


def reset_hub_config() -> None:
    """清空配置缓存（管理页保存后、测试用）。"""
    global _hub_cache
    _hub_cache = None
    _merged_cache.clear()
    _saved_cache["data"] = None
    _saved_cache["at"] = 0.0


__all__ = [
    "DecisionHubConfig",
    "POSTS",
    "ENV_PREFIX",
    "get_hub_config",
    "merge_hub_config",
    "reset_hub_config",
]
