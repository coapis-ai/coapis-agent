# -*- coding: utf-8 -*-
"""判断中枢配置（v13 第 15 章 D5：判据不入库，这里只有开关与阈值）。

来源优先级：**智能体 running_config.decision_hub > 环境变量 > 默认值**
（与既有配置优先级约定一致）。

开关粒度：一个总开关 ``enabled`` + 每岗位一个开关。一期只接了技能触发与
计划闸门两个岗位，岗位开关就是「一键关闭回到今天」的落点。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping

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
    "breaker_probe_timeout_s": 3.0,
    "breaker_probe_max_in_flight": 1,
    "breaker_window_seconds": 60.0,
    "breaker_half_open_cooldown_s": 60.0,
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
    # v15 §M2 软超时：主链最多等判官 2 秒，超时先返回降级、
    # 判官后台跑完补写台账。拍板依据：判官是增强岗不是主链依赖，
    # 主链为一句话等 4 秒不可接受（小蜜蜂 2026-11-04 定案）。
    "judge_soft_ms": 2000.0,
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
    # ── 判官设置项 API 的两处配置位（v14 §5.2）─────────────────────
    # 事中改道：每 N 个迭代让判官插话一次；**0 = 关闭事中改道**。
    "advisor_every_iters": 6,
    # 前 N 个迭代不判改道：动作太少，判了也看不出来，只产噪声台账。
    "advisor_min_iters": 3,
    # 验收喂给判官的交付文本上限（字）。交付越长越贵，摘要足够判。
    "acceptance_max_chars": 4000,
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
    breaker_probe_timeout_s: float = 3.0
    breaker_probe_max_in_flight: int = 1
    breaker_window_seconds: float = 60.0
    breaker_half_open_cooldown_s: float = 60.0
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

    @property
    def advisor_enabled(self) -> bool:
        """事中改道是否开启（API 契约名 = 每 N 轮复核，N>0 即开启）。"""
        return self.advisor_every_iters > 0
    # 每轮判官 LLM 调用上限。判档 + 技能触发 + 验收加起来就该封顶，
    # 不能把整轮预算吃在判断上——这是"重复/循环判断"的根治闸门。
    judge_max_calls_per_turn: int = 7
    # v14 §批次3 软超时（毫秒）：超过即主链先返回降级、判官后台跑完
    # 补写台账；硬超时 effective_timeout_ms 退居保险丝。
    judge_soft_ms: float = 2000.0
    # 验收岗单独的软阈值（毫秒）。验收是幕后岗：整轮交付跑完才触发，
    # 没有任何消费者在等它的结论，所以不该吃主链那 4 秒的预算。
    # 它的 verdict 是判档行 outcome 的唯一来源——验收弃权 = 闭环恒 0。
    judge_soft_ms_acceptance: float = 12000.0
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

    # ── 判官设置项 API 的两处配置位（v14 §5.2）─────────────────────
    # 事中改道：每 N 个迭代让判官插话一次；**0 = 关闭事中改道**。
    advisor_every_iters: int = 6
    advisor_min_iters: int = 3
    acceptance_max_chars: int = 4000
    # 预算豁免轮数：前 N 轮不吃思考预算降级。
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
                # 岗位上限表（v14 §4.3）：逐岗位取整数上限，缺的岗位回落默认。
                got = val if isinstance(val, dict) else {}
                table: dict[str, int] = {}
                for name, dv in dict(default).items():
                    table[name] = max(_as_int(got.get(name, dv), int(dv)), 0)
                for name, v in got.items():
                    if name not in table:
                        table[name] = max(
                            _as_int(v, int(DEFAULTS["judge_post_limit_default"])),
                            0,
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
        self.judge_max_calls_per_turn = min(
            max(int(self.judge_max_calls_per_turn), 1), 8,
        )
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
