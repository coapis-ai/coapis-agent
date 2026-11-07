# -*- coding: utf-8 -*-
"""v19 逻辑优化批（B1/B2）行为锁。

覆盖：
- 配置层：按岗位软阈值（v19 P1-2）、岗位表夹取、``judge_soft_ms_post``
  必须是数据类字段（只写进 DEFAULTS 会让整个中枢配置装载 TypeError —— 实测过）。
- 判官：软阈值是中性事件（连续计数才冷却）、非终态不落台账（P0-2）。
- 技能触发：Tier2 幽灵引用丢弃 + 兜底条数走配置 + 短词不打分（P0-3/P0-4/P1-4）。
- 治理闸门：六岗配置写入口要权限、技能写端点挂审计依赖（P2-3）。
"""

from __future__ import annotations

import asyncio

import pytest

from coapis.decision import gateway as gw
from coapis.decision.breaker import reset_breakers
from coapis.decision.config import DecisionHubConfig
from coapis.skills.manager import SkillManager


# ---------------------------------------------------------------- 配置层 --
def test_soft_ms_is_per_post_and_acceptance_is_widest():
    """一把尺子量七岗是真判率被绞掉的成因：软阈值必须按岗位取。"""
    cfg = DecisionHubConfig.from_dict(None)
    assert cfg.soft_ms_for("tool_gate") != cfg.soft_ms_for("plan_gate")
    # 验收在幕后（没人等它的结论），阈值只放宽不收紧
    assert cfg.soft_ms_for("acceptance") >= cfg.judge_soft_ms_acceptance
    # 表里没有的岗位回落全局阈值
    assert cfg.soft_ms_for("no_such_post") == cfg.judge_soft_ms


def test_soft_ms_post_map_is_clamped_and_typed():
    """回归锁：岗位表只写进 DEFAULTS 时，``cls(**merged)`` 直接 TypeError。"""
    cfg = DecisionHubConfig.from_dict(
        {"judge_soft_ms_post": {"tool_gate": 1, "plan_gate": 99999, "advisor": "x"}},
    ).normalized()
    assert cfg.judge_soft_ms_post["tool_gate"] == 200.0  # 下限夹取
    assert cfg.judge_soft_ms_post["plan_gate"] == 20000.0  # 上限夹取
    # 非数值项由 _as_float 回落该岗位默认（不炸配置装载）
    assert cfg.judge_soft_ms_post["advisor"] > 0


def test_v19_new_knobs_exist_and_clamp():
    cfg = DecisionHubConfig.from_dict(
        {"skill_fallback_cap": 99, "breaker_soft_streak": 0},
    ).normalized()
    assert cfg.skill_fallback_cap == 10
    assert cfg.breaker_soft_streak == 1
    assert DecisionHubConfig.from_dict(None).skill_tier2_enabled is True
    assert DecisionHubConfig.from_dict(None).skill_gate_audit is True


# ------------------------------------------------------------------ 判官 --
class _LedgerSpy:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def __call__(self, **kw) -> None:
        self.rows.append(dict(kw))


@pytest.fixture()
def spy_ledger(monkeypatch):
    spy = _LedgerSpy()
    monkeypatch.setattr(gw, "write_ledger", spy)
    reset_breakers()
    gw._soft_streaks.clear()
    yield spy
    reset_breakers()
    gw._soft_streaks.clear()


def test_soft_timeout_streak_is_neutral_until_threshold():
    """连续软超时计数：中性累计，到阈值才该冷却（v19 P0-2 ①）。"""
    key = "judge:plan_gate"
    assert gw._note_soft_timeout(key) == 1
    assert gw._note_soft_timeout(key) == 2
    assert gw._soft_streak_of(key) == 2
    gw._reset_soft_streak(key)
    assert gw._soft_streak_of(key) == 0
    assert gw._note_soft_timeout(key) == 1


def test_degrade_can_skip_ledger_for_non_terminal_judgment(spy_ledger):
    """软阈值不是终态：主链先走时不落账，台账只记判官终态那一行（P0-2 ②）。"""
    gateway = gw.JudgeGateway()

    async def run() -> gw.JudgeReply:
        return await gateway._degrade(  # noqa: SLF001 - 测试直调内部出口
            "plan_gate",
            gw.LAYER_TIMEOUT,
            "判断超时（软阈值 0.0s，判官后台补判中）",
            None,
            None,
            lambda: 12,
            {"chat_id": "c1", "turn": 1},
            ledger=False,
        )

    reply = asyncio.run(run())
    assert reply.hit_layer == gw.LAYER_TIMEOUT
    assert spy_ledger.rows == [], "软阈值这一手不该写台账"


# ---------------------------------------------------------------- 技能层 --
def _mk_manager(tmp_path, skills: dict[str, dict]) -> SkillManager:
    for name, spec in skills.items():
        skill_dir = tmp_path / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            f"name: {name}\n"
            f"description: {spec.get('description', name)}\n"
            + (
                "trigger_keywords:\n" + "".join(
                    f"  - {k}\n" for k in spec.get("keywords", [])
                )
                if spec.get("keywords")
                else ""
            )
            + "---\n"
            "# body\ncontent\n",
            encoding="utf-8",
        )
    mgr = SkillManager(tmp_path)
    asyncio.run(mgr.discover())
    return mgr


def test_short_keyword_does_not_hijack(tmp_path, monkeypatch):
    """'设计'(2字) 不该把 '绘画' 顶进提示（v19 P1-4）。

    尺子：1-2 字中文词**只允许与技能自己的词完全相等**才命中（Tier1 精确词
    要求 3 字起、Tier2 写死表丢掉 1-2 字中文别名、Tier3 短 token 要求全等）。
    兜底置 0 后断言"什么都没选中"，才证明短词真的**没打分**——兜底是另一码事。
    """
    from coapis.decision import config as cfg_mod

    monkeypatch.setattr(
        cfg_mod,
        "get_hub_config",
        lambda: DecisionHubConfig.from_dict({"skill_fallback_cap": 0}),
    )
    mgr = _mk_manager(
        tmp_path,
        {"绘画助手": {"keywords": ["绘画"], "description": "画画"}},
    )
    assert mgr.match_skills_by_query("帮我设计一下") == []


def test_ghost_trigger_refs_are_dropped(tmp_path):
    """写死触发表指向池外技能：丢弃且留痕（v19 P0-4）。"""
    from coapis.skills import manager as m

    m._ghost_skill_seen.clear()
    mgr = _mk_manager(tmp_path, {"只有这个": {"keywords": [], "description": "x"}})
    mgr.match_skills_by_query("生成一份PDF报告")
    ghosts = {k.split(":", 1)[1] for k in m._ghost_skill_seen}
    assert ghosts, "幽灵引用应被记录"
    assert all(g not in mgr._skills for g in ghosts)


def test_fallback_cap_follows_config(tmp_path, monkeypatch):
    """兜底条数是成本旋钮：装载层按名单灌全文（v19 P0-3/P2-2）。"""
    from coapis.decision import config as cfg_mod

    mgr = _mk_manager(
        tmp_path,
        {f"skill{i}": {"keywords": [], "description": f"说明{i}"} for i in range(6)},
    )
    monkeypatch.setattr(
        cfg_mod,
        "get_hub_config",
        lambda: DecisionHubConfig.from_dict({"skill_fallback_cap": 1}),
    )
    assert len(mgr._fallback_skills()) == 1


# ---------------------------------------------------------------- 治理闸门 --
def test_hub_config_write_endpoint_is_gated():
    """六岗配置写入口不能人人可改（v19 P2-3）。"""
    from coapis.app.routers import decisions as dr

    put_cfg = next(
        r for r in dr.router.routes
        if r.path == "/config" and "PUT" in r.methods
    )
    assert getattr(put_cfg, "dependencies", []), "PUT /config 必须挂权限依赖"


def test_skill_write_endpoints_are_audited():
    """技能清单每个**会改东西**的端点都要挂审计依赖（v19 P2-3）。"""
    from coapis.app.routers import skills as sr

    # 只读端点（导出/下载/体检/刷新缓存）不记审计——它们不改清单。
    read_only = {
        ("/skills/export", "POST"),
        ("/skills/pool/download", "POST"),
        ("/skills/debug/trigger-analysis", "POST"),
        ("/skills/pool/refresh", "POST"),
        ("/skills/refresh", "POST"),
    }
    missing = []
    for route in sr.router.routes:
        methods = {m for m in route.methods if m not in ("GET", "HEAD", "OPTIONS")}
        if not methods:
            continue
        for method in methods:
            if (route.path, method) in read_only:
                continue
            if "skill_gate_audit" not in repr(getattr(route, "dependencies", [])):
                missing.append((method, route.path))
    assert not missing, f"这些写端点没有审计依赖：{missing}"
