"""计划本跨轮持久化/恢复的回归测试（2026-11-20）。

背景：agentscope 的 ``ReActAgent`` 把 ``plan_notebook`` 当普通属性挂着，没有
``register_state``，所以 ``agent.state_dict()`` / ``load_session_state`` 都不会
带上它。实测 32 个会话文件里 ``current_plan`` 全是 None —— 计划只在单轮内存里
活着。用户回复"确认"的那一轮拿不到计划，模型把三步全跑完，``finish_plan`` 仍
报 "There is no plan to finish"，前端卡片永远停在 0/3。

这里锁两件事：
1. ``notebook_state_payload`` / ``restore_notebook_state`` 能落盘并装回计划；
2. runner 真的把这两个函数接进了主链（防止以后重构把接线弄丢）。
"""

from __future__ import annotations

import copy
import io
import os

import pytest
from agentscope.plan import InMemoryPlanStorage, PlanNotebook, SubTask

from coapis.plan.lifecycle import (
    notebook_state_payload,
    restore_notebook_state,
)


def _sub(name: str) -> SubTask:
    return SubTask(name=name, description="do it", expected_outcome="done")


async def _make_notebook() -> PlanNotebook:
    nb = PlanNotebook(storage=InMemoryPlanStorage())
    await nb.create_plan(
        name="跨轮计划",
        description="验证计划能跨轮恢复",
        expected_outcome="产出三个文件",
        subtasks=[_sub("步骤一"), _sub("步骤二"), _sub("步骤三")],
    )
    return nb


# ---------------------------------------------------------------- 落盘侧


def test_payload_empty_when_nothing_to_save() -> None:
    assert notebook_state_payload(None) == {}


async def test_payload_carries_current_plan() -> None:
    nb = await _make_notebook()
    payload = notebook_state_payload(nb)
    assert isinstance(payload, dict)
    current = payload.get("current_plan")
    assert isinstance(current, dict)
    assert current["name"] == "跨轮计划"
    assert current["state"] in ("todo", "in_progress")
    assert len(current.get("subtasks") or []) == 3


# ---------------------------------------------------------------- 恢复侧


@pytest.mark.parametrize(
    "saved",
    [
        None,
        {},
        "not-a-dict",
        {"current_plan": None},
        {"current_plan": {"name": "x", "state": "done"}},
        {"current_plan": {"name": "x", "state": "abandoned"}},
    ],
)
def test_restore_rejects_nothing_to_resume(saved) -> None:
    assert restore_notebook_state(PlanNotebook(), saved) is False


def test_restore_rejects_broken_notebook() -> None:
    assert restore_notebook_state(None, {"current_plan": {"state": "todo"}}) is False


async def test_restore_brings_the_plan_back() -> None:
    nb = await _make_notebook()
    saved = copy.deepcopy(notebook_state_payload(nb))

    fresh = PlanNotebook(storage=InMemoryPlanStorage())
    assert fresh.current_plan is None
    assert restore_notebook_state(fresh, saved) is True
    assert fresh.current_plan is not None
    assert fresh.current_plan.name == "跨轮计划"
    assert len(fresh.current_plan.subtasks or []) == 3


async def test_restored_plan_accepts_plan_tool_calls() -> None:
    """恢复出来的计划必须还能被计划工具操作——这才是"确认"那一轮真正要的。"""
    nb = await _make_notebook()
    saved = copy.deepcopy(notebook_state_payload(nb))

    fresh = PlanNotebook(storage=InMemoryPlanStorage())
    assert restore_notebook_state(fresh, saved) is True

    # 恢复前这些调用只会得到 "There is no plan"。
    # 注意 SDK 的签名是 ``update_subtask_state(subtask_idx: int, state)``，
    # 且要求按顺序推进（上一步没 done 就不许动下一步）。
    upd = await fresh.update_subtask_state(0, "in_progress")
    assert "There is no plan" not in str(getattr(upd, "content", upd))
    assert fresh.current_plan.subtasks[0].state == "in_progress"

    fin = await fresh.finish_plan(state="done", outcome="三个文件已产出")
    assert "no plan" not in str(getattr(fin, "content", fin)).lower()
    assert fresh.current_plan is None


# ---------------------------------------------------------------- 主链接线


def test_runner_wires_persist_and_restore() -> None:
    """runner 里两处接线不能被人重构掉（删一行这里就红）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.normpath(
        os.path.join(here, "..", "coapis", "app", "runner", "runner.py"),
    )
    src = io.open(path, encoding="utf-8").read()
    assert "_persist_finished_plans(_finished_plan_snapshots(nb))" in src
    assert "_persist_notebook(nb)" in src
    assert "def _persist_notebook(" in src
    assert "restore_notebook_state(plan_notebook, _saved_nb)" in src
    # 簿记工具必须在恢复后补配，否则这一轮调 update_subtask_state 会
    # FunctionNotFoundError，卡片步骤永远 0/3。
    assert '_equip("restored plan")' in src
