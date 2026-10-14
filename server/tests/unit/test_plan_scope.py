# -*- coding: utf-8 -*-
"""片0 · 方案授权域与计划门禁测试。"""
import pytest

from coapis.plan.scope import (
    SCOPE_STATUS_EXECUTING,
    SCOPE_STATUS_PENDING,
    SCOPE_STATUS_REVOKED,
    PlanScope,
    build_plan_spec,
    classify_plan,
    confirm_session_scope,
    derive_subagent_scope,
    evaluate_scope,
    get_registry,
    sync_session_scope,
)
from coapis.security.action_semantics import ActionSemantics

SESSION = "sess-plan-scope-test"
CHILD = "sess-plan-scope-child"


@pytest.fixture(autouse=True)
def _clean_registry():
    get_registry().clear()
    yield
    get_registry().clear()


class _FakePlan:
    """最小计划本对象（对齐 agentscope 计划字段名）。"""

    def __init__(self, name, description="", subtasks=None):
        self.name = name
        self.description = description
        self.subtasks = subtasks or []


class _FakeStep:
    def __init__(self, name, description=""):
        self.name = name
        self.description = description


# ---------------------------------------------------------------------------
# 计划门禁判定
# ---------------------------------------------------------------------------


def test_pure_read_plan_can_auto_execute():
    spec = build_plan_spec(
        "梳理进度",
        "读取文档并汇总",
        [_FakeStep("读取三份文档", "读取并列出要点")],
    )
    verdict, worst, reason = classify_plan(spec)
    assert verdict == "auto_execute"
    assert worst is ActionSemantics.READ
    assert "可直接执行" in reason


def test_plan_with_external_side_effect_needs_confirmation():
    spec = build_plan_spec(
        "发布进度",
        "汇总后发送给用户",
        [
            _FakeStep("读取文档", "读取要点"),
            _FakeStep("发送汇报", "把结果发送给用户"),
        ],
    )
    verdict, worst, _ = classify_plan(spec)
    assert verdict == "needs_confirmation"
    assert rank_of(worst) >= rank_of(ActionSemantics.EXTERNAL_WRITE)


def test_plan_with_destructive_step_needs_confirmation():
    spec = build_plan_spec(
        "清理旧数据",
        "清空历史文件",
        [_FakeStep("销毁旧库", "drop table users")],
    )
    verdict, worst, reason = classify_plan(spec)
    assert verdict == "needs_confirmation"
    assert worst is ActionSemantics.DESTRUCTIVE
    assert "破坏性" in reason


def test_empty_plan_classifies_from_title():
    spec = build_plan_spec("读取并核对配置", "")
    verdict, worst, _ = classify_plan(spec)
    assert verdict == "auto_execute"
    assert worst is ActionSemantics.READ


def rank_of(sem):
    from coapis.security.action_semantics import rank

    return rank(sem)


# ---------------------------------------------------------------------------
# 授权域同步
# ---------------------------------------------------------------------------


def test_no_plan_clears_scope():
    get_registry().grant(SESSION, "旧计划", max_semantics=ActionSemantics.LOCAL_WRITE)
    verdict, _ = sync_session_scope(SESSION, None)
    assert verdict == "no_plan"
    assert get_registry().get(SESSION) is None


def test_auto_execute_plan_grants_active_scope():
    plan = _FakePlan("梳理进度", "读取汇总", [_FakeStep("读取文档", "读取要点")])
    verdict, _ = sync_session_scope(SESSION, plan)
    assert verdict == "auto_execute"
    scope = get_registry().get(SESSION)
    assert scope is not None
    assert scope.status == SCOPE_STATUS_EXECUTING
    assert scope.max_semantics is ActionSemantics.READ


def test_side_effect_plan_pends_until_confirmed():
    plan = _FakePlan("发布汇报", "发送给用户", [_FakeStep("发送", "发送给用户")])
    verdict, _ = sync_session_scope(SESSION, plan)
    assert verdict == "pending"
    scope = get_registry().get(SESSION)
    assert scope.status == SCOPE_STATUS_PENDING

    # 挂起期间不放行任何动作
    decision = evaluate_scope(SESSION, "write_file", {"file_path": "a.md"})
    assert decision.covered is False
    assert "尚未确认" in decision.reason

    # 用户确认后放行
    confirm_session_scope(SESSION)
    decision = evaluate_scope(SESSION, "write_file", {"file_path": "a.md"})
    assert decision.covered is True


def test_scope_grants_within_ceiling_only():
    get_registry().grant(
        SESSION,
        "改代码",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    assert evaluate_scope(SESSION, "read_file", {"file_path": "a.py"}).covered is True
    assert evaluate_scope(SESSION, "write_file", {"file_path": "a.py"}).covered is True
    # 删除高于上限 → 越界回落
    decision = evaluate_scope(SESSION, "delete_file", {"file_path": "a.py"})
    assert decision.covered is False
    assert "越界" in decision.reason


def test_destructive_never_covered_even_at_top_ceiling():
    get_registry().grant(
        SESSION,
        "全量清理",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.DESTRUCTIVE,
    )
    decision = evaluate_scope(
        SESSION,
        "execute_shell_command",
        {"command": "rm" + " -rf ./build"},
    )
    assert decision.covered is False
    assert "破坏性" in decision.reason


def test_tool_whitelist_out_of_scope_falls_back():
    get_registry().grant(
        SESSION,
        "只改文档",
        status=SCOPE_STATUS_EXECUTING,
        allowed_tools=("write_file", "edit_file"),
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    assert evaluate_scope(SESSION, "write_file", {"file_path": "a.md"}).covered is True
    decision = evaluate_scope(SESSION, "edit_file2", {"file_path": "a.md"})
    assert decision.covered is False
    assert "不在方案授权范围" in decision.reason


def test_path_whitelist_out_of_scope_falls_back():
    get_registry().grant(
        SESSION,
        "只改 docs",
        status=SCOPE_STATUS_EXECUTING,
        allowed_paths=("docs/",),
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    assert evaluate_scope(SESSION, "write_file", {"file_path": "docs/a.md"}).covered
    decision = evaluate_scope(SESSION, "write_file", {"file_path": "server/x.py"})
    assert decision.covered is False
    assert "路径" in decision.reason


def test_no_scope_means_no_coverage():
    decision = evaluate_scope("sess-none", "write_file", {"file_path": "a.py"})
    assert decision.covered is False
    assert "无有效方案授权域" in decision.reason


def test_scope_expiry_revokes_access():
    get_registry().grant(
        SESSION,
        "短窗口",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
        ttl_seconds=1,
    )
    scope = get_registry().get(SESSION)
    assert scope is not None
    # 直接把到期时间提前，验证过期即失效
    from datetime import datetime, timedelta, timezone

    scope.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert get_registry().get(SESSION) is None
    assert evaluate_scope(SESSION, "write_file", {}).covered is False


def test_scope_counters_record_hits_and_denials():
    get_registry().grant(
        SESSION,
        "改代码",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    evaluate_scope(SESSION, "read_file", {})
    evaluate_scope(SESSION, "delete_file", {"file_path": "a"})
    scope = get_registry().get(SESSION)
    assert scope.hits == 1
    assert scope.denials == 1


# ---------------------------------------------------------------------------
# 子智能体继承（拍板 2：继承除破坏性之外全部）
# ---------------------------------------------------------------------------


def test_subagent_inherits_scope_without_destructive():
    get_registry().grant(
        SESSION,
        "改代码",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.DESTRUCTIVE,
        allowed_paths=("src/",),
    )
    child = derive_subagent_scope(SESSION, CHILD)
    assert child is not None
    assert child.max_semantics is not ActionSemantics.DESTRUCTIVE
    assert child.origin == "subagent_inherit"
    assert child.parent_plan_id
    assert child.allowed_paths == ("src/",)

    # 子智能体域内可写，但破坏性仍不覆盖
    assert evaluate_scope(CHILD, "write_file", {"file_path": "src/a.py"}).covered
    decision = evaluate_scope(
        CHILD,
        "execute_shell_command",
        {"command": "rm" + " -rf ./x"},
    )
    assert decision.covered is False


def test_subagent_without_parent_scope_gets_nothing():
    assert derive_subagent_scope("sess-absent", CHILD) is None
    assert get_registry().get(CHILD) is None


def test_subagent_of_pending_parent_gets_nothing():
    get_registry().grant(
        SESSION,
        "待确认",
        status=SCOPE_STATUS_PENDING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    assert derive_subagent_scope(SESSION, CHILD) is None


def test_revoke_removes_scope():
    get_registry().grant(SESSION, "x", max_semantics=ActionSemantics.LOCAL_WRITE)
    assert get_registry().revoke(SESSION, "测试") is True
    assert get_registry().get(SESSION) is None
    assert get_registry().revoke(SESSION) is False


def test_snapshot_reports_active_scopes():
    get_registry().grant(
        SESSION,
        "改代码",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    snap = get_registry().snapshot()
    assert len(snap) == 1
    assert snap[0]["session_id"] == SESSION
    assert snap[0]["max_semantics"] == "local_write"
