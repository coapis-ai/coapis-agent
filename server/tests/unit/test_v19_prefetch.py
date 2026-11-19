#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v19 P1-1：决策模型异步预判（拍板 D3）。

台账实测的前摇：判档 avg 2841ms、技能岗 avg 5321ms，两处**串行** await
= 用户干等 8s 量级。本文件只测预判这层机件的四条硬规矩：

  1. 中枢开着 → reply 开头就把两判**并行发起**（两个 task 同时在跑）；
  2. 中枢关着 / 岗位关着 → 一个预判都不发起（不白烧决策模型额度）；
  3. 消费处有预判就吃预判，**没有预判必须原路补判**——加了预判不许少判；
  4. 预判自身出问题 → 原路补判，绝不把异常泼到主链上。
"""

import asyncio
from types import SimpleNamespace



from coapis.agents.react_agent import CoApisAgent as CoPawAgent


class _Hub:
    def __init__(self, enabled=True, plan=True, skill=True):
        self.enabled = enabled
        self.llm_timeout_ms = 1000
        self.llm_max_tokens = 256
        self._posts = {"plan_gate": plan, "skill_trigger": skill}

    def post_enabled(self, post):
        return self._posts.get(post, False)


class _Stub:
    """只带预判机件的最小桩（不建智能体，不碰模型）。"""

    def __init__(self, hub):
        self._hub = hub
        self._calls = []
        self._skill_selector = type("S", (), {"scene_skills": ["mail"]})()
        self._workspace_dir = ""

    def _decision_hub(self):
        return self._hub

    def _decision_scope(self):
        return {"chat_id": "c1", "turn_no": 1, "session_id": "s1",
                "user_id": "u1", "agent_id": "a1"}

    def _prepare_plan_gate(self, msg):
        self._calls.append("prepare")
        return "第一步做A，第二步做B，第三步做C"

    def _classify_plan_level(self, text):
        async def _run():
            await asyncio.sleep(0)
            self._calls.append("plan")
            return "complex"
        return _run()

    def _prefetch_skill_names(self, query):
        async def _run():
            await asyncio.sleep(0)
            self._calls.append("skill")
            return ["mail"]
        return _run()

    # 绑定被测方法
    _start_judge_prefetch = CoPawAgent._start_judge_prefetch
    _spawn_prefetch = CoPawAgent._spawn_prefetch
    _cancel_prefetch = CoPawAgent._cancel_prefetch
    _await_prefetch = CoPawAgent._await_prefetch


async def test_hub_on_launches_both_judges_in_parallel():
    st = _Stub(_Hub())
    st._start_judge_prefetch(None, "第一步做A，第二步做B")
    tasks = dict(st._prefetch_tasks)
    assert set(tasks) == {"plan_gate", "skill_trigger"}, "两判必须同时发起"
    # 并行：发起时两个都还没跑完（不是串行 await）
    assert all(not t.done() for t in tasks.values())
    results = await asyncio.gather(*tasks.values())
    assert results == ["complex", ["mail"]]
    assert set(st._calls) >= {"prepare", "plan", "skill"}


async def test_hub_off_launches_nothing():
    st = _Stub(_Hub(enabled=False))
    st._start_judge_prefetch(None, "随便说点什么")
    assert st._prefetch_tasks == {}, "中枢关闭不得发起预判（白烧决策模型额度）"


async def test_disabled_post_classifies_but_never_judges(monkeypatch):
    """v21 F2：plan_gate 岗位关闭 ⇒ 规则判档照发，但绝不请决策模型。

    旧契约「岗位关着就一个预判都不发起」已废止：它把零成本的规则层和花钱的
    决策模型绑在同一颗开关上，岗位一关，规则判档一起停摆，计划链在默认配置下
    整体静默（实测 1806 轮对话 create_plan 调用 0 次）。现在岗位只决定
    「请不请决策模型」，由 _classify_plan_level 里的 judge_enabled 单独把关。
    """
    from coapis.agents.react_agent import CoApisAgent

    st = _Stub(_Hub(plan=False, skill=True))
    st._start_judge_prefetch(None, "第一步做A，第二步做B")
    assert set(st._prefetch_tasks) == {"plan_gate", "skill_trigger"}
    await asyncio.gather(*st._prefetch_tasks.values())

    seen = {}

    class _Cap:
        def __init__(self, **kw):
            seen.update(kw)

        def set_ledger_scope(self, *_args):
            pass

        def set_skills_dir(self, *_args):
            pass

        async def classify_smart(self, _text):
            return "simple"

    monkeypatch.setattr(
        "coapis.agents.plan_gate.ComplexityClassifier", _Cap,
    )
    # _Stub 用假实现覆盖了 _classify_plan_level，这里显式跑真方法。
    assert await CoApisAgent._classify_plan_level(st, "hello") == "simple"
    assert seen.get("judge_enabled") is False, "岗位关闭却仍请了决策模型"


async def test_arm_plan_sets_auto_hint_when_rules_say_complex():
    """v21 F3：规则判为多步 ⇒ notebook._plan_auto_hint 点亮，供逐轮注入。

    只点亮提示、不锁工具闸：模型自主判断不需要计划时仍可直答。
    """
    from coapis.agents.react_agent import CoApisAgent

    async def _ready(value):
        return value

    def _arm(level):
        st = _Stub(_Hub(True, True))
        st._prepare_plan_gate = lambda _m: "多步任务"
        st._PLAN_SKELETON_HINT = "skeleton"
        st.plan_notebook = SimpleNamespace(_plan_auto_hint=False)
        added = []
        st.memory = SimpleNamespace(
            add=_sink(added),
        )
        st._prefetch_tasks = {"plan_gate": _ready(level)}
        return st, added

    def _sink(sink):
        async def _add(*_args, **_kwargs):
            sink.append(1)

        return _add

    armed, added_a = _arm("complex")
    await CoApisAgent._maybe_arm_plan(armed, [])
    assert armed.plan_notebook._plan_auto_hint is True
    assert len(added_a) == 1, "多步任务应写入计划骨架提示"

    quiet, added_q = _arm("simple")
    await CoApisAgent._maybe_arm_plan(quiet, [])
    assert quiet.plan_notebook._plan_auto_hint is False
    assert added_q == [], "简单任务不该注入计划骨架"

async def test_no_prefetch_falls_back_to_sync_judge():
    """预判缺席时必须原路补判：加了预判不许少判一次。"""
    st = _Stub(_Hub())
    st._prefetch_tasks = {}
    hits = []

    async def _fb():
        hits.append(1)
        return "medium"

    assert await st._await_prefetch("plan_gate", _fb) == "medium"
    assert hits == [1]


async def test_broken_prefetch_falls_back_to_sync_judge():
    st = _Stub(_Hub())

    async def _boom():
        raise RuntimeError("决策模型炸了")

    st._spawn_prefetch("plan_gate", _boom())
    await asyncio.sleep(0.01)

    async def _fb():
        return "simple"

    assert await st._await_prefetch("plan_gate", _fb) == "simple"


async def test_cancel_drops_pending_task_and_key():
    st = _Stub(_Hub())

    async def _slow():
        await asyncio.sleep(5)
        return ["never"]

    st._spawn_prefetch("skill_trigger", _slow())
    task = st._prefetch_tasks["skill_trigger"]
    st._cancel_prefetch("skill_trigger", "关键词已命中")
    await asyncio.sleep(0.01)
    assert "skill_trigger" not in st._prefetch_tasks
    assert task.cancelled() or task.done(), "取消后不得再有第二份技能判断在跑"


async def test_prefetch_tasks_keep_strong_reference():
    """事件循环只存弱引用：没人持有的任务会被 GC，预判就变成碰运气。"""
    from coapis.agents import react_agent as ra

    st = _Stub(_Hub())
    st._start_judge_prefetch(None, "第一步做A，第二步做B")
    task = st._prefetch_tasks["plan_gate"]
    assert task in ra._PREFETCH_TASKS
    await asyncio.gather(*st._prefetch_tasks.values())
    await asyncio.sleep(0)
    assert task not in ra._PREFETCH_TASKS, "完成后要释放强引用，不能越积越多"
