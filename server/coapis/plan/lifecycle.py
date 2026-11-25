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
import os
import time
from typing import Any

from .schemas import outcome_pending, plan_to_response

logger = logging.getLogger(__name__)

#: Session-state key holding the legacy single finished-plan snapshot.
FINISHED_PLAN_KEY = "coapis_finished_plan"
#: Session-state key holding every finished-plan snapshot of a session.
FINISHED_PLANS_KEY = "coapis_finished_plans"
#: How many finished plans we keep per session (newest wins).
MAX_FINISHED_PLANS = 20

# ---------------------------------------------------------------------------
# 「这份计划还算当前吗」的唯一尺子
#
# 计划是会话级状态，面板却是轮次级的展示。两者不挂钩时，任何一次
# /plan/current 轮询都能把历史上最后一份计划捞出来当"当前计划"——用户
# 问"今天有哪些热点"，面板却显示三天前那份已完成的任务。下面的元数据
# 在每次落盘时盖章，读取侧统一按新鲜度裁决。
# ---------------------------------------------------------------------------
#: 随 notebook / 快照一起持久化：上次落盘的时刻（epoch 秒）
PLAN_META_SAVED_AT = "_qp_saved_at"

#: 距上次落盘超过这么久就不再算"当前计划"。默认 30 分钟：够覆盖"模型等
#: 用户确认"的正常停顿，又能挡住隔夜僵尸。设为 0 表示不看新鲜度。
PLAN_CURRENT_MAX_AGE_SECONDS = float(
    os.getenv("COAPIS_PLAN_CURRENT_MAX_AGE", "") or 1800.0,
)


def stamp_plan_metadata(
    saved: dict,
    *,
    now: float | None = None,
) -> dict:
    """给 notebook 状态字典盖上落盘时刻戳（就地返回同一对象）。"""
    if not isinstance(saved, dict):
        return saved
    saved[PLAN_META_SAVED_AT] = time.time() if now is None else float(now)
    return saved


def plan_saved_at(saved: dict) -> float | None:
    """读出落盘时刻；兼容"计划被包在 SSE 信封里"的两种形状。"""
    if not isinstance(saved, dict):
        return None
    raw = saved.get(PLAN_META_SAVED_AT)
    if raw is None:
        inner = saved.get("plan")
        if isinstance(inner, dict):
            raw = inner.get(PLAN_META_SAVED_AT)
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def plan_age_seconds(saved: dict, *, now: float | None = None) -> float | None:
    """距上次落盘过了多久；没盖过章返回 ``None``。"""
    saved_at = plan_saved_at(saved)
    if saved_at is None:
        return None
    return max(0.0, (time.time() if now is None else float(now)) - saved_at)


def plan_is_current(
    saved: dict,
    *,
    max_age: float | None = None,
    now: float | None = None,
) -> bool:
    """能否把它当作"当前计划"展示。

    没盖过章的一律视为过期：那些正是本规则之前留下的僵尸，宁可少显示，
    也不能让它们跑到毫不相干的轮次上。
    """
    limit = (
        PLAN_CURRENT_MAX_AGE_SECONDS if max_age is None else float(max_age)
    )
    if limit <= 0:
        return True
    age = plan_age_seconds(saved, now=now)
    if age is None:
        return False
    return age <= limit


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
        # 只有首次进台账的快照才盖落盘时刻；已在台账里的沿用原时刻。
        # 这样"历史上的已完成计划"才会随时间变陈旧，不再冒充当前计划。
        if PLAN_META_SAVED_AT not in snap:
            snap[PLAN_META_SAVED_AT] = time.time()
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
    # 盖上落盘时刻与轮次：读取侧据此判断"这份计划还是不是当前的"。
    return stamp_plan_metadata(dict(state))


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
    # 状态白名单挡不住"一直挂着没动的僵尸"：再按新鲜度拦一道。
    if not plan_is_current(saved):
        return False
    try:
        notebook.load_state_dict(copy.deepcopy(saved), strict=False)
    except Exception:  # pragma: no cover - SDK 内部结构变化
        logger.warning("plan notebook restore failed", exc_info=True)
        return False
    return getattr(notebook, "current_plan", None) is not None


# ---------------------------------------------------------------- 本轮计划快照
# 计划卡过去只活在"当前会话"这一个视图里：刷新一次换一批，历史轮次里的计划
# 跟着一起消失。小蜜蜂 2026-11-24 拍板：计划和进度是聊天输出的一部分，应该
# 跟着那一轮的消息一起存进聊天记录，各轮独立。这里负责把"这一轮动过的计划"
# 取出来；落库点见 runner._annotate_turn_resources。

# 只认"真的动了计划"的工具。view_subtasks / get_subtask_count 这类只读的不算，
# 否则一个只是瞟了一眼进度的轮次也会凭空长出一张计划卡。
PLAN_TURN_TOOLS: frozenset[str] = frozenset(
    {
        "create_plan",
        "revise_current_plan",
        "update_subtask_state",
        "finish_subtask",
    },
)


def plan_to_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """计划字典 → 前端认识的快照（接口与落库共用这一把尺子）。

    /api/plan/updates 推的、/api/plan/current 给的、消息 metadata 里存的，
    必须是同一份字段：否则刷新一次，卡片上的"已完成"会自己变。
    """
    subtasks = []
    for st in raw.get("subtasks", []):
        if not isinstance(st, dict):
            continue
        entry = {
            "name": st.get("name", ""),
            "description": st.get("description", ""),
            "expected_outcome": st.get("expected_outcome", ""),
            "outcome": st.get("outcome"),
            "state": st.get("state", "todo"),
            "created_at": st.get("created_at"),
            "finished_at": st.get("finished_at"),
        }
        # Same ruler as plan_to_response, so a snapshot persisted before
        # this field existed still reports "结果待补" truthfully.
        entry["outcome_pending"] = bool(st.get("outcome_pending")) or (
            outcome_pending(
                entry["expected_outcome"],
                entry["outcome"],
                entry["state"],
            )
        )
        subtasks.append(entry)
    return {
        "id": raw.get("id", ""),
        "name": raw.get("name", ""),
        "description": raw.get("description", ""),
        "expected_outcome": raw.get("expected_outcome", ""),
        "state": raw.get("state", "todo"),
        "subtasks": subtasks,
        "created_at": raw.get("created_at"),
        "finished_at": raw.get("finished_at"),
        # finished 的唯一尺子见本文件 plan_really_done：runner 只在
        # 新开计划时才清 current，不能靠「它还是不是 current」判定在跑。
        "finished": bool(raw.get("finished")) or plan_really_done(raw),
        "outcome": raw.get("outcome"),
    }


def used_plan_tools(agent_messages: list) -> bool:
    """这一轮是否真的调用过计划工具。

    拿工具调用作证，不拿模型的自述当证据：模型说"我建了个计划"不算，
    真发了 create_plan 才算。
    """
    for msg in agent_messages or []:
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            block_type = getattr(block, "type", None) or (
                block.get("type") if isinstance(block, dict) else None
            )
            if block_type != "tool_use":
                continue
            name = getattr(block, "name", None) or (
                block.get("name") if isinstance(block, dict) else None
            )
            if name in PLAN_TURN_TOOLS:
                return True
    return False


def storage_plans(state: dict[str, Any]) -> list[dict[str, Any]]:
    """从 state_dict 里取出全部计划。

    agentscope 把 storage 存成 {"plans": {id: 计划}}，不是列表。按列表遍历
    只会拿到字符串键 "plans"，一个计划都取不出来。
    """
    storage = state.get("storage")
    if isinstance(storage, dict):
        plans = storage.get("plans")
        if isinstance(plans, dict):
            return [p for p in plans.values() if isinstance(p, dict)]
        if isinstance(plans, list):
            return [p for p in plans if isinstance(p, dict)]
    if isinstance(storage, list):
        return [p for p in storage if isinstance(p, dict)]
    return []


def turn_plan_snapshot(
    notebook: Any,
    agent_messages: list,
) -> dict[str, Any] | None:
    """这一轮的计划快照；这一轮没动计划就返回 None，前端也就不长卡片。

    优先取当前计划；计划办完后 current_plan 可能被清掉，退回复盘用的最后一份，
    保证"把事办完的那一轮"也有卡可看。
    """
    if notebook is None or not used_plan_tools(agent_messages):
        return None
    try:
        state = notebook_state_payload(notebook)
    except Exception:  # pragma: no cover - SDK 内部结构变化
        logger.warning("plan: snapshot state_dict failed", exc_info=True)
        return None
    current = state.get("current_plan")
    raw = current if isinstance(current, dict) else None
    if raw is None:
        plans = storage_plans(state)
        raw = plans[-1] if plans else None
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    return plan_to_dict(raw)
