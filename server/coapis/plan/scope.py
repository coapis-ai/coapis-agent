# -*- coding: utf-8 -*-
"""方案授权域（片0 · 限制治理地基）。

对应拍板 1：**计划源于方案，方案必须经过确认**；计划里除非涉及"出入"，
可直接执行。落地形态：

    方案确认 → 生成授权域（scope）→ 计划内动作按域放行 → 越界回落单独审批

三条硬规则（不可配置绕过）：
    1. 破坏性动作永不被授权域覆盖，一律单独审批；
    2. 未确认（pending_confirmation）的授权域不放行任何动作；
    3. 越界（工具/路径/语义任一不匹配）回落单次审批，不静默放行。

授权域按会话隔离，带 TTL，随会话结束/撤销失效。
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from coapis.security.action_semantics import (
    ActionSemantics,
    classify_action,
    get_config,
    is_destructive,
    plan_text_semantics,
    rank,
    requires_confirmation,
)

logger = logging.getLogger(__name__)

SCOPE_STATUS_PENDING = "pending_confirmation"
SCOPE_STATUS_APPROVED = "approved"
SCOPE_STATUS_EXECUTING = "executing"
SCOPE_STATUS_DONE = "done"
SCOPE_STATUS_REVOKED = "revoked"
#: 连续越界收口：方案内累计越界达阈值后置位，后续有副作用的动作一律
#: 否决并提示模型停下来向用户汇报，避免原地重试到超时。
SCOPE_STATUS_STALLED = "stalled"

#: 同一方案授权域内累计越界多少次即触发收口
PLAN_SCOPE_STRIKE_LIMIT = 3

_ACTIVE_STATUSES = frozenset({SCOPE_STATUS_APPROVED, SCOPE_STATUS_EXECUTING})

#: 默认授权域有效期（秒）
DEFAULT_SCOPE_TTL = 1800
#: 子智能体授权域有效期上限（秒）——继承可以，但窗口更短
SUBAGENT_SCOPE_TTL = 900


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class PlanStep:
    """计划中的一步。"""

    name: str
    semantics: ActionSemantics = ActionSemantics.READ
    side_effect: bool = False

    def is_destructive(self) -> bool:
        return is_destructive(self.semantics)


@dataclass
class PlanSpec:
    """计划规格（用于计划级门禁判定）。"""

    title: str
    description: str = ""
    steps: list[PlanStep] = field(default_factory=list)

    def max_semantics(self) -> ActionSemantics:
        """计划内最重的语义档。"""
        if not self.steps:
            return plan_text_semantics(f"{self.title} {self.description}")
        worst = ActionSemantics.READ
        for step in self.steps:
            if rank(step.semantics) > rank(worst):
                worst = step.semantics
        return worst

    def has_destructive(self) -> bool:
        return any(step.is_destructive() for step in self.steps)


@dataclass
class PlanScope:
    """一个会话的方案授权域。"""

    plan_id: str
    session_id: str
    title: str
    status: str
    #: 允许的工具名集合；空集合表示"计划文本语义覆盖的所有工具"
    allowed_tools: frozenset[str] = frozenset()
    #: 允许的路径前缀；空表示不限制路径（由 tool_guard 继续管路径）
    allowed_paths: tuple[str, ...] = ()
    #: 域内可免单独审批的最高语义档
    max_semantics: ActionSemantics = ActionSemantics.LOCAL_WRITE
    granted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    #: 授权来源：plan / user / subagent_inherit
    origin: str = "plan"
    #: 继承链（子智能体记录父域）
    parent_plan_id: str | None = None
    #: 发牌理由：放行原因，或等待确认的原因（控制台原样展示）
    reason: str = ""
    #: 命中统计（审计用）
    hits: int = 0
    denials: int = 0

    def is_active(self) -> bool:
        if self.status not in _ACTIVE_STATUSES:
            return False
        return self.expires_at > datetime.now(timezone.utc)

    def remaining_seconds(self) -> float:
        delta = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)


@dataclass
class ScopeDecision:
    """授权域判定结果。"""

    covered: bool
    reason: str
    semantics: ActionSemantics
    plan_id: str | None = None
    #: 判定后该方案授权域的累计越界次数，供上层做连续越界熔断
    denials: int = 0

    def __bool__(self) -> bool:
        return self.covered


# ---------------------------------------------------------------------------
# 注册表（按会话隔离）
# ---------------------------------------------------------------------------


class ScopeRegistry:
    """会话 → 授权域 的进程内注册表。"""

    def __init__(self) -> None:
        self._scopes: dict[str, PlanScope] = {}
        #: 别名键 → 同一 PlanScope（会话键与聊天 UUID 都能命中）
        self._aliases: dict[str, set[str]] = {}

    # -- 写入 ---------------------------------------------------------------

    def grant(
        self,
        session_id: str,
        title: str,
        *,
        status: str = SCOPE_STATUS_APPROVED,
        allowed_tools: Iterable[str] = (),
        allowed_paths: Iterable[str] = (),
        max_semantics: ActionSemantics = ActionSemantics.LOCAL_WRITE,
        ttl_seconds: int = DEFAULT_SCOPE_TTL,
        origin: str = "plan",
        parent_plan_id: str | None = None,
        plan_id: str | None = None,
        aliases: Iterable[str] = (),
        reason: str = "",
    ) -> PlanScope:
        """建立/覆盖一个会话的授权域。"""
        now = datetime.now(timezone.utc)
        scope = PlanScope(
            plan_id=plan_id or uuid.uuid4().hex[:12],
            session_id=session_id,
            title=title,
            status=status,
            allowed_tools=frozenset(str(t) for t in allowed_tools),
            allowed_paths=tuple(str(p) for p in allowed_paths),
            max_semantics=max_semantics,
            granted_at=now,
            expires_at=now + timedelta(seconds=max(1, int(ttl_seconds))),
            origin=origin,
            parent_plan_id=parent_plan_id,
            reason=reason,
        )
        keys = [session_id] + [
            a for a in (aliases or ()) if a and a != session_id
        ]
        for key in keys:
            stale = self._scopes.get(key)
            if stale is not None:
                self._drop_all(stale)
        for key in keys:
            self._scopes[key] = scope
        if len(keys) > 1:
            self._aliases[scope.plan_id] = set(keys[1:])
        logger.info(
            "plan-scope granted: session=%s plan=%s status=%s max=%s ttl=%ss "
            "origin=%s reason=%s",
            session_id,
            scope.plan_id,
            status,
            max_semantics.value,
            ttl_seconds,
            origin,
            reason,
        )
        return scope

    def revoke(self, session_id: str, reason: str = "") -> bool:
        """撤销授权域，返回是否存在过。"""
        scope = self._scopes.get(session_id)
        if scope is not None:
            self._drop_all(scope)
        if scope is None:
            return False
        logger.info(
            "plan-scope revoked: session=%s plan=%s reason=%s hits=%s denials=%s",
            session_id,
            scope.plan_id,
            reason or "-",
            scope.hits,
            scope.denials,
        )
        return True

    def set_status(self, session_id: str, status: str) -> PlanScope | None:
        """更新授权域状态。"""
        scope = self._scopes.get(session_id)
        if scope is None:
            return None
        scope.status = status
        return scope

    # -- 别名（同一授权域可被多个会话键命中） ---------------------

    def _drop_all(self, scope: PlanScope) -> None:
        """摘掉指向同一对象的**所有**键（主键 + 别名）。"""
        for key in [k for k, v in self._scopes.items() if v is scope]:
            self._scopes.pop(key, None)
        self._aliases.pop(scope.plan_id, None)

    def add_aliases(self, session_id: str, extras: Iterable[str]) -> bool:
        """给已存在的授权域补登别名键（如聊天 UUID ↔ 运行时会话键）。"""
        scope = self._scopes.get(session_id)
        if scope is None:
            return False
        added = False
        for key in extras:
            if not key or key == session_id:
                continue
            if self._scopes.get(key) is None:
                self._scopes[key] = scope
                added = True
        if added:
            keys = {
                k for k, v in self._scopes.items() if v is scope and k != session_id
            }
            self._aliases[scope.plan_id] = keys
        return True

    # -- 读取 ---------------------------------------------------------------

    def get(self, session_id: str) -> PlanScope | None:
        """取会话授权域；过期即清除。"""
        scope = self._scopes.get(session_id)
        if scope is None:
            return None
        if scope.status in _ACTIVE_STATUSES and scope.expires_at <= datetime.now(
            timezone.utc,
        ):
            self._drop_all(scope)
            logger.info(
                "plan-scope expired: session=%s plan=%s",
                session_id,
                scope.plan_id,
            )
            return None
        return scope

    def snapshot(self) -> list[dict[str, Any]]:
        """当前所有授权域的快照（诊断用）。"""
        out = []
        seen: list[PlanScope] = []
        # 同一授权域可能挂在多个键下（会话键 + 聊天 UUID），只报一次
        for scope in self._scopes.values():
            if any(s is scope for s in seen):
                continue
            seen.append(scope)
            out.append(
                {
                    "session_id": scope.session_id,
                    "plan_id": scope.plan_id,
                    "title": scope.title,
                    "status": scope.status,
                    "max_semantics": scope.max_semantics.value,
                    "origin": scope.origin,
                    "parent_plan_id": scope.parent_plan_id,
                    "remaining_seconds": round(scope.remaining_seconds(), 1),
                    "hits": scope.hits,
                    "denials": scope.denials,
                },
            )
        return out

    def clear(self) -> None:
        """清空（测试用）。"""
        self._scopes.clear()
        self._aliases.clear()


_REGISTRY = ScopeRegistry()


def get_registry() -> ScopeRegistry:
    """授权域注册表单例。"""
    return _REGISTRY


# ---------------------------------------------------------------------------
# 计划级门禁判定
# ---------------------------------------------------------------------------


def classify_plan(plan: PlanSpec) -> tuple[str, ActionSemantics, str]:
    """判定计划该"直接执行"还是"先确认方案"。

    返回 ``(verdict, max_semantics, reason)``，verdict ∈
    ``auto_execute`` / ``needs_confirmation``。
    """
    worst = plan.max_semantics()
    if plan.has_destructive():
        return (
            "needs_confirmation",
            ActionSemantics.DESTRUCTIVE,
            "计划含破坏性动作，必须先确认方案并逐项审批",
        )
    cfg = get_config()
    if rank(worst) <= rank(cfg.plan_auto_max):
        return (
            "auto_execute",
            worst,
            f"计划最重动作为 {worst.value}，未涉及出入，可直接执行",
        )
    return (
        "needs_confirmation",
        worst,
        f"计划最重动作为 {worst.value}，涉及出入，必须先确认方案",
    )


def build_plan_spec(
    title: str,
    description: str = "",
    subtasks: Iterable[Any] | None = None,
) -> PlanSpec:
    """从计划文本/子任务构造计划规格。

    子任务可为字符串，或含 ``name``/``description`` 的字典。
    """
    spec = PlanSpec(title=title or "", description=description or "")
    for item in subtasks or ():
        if isinstance(item, str):
            name, text = item, item
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("description") or "")
            text = str(item.get("description") or item.get("name") or "")
        else:  # pragma: no cover - 兼容 agentscope 的 SubTask 对象
            name = str(getattr(item, "name", "") or "")
            text = str(
                getattr(item, "description", "") or getattr(item, "name", "") or "",
            )
        sem = plan_text_semantics(f"{name} {text}")
        spec.steps.append(
            PlanStep(
                name=name[:200],
                semantics=sem,
                side_effect=requires_confirmation(sem),
            ),
        )
    if not spec.steps:
        sem = plan_text_semantics(f"{title} {description}")
        spec.steps.append(
            PlanStep(name=title[:200], semantics=sem, side_effect=requires_confirmation(sem)),
        )
    return spec


# ---------------------------------------------------------------------------
# 授权域判定
# ---------------------------------------------------------------------------


def _path_param(params: dict[str, Any]) -> str | None:
    for key in ("file_path", "path", "target", "dest", "source", "cwd"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def evaluate_scope(
    session_id: str,
    tool_name: str,
    params: dict[str, Any] | None = None,
) -> ScopeDecision:
    """判断一次调用是否被当前会话的方案授权域覆盖。

    覆盖 → 免单独审批；不覆盖 → 回落正常审批流程（不阻断）。
    """
    params = params or {}
    sem = classify_action(tool_name, params)

    if is_destructive(sem):
        return ScopeDecision(
            covered=False,
            reason="破坏性动作不受方案授权域覆盖",
            semantics=sem,
        )

    scope = _REGISTRY.get(session_id) if session_id else None
    if scope is None:
        return ScopeDecision(
            covered=False,
            reason="无有效方案授权域",
            semantics=sem,
        )

    if scope.status == SCOPE_STATUS_PENDING:
        scope.denials += 1
        return ScopeDecision(
            covered=False,
            reason="方案尚未确认，授权域未生效",
            semantics=sem,
            plan_id=scope.plan_id,
            denials=scope.denials,
        )

    # 收口态（stalled）仍算活跃域：纯读要放行，模型才能汇报进展；
    # 有副作用的动作由 ceiling 判越界，再交给 veto 明确否决。
    if not (
        scope.is_active() or scope.status == SCOPE_STATUS_STALLED
    ):
        return ScopeDecision(
            covered=False,
            reason="方案授权域已失效",
            semantics=sem,
            plan_id=scope.plan_id,
            denials=scope.denials,
        )

    # 语义档越界
    cfg = get_config()
    ceiling = scope.max_semantics
    if rank(sem) > rank(ceiling):
        scope.denials += 1
        return ScopeDecision(
            covered=False,
            reason=(
                f"越界：动作 {sem.value} 高于授权域上限 {ceiling.value}"
            ),
            semantics=sem,
            plan_id=scope.plan_id,
            denials=scope.denials,
        )

    # 工具白名单越界（白名单为空表示不限工具，仅按语义）
    if scope.allowed_tools and tool_name not in scope.allowed_tools:
        scope.denials += 1
        return ScopeDecision(
            covered=False,
            reason=f"越界：工具 {tool_name} 不在方案授权范围内",
            semantics=sem,
            plan_id=scope.plan_id,
            denials=scope.denials,
        )

    # 路径越界
    path = _path_param(params)
    if path and scope.allowed_paths:
        if not any(path.startswith(prefix) for prefix in scope.allowed_paths):
            scope.denials += 1
            return ScopeDecision(
                covered=False,
                reason=f"越界：路径 {path} 不在方案授权范围内",
                semantics=sem,
                plan_id=scope.plan_id,
            denials=scope.denials,
            )

    # 域内免审上限（配置层再收一道）
    if rank(sem) > rank(cfg.scope_auto_max):
        scope.denials += 1
        return ScopeDecision(
            covered=False,
            reason=f"动作 {sem.value} 高于域内免审上限 {cfg.scope_auto_max.value}",
            semantics=sem,
            plan_id=scope.plan_id,
            denials=scope.denials,
        )

    scope.hits += 1
    return ScopeDecision(
        covered=True,
        reason=f"方案授权域内放行（{sem.value} ≤ {ceiling.value}）",
        semantics=sem,
        plan_id=scope.plan_id,
    )


# ---------------------------------------------------------------------------
# 子智能体继承（拍板 2：继承除破坏性之外全部）
# ---------------------------------------------------------------------------


def derive_subagent_scope(
    parent_session_id: str,
    child_session_id: str,
    *,
    ttl_seconds: int = SUBAGENT_SCOPE_TTL,
) -> PlanScope | None:
    """把父会话授权域继承给子智能体，剔除破坏性。

    父域不存在/未确认 → 子智能体无授权域（走正常审批）。
    """
    parent = _REGISTRY.get(parent_session_id)
    if parent is None or not parent.is_active():
        return None

    cfg = get_config()
    ceiling = parent.max_semantics
    if rank(ceiling) > rank(cfg.subagent_max):
        ceiling = cfg.subagent_max

    remaining = int(parent.remaining_seconds())
    ttl = max(1, min(int(ttl_seconds), remaining or 1))

    return _REGISTRY.grant(
        child_session_id,
        title=f"继承自 {parent.title}",
        status=SCOPE_STATUS_EXECUTING,
        allowed_tools=parent.allowed_tools,
        allowed_paths=parent.allowed_paths,
        max_semantics=ceiling,
        ttl_seconds=ttl,
        origin="subagent_inherit",
        parent_plan_id=parent.plan_id,
        reason=parent.reason,
    )


# ---------------------------------------------------------------------------
# 与计划本同步（每轮推理开始时调用）
# ---------------------------------------------------------------------------


def _plan_to_spec(plan: Any) -> PlanSpec | None:
    """把计划本对象转成 PlanSpec；无法识别时返回 None。"""
    if plan is None:
        return None
    title = str(getattr(plan, "name", "") or getattr(plan, "title", "") or "")
    desc = str(getattr(plan, "description", "") or "")
    subtasks = getattr(plan, "subtasks", None) or getattr(plan, "steps", None) or []
    if not title and not desc and not subtasks:
        return None
    return build_plan_spec(title, desc, subtasks)


def sync_session_scope(
    session_id: str,
    plan: Any,
    *,
    auto_approve_pure_read: bool = True,
    aliases: Iterable[str] = (),
) -> tuple[str, str]:
    """按当前计划同步会话授权域。

    返回 ``(verdict, reason)``：

    - ``no_plan``      无计划 → 撤销授权域
    - ``auto_execute`` 纯读取/工作区内动作 → 直接生效
    - ``pending``      涉及出入/破坏性 → 挂起，等用户确认方案
    - ``approved``     用户已确认 → 生效
    - ``unchanged``    与已生效的域一致，无需变动
    """
    if not session_id:
        return ("no_session", "无会话标识")

    spec = _plan_to_spec(plan)
    existing = _REGISTRY.get(session_id)

    if spec is None:
        if existing is not None:
            _REGISTRY.revoke(session_id, reason="计划已结束/清空")
        return ("no_plan", "无计划，授权域已清空")

    verdict, worst, reason = classify_plan(spec)

    # 已确认过的同一计划不重复处理
    if existing is not None and existing.status in _ACTIVE_STATUSES:
        if existing.title == spec.title and existing.max_semantics == worst:
            return ("unchanged", reason)
    # ── F2 防洗白：用户尚未回应的"待确认"不因换标题而失效 ────────
    # 模型把待确认的破坏性方案改个标题重新登记，新文案若读起来"无害"，
    # 就会落到下面的 auto_execute 分支被重新发牌成 EXECUTING —— 等于
    # 绕过用户确认（E2E 实测：scope 仍显示 pending，3 个文件照删）。
    # 规则：pending 只能被用户的 confirm/deny 或 TTL 过期终结；
    #       重新规划最多补充别名，绝不降级、绝不静默放行。
    if existing is not None and existing.status == SCOPE_STATUS_PENDING:
        if aliases:
            _REGISTRY.add_aliases(session_id, aliases)
        return ("pending", reason)


    if verdict == "auto_execute":
        if not auto_approve_pure_read:
            return ("pending", reason)
        _REGISTRY.grant(
            session_id,
            title=spec.title,
            status=SCOPE_STATUS_EXECUTING,
            max_semantics=worst,
            origin="plan_auto",
            aliases=aliases,
            reason=reason,
        )
        return ("auto_execute", reason)

    # 同一轮反复同步时不重新发牌：档位没升级、仍是待确认 → 保留原域与原
    # TTL。否则每步都 mint 新 plan_id，会刷掉 TTL 并反复注入确认提示
    # （实测 pending 发牌 62 次，正是"一轮重建 50 个计划"的放大器）。
    if (
        existing is not None
        and existing.status == SCOPE_STATUS_PENDING
        and rank(worst) <= rank(existing.max_semantics)
    ):
        if aliases:
            _REGISTRY.add_aliases(existing.session_id, aliases)
        return ("pending", reason)

    # 需要确认：挂起，不放行任何动作
    _REGISTRY.grant(
        session_id,
        title=spec.title,
        status=SCOPE_STATUS_PENDING,
        max_semantics=worst,
        origin="plan_confirm",
        aliases=aliases,
        reason=reason,
    )
    return ("pending", reason)


def add_scope_aliases(session_id: str, aliases: Iterable[str]) -> bool:
    """把同一计划的多个会话键并入一条授权域。

    运行时会话键（如 ``console:admin``）与聊天 UUID 不是同一个字符串，
    前端确认时用的是聊天键。不并键的话，确认请求永远找不到那条待确认域
    ——这就是"方案确认未接线"的另一半。
    """
    return _REGISTRY.add_aliases(session_id, aliases)


def peek_scope(session_id: str) -> "PlanScope | None":
    """只读查看某会话的授权域（含别名键）；不存在或已过期返回 None。"""
    return _REGISTRY.get(session_id)


def confirm_session_scope(session_id: str, plan_title: str = "") -> PlanScope | None:
    """用户确认方案后放行授权域（状态 pending → executing）。"""
    scope = _REGISTRY.get(session_id)
    if scope is None:
        return None
    if plan_title and scope.title != plan_title:
        return None
    return _REGISTRY.set_status(session_id, SCOPE_STATUS_EXECUTING)


__all__ = [
    "DEFAULT_SCOPE_TTL",
    "PlanScope",
    "PlanSpec",
    "PlanStep",
    "SUBAGENT_SCOPE_TTL",
    "ScopeDecision",
    "ScopeRegistry",
    "build_plan_spec",
    "classify_plan",
    "confirm_session_scope",
    "peek_scope",
    "derive_subagent_scope",
    "evaluate_scope",
    "get_registry",
    "sync_session_scope",
    "add_scope_aliases",
]
