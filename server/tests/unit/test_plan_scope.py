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
    peek_scope,
    sync_session_scope,
)
from coapis.plan.scope import (
    add_scope_aliases,
    confirm_session_scope,
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




class _ProbePlan:
    """鸭子类型的计划（只用到 name/description/subtasks）。"""

    def __init__(self, name, description, subtasks):
        self.name = name
        self.description = description
        self.subtasks = [{"name": s, "description": s} for s in subtasks]


def test_alias_key_can_confirm_and_revoke():
    """发牌用运行时会话键，确认用聊天 UUID：两个键必须指向同一条域。"""
    reg = get_registry()
    scope = reg.grant(
        SESSION,
        "改代码",
        max_semantics=ActionSemantics.LOCAL_WRITE,
        aliases=["chat-uuid-1"],
    )
    assert reg.get("chat-uuid-1") is scope

    assert confirm_session_scope("chat-uuid-1") is not None
    assert reg.get(SESSION).status == SCOPE_STATUS_EXECUTING

    assert reg.revoke(SESSION, "测试") is True
    assert reg.get("chat-uuid-1") is None


def test_add_aliases_merges_keys_after_grant():
    """发牌之后才知道聊天 UUID：补登别名也要能撤销干净。"""
    reg = get_registry()
    scope = reg.grant(
        SESSION,
        "改代码",
        max_semantics=ActionSemantics.LOCAL_WRITE,
    )
    assert add_scope_aliases(SESSION, ["chat-uuid-2", ""]) is True
    assert reg.get("chat-uuid-2") is scope
    assert reg.revoke("chat-uuid-2", "测试") is True
    assert reg.get(SESSION) is None


def test_snapshot_reports_alias_scope_once():
    reg = get_registry()
    reg.grant(
        SESSION,
        "改代码",
        status=SCOPE_STATUS_EXECUTING,
        max_semantics=ActionSemantics.LOCAL_WRITE,
        aliases=["chat-uuid-3"],
    )
    assert len(reg.snapshot()) == 1


def test_pending_scope_is_not_reminted_on_repeat_sync():
    """反复同步不该重新发牌：否则刷 TTL、反复注入确认提示，实测放大成
    一轮重建 50 个计划。"""
    reg = get_registry()
    plan = _ProbePlan("发通知", "把结果发送给用户", ["发送消息给张三"])

    first, _ = sync_session_scope(SESSION, plan, aliases=["chat-uuid-4"])
    scope1 = reg.get(SESSION)
    second, _ = sync_session_scope(SESSION, plan)
    scope2 = reg.get(SESSION)

    assert first == "pending"
    assert second == "pending"
    assert scope1 is not None and scope2 is not None
    assert scope1.plan_id == scope2.plan_id
    assert reg.get("chat-uuid-4") is scope2


def test_workspaced_plan_syncs_to_auto_execute():
    """工作区内写入不该被当成出入，否则几乎每个计划都要用户确认。"""
    reg = get_registry()
    plan = _ProbePlan(
        "三步写入验证",
        "在工作区写文件并读回核对",
        ["write_file 写 a.txt", "read_file 读回核对"],
    )
    state, _ = sync_session_scope(SESSION, plan)
    assert state == "auto_execute"
    assert reg.get(SESSION).status == SCOPE_STATUS_EXECUTING


# ---------------------------------------------------------------------------


def _spec_external():
    return build_plan_spec(
        "发布进度",
        "汇总后发送给用户",
        [
            _FakeStep("读取文档", "读取要点"),
            _FakeStep("发送汇报", "把结果发送给用户"),
        ],
    )


def test_auto_scope_carries_classifier_reason():
    spec = build_plan_spec(
        "梳理进度",
        "读取文档并汇总",
        [_FakeStep("读取三份文档", "读取并列出要点")],
    )
    verdict, reason = sync_session_scope(SESSION, spec, aliases=("alias-auto",))
    assert verdict == "auto_execute"
    scope = peek_scope("alias-auto")
    assert scope is not None
    assert scope.status == SCOPE_STATUS_EXECUTING
    # 放行也要留理由：控制台与审计都要能看到"为什么直接执行"
    assert scope.reason == reason
    assert scope.reason


def test_pending_scope_reason_explains_confirmation():
    verdict, reason = sync_session_scope(
        SESSION, _spec_external(), aliases=("alias-pending",)
    )
    assert verdict == "pending"
    scope = peek_scope("alias-pending")
    assert scope is not None
    assert scope.status == SCOPE_STATUS_PENDING
    # 理由不能只活在返回值里：确认卡渲染的是 scope.reason
    assert scope.reason == reason
    assert scope.reason


def test_inherited_scope_keeps_parent_reason():
    get_registry().grant(
        SESSION,
        "父计划",
        allowed_tools=("*",),
        reason="父域理由",
    )
    child = derive_subagent_scope(SESSION, "child-of-" + SESSION)
    assert child.reason == "父域理由"


def test_plan_router_only_reads_declared_scope_attributes():
    """路由里 scope.<attr> 的每个名字都必须在 PlanScope 上真实存在。"""
    import ast
    import dataclasses
    from pathlib import Path

    from coapis.plan.scope import PlanScope

    router = Path(__file__).resolve().parents[2] / "coapis" / "app" / "routers" / "plan.py"
    tree = ast.parse(router.read_text(encoding="utf-8"))
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "scope":
                used.add(node.attr)
    assert used, "路由里没找到任何 scope.<attr>，这条契约测试本身失效了"
    declared = {f.name for f in dataclasses.fields(PlanScope)} | set(dir(PlanScope))
    missing = sorted(used - declared)
    assert not missing, "路由读取了 PlanScope 上不存在的属性: %s" % missing


def test_replanning_cannot_downgrade_pending_to_auto_execute():
    """用户还没回应时，换个标题重新规划不得把待确认洗成免确认执行。

    回归：E2E 里模型把待确认的破坏性方案改了名重报，新文案读起来
    "无害"，sync 就落到 auto_execute 分支重新发牌成 EXECUTING，
    于是 scope 仍显示待确认、文件却照删。pending 只能由用户回应
    （或 TTL 过期）终结，重新规划最多补别名。
    """
    spec = build_plan_spec(
        "发布进度",
        "汇总后发送给用户",
        [
            _FakeStep("读取文档", "读取要点"),
            _FakeStep("发送汇报", "把结果发送给用户"),
        ],
    )
    verdict, _ = sync_session_scope(SESSION, spec)
    assert verdict == "pending"

    # 换一个"读起来人畜无害"的标题与只读步骤重新登记
    swapped = build_plan_spec(
        "整理并查看汇总",
        "读取汇总文件内容",
        [_FakeStep("查看汇总", "读取汇总文件内容")],
    )
    verdict2, _ = sync_session_scope(SESSION, swapped)
    assert verdict2 == "pending"
    scope = peek_scope(SESSION)
    assert scope is not None
    assert scope.status == SCOPE_STATUS_PENDING
