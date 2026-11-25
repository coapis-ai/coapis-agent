# -*- coding: utf-8 -*-
"""计划快照进聊天记录：每一轮的计划跟着那一轮的 assistant 消息落库。

背景（小蜜蜂 2026-11-24 拍板）：进度卡此前只活在「当前会话」这一个视图里，
靠 /plan/current + SSE 各自处理，刷新一次换一批，历史轮次里的计划跟着一起
消失。计划和进度本来就是那一轮聊天输出的一部分，应该和正文、资源一样存进
聊天记录，各轮独立。

锁死六件事：
 1. 本轮真的调用过计划工具才算「动了计划」；只查看进度的只读工具不算
 2. 没动计划 → 返回 None，前端不长卡片（老会话显示不了就不显示）
 3. 快照字段与 /api/plan/updates 推的是同一把尺子（不许各写一份）
 4. agentscope 的 storage 是 {"plans": {id: 计划}}，按列表遍历会一个都取不到
 5. current_plan 被清掉时退回复盘用的最后一份，办完的那一轮也有卡可看
 6. 只有计划、没有产出没有引用的轮次，也必须写进 metadata
"""

from __future__ import annotations

import asyncio

from agentscope.plan import InMemoryPlanStorage, Plan, PlanNotebook, SubTask

from coapis.app.runner.runner import _annotate_turn_resources
from coapis.plan.lifecycle import (
    plan_to_dict,
    storage_plans,
    turn_plan_snapshot,
    used_plan_tools,
)


class _Msg:
    def __init__(self, role, metadata=None, content=None):
        self.role = role
        self.metadata = metadata
        self.content = content


class _ToolUse:
    """够用的 tool_use 块替身：只暴露 type / name。"""

    def __init__(self, name):
        self.type = "tool_use"
        self.name = name


def _turn_with(*tool_names):
    return [_Msg("assistant", content=[_ToolUse(n) for n in tool_names])]


def _notebook(*, current=True, in_storage=True):
    nb = PlanNotebook(
        plan_to_hint=lambda *a, **k: "",
        storage=InMemoryPlanStorage(),
    )
    plan = Plan(
        name="查天气",
        description="查一下今天有哪些热点",
        expected_outcome="给出热点清单",
        subtasks=[
            SubTask(
                name="搜热点",
                description="搜",
                expected_outcome="拿到列表",
                outcome="3 条",
                state="done",
            ),
            SubTask(
                name="写结论",
                description="写",
                expected_outcome="成文",
                state="in_progress",
            ),
        ],
    )
    if in_storage:
        # add_plan 是协程；测试里同步跑一次即可，别把 storage 留成空壳
        asyncio.run(nb.storage.add_plan(plan))
    nb.current_plan = plan if current else None
    return nb


# ---------------------------------------------------------------- 轮次判据
def test_plan_tool_makes_it_a_plan_turn():
    assert used_plan_tools(_turn_with("create_plan")) is True
    assert used_plan_tools(_turn_with("finish_subtask")) is True


def test_readonly_plan_tool_is_not_a_plan_turn():
    """只是瞟了一眼进度，不该凭空长出一张计划卡。"""
    assert used_plan_tools(_turn_with("view_subtasks")) is False
    assert used_plan_tools(_turn_with("get_subtask_count")) is False


def test_plain_chat_turn_is_not_a_plan_turn():
    assert used_plan_tools(_turn_with("execute_shell_command")) is False
    assert used_plan_tools([]) is False
    assert used_plan_tools([_Msg("assistant", content="纯文本回复")]) is False


# ---------------------------------------------------------------- 快照本体
def test_no_plan_tools_means_no_snapshot():
    nb = _notebook()
    assert turn_plan_snapshot(nb, _turn_with("execute_shell_command")) is None


def test_no_notebook_means_no_snapshot():
    assert turn_plan_snapshot(None, _turn_with("create_plan")) is None


def test_snapshot_carries_current_plan():
    nb = _notebook()
    snap = turn_plan_snapshot(nb, _turn_with("create_plan"))
    assert snap is not None
    assert snap["name"] == "查天气"
    assert [s["name"] for s in snap["subtasks"]] == ["搜热点", "写结论"]
    assert snap["subtasks"][0]["state"] == "done"
    assert snap["subtasks"][0]["outcome"] == "3 条"
    # 还没全办完，不能谎报已完成
    assert snap["finished"] is False


def test_snapshot_falls_back_to_storage_when_current_cleared():
    """计划办完后 current_plan 可能被清掉，办完那一轮仍要有卡可看。"""
    nb = _notebook(current=False)
    snap = turn_plan_snapshot(nb, _turn_with("finish_subtask"))
    assert snap is not None
    assert snap["name"] == "查天气"


def test_empty_notebook_gives_no_snapshot():
    nb = PlanNotebook(plan_to_hint=lambda *a, **k: "", storage=InMemoryPlanStorage())
    assert turn_plan_snapshot(nb, _turn_with("create_plan")) is None


# ---------------------------------------------------------------- 字段尺子
def test_storage_plans_handles_real_dict_shape():
    """agentscope 把 storage 存成 {"plans": {id: 计划}}，不是列表。"""
    state = _notebook().state_dict()
    plans = storage_plans(state)
    assert len(plans) == 1
    assert plans[0]["name"] == "查天气"
    # 按列表遍历只会拿到字符串键 "plans"，一个计划都取不出来
    assert [p for p in state["storage"] if isinstance(p, dict)] == []


def test_plan_to_dict_matches_router_ruler():
    """落库快照和 SSE 推送必须是同一把尺子，否则刷新一次字段就自己变。"""
    from coapis.app.routers.plan import _normalize_plan_data

    raw = _notebook().state_dict()["storage"]["plans"]
    one = next(iter(raw.values()))
    assert plan_to_dict(one) == _normalize_plan_data(one)


def test_finished_ruler_is_shared():
    """state=done 且子任务全办完才算真办完；接口和落库必须同一口径。"""
    from coapis.app.routers.plan import _normalize_plan_data

    raw = {
        "id": "p1",
        "name": "n",
        "state": "done",
        "subtasks": [
            {"name": "a", "state": "done", "outcome": "o", "expected_outcome": "eo"},
        ],
    }
    assert plan_to_dict(raw)["finished"] is True
    assert _normalize_plan_data(raw)["finished"] is True

    # 子任务都勾完了但计划本身还没收口 → 不算办完，别谎报
    half = {**raw, "state": "in_progress"}
    assert plan_to_dict(half)["finished"] is False
    assert _normalize_plan_data(half)["finished"] is False


# ---------------------------------------------------------------- 落库
def test_plan_only_turn_still_writes_metadata():
    """本轮没产出、没引用，只有计划 → 也必须写，否则刷新后卡片消失。"""
    msgs = [_Msg("user"), _Msg("assistant", {"original_id": "a1"})]
    snap = {"id": "p1", "name": "查天气", "subtasks": [], "finished": False}
    n = _annotate_turn_resources(msgs, [], [], plan_snapshot=snap)
    assert n == 1
    assert msgs[1].metadata["plan_snapshot"] == snap
    assert msgs[1].metadata["original_id"] == "a1"
    assert "resources" not in msgs[1].metadata


def test_snapshot_and_resources_coexist():
    msgs = [_Msg("assistant", {})]
    snap = {"id": "p1", "name": "n", "subtasks": [], "finished": True}
    _annotate_turn_resources(msgs, [{"name": "a.md"}], [], plan_snapshot=snap)
    assert msgs[0].metadata["resources"] == [{"name": "a.md"}]
    assert msgs[0].metadata["plan_snapshot"] == snap


def test_no_snapshot_writes_no_key():
    """没计划的轮次不许制造空壳字段。"""
    msgs = [_Msg("assistant", {"original_id": "a1"})]
    n = _annotate_turn_resources(msgs, [], [])
    assert n == 0
    assert msgs[0].metadata == {"original_id": "a1"}


def test_snapshot_lands_on_last_assistant_only():
    msgs = [
        _Msg("assistant", {"original_id": "a1"}),
        _Msg("assistant", {"original_id": "a2"}),
    ]
    _annotate_turn_resources(msgs, [], [], plan_snapshot={"id": "p"})
    assert "plan_snapshot" not in msgs[0].metadata
    assert msgs[1].metadata["plan_snapshot"] == {"id": "p"}


def test_persist_call_site_actually_passes_snapshot():
    """调用点必须真把快照传进去。

    2026-11-24 实锤过一次「零件全对、线没接上」：_annotate_turn_resources
    支持 plan_snapshot、turn_plan_snapshot 也算得出快照，唯独
    _persist_chat_messages 的调用漏传了这个参数（还写成一句没人用的元组
    赋值），快照算完就丢，刷新后计划卡照样不显示。单测各测各的零件，
    全绿也发现不了。这条用 AST 锁住调用点，防止再断。
    """
    import ast
    from pathlib import Path

    import coapis.app.runner.runner as runner_mod

    tree = ast.parse(Path(runner_mod.__file__).read_text(encoding="utf-8"))
    holder = None
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.name == "_persist_chat_messages":
            holder = node
            break
    assert holder is not None, "找不到 _persist_chat_messages"

    calls = [
        n
        for n in ast.walk(holder)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", "") == "_annotate_turn_resources"
    ]
    assert calls, "_persist_chat_messages 里找不到 _annotate_turn_resources 调用"
    for call in calls:
        passed = {k.arg for k in call.keywords}
        assert "plan_snapshot" in passed, (
            f"调用点漏传 plan_snapshot（实际关键字={sorted(passed)}），"
            "计划快照进不了聊天记录"
        )
