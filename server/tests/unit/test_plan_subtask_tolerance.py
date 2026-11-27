# -*- coding: utf-8 -*-
"""计划工具的子任务字段容错（2026-11-27）。

锁两件事：
1. 模型漏 ``name`` / ``expected_outcome`` 时，pydantic ``SubTask`` 必须接得住
   ——之前连撞 4 条 ``'name' is required`` 就是这么来的。
2. **不许改写**模型已经给出的字段值。
"""

import pytest
from agentscope.plan import PlanNotebook, SubTask

from coapis.agents.react_agent import (
    _make_bookkeeping_idempotent,
    _tolerate_missing_subtask_fields,
)


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


# ── 真链路契约：必须走 agentscope 自己的注册与调用入口 ──────────────
# 教训：只测"我自己造的假函数 + 假 notebook"，锁不住生产接线——摘掉
# _register_plan_tools 里的包裹层，上面那批用例照样全绿，台账照样报错。


def _production_chain(notebook):
    """按 :func:`CoApisAgent._register_plan_tools` 的**同一顺序**组装包裹层。

    生产代码是 ``_make_bookkeeping_idempotent(
    _tolerate_missing_subtask_fields(_tolerate_plan_arg_aliases(fn)), notebook)``；
    顺序一旦被抓换（抓错层、漏抓），下面的真链路契约用例就会红。
    """
    from coapis.agents.react_agent import _tolerate_plan_arg_aliases

    return _make_bookkeeping_idempotent(
        _tolerate_missing_subtask_fields(
            _tolerate_plan_arg_aliases(notebook.create_plan),
        ),
        notebook,
    )


@pytest.mark.asyncio
async def test_real_agentscope_plan_notebook_accepts_incomplete_subtasks():
    """真链路契约：真 ``PlanNotebook.create_plan`` + 生产包裹顺序。

    台账现场取自 ``system/tool_usage.jsonl`` 的 ts=1795710913 一行，
    它的 ``error`` 原文是::

        2 validation errors for Plan
        subtasks.0.name
          Field required [type=missing, input_value={'description': '拉取...'}, input_type=dict]
        subtasks.3.name
          Field required [type=missing, ...]

    两点很关键：① 报错点是**嵌套的 SubTask.name**，不是顶层
    ``create_plan(name=...)``（顶层 name 模型一直是给的）；② agentscope
    生成的 JSON Schema 里 subtasks.items 根本没有 ``required``，所以这句
    报错不是框架校验打的，而是 ``create_plan`` 内部构造 ``Plan`` 时
    pydantic 抛的 —— 光靠"注册时 schema 合法"锁不住，必须真调用。
    """
    from agentscope.plan import PlanNotebook
    import inspect

    notebook = PlanNotebook()
    func = _production_chain(notebook)
    desc = "拉取本周 OA 待办，按逾期时长降序排列，输出前 20 条到 /tmp/overdue.md"

    # 现场形态：4 个子任务，0 号和 3 号没给 name
    res = await func(
        name="本周逾期待办清单",
        description="整理本周逾期最久的待办",
        expected_outcome="逾期清单",
        subtasks=[
            {"description": desc},  # 0 号缺 name（现场报错点）
            {"name": "核对数据", "description": "核对数据", "expected_outcome": "已核对"},
            {"description": desc},  # 3 号缺 name（现场报错点）
            {"description": desc},
        ],
    )

    # toolkit 的硬契约（2026-11-27 dev 真流量实锤）：包裹层只写同步分支时，
    # 框架拿到的是一枚协程对象，直接打回
    # "The tool function must return a ToolResponse ... but got coroutine"，
    # 计划一次都建不起来。光 await 看不出这个问题，必须显式验返回类型。
    assert inspect.iscoroutinefunction(func), "包裹层退化成同步函数"
    assert not inspect.isawaitable(res), f"离开包裹层的仍是待 await 对象: {type(res)}"
    assert type(res).__name__ == "ToolResponse", type(res).__name__

    assert notebook.current_plan is not None, "计划没落账（仍被校验期打回）"
    names = [s.name for s in notebook.current_plan.subtasks]
    assert len(names) == 4
    assert names[1] == "核对数据", "模型给的名字被改了"
    assert all(names[i] for i in (0, 2, 3)), f"缺名没补齐: {names}"
    assert all(s.expected_outcome for s in notebook.current_plan.subtasks)


def test_wrapper_is_hooked_into_plan_tool_registration():
    """反证：把包裹层从 ``_register_plan_tools`` 里摘掉，本用例必须红。"""
    import ast
    import inspect

    import coapis.agents.react_agent as ra

    tree = ast.parse(inspect.getsource(ra))
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_register_plan_tools"
    )
    hooked = any(
        isinstance(node, ast.Name) and node.id == "_tolerate_missing_subtask_fields"
        for node in ast.walk(target)
    )
    assert hooked, (
        "_register_plan_tools 没有包 _tolerate_missing_subtask_fields —— "
        "摘掉接线后子任务缺 name 又会整份打回，台账里会重新出现 "
        "'validation error for Plan / subtasks.N.name'"
    )
