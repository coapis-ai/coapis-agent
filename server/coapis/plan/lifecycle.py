"""Plan lifecycle helpers shared by the runner and the API layer.

``finish_plan`` in AgentScope moves the plan into ``notebook.storage`` and
sets ``current_plan`` to ``None``. A hook that naively forwards ``None``
makes a finished plan vanish from the UI the moment it completes, so the
final snapshot has to be reconstructed here.

2026-11-19 (计划执行能力优化) — 这里原本只交回**最后一份**计划：一个会话跑过
多个计划时，前面的计划在 UI 上直接消失。实测（29 个真实会话）
``notebook.storage.plans`` 并不随会话状态落盘，所以"历史计划"必须由运行时
自己持久化到 ``agent.coapis_finished_plans``。本模块因此提供三件事：

* :func:`finished_plan_snapshots` —— 进程内可见的全部计划（最旧在前）；
* :func:`merge_finished_plan_snapshots` —— 持久化列表的唯一合并尺子；
* :func:`finished_plan_snapshot` —— 兼容旧调用，返回最新一份。
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from .schemas import plan_to_response

logger = logging.getLogger(__name__)

#: Session-state key holding the legacy single finished-plan snapshot.
FINISHED_PLAN_KEY = "coapis_finished_plan"
#: Session-state key holding every finished-plan snapshot of a session.
FINISHED_PLANS_KEY = "coapis_finished_plans"
#: How many finished plans we keep per session (newest wins).
MAX_FINISHED_PLANS = 20


def _stored_plan_objects(notebook: Any) -> list[Any]:
    """Every plan object (or serialized dict) the notebook can still see."""
    stored: list[Any] = []
    try:
        plans = getattr(getattr(notebook, "storage", None), "plans", None)
        if isinstance(plans, dict):
            stored = list(plans.values())
        elif isinstance(plans, (list, tuple)):
            stored = list(plans)
    except Exception:  # pragma: no cover - defensive
        stored = []
    return stored


def _normalize_finished(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Truthfully restate a plan's final state and mark it as finished."""
    snapshot = dict(snapshot)
    states = [
        s.get("state")
        for s in (snapshot.get("subtasks") or [])
        if isinstance(s, dict)
    ]
    if not states:
        snapshot["state"] = "done"
    elif all(s == "done" for s in states):
        snapshot["state"] = "done"
    elif all(s == "todo" for s in states):
        snapshot["state"] = "abandoned"
    else:
        snapshot["state"] = "in_progress"
    snapshot["finished"] = True
    return snapshot


def plan_really_done(snapshot: dict[str, Any]) -> bool:
    """「跑完了」的唯一尺子：state 是 done，**且每一步都真打上了勾**。

    为什么不能只看 id/finished：runner 只在新开一份计划时才清空
    ``current_plan``，于是本会话最后一份计划会永远「还是 current」。实测
    会话 1e9c20b7 四步全 done、finished_at 已落，卡片仍显示「进行中」且一直
    轮询——就是因为它无条件地把自己报成 unfinished。

    为什么也不能只看 state：``_normalize_finished`` 的 state 是按子任务**推断**
    的（全 todo 会被推成 abandoned），那种计划其实还没开工、仍可能由 runner
    继续推，不能当终点态（2026-11-20 面板停在「3/5」不动就是这么来的）。
    """
    if str(snapshot.get("state") or "") != "done":
        return False
    states = [
        str(s.get("state") or "")
        for s in (snapshot.get("subtasks") or [])
        if isinstance(s, dict)
    ]
    return bool(states) and all(s == "done" for s in states)


def finished_plan_snapshots(notebook: Any) -> list[dict[str, Any]]:
    """All plans this notebook still knows about, oldest first.

    Preference order per plan: the objects parked in ``notebook.storage``
    (agentscope keeps finished plans there with their true final state),
    then ``notebook._qp_last_plan_data`` — the last snapshot a change hook
    observed while the plan was still live.
    """
    snapshots: list[dict[str, Any]] = []
    for item in _stored_plan_objects(notebook):
        if isinstance(item, dict):
            snapshots.append(dict(item))
            continue
        try:
            snapshots.append(plan_to_response(item).model_dump())
        except Exception:
            logger.debug(
                "Could not serialize stored plan; trying the next one",
                exc_info=True,
            )

    last = getattr(notebook, "_qp_last_plan_data", None)
    if isinstance(last, dict) and last:
        ids = {s.get("id") for s in snapshots}
        if last.get("id") not in ids:
            snapshots.append(dict(last))

    if not snapshots:
        return []

    finished = [_normalize_finished(s) for s in snapshots]
    # The live plan, if any, is not "finished".
    try:
        current_id = getattr(getattr(notebook, "current_plan", None), "id", None)
    except Exception:  # pragma: no cover - defensive
        current_id = None
    if current_id is not None:
        for snap in finished:
            if snap.get("id") == current_id and not plan_really_done(snap):
                snap["finished"] = False

    try:
        notebook._qp_last_plan_data = finished[-1]
    except Exception:  # pragma: no cover - defensive
        pass
    return finished


def finished_plan_snapshot(notebook: Any) -> dict[str, Any] | None:
    """Rebuild the final snapshot of the most recently finished plan."""
    snapshots = finished_plan_snapshots(notebook)
    if not snapshots:
        return None
    for snap in reversed(snapshots):
        if snap.get("finished"):
            return snap
    return snapshots[-1]


def merge_finished_plan_snapshots(
    existing: Any,
    fresh: list[dict[str, Any]],
    limit: int = MAX_FINISHED_PLANS,
) -> list[dict[str, Any]]:
    """Merge freshly observed plans into the persisted list.

    Single source of truth for "what has this session planned so far":
    both the runner (writing) and the API (reading) go through it, so the
    two sides can never disagree about ordering or de-duplication.
    """
    merged: list[dict[str, Any]] = []
    if isinstance(existing, (list, tuple)):
        merged.extend(dict(s) for s in existing if isinstance(s, dict))
    elif isinstance(existing, dict) and existing:
        merged.append(dict(existing))

    seen = {s.get("id") for s in merged}
    for snap in fresh or []:
        if not isinstance(snap, dict):
            continue
        sid = snap.get("id")
        if sid in seen:
            # Refresh the newer copy in place, keeping chronological order.
            for idx, old in enumerate(merged):
                if old.get("id") == sid:
                    merged[idx] = {**old, **snap}
                    break
            continue
        seen.add(sid)
        merged.append(dict(snap))

    if limit and len(merged) > limit:
        merged = merged[-limit:]
    return merged


# ---------------------------------------------------------------------------
# 跨轮持久化 / 恢复（2026-11-20 定位）
# ---------------------------------------------------------------------------

# agentscope 的 ``ReActAgent.__init__`` 只是把 ``plan_notebook`` 当普通属性
# 挂着（没有 ``register_state``），所以 ``agent.state_dict()`` 里根本没有它，
# ``load_session_state`` 也就无从恢复。实测 32 个会话文件里 ``current_plan``
# 全是 None：计划只在单轮内存里活着，用户回复"确认"的那一轮拿不到计划，
# 模型把三步全跑完、``finish_plan`` 仍报 "There is no plan to finish"，
# 前端卡片永远停在 0/3。下面两个函数是这条链路上唯一的落盘/恢复通路。

RESUMABLE_PLAN_STATES = ("todo", "in_progress")


def notebook_state_payload(notebook: Any) -> dict:
    """把计划本序列化成可写进 session store 的 dict；不可用时返回 ``{}``。"""
    if notebook is None:
        return {}
    try:
        state = notebook.state_dict()
    except Exception:  # pragma: no cover - SDK 内部结构变化
        logger.warning("plan notebook state_dict failed", exc_info=True)
        return {}
    return state if isinstance(state, dict) else {}


def restore_notebook_state(notebook: Any, saved: Any) -> bool:
    """把上一轮持久化的计划本装回新建的实例。

    只恢复还没跑完的计划（``todo`` / ``in_progress``）：已完成或已放弃的计划
    不该在下一轮复活。返回 ``True`` 表示 ``notebook.current_plan`` 已可用。
    """
    if notebook is None or not isinstance(saved, dict) or not saved:
        return False
    current = saved.get("current_plan")
    if not isinstance(current, dict):
        return False
    if current.get("state") not in RESUMABLE_PLAN_STATES:
        return False
    try:
        notebook.load_state_dict(copy.deepcopy(saved), strict=False)
    except Exception:  # pragma: no cover - SDK 内部结构变化
        logger.warning("plan notebook restore failed", exc_info=True)
        return False
    return getattr(notebook, "current_plan", None) is not None
