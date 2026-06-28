# -*- coding: utf-8 -*-
"""Input guard engine – orchestrates all registered guardians."""

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
        logger.info(
            "InputGuardEngine initialized with %d guardian(s)",
            len(self._guardians),
        )

    def check(self, text: str) -> InputGuardResult:
        """Check input text against all guardians. Returns aggregated result."""
        aggregated = InputGuardResult()
        for guardian in self._guardians:
            result = guardian.check(text)
            for finding in result.findings:
                aggregated.add_finding(finding)
        return aggregated

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
