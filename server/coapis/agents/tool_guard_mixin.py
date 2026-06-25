# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tool-guard mixin for CoApisAgent.

Provides ``_acting`` and ``_reasoning`` overrides that intercept
sensitive tool calls before execution, implementing the deny /
guard / approve flow.

Separated from ``react_agent.py`` to keep the main agent class
focused on lifecycle management.
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import uuid as _uuid
from typing import TYPE_CHECKING, Any, Literal

from agentscope.message import Msg

from ..security.tool_guard.models import (
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
    GuardFinding,
)
from ..security.tool_guard.execution_level import ToolExecutionLevel
from ..security.tool_guard.i18n import _TOOL_GUARD_I18N
from ..constant import (
    TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
    TOOL_GUARD_APPROVAL_HEARTBEAT_INTERVAL,
)

if TYPE_CHECKING:
    from coapis.app.approvals.models import PendingApproval
    from coapis.security.tool_guard.approval import ApprovalDecision

logger = logging.getLogger(__name__)


def _normalize_tool_guard_ui_lang(raw: Any) -> str:
    """Map language code to tool-guard UI bundle (en/zh/ru/ja)."""
    if not isinstance(raw, str) or not raw.strip():
        return "en"
    s = raw.strip().lower()
    if s in ("zh", "en", "ru", "ja"):
        return s
    for prefix in ("zh", "ru", "ja", "en"):
        if s.startswith(prefix):
            return prefix
    return "en"


def _tool_guard_t(lang: str, key: str) -> str:
    """Localized string for tool-guard user messages."""
    blob = _TOOL_GUARD_I18N.get(lang) or _TOOL_GUARD_I18N["en"]
    return blob.get(key) or _TOOL_GUARD_I18N["en"].get(key, key)


class _GuardAction:
    """Lightweight container for a guard decision made under lock."""

    __slots__ = ("kind", "tool_name", "tool_input", "guard_result")

    def __init__(
        self,
        kind: str,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        guard_result: Any = None,
    ) -> None:
        self.kind = kind
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.guard_result = guard_result


class ToolGuardMixin:
    """Mixin that adds tool-guard interception to a ReActAgent.

    At runtime this class is always combined with
    ``agentscope.agent.ReActAgent`` via MRO, so ``super()._acting``
    and ``super()._reasoning`` resolve to the concrete agent methods.
    """

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _init_tool_guard(self) -> None:
        """Lazy-init tool-guard components (called once)."""
        from coapis.security.tool_guard.engine import get_guard_engine
        from coapis.app.approvals import get_approval_service

        self._tool_guard_engine = get_guard_engine()
        self._tool_guard_approval_service = get_approval_service()
        self._tool_guard_pending_info: dict | None = None
        self._tool_guard_lock = asyncio.Lock()

    def _ensure_tool_guard(self) -> None:
        if not hasattr(self, "_tool_guard_engine"):
            self._init_tool_guard()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_require_approval(self) -> bool:
        """``True`` when a ``session_id`` is available for approval."""
        return bool(self._request_context.get("session_id"))

    def _get_current_user_role(self) -> str:
        """Get current user's role from context.
        
        Returns:
            User role string (user/advanced/admin), defaults to 'user'
        """
        try:
            from coapis.config.context import get_current_user_role
            role = get_current_user_role()
            if role:
                return role
        except (ImportError, RuntimeError):
            pass
        return "user"

    def _get_tool_execution_level(self) -> ToolExecutionLevel:
        """Get current tool execution level.

        Priority:
        1. Explicit agent config (approval_level in agent.json)
        2. Role-based default (user=SMART, admin=AUTO)
        3. Fallback: AUTO
        """
        agent_config = getattr(self, "_agent_config", None)
        config_level = None

        if agent_config is not None:
            if isinstance(agent_config, dict):
                level_str = agent_config.get("approval_level")
            else:
                level_str = getattr(agent_config, "approval_level", None)
            if level_str:
                config_level = ToolExecutionLevel.from_config(level_str)

        # Apply role-based default when config doesn't specify
        from ..security.tool_guard.execution_level import get_effective_execution_level
        role = self._get_current_user_role()
        return get_effective_execution_level(config_level, role)

    def _tool_guard_ui_lang(self) -> str:
        """Locale for tool-guard alerts from agent language."""
        raw = getattr(self, "_language", None)
        if isinstance(raw, str) and raw.strip():
            return _normalize_tool_guard_ui_lang(raw)
        return "en"

    # ------------------------------------------------------------------
    # _acting override
    # ------------------------------------------------------------------

    async def _acting(self, tool_call) -> dict | None:  # noqa: C901
        """Intercept sensitive tool calls before execution.

        1. If tool is in *denied_tools*, auto-deny unconditionally.
        2. If tool is in the guarded scope, check for a one-shot
           pre-approval, then run all guardians.
        3. For non-guarded tools, run only ``always_run`` guardians
           (e.g. sensitive file path checks).
        4. If findings exist, enter the approval flow.
        5. Otherwise, delegate to ``super()._acting``.

        The guard *decision* block is serialised via ``_tool_guard_lock``
        so that ``parallel_tool_calls=True`` does not cause state races
        on shared mixin attributes.  Actual tool execution (both
        pre-approved and non-guarded) runs **outside** the lock for
        true parallelism.
        """
        ctx = getattr(self, "_request_context", None) or {}
        # TODO: remove this
        if ctx.get("_headless_tool_guard", "true").lower() == "false":
            return await super()._acting(tool_call)  # type: ignore[misc]

        self._ensure_tool_guard()

        # ── ToolCallMonitor: behavioral blocking ──
        # Check if the user is blocked due to anomalous behavior patterns
        try:
            from ..security.tool_monitor import get_tool_call_monitor
            monitor = get_tool_call_monitor()
            username = ctx.get("username", "unknown")
            blocked, reason = monitor.should_block(username)
            if blocked:
                logger.warning(
                    "ToolCallMonitor blocked tool call for %s: %s",
                    username, reason,
                )
                # Write audit event for behavioral blocking
                try:
                    from .security.audit_logger import AuditLogger, create_audit_event
                    ev = create_audit_event(
                        event_type="tool_monitor_blocked",
                        tool_name=tool_name,
                        command=tool_input.get("command", ""),
                        result="blocked",
                        reason=reason,
                    )
                    ev.risk_level = "critical"
                    ev.confirm_result = "monitor_blocked"
                    AuditLogger.log(ev)
                except Exception:
                    pass
                return await super()._acting(tool_call)  # type: ignore[misc]
        except Exception:
            pass  # Non-blocking: if monitor unavailable, proceed

        action: _GuardAction | None = None
        async with self._tool_guard_lock:
            try:
                action = await self._decide_guard_action(tool_call)
            except Exception as exc:
                logger.warning(
                    "Tool guard check error (non-blocking): %s",
                    exc,
                    exc_info=True,
                )

        if action is not None:
            return await self._execute_guard_action(action, tool_call)

        return await super()._acting(tool_call)  # type: ignore[misc]

    # pylint: disable=too-many-return-statements
    async def _decide_guard_action(
        self,
        tool_call: dict[str, Any],
    ) -> "_GuardAction | None":
        """Decide what guard action to take with execution level support.

        Returns a ``_GuardAction`` describing what to do, or ``None``
        to fall through to the default ``super()._acting`` path.
        No actual tool execution happens here.
        """
        engine = self._tool_guard_engine
        tool_name = str(tool_call.get("name", ""))
        tool_input = tool_call.get("input", {})

        if not tool_name or not engine.enabled:
            return None

        # Get tool execution level and user role
        exec_level = self._get_tool_execution_level()
        user_role = self._get_current_user_role()

        # OFF mode: completely bypass guard
        if exec_level.is_disabled():
            logger.debug(
                "Tool guard: OFF mode, allowing tool '%s' without checks",
                tool_name,
            )
            return None

        # Check denied list (applies to all modes and all roles)
        if engine.is_denied(tool_name):
            logger.warning(
                "Tool guard: tool '%s' is in denied set, auto-denying "
                "(user=%s, role=%s)",
                tool_name,
                tool_name,
                user_role,
            )
            denied_result = engine.guard(tool_name, tool_input)
            return _GuardAction(
                "auto_denied",
                tool_name,
                tool_input,
                guard_result=denied_result,
            )

        # ── CommandRiskClassifier: three-level classification ──
        # Only applies to shell commands; non-shell tools skip this layer
        # to avoid false positives from URL/file path parameters.
        if tool_name != "execute_shell_command":
            cr = None  # skip CommandRiskClassifier for non-shell tools
        else:
            cr = None
            try:
                from ..security.command_risk_classifier import (
                    CommandRiskClassifier,
                )
                if not hasattr(self, "_command_risk_classifier"):
                    self._command_risk_classifier = CommandRiskClassifier()
                cr = self._command_risk_classifier.classify(
                    tool_name, tool_input, user_role,
                )
            except Exception as exc:
                logger.debug(
                    "CommandRiskClassifier error (non-blocking): %s", exc,
                )

        if cr is not None:
            from ..security.command_risk_classifier import CommandRiskLevel
            if cr.risk_level == CommandRiskLevel.DENIED:
                logger.warning(
                    "CommandRiskClassifier: DENIED tool=%s role=%s "
                    "category=%s reason=%s",
                    tool_name, user_role, cr.command_category.value,
                    cr.reason,
                )
                return _GuardAction(
                    "auto_denied", tool_name, tool_input,
                    guard_result=ToolGuardResult(
                        tool_name=tool_name, params=tool_input,
                        findings=[GuardFinding(
                            id="risk-classifier-denied",
                            rule_id="command_risk_classifier",
                            category=GuardThreatCategory.COMMAND_INJECTION,
                            severity=GuardSeverity.CRITICAL,
                            title="Command Risk: DENIED",
                            description=cr.reason,
                            tool_name=tool_name, param_name="command",
                            matched_value=None, matched_pattern=None,
                            snippet=None, remediation=cr.reason,
                            guardian="command_risk_classifier",
                            metadata={
                                "risk_level": cr.risk_level.value,
                                "command_category": cr.command_category.value,
                            },
                        )],
                        guardians_used=["command_risk_classifier"],
                    ),
                )
            if cr.risk_level == CommandRiskLevel.BLOCK:
                logger.warning(
                    "CommandRiskClassifier: BLOCK tool=%s role=%s "
                    "category=%s reason=%s",
                    tool_name, user_role, cr.command_category.value,
                    cr.reason,
                )
                return _GuardAction(
                    "auto_denied", tool_name, tool_input,
                    guard_result=ToolGuardResult(
                        tool_name=tool_name, params=tool_input,
                        findings=[GuardFinding(
                            id="risk-classifier-block",
                            rule_id="command_risk_classifier",
                            category=GuardThreatCategory.COMMAND_INJECTION,
                            severity=GuardSeverity.CRITICAL,
                            title="Command Risk: BLOCK",
                            description=cr.reason,
                            tool_name=tool_name, param_name="command",
                            matched_value=None, matched_pattern=None,
                            snippet=None, remediation=cr.reason,
                            guardian="command_risk_classifier",
                            metadata={
                                "risk_level": cr.risk_level.value,
                                "command_category": cr.command_category.value,
                            },
                        )],
                        guardians_used=["command_risk_classifier"],
                    ),
                )
            if cr.risk_level == CommandRiskLevel.CONFIRM:
                # Still run engine.guard for detailed findings, but
                # always require approval regardless of execution level
                logger.info(
                    "CommandRiskClassifier: CONFIRM tool=%s role=%s "
                    "category=%s timeout=%ds",
                    tool_name, user_role, cr.command_category.value,
                    cr.timeout_seconds,
                )
                guard_result = engine.guard(
                    tool_name, tool_input, only_always_run=False,
                )
                if guard_result is None or not guard_result.findings:
                    guard_result = self._create_risk_classifier_finding(
                        tool_name, tool_input, cr,
                    )
                return _GuardAction(
                    "needs_approval", tool_name, tool_input,
                    guard_result=guard_result,
                )
            # AUTO → fall through to existing execution-level logic

        # Role-based policy: admin gets relaxed checks for low-risk tools
        if user_role == "admin" and exec_level.is_smart_mode():
            # Admin can auto-allow even MEDIUM risk in SMART mode
            guarded = engine.is_guarded(tool_name)
            guard_result = engine.guard(
                tool_name,
                tool_input,
                only_always_run=not guarded,
            )

            if guard_result is not None and guard_result.findings:
                max_sev = guard_result.max_severity
                if max_sev in (GuardSeverity.INFO, GuardSeverity.LOW, GuardSeverity.MEDIUM):
                    logger.info(
                        "Tool guard: Admin auto-allowing tool '%s' "
                        "(severity: %s, role: admin)",
                        tool_name,
                        max_sev.value,
                    )
                    return None

        # STRICT mode: all tools need approval
        if exec_level.requires_approval_for_all_tools():
            if self._should_require_approval():
                # Run guard checks
                guard_result = engine.guard(
                    tool_name,
                    tool_input,
                    only_always_run=False,
                )
                # If no findings, create INFO-level finding for STRICT mode
                if guard_result is None or not guard_result.findings:
                    guard_result = self._create_info_guard_result(
                        tool_name,
                        tool_input,
                    )
                return _GuardAction(
                    "needs_approval",
                    tool_name,
                    tool_input,
                    guard_result=guard_result,
                )
            return None

        # Run guard checks for AUTO/SMART modes
        guarded = engine.is_guarded(tool_name)
        guard_result = engine.guard(
            tool_name,
            tool_input,
            only_always_run=not guarded,
        )

        if guard_result is None or not guard_result.findings:
            return None

        from coapis.security.tool_guard.utils import log_findings

        log_findings(tool_name, guard_result)

        # SMART mode: auto-allow low-risk findings
        if exec_level.is_smart_mode():
            max_sev = guard_result.max_severity
            if max_sev in (GuardSeverity.INFO, GuardSeverity.LOW):
                logger.info(
                    "Tool guard: SMART mode auto-allowing low-risk tool '%s' "
                    "(severity: %s)",
                    tool_name,
                    max_sev.value,
                )
                return None  # Allow

        # AUTO/SMART modes: medium+ risk needs approval
        if self._should_require_approval():
            return _GuardAction(
                "needs_approval",
                tool_name,
                tool_input,
                guard_result=guard_result,
            )

        return None

    def _create_risk_classifier_finding(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        classification: Any,
    ) -> ToolGuardResult:
        """Create a ToolGuardResult from CommandRiskClassifier CONFIRM result."""
        finding = GuardFinding(
            id="risk-classifier-confirm",
            rule_id="command_risk_classifier",
            category=GuardThreatCategory.COMMAND_INJECTION,
            severity=GuardSeverity.HIGH,
            title=f"Command Risk: CONFIRM ({classification.command_category.value})",
            description=classification.reason,
            tool_name=tool_name,
            param_name="command",
            matched_value=None,
            matched_pattern=None,
            snippet=None,
            remediation="User confirmation required for this command category",
            guardian="command_risk_classifier",
            metadata={
                "risk_level": classification.risk_level.value,
                "command_category": classification.command_category.value,
                "timeout_seconds": classification.timeout_seconds,
            },
        )

        return ToolGuardResult(
            tool_name=tool_name,
            params=tool_input,
            findings=[finding],
            guardians_used=["command_risk_classifier"],
        )

    def _log_approval_audit(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        guard_result,
        confirm_result: str,
    ) -> None:
        """Write an audit event for approval flow outcomes."""
        try:
            from .security.audit_logger import AuditLogger, create_audit_event
            risk_level = ""
            cmd_category = ""
            if guard_result is not None and guard_result.findings:
                for f in guard_result.findings:
                    if f.metadata:
                        risk_level = f.metadata.get("risk_level", risk_level)
                        cmd_category = f.metadata.get("command_category", cmd_category)
            ev = create_audit_event(
                event_type="tool_guard_approval",
                tool_name=tool_name,
                command=tool_input.get("command", ""),
                result=confirm_result,
                reason=f"approval {confirm_result}",
            )
            ev.risk_level = risk_level or "confirm"
            ev.command_category = cmd_category
            ev.confirm_result = confirm_result
            AuditLogger.log(ev)
        except Exception:
            pass

    def _create_info_guard_result(
        self,
        tool_name: str,
        tool_input: dict[str, Any],  # noqa: ARG002
    ) -> ToolGuardResult:
        """Create INFO-level guard result for STRICT mode."""
        finding = GuardFinding(
            id=str(_uuid.uuid4())[:8],
            rule_id="strict_mode",
            category=GuardThreatCategory.RESOURCE_ABUSE,
            severity=GuardSeverity.INFO,
            title="STRICT Mode Approval",
            description=(
                f"Tool '{tool_name}' requires approval in STRICT mode"
            ),
            tool_name=tool_name,
            param_name=None,
            matched_value=None,
            matched_pattern=None,
            snippet=None,
            remediation="Approve or deny this tool call",
            guardian="strict_mode",
            metadata={"reason": "strict_mode_enabled"},
        )

        return ToolGuardResult(
            tool_name=tool_name,
            params=tool_input,
            findings=[finding],
            guardians_used=["strict_mode"],
        )

    async def _execute_guard_action(
        self,
        action: "_GuardAction",
        tool_call: dict[str, Any],
    ) -> dict | None:
        """Execute the guard action decided under lock (runs outside lock)."""
        if action.kind == "auto_denied":
            return await self._acting_auto_denied(
                tool_call,
                action.tool_name,
                action.guard_result,
            )
        if action.kind == "needs_approval":
            return await self._acting_with_approval(
                tool_call,
                action.tool_name,
                action.guard_result,
            )
        return None

    # ------------------------------------------------------------------
    # Denied / Approval responses
    # ------------------------------------------------------------------

    async def _acting_auto_denied(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        guard_result=None,
    ) -> dict | None:
        """Auto-deny a tool call without offering approval."""
        from agentscope.message import ToolResultBlock
        from coapis.security.tool_guard.approval import (
            format_findings_summary,
        )

        lang = self._tool_guard_ui_lang()

        def tg(key: str) -> str:
            return _tool_guard_t(lang, key)

        if guard_result is not None and guard_result.findings:
            findings_text = format_findings_summary(guard_result)
            severity = guard_result.max_severity.value
            count = str(guard_result.findings_count)
        else:
            findings_text = f"- {tg('denied_list_msg')}"
            severity = tg("severity_denied")
            count = tg("na_count")

        # Adaptive format: markdown for supported channels, plain text otherwise
        channel = str(self._request_context.get("channel") or "")
        _MD_CHANNELS = {"wecom", "dingtalk", "discord", "telegram"}
        use_md = channel in _MD_CHANNELS or channel.startswith("wecom")

        if use_md:
            denied_text = (
                f"{tg('tool_blocked')}\n\n"
                f"- {tg('tool')}: `{tool_name}`\n"
                f"- {tg('severity')}: `{severity}`\n"
                f"- {tg('findings')}: `{count}`\n\n"
                f"{findings_text}\n\n"
                f"{tg('blocked_footer')}"
            )
        else:
            denied_text = (
                f"{tg('tool_blocked')}\n\n"
                f"  {tg('tool')}: {tool_name}\n"
                f"  {tg('severity')}: {severity}\n"
                f"  {tg('findings')}: {count}\n\n"
                f"{findings_text}\n\n"
                f"{tg('blocked_footer')}"
            )

        tool_res_msg = Msg(
            "system",
            [
                ToolResultBlock(
                    type="tool_result",
                    id=tool_call["id"],
                    name=tool_name,
                    output=[
                        {"type": "text", "text": denied_text},
                    ],
                ),
            ],
            "system",
        )

        await self.print(tool_res_msg, True)
        await self.memory.add(tool_res_msg)

        # Write audit event with risk classification fields
        try:
            from .security.audit_logger import AuditLogger, create_audit_event
            meta_extra = {}
            risk_level = ""
            cmd_category = ""
            if guard_result is not None and guard_result.findings:
                for f in guard_result.findings:
                    if f.metadata:
                        risk_level = f.metadata.get("risk_level", risk_level)
                        cmd_category = f.metadata.get("command_category", cmd_category)
            ev = create_audit_event(
                event_type="tool_guard_denied",
                tool_name=tool_name,
                command=tool_input.get("command", ""),
                result="denied",
                reason=f"auto_denied by tool guard",
                metadata=meta_extra,
            )
            ev.risk_level = risk_level or "block"
            ev.command_category = cmd_category
            ev.confirm_result = "denied"
            AuditLogger.log(ev)
        except Exception:
            pass

        return None

    async def _acting_with_approval(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        guard_result,
    ) -> dict | None:
        """Block and wait for user approval with heartbeat keep-alive.

        This method creates a Future, sends an approval request message to
        the user, then blocks waiting for the Future to be resolved by
        /approval approve or /approval deny command. During the wait,
        periodic heartbeat messages are sent to keep SSE connection alive.
        """
        from coapis.security.tool_guard.approval import ApprovalDecision

        session_id = str(self._request_context.get("session_id") or "")
        user_id = str(self._request_context.get("user_id") or "")
        channel = str(self._request_context.get("channel") or "")
        agent_id = str(self._request_context.get("agent_id", "unknown"))

        # Get root_session_id for cross-session approval routing
        root_session_id = str(
            self._request_context.get("root_session_id") or session_id,
        )

        svc = self._tool_guard_approval_service
        tool_call_id = tool_call.get("id", "")

        # Cancel any stale pending approvals for this tool call
        if session_id and tool_call_id:
            await svc.cancel_stale_pending_for_tool_call(
                session_id,
                tool_call_id,
            )

        # Create pending approval with Future
        extra: dict[str, Any] = {"tool_call": tool_call}
        pending = await svc.create_pending(
            session_id=session_id,
            root_session_id=root_session_id,
            user_id=user_id,
            channel=channel,
            agent_id=agent_id,
            tool_name=tool_name,
            result=guard_result,
            timeout_seconds=TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
            extra=extra,
        )

        # Send approval request message to user (with frontend metadata)
        await self._emit_waiting_for_approval_blocking(pending, guard_result)

        # **Block and wait** for approval decision with heartbeat
        try:
            decision = await self._wait_for_approval_with_heartbeat(
                pending.request_id,
                pending.future,
                timeout_seconds=TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.error(
                "Wait for approval failed: %s",
                exc,
                exc_info=True,
            )
            decision = ApprovalDecision.TIMEOUT

        # Execute or deny based on decision
        if decision == ApprovalDecision.APPROVED:
            logger.info(
                "Tool '%s' approved by user, executing...",
                tool_name,
            )
            # Audit: approved
            self._log_approval_audit(tool_name, tool_input, guard_result, "approved")
            # Execute the tool
            return await super()._acting(tool_call)  # type: ignore[misc]
        elif decision == ApprovalDecision.DENIED:
            logger.info(
                "Tool '%s' denied by user",
                tool_name,
            )
            self._log_approval_audit(tool_name, tool_input, guard_result, "denied")
            return await self._acting_denied(
                tool_call,
                tool_name,
                guard_result,
            )
        else:  # TIMEOUT
            logger.warning(
                "Tool '%s' approval timeout (%ds)",
                tool_name,
                TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
            )
            self._log_approval_audit(tool_name, tool_input, guard_result, "timeout")
            return await self._acting_timeout(
                tool_call,
                tool_name,
                guard_result,
            )

    # pylint: disable=unused-argument
    async def _wait_for_approval_with_heartbeat(
        self,
        request_id: str,
        future: "asyncio.Future[ApprovalDecision]",
        timeout_seconds: float,
        heartbeat_interval: float = (TOOL_GUARD_APPROVAL_HEARTBEAT_INTERVAL),
    ) -> "ApprovalDecision":
        """Wait for approval decision with timeout and cancellation support.

        Waits for approval Future while also listening for task cancellation.
        If the outer task is cancelled (e.g., user /stop), immediately
        auto-denies the approval and re-raises CancelledError.

        Args:
            request_id: Approval request ID
            future: Future to wait for
            timeout_seconds: Total timeout in seconds
            heartbeat_interval: Unused (kept for API compatibility)

        Returns:
            ApprovalDecision (APPROVED/DENIED/TIMEOUT)
        """
        from coapis.security.tool_guard.approval import (
            ApprovalDecision,
        )

        logger.debug(
            "[APPROVAL WAIT] Waiting for approval: request_id=%s "
            "timeout=%.0fs",
            request_id[:8],
            timeout_seconds,
        )

        # Create a wrapper task that can be cancelled
        async def wait_for_future():
            logger.debug(
                "[APPROVAL WAIT] wait_for_future started for request_id=%s",
                request_id[:8],
            )
            result = await future
            logger.debug(
                "[APPROVAL WAIT] wait_for_future completed for request_id=%s",
                request_id[:8],
            )
            return result

        wait_task = asyncio.create_task(wait_for_future())
        logger.debug(
            "[APPROVAL WAIT] Created wait_task for request_id=%s",
            request_id[:8],
        )

        try:
            logger.debug(
                "[APPROVAL WAIT] Calling asyncio.wait_for for request_id=%s",
                request_id[:8],
            )
            decision = await asyncio.wait_for(
                wait_task,
                timeout=timeout_seconds,
            )
            logger.debug(
                "[APPROVAL WAIT] asyncio.wait_for completed for request_id=%s "
                "decision=%s",
                request_id[:8],
                decision.value if hasattr(decision, "value") else decision,
            )
            return decision
        except asyncio.TimeoutError:
            logger.debug(
                "[APPROVAL WAIT] Timeout for request_id=%s after %.0fs",
                request_id[:8],
                timeout_seconds,
            )
            wait_task.cancel()
            return ApprovalDecision.TIMEOUT
        except asyncio.CancelledError:
            # Task cancelled (e.g., user /stop or SSE disconnect)
            # Cancel the wait task and auto-deny the pending approval
            logger.debug(
                "[APPROVAL WAIT] CancelledError caught for request_id=%s, "
                "cancelling wait_task and auto-denying",
                request_id[:8],
            )
            wait_task.cancel()
            svc = self._tool_guard_approval_service
            await svc.resolve_request(
                request_id,
                ApprovalDecision.DENIED,
            )
            logger.debug(
                "[APPROVAL WAIT] Auto-denied request_id=%s, re-raising "
                "CancelledError",
                request_id[:8],
            )
            # Re-raise to propagate cancellation
            raise

    async def _emit_waiting_for_approval_blocking(
        self,
        pending: "PendingApproval",
        guard_result: ToolGuardResult,
    ) -> None:
        """Emit approval request message with frontend metadata.

        The frontend will render this as an ApprovalCard with
        approve/deny buttons based on metadata.message_type.
        """
        from agentscope.message import TextBlock

        lang = self._tool_guard_ui_lang()
        tool_input = pending.extra.get("tool_call", {}).get("input", {})

        def tg(key: str) -> str:
            return _tool_guard_t(lang, key)

        # Format message text
        from coapis.security.tool_guard.approval import (
            format_findings_summary,
        )

        findings_text = format_findings_summary(guard_result)
        max_sev = guard_result.max_severity
        sev_emoji, sev_name = self._severity_emoji_and_localized_name(
            max_sev,
            lang,
        )

        params_text = _json.dumps(tool_input, ensure_ascii=False, indent=2)

        # Determine channel type for message format adaptation
        channel = str(self._request_context.get("channel") or "")
        # Channels that support native Markdown rendering
        _MD_CHANNELS = {"wecom", "dingtalk", "discord", "telegram"}
        # Telegram uses HTML internally but markdown_to_html covers it
        # Feishu/Weixin/QQ/Onebot/Xiaoyi: no native markdown
        use_markdown = channel in _MD_CHANNELS or channel.startswith("wecom")

        if use_markdown:
            message_text = (
                f"🛡️ **{tg('wait_title')}**\n\n"
                f"- {tg('tool')}: `{pending.tool_name}`\n"
                f"- {sev_emoji} {tg('severity')}: `{max_sev.value}` ({sev_name})\n"
                f"- {tg('findings')}: `{guard_result.findings_count}`\n"
                f"- {tg('risk_summary')}:\n{findings_text}\n\n"
                f"- {tg('parameters')}:\n```json\n{params_text}\n```\n\n"
                f"💡 **操作指令**\n"
                f"- 审批通过: `/approve` 或 `/approval approve`\n"
                f"- 拒绝执行: `/deny` 或 `/approval deny`\n"
                f"- 查看待审批: `/approval list`"
            )
        else:
            # Plain text format for non-markdown channels
            message_text = (
                f"🛡️ {tg('wait_title')}\n\n"
                f"  {tg('tool')}: {pending.tool_name}\n"
                f"  {sev_emoji} {tg('severity')}: {max_sev.value} ({sev_name})\n"
                f"  {tg('findings')}: {guard_result.findings_count}\n"
                f"  {tg('risk_summary')}:\n{findings_text}\n\n"
                f"  {tg('parameters')}:\n{params_text}\n\n"
                f"💡 操作指令\n"
                f"  审批通过: /approve 或 /approval approve\n"
                f"  拒绝执行: /deny 或 /approval deny\n"
                f"  查看待审批: /approval list"
            )

        # Create message with special metadata for frontend rendering
        msg = Msg(
            self.name,
            [TextBlock(type="text", text=message_text)],
            "assistant",
            metadata={
                # Frontend detection marker
                "message_type": "tool_guard_approval",
                "approval_request_id": pending.request_id,
                "session_id": pending.session_id,
                "agent_id": pending.agent_id,
                "tool_name": pending.tool_name,
                "severity": pending.severity,
                "findings_count": pending.findings_count,
                "findings_summary": pending.result_summary,
                "tool_params": tool_input,
                "created_at": pending.created_at,
            },
        )

        # Print to user but DO NOT add to memory
        # This is a temporary UI prompt, not part of conversation history
        await self.print(msg, True)

    async def _acting_denied(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        guard_result,
    ) -> dict | None:
        """Handle user denial of tool execution."""
        from agentscope.message import ToolResultBlock
        from coapis.security.tool_guard.approval import (
            format_findings_summary,
        )

        lang = self._tool_guard_ui_lang()

        def tg(key: str) -> str:
            return _tool_guard_t(lang, key)

        findings_text = (
            format_findings_summary(guard_result) if guard_result else ""
        )

        # Adaptive format: markdown for supported channels, plain text otherwise
        channel = str(self._request_context.get("channel") or "")
        _MD_CHANNELS = {"wecom", "dingtalk", "discord", "telegram"}
        use_md = channel in _MD_CHANNELS or channel.startswith("wecom")

        if use_md:
            denied_text = (
                f"🚫 **{tg('tool_blocked')}**\n\n"
                f"- {tg('tool')}: `{tool_name}`\n"
                f"- {tg('reason')}: {tg('reason_denied')}\n\n"
                f"{findings_text}"
            )
        else:
            denied_text = (
                f"🚫 {tg('tool_blocked')}\n\n"
                f"  {tg('tool')}: {tool_name}\n"
                f"  {tg('reason')}: {tg('reason_denied')}\n\n"
                f"{findings_text}"
            )

        tool_res_msg = Msg(
            "system",
            [
                ToolResultBlock(
                    type="tool_result",
                    id=tool_call["id"],
                    name=tool_name,
                    output=[{"type": "text", "text": denied_text}],
                ),
            ],
            "system",
        )

        await self.print(tool_res_msg, True)
        await self.memory.add(tool_res_msg)

        # Write audit event with risk classification fields
        try:
            from .security.audit_logger import AuditLogger, create_audit_event
            meta_extra = {}
            risk_level = ""
            cmd_category = ""
            if guard_result is not None and guard_result.findings:
                for f in guard_result.findings:
                    if f.metadata:
                        risk_level = f.metadata.get("risk_level", risk_level)
                        cmd_category = f.metadata.get("command_category", cmd_category)
            ev = create_audit_event(
                event_type="tool_guard_denied",
                tool_name=tool_name,
                command=tool_input.get("command", ""),
                result="denied",
                reason=f"auto_denied by tool guard",
                metadata=meta_extra,
            )
            ev.risk_level = risk_level or "block"
            ev.command_category = cmd_category
            ev.confirm_result = "denied"
            AuditLogger.log(ev)
        except Exception:
            pass

        return None

    async def _acting_timeout(
        self,
        tool_call: dict[str, Any],
        tool_name: str,
        guard_result,
    ) -> dict | None:
        """Handle approval timeout (auto-deny)."""
        from agentscope.message import ToolResultBlock
        from coapis.security.tool_guard.approval import (
            format_findings_summary,
        )

        lang = self._tool_guard_ui_lang()

        def tg(key: str) -> str:
            return _tool_guard_t(lang, key)

        findings_text = (
            format_findings_summary(guard_result) if guard_result else ""
        )

        reason_text = tg("reason_timeout").replace(
            "{timeout}",
            str(TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS),
        )

        # Adaptive format: markdown for supported channels, plain text otherwise
        channel = str(self._request_context.get("channel") or "")
        _MD_CHANNELS = {"wecom", "dingtalk", "discord", "telegram"}
        use_md = channel in _MD_CHANNELS or channel.startswith("wecom")

        if use_md:
            timeout_text = (
                f"{tg('timeout_title')}\n\n"
                f"- {tg('tool')}: `{tool_name}`\n"
                f"- {tg('reason')}: {reason_text}\n\n"
                f"{findings_text}"
            )
        else:
            timeout_text = (
                f"{tg('timeout_title')}\n\n"
                f"  {tg('tool')}: {tool_name}\n"
                f"  {tg('reason')}: {reason_text}\n\n"
                f"{findings_text}"
            )

        tool_res_msg = Msg(
            "system",
            [
                ToolResultBlock(
                    type="tool_result",
                    id=tool_call["id"],
                    name=tool_name,
                    output=[{"type": "text", "text": timeout_text}],
                ),
            ],
            "system",
        )

        await self.print(tool_res_msg, True)
        await self.memory.add(tool_res_msg)

        # Write audit event with risk classification fields
        try:
            from .security.audit_logger import AuditLogger, create_audit_event
            meta_extra = {}
            risk_level = ""
            cmd_category = ""
            if guard_result is not None and guard_result.findings:
                for f in guard_result.findings:
                    if f.metadata:
                        risk_level = f.metadata.get("risk_level", risk_level)
                        cmd_category = f.metadata.get("command_category", cmd_category)
            ev = create_audit_event(
                event_type="tool_guard_denied",
                tool_name=tool_name,
                command=tool_input.get("command", ""),
                result="denied",
                reason=f"auto_denied by tool guard",
                metadata=meta_extra,
            )
            ev.risk_level = risk_level or "block"
            ev.command_category = cmd_category
            ev.confirm_result = "denied"
            AuditLogger.log(ev)
        except Exception:
            pass

        return None

    # ------------------------------------------------------------------
    # _reasoning override (guard-aware)
    # ------------------------------------------------------------------

    async def _reasoning(
        self,
        tool_choice: Literal["auto", "none", "required"] | None = None,
    ) -> Msg:
        """Delegate to parent ReActAgent reasoning.

        Tool guard approval is now handled synchronously in
        _acting_with_approval, so no special reasoning logic is needed.
        """
        return await super()._reasoning(  # type: ignore[misc]
            tool_choice=tool_choice,
        )

    @staticmethod
    def _severity_emoji_and_localized_name(
        severity: GuardSeverity,
        lang: str,
    ) -> tuple[str, str]:
        """Return (emoji, localized severity name) for the UI language."""
        high = (GuardSeverity.CRITICAL, GuardSeverity.HIGH)
        emoji = "🔴" if severity in high else "🟡"
        key = f"sev_{severity.value}"
        name = _tool_guard_t(lang, key)
        return emoji, name
