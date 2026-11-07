# v19 P1-5 / P1-3 回归测试（主代理owns：react_agent 点名装载 + 注入体积闸）
#
# 覆盖：
#   P1-5 逐条指定技能：点名 = 直装（跳过关键词/判官）、台账 origin=user_picked
#        单列、点空了必须留痕、后端透传契约（meta.picked_skills）。
#   P1-3 注入体积闸：场景核心段受字节预算约束 + 裁项可见 + 台账可查体积。
import inspect
from pathlib import Path

import pytest

from coapis.agents.react_agent import CoApisAgent


# ── P1-5 ──────────────────────────────────────────────────────────────


class _PickedStub:
    """`_load_on_demand_skills` 的最小宿主：只保留点名路径要碰的属性。

    `_skill_selector=None` 且点完名后候选池清空，关键词/判官两条路自然跳过，
    于是本文件只测"点名"这一件事，不依赖判官与模型。
    """

    _agent_id = "a1"
    _request_context = {"username": "u1"}
    _skill_selector = None
    _scene_skill_names: list = []
    _scene_overflow_skills: list = []
    _scene_core_skills: list = []
    _core_skills: list = []
    _scene_core_bytes = 0

    def __init__(self, pool, picked):
        self._on_demand_skills = dict(pool)
        self._picked_skills = list(picked)
        self.registered: list = []

    def _scan_and_register_skill(self, **kw):
        self.registered.append({
            "skill": kw.get("skill_name"),
            "method": kw.get("trigger_method"),
            "keywords": kw.get("matched_keywords"),
        })
        return True

    async def _llm_classify_skills(self, *a, **kw):
        """判官层桩：本文件不测判官，返回空命中即可。"""
        return []

    # v19 P1-1：Phase2 走「取消预判 / 消费预判」两个新方法，桩给最小实现
    _prefetch_tasks: dict = {}
    _prefetch_plan_level = None

    def _cancel_prefetch(self, key, why=""):
        return None

    async def _await_prefetch(self, key, fallback):
        return await fallback()


def _stub(pool, picked):
    st = _PickedStub(pool, picked)
    st.registered = []
    return st


@pytest.mark.asyncio
async def test_picked_skills_load_directly_and_bill_as_user_picked(monkeypatch):
    """用户点名 = 直装：跳过关键词/判官，台账 origin=user_picked 单列。"""
    from coapis.agents import react_agent as ra

    events = []
    monkeypatch.setattr(ra, "record_skill_trigger", lambda **kw: events.append(kw))
    st = _stub({"mail": ("/tmp/pool/mail", ["邮件"])}, ["mail"])
    await CoApisAgent._load_on_demand_skills(st, "帮我发个通知")
    assert st.registered == [{"skill": "mail", "method": "user_picked",
                              "keywords": ["user_picked"]}], "点名技能必须直装并标注来源"
    assert st._core_skills == ["mail"], "点名技能必须进入场景核心，否则等于没指定"
    assert "mail" not in st._on_demand_skills, "点过的技能必须退出候选池（防二次命中虚增命中率）"
    trig = [e for e in events if e.get("skill_name") == "mail"]
    assert trig and trig[0]["origin"] == "user_picked"
    assert trig[0]["strategy"] == "user_picked"


@pytest.mark.asyncio
async def test_picked_skill_missing_in_pool_is_loud_not_silent(monkeypatch):
    """点名了不存在的技能：告警 + 留痕，绝不静默忽略。"""
    from coapis.agents import react_agent as ra

    events = []
    monkeypatch.setattr(ra, "record_skill_trigger", lambda **kw: events.append(kw))
    st = _stub({"mail": ("/tmp/pool/mail", ["邮件"])}, ["ghost"])
    await CoApisAgent._load_on_demand_skills(st, "随便")
    assert st.registered == [], "不存在的技能不许被装载"
    ghost = [e for e in events if e.get("skill_name") == "ghost"]
    assert ghost, "点空了必须留痕"
    assert ghost[0]["matched_keywords"] == ["__not_found__"]
    assert ghost[0]["origin"] == "user_picked"
    assert ghost[0]["candidates"] == 1


@pytest.mark.asyncio
async def test_picked_skills_capped_at_three(monkeypatch):
    """点名上限 3 个：超过 3 个不叫"指定"，叫"全都要"。"""
    from coapis.agents import react_agent as ra

    events = []
    monkeypatch.setattr(ra, "record_skill_trigger", lambda **kw: events.append(kw))
    pool = {f"s{i}": (f"/tmp/pool/s{i}", []) for i in range(6)}
    st = _stub(pool, [f"s{i}" for i in range(6)])
    await CoApisAgent._load_on_demand_skills(st, "全都要")
    assert len(st.registered) == 3, "点名装载必须截断在 3 个"


def test_picked_skills_console_passthrough_contract():
    """后端契约（前端按此实现 UI）：biz_params.skills → meta.picked_skills。"""
    root = Path(__file__).resolve().parents[3]
    code = (root / "server/coapis/app/routers/console.py").read_text(encoding="utf-8")
    assert 'biz_params.get("skills"' in code, "console 未读取 biz_params.skills"
    assert 'native_payload["meta"]["picked_skills"]' in code, "meta 键名是前端契约，不得漂移"
    chan = (root / "server/coapis/app/channels/base.py").read_text(encoding="utf-8")
    assert 'msg.metadata["picked_skills"]' in chan, "通道未透传点名技能"


# ── P1-3 ──────────────────────────────────────────────────────────────


def _scene_seg(core, budget):
    names = [n for n, _ in core]

    class Stub:
        _scene_core_skills = names
        _scene_overflow_skills: list = []
        _request_context: dict = {}
        _skill_meta = {
            n: {"name": n, "description": "长" * 300, "dir": Path("/tmp") / n}
            for n in names
        }

        def _scene_skill_byte_budget(self):
            return budget

        def _get_skill_summary(self, sdir, cap):
            return "描" * min(int(cap), 200)

        def _cap_skill_index(self, block, skill_dir):
            return block

    return CoApisAgent._build_scene_skill_segment(Stub())


def test_scene_core_segment_respects_byte_budget():
    """场景核心段必须受字节闸约束（逐轮重复注入，无上限就是逐轮膨胀）。"""
    core = [(f"s{i}", i + 1) for i in range(8)]
    seg = _scene_seg(core, budget=600)
    size = len(seg.encode("utf-8"))
    assert size <= 800, f"注入段必须落在预算内（实测 {size}B）"
    assert "省略" in seg, "被闸裁掉的项数必须写进提示词，不许静默消失"


def test_scene_core_segment_under_budget_is_untouched():
    seg = _scene_seg([("s1", 1)], budget=4096)
    assert "省略" not in seg


def test_skill_trigger_ledger_carries_strategy_score_and_bytes():
    """P2-2/P1-3：台账要能回答"凭什么装的、得分多少、在多大池里选、注入多少字节"。"""
    from coapis.agents.utils.usage_tracker import record_skill_trigger

    sig = inspect.signature(record_skill_trigger)
    for field in ("strategy", "score", "candidates", "origin", "injected_bytes"):
        assert field in sig.parameters, f"技能台账缺字段 {field}"


def test_scene_byte_budget_is_declared():
    """字节闸必须有明确预算值（不是"以后再说"）。"""
    src = Path(__file__).resolve().parents[3] / "server/coapis/agents/react_agent.py"
    code = src.read_text(encoding="utf-8")
    assert "_scene_skill_byte_budget" in code
    assert "_scene_core_bytes" in code, "注入体积必须落进可观测口径"
