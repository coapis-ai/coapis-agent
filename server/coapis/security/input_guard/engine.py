# -*- coding: utf-8 -*-
"""Input guard engine – orchestrates all registered guardians.

Security checks:
- Command injection detection
- Prompt injection detection
- Data exfiltration detection
- Path traversal detection

All blocked inputs are logged to SecurityAuditLogger.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .guardians import BaseInputGuardian
from .guardians.rule_guardian import RuleBasedInputGuardian
from .models import InputGuardResult, InputGuardSeverity

logger = logging.getLogger(__name__)

_engine: InputGuardEngine | None = None


class InputGuardEngine:
    """Orchestrates pre-input content guarding.

    Usage::

        result = InputGuardEngine().check("rm -rf /")
        if not result.is_safe:
            print(result.block_message)
    """

    def __init__(
        self,
        guardians: list[BaseInputGuardian] | None = None,
        rules_path: str | Path | None = None,
    ):
        if guardians is not None:
            self._guardians = guardians
        else:
            self._guardians = [RuleBasedInputGuardian(rules_path=rules_path)]
        self._audit_logger = None
        logger.info(
            "InputGuardEngine initialized with %d guardian(s)",
            len(self._guardians),
        )

    def _get_audit_logger(self):
        """Lazy-load SecurityAuditLogger."""
        if self._audit_logger is None:
            try:
                from coapis.security.audit_logger import SecurityAuditLogger
                self._audit_logger = SecurityAuditLogger.get_instance()
            except Exception:
                pass
        return self._audit_logger

    def check(self, text: str, username: str = "", agent_id: str = "") -> InputGuardResult:
        """Check input text against all guardians. Returns aggregated result.

        If input is blocked, logs to SecurityAuditLogger.
        """
        aggregated = InputGuardResult()
        for guardian in self._guardians:
            result = guardian.check(text)
            for finding in result.findings:
                aggregated.add_finding(finding)

        # Log blocked inputs to audit
        if not aggregated.is_safe:
            self._log_blocked_input(text, aggregated, username, agent_id)

        return aggregated

    def _log_blocked_input(
        self, text: str, result: InputGuardResult, username: str, agent_id: str
    ):
        """Log blocked input to audit logger."""
        audit = self._get_audit_logger()
        if audit is None:
            return

        try:
            matched_rules = []
            for finding in result.findings:
                matched_rules.append({
                    "rule_id": getattr(finding, "rule_id", "unknown"),
                    "category": getattr(finding, "category", "unknown"),
                    "severity": str(getattr(finding, "severity", "MEDIUM")),
                })

            audit.log_input_block(
                user=username or "unknown",
                input_summary=text[:200],
                reason=result.block_message or "Input blocked by guard",
                agent_id=agent_id,
                matched_rules=matched_rules,
            )
        except Exception as e:
            logger.debug(f"Failed to log blocked input: {e}")

    def list_rules(self) -> list[dict[str, Any]]:
        """List all rules from the first RuleBasedInputGuardian."""
        for g in self._guardians:
            if isinstance(g, RuleBasedInputGuardian):
                return g.list_rules()
        return []

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        for g in self._guardians:
            if isinstance(g, RuleBasedInputGuardian):
                return g.get_rule(rule_id)
        return None

    def add_rule(self, rule: dict[str, Any]) -> None:
        for g in self._guardians:
            if isinstance(g, RuleBasedInputGuardian):
                g.add_rule(rule)
                return

    def update_rule(self, rule_id: str, rule: dict[str, Any]) -> bool:
        for g in self._guardians:
            if isinstance(g, RuleBasedInputGuardian):
                return g.update_rule(rule_id, rule)
        return False

    def delete_rule(self, rule_id: str) -> bool:
        for g in self._guardians:
            if isinstance(g, RuleBasedInputGuardian):
                return g.delete_rule(rule_id)
        return False

    def reload(self) -> int:
        """Reload all guardians from disk. Returns total rule count."""
        total = 0
        for g in self._guardians:
            if isinstance(g, RuleBasedInputGuardian):
                total += g.reload()
        return total


def get_input_guard_engine() -> InputGuardEngine:
    """Get or create the global InputGuardEngine singleton."""
    global _engine
    if _engine is None:
        _engine = InputGuardEngine()
    return _engine
