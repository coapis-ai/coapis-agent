"""Regression tests for the 2026-11-19 plan-execution work (K1-K4).

What these lock down, in the order the user can see them:

1. **Every plan of a session survives a refresh.** ``finish_plan`` clears
   ``current_plan`` and the notebook only keeps the newest plan, so a session
   that planned twice used to show one board item. The durable list lives in
   ``agent.coapis_finished_plans`` and is merged by one ruler.
2. **The read side finds the session store on the real workspace object.**
   ``Workspace`` exposes ``runner.session``; reading ``workspace.session``
   raised ``AttributeError`` that was swallowed by the broad ``except``, so the
   history silently came back empty.
3. **``/plan/current`` does not explode on a live plan.** The workspace was
   only bound inside the session-store branches, so a live-cache hit reached
   the history builder with an unbound local (HTTP 500).
4. **A step that "finished" without an outcome is not a green tick.**
   ``outcome_pending`` is the ruler both the API and the prompt use.
"""
from __future__ import annotations

import types
import time

import pytest

from coapis.app.routers.plan import (
    _build_plan_history,
    _get_finished_plans,
    get_current_plan,
)
from coapis.plan.lifecycle import (
    PLAN_META_SAVED_AT,
    FINISHED_PLAN_KEY,
    FINISHED_PLANS_KEY,
    MAX_FINISHED_PLANS,
    finished_plan_snapshots,
    merge_finished_plan_snapshots,
    plan_really_done,
)
from coapis.plan.schemas import outcome_pending, plan_to_response


def _step(name, state="todo", outcome="", expected=""):
    return {
        "name": name,
        "description": f"do {name}",
        "expected_outcome": expected or f"result of {name}",
        "outcome": outcome,
        "state": state,
        "created_at": "2026-11-19T00:00:00",
        "finished_at": None,
    }


def _plan(pid, name, steps, state="in_progress"):
    return {
        "id": pid,
        "name": name,
        "description": f"plan {name}",
        "expected_outcome": f"outcome of {name}",
        "state": state,
        "subtasks": steps,
        "created_at": "2026-11-19T00:00:00",
        "finished_at": None,
    }


# ---------------------------------------------------------------------------
# 4. outcome ruler
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "expected,outcome,state,pending",
    [
        ("写一份说明", "", "done", True),          # 结束但什么都没写
        ("写一份说明", "done", "done", True),      # 占位词不算交付
        ("写一份说明", "完成", "done", True),
        ("写一份说明", "写一份说明", "done", True),  # 只复述承诺
        ("写一份说明", "已生成 lifecycle.md 共 240 行", "done", False),
        ("写一份说明", "", "todo", False),        # 未结束不判
        ("写一份说明", "", "abandoned", True),    # 放弃同样要交代
    ],
)
def test_outcome_pending_ruler(expected, outcome, state, pending):
    assert outcome_pending(expected, outcome, state) is pending


def test_plan_to_response_exposes_outcome_pending():
    class _Sub:
        def __init__(self, raw):
            for key, value in raw.items():
                setattr(self, key, value)

    class _Plan:
        id = "p1"
        name = "计划一"
        description = "desc"
        expected_outcome = "out"
        state = "in_progress"
        created_at = "2026-11-19T00:00:00"
        finished_at = None
        outcome = ""
        subtasks = [
            _Sub(_step("甲", "done", outcome="done")),
            _Sub(_step("乙", "done", outcome="产出乙文件")),
            _Sub(_step("丙", "todo")),
        ]

    resp = plan_to_response(_Plan())
    assert [s.outcome_pending for s in resp.subtasks] == [True, False, False]


# ---------------------------------------------------------------------------
# 1. merge ruler + snapshots
# ---------------------------------------------------------------------------

def test_merge_keeps_chronological_order_and_dedupes_by_id():
    first = _plan("p1", "第一件", [_step("甲", "done", outcome="甲结果")])
    second = _plan("p2", "第二件", [_step("乙", "done", outcome="乙结果")])
    merged = merge_finished_plan_snapshots([first], [second])
    assert [p["id"] for p in merged] == ["p1", "p2"]

    # 同一份计划再次观测到：原位刷新，不追加、不重排
    first_done = _plan(
        "p1",
        "第一件",
        [_step("甲", "done", outcome="甲结果")],
        state="done",
    )
    merged2 = merge_finished_plan_snapshots(merged, [first_done])
    assert [p["id"] for p in merged2] == ["p1", "p2"]
    assert merged2[0]["state"] == "done"


def test_merge_accepts_legacy_single_dict_and_caps_history():
    legacy = _plan("p0", "旧版单份", [_step("甲")])
    many = [_plan(f"p{i}", f"计划{i}", [_step("甲")]) for i in range(1, 6)]
    merged = merge_finished_plan_snapshots(legacy, many, limit=3)
    assert len(merged) == 3
    assert [p["id"] for p in merged] == ["p3", "p4", "p5"]
    assert MAX_FINISHED_PLANS > 0


def test_finished_plan_snapshots_returns_all_plans_oldest_first():
    class _NB:
        def __init__(self):
            self.storage = types.SimpleNamespace(
                plans=[_plan("p1", "第一件", [_step("甲")]),
                       _plan("p2", "第二件", [_step("乙")])],
            )
            self.current_plan = None
            self._qp_last_plan_data = None

    snaps = finished_plan_snapshots(_NB())
    assert [s["id"] for s in snaps] == ["p1", "p2"]
    assert all(s["finished"] for s in snaps)


def test_finished_plan_snapshots_marks_live_plan_not_finished():
    class _NB:
        def __init__(self):
            self.storage = types.SimpleNamespace(
                plans={"p1": _plan("p1", "第一件", [_step("甲")])},
            )
            self.current_plan = types.SimpleNamespace(id="p1")
            self._qp_last_plan_data = None

    snaps = finished_plan_snapshots(_NB())
    assert len(snaps) == 1
    assert snaps[0]["finished"] is False


# ---------------------------------------------------------------------------
# 2. read side must find runner.session (regression: workspace.session)
# ---------------------------------------------------------------------------

class _FakeSessionStore:
    def __init__(self, agent_state):
        self._agent_state = agent_state
        self.calls = []

    async def get_session_state_dict(self, session_id, user_id="", allow_not_exist=True):
        self.calls.append((session_id, user_id))
        return {"agent": self._agent_state}


class _FakeWorkspace:
    """Mirrors the real Workspace shape: the store hangs off ``runner``."""

    def __init__(self, agent_state):
        self.runner = types.SimpleNamespace(
            session=_FakeSessionStore(agent_state),
        )


async def test_get_finished_plans_reads_new_list_key():
    plans = [
        _plan("p1", "第一件", [_step("甲", "done", outcome="甲结果")]),
        _plan("p2", "第二件", [_step("乙", "done", outcome="")]),
    ]
    ws = _FakeWorkspace({FINISHED_PLANS_KEY: plans})
    result = await _get_finished_plans(ws, "chat-1", "admin")
    assert [p["id"] for p in result] == ["p1", "p2"]
    assert all(p["finished"] for p in result)
    # 第二件的步骤没有产出 → 同一把尺子标记待补
    assert result[1]["subtasks"][0]["outcome_pending"] is True


async def test_get_finished_plans_falls_back_to_legacy_single_key():
    ws = _FakeWorkspace({FINISHED_PLAN_KEY: _plan("p1", "旧版", [_step("甲")])})
    result = await _get_finished_plans(ws, "chat-1", "admin")
    assert [p["id"] for p in result] == ["p1"]


async def test_get_finished_plans_tolerates_missing_store():
    assert await _get_finished_plans(None, "chat-1", "admin") == []
    bare = types.SimpleNamespace()
    assert await _get_finished_plans(bare, "chat-1", "admin") == []


# ---------------------------------------------------------------------------
# 3. /plan/current envelope
# ---------------------------------------------------------------------------

def _fake_request(manager):
    state = types.SimpleNamespace(username="admin", user_info=None)
    app = types.SimpleNamespace(state=types.SimpleNamespace(multi_agent_manager=manager))
    return types.SimpleNamespace(
        app=app,
        state=state,
        query_params={"session_id": "chat-1"},
        headers={},
    )


async def test_current_plan_returns_history_when_live_cache_hits(monkeypatch):
    """Live cache hit → workspace is still resolved (was UnboundLocalError)."""
    from coapis.plan import broadcast

    live = _plan("p2", "进行中", [_step("甲", "in_progress")])
    live[PLAN_META_SAVED_AT] = time.time()
    monkeypatch.setattr(
        broadcast, "get_live_plan", lambda agent_id, sid: (True, live)
    )
    stored = [_plan("p1", "已完成的第一件", [_step("甲", "done", outcome="甲结果")])]
    ws = _FakeWorkspace({FINISHED_PLANS_KEY: stored})
    manager = types.SimpleNamespace(
        get_workspace=lambda agent_id, username=None: ws,
    )

    body = await get_current_plan(_fake_request(manager), session_id="chat-1")

    assert [p["id"] for p in body["plans"]] == ["p1", "p2"]
    assert body["plans"][0]["finished"] is True
    assert body["plans"][-1]["finished"] is False
    assert body["plan"]["id"] == "p2"


async def test_current_plan_rejects_stale_history_as_current(monkeypatch):
    """陈旧的历史计划不得冒充「当前计划」。

    小蜜蜂 2026-11-23 报障：问「今天有哪些热点」，计划面板直接弹出三天前
    那份已完成任务。根因是 /plan/current 把历史台账里最新的一份当兜底返回，
    而这份兜底没有时间维度的闸。
    """
    from coapis.plan import broadcast

    monkeypatch.setattr(
        broadcast, "get_live_plan", lambda agent_id, sid: (False, None)
    )

    stale = _plan(
        "old",
        "三天前的计划",
        [_step("甲", "done", outcome="甲结果")],
    )
    stale[PLAN_META_SAVED_AT] = time.time() - 3 * 24 * 3600
    ws = _FakeWorkspace({FINISHED_PLANS_KEY: [stale]})
    manager = types.SimpleNamespace(
        get_workspace=lambda agent_id, username=None: ws,
    )

    body = await get_current_plan(_fake_request(manager), session_id="chat-1")

    # 不得当作当前计划返回……
    assert body["plan"] is None
    # ……但台账仍要查得到，供「查看历史计划」入口使用。
    assert [p["id"] for p in body["plans"]] == ["old"]


async def test_current_plan_without_manager_returns_empty_history(monkeypatch):
    from coapis.plan import broadcast

    monkeypatch.setattr(broadcast, "get_live_plan", lambda agent_id, sid: (False, None))
    body = await get_current_plan(_fake_request(None), session_id="chat-1")
    assert body["plans"] == []
    assert body["plan"] is None


def test_build_plan_history_dedupes_and_marks_live():
    finished = [
        dict(_plan("p1", "第一件", [_step("甲")]), finished=True),
        dict(_plan("p2", "第二件", [_step("乙")]), finished=True),
    ]
    current = dict(_plan("p2", "第二件", [_step("乙", "done")]), finished=False)
    history = _build_plan_history(current, finished)
    assert [p["id"] for p in history] == ["p1", "p2"]
    assert history[-1]["finished"] is False
    assert _build_plan_history(None, []) == []


# ---------------------------------------------------------------------------
# 「跑完了」的唯一尺子：state=done 且每一步都真打上勾
# （回归 1e9c20b7：4/4 全 done 的计划仍显示「进行中」且一直轮询）
# ---------------------------------------------------------------------------
def test_current_plan_that_is_really_done_stays_finished():
    done = _plan(
        "p1",
        "收尾",
        [_step("落账", state="done"), _step("验收", state="done")],
        state="done",
    )
    notebook = types.SimpleNamespace(
        storage=types.SimpleNamespace(plans={"p1": done}),
        current_plan=types.SimpleNamespace(id="p1"),
    )

    snaps = finished_plan_snapshots(notebook)

    assert snaps[0]["finished"] is True
    assert snaps[0]["state"] == "done"


def test_current_plan_with_untouched_steps_is_still_live():
    """还没开跑（全 todo）的计划仍算在跑：不能把推断出的 abandoned 当终点态。"""
    not_started = _plan("p1", "收尾", [_step("落账")])
    notebook = types.SimpleNamespace(
        storage=types.SimpleNamespace(plans={"p1": not_started}),
        current_plan=types.SimpleNamespace(id="p1"),
    )

    snaps = finished_plan_snapshots(notebook)

    assert snaps[0]["finished"] is False


def test_plan_really_done_requires_every_step_checked():
    assert plan_really_done(
        {"state": "done", "subtasks": [{"state": "done"}, {"state": "done"}]},
    ) is True
    assert plan_really_done(
        {"state": "done", "subtasks": [{"state": "done"}, {"state": "todo"}]},
    ) is False
    # 无子任务的空计划不算跑完：轮询得留着，等真正的落账。
    assert plan_really_done({"state": "done", "subtasks": []}) is False
    assert plan_really_done(
        {"state": "in_progress", "subtasks": [{"state": "done"}]},
    ) is False
