# -*- coding: utf-8 -*-
"""计划工具的子任务字段容错（2026-11-27）。

锁两件事：
1. 模型漏 ``name`` / ``expected_outcome`` 时，pydantic ``SubTask`` 必须接得住
   ——之前连撞 4 条 ``'name' is required`` 就是这么来的。
2. **不许改写**模型已经给出的字段值。
"""

from agentscope.plan import SubTask

from coapis.agents.react_agent import _tolerate_missing_subtask_fields


def _call(**kwargs):
    """跑一遍装饰器，把归一化后的 kwargs 抓出来。"""
    captured: dict = {}

    async def _fake_create_plan(**kw):
        captured.update(kw)

    _fake_create_plan.__name__ = "create_plan"
    return _fake_create_plan, captured


async def test_missing_name_is_filled_from_description():
    fn, got = _call()
    wrapped = _tolerate_missing_subtask_fields(fn)
    await wrapped(
        name="p",
        description="d",
        expected_outcome="o",
        subtasks=[{"description": "查台账里 create_plan 的失败原因，逐条核对"}],
    )
    item = got["subtasks"][0]
    assert item["name"]
    assert item["name"] != "未命名子任务"
    # 一行一条：长描述截断成短标题，不能把整句塞进名字
    assert len(item["name"]) <= 40
    assert item["description"] == "查台账里 create_plan 的失败原因，逐条核对"
    assert item["expected_outcome"]


async def test_filled_item_passes_the_real_pydantic_model():
    """补出来的字典必须真能构造 SubTask —— 这才是修复的全部意义。"""
    fn, got = _call()
    wrapped = _tolerate_missing_subtask_fields(fn)
    await wrapped(
        name="p",
        description="d",
        expected_outcome="o",
        subtasks=[
            {"description": "定位问题"},
            {"name": "只有名字", "expected_outcome": "有产出"},
            {},
        ],
    )
    subs = [SubTask.model_validate(x) for x in got["subtasks"]]
    assert [s.name for s in subs][0] == "定位问题"
    assert subs[1].description == "只有名字"
    assert subs[2].name == "未命名子任务"


async def test_model_given_values_are_never_rewritten():
    fn, got = _call()
    wrapped = _tolerate_missing_subtask_fields(fn)
    given = {
        "name": "拉取窗口",
        "description": "拉取 30 天窗口",
        "expected_outcome": "窗口内数据齐全",
        "state": "in_progress",
    }
    await wrapped(
        name="p",
        description="d",
        expected_outcome="o",
        subtasks=[dict(given)],
    )
    assert got["subtasks"][0] == given


async def test_subtask_instance_passthrough():
    fn, got = _call()
    wrapped = _tolerate_missing_subtask_fields(fn)
    obj = SubTask(name="已构造", description="d", expected_outcome="o")
    await wrapped(name="p", description="d", expected_outcome="o", subtasks=[obj])
    assert got["subtasks"][0] is obj


async def test_revise_current_plan_single_subtask_normalized():
    captured: dict = {}

    async def _fake_revise(**kw):
        captured.update(kw)

    _fake_revise.__name__ = "revise_current_plan"
    wrapped = _tolerate_missing_subtask_fields(_fake_revise)
    await wrapped(index=0, subtask={"description": "改前端编译错误"})
    assert captured["subtask"]["name"] == "改前端编译错误"


async def test_other_plan_tools_untouched():
    """非计划工具不许被动过（避免把无关调用改坏）。"""
    captured: dict = {}

    async def _finish(**kw):
        captured.update(kw)

    _finish.__name__ = "finish_subtask"
    wrapped = _tolerate_missing_subtask_fields(_finish)
    payload = {"subtask_outcome": "搞定"}
    await wrapped(**payload)
    assert captured == payload


async def test_composed_with_alias_wrapper_keeps_good_args_intact():
    """与别名层叠加后，命名正确的参数必须一个都不动。

    台账里 447 次计划工具调用只有 4 次失败，全是子任务缺字段，**没有一次**
    是参数名写错——所以这里只锁"叠加不伤害"，不发明新的别名。
    """
    from coapis.agents.react_agent import _tolerate_plan_arg_aliases

    captured: dict = {}

    async def _create_plan(name, description, expected_outcome, subtasks, **kw):
        captured["name"] = name
        captured["description"] = description
        captured["expected_outcome"] = expected_outcome
        captured["subtasks"] = subtasks

    _create_plan.__name__ = "create_plan"
    wrapped = _tolerate_missing_subtask_fields(
        _tolerate_plan_arg_aliases(_create_plan),
    )
    good = [
        {
            "name": "定位失败",
            "description": "查台账里 create_plan 的失败原因",
            "expected_outcome": "失败原因有实证",
        },
    ]
    await wrapped(
        name="p",
        description="d",
        expected_outcome="o",
        subtasks=[dict(x) for x in good],
    )
    assert captured["name"] == "p"
    assert captured["subtasks"] == good
