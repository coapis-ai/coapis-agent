# -*- coding: utf-8 -*-
"""YAML-rule-based input content guardian."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

import yaml

from ..models import (
    InputGuardFinding,
    InputGuardResult,
    InputGuardSeverity,
    InputGuardThreatCategory,
)
from . import BaseInputGuardian

logger = logging.getLogger(__name__)

from ....constant import SYSTEM_DIR

_SEVERITY_MAP = {s.value: s for s in InputGuardSeverity}
_CATEGORY_MAP = {c.value: c for c in InputGuardThreatCategory}


class RuleBasedInputGuardian(BaseInputGuardian):
    """Guardian that loads YAML rules and performs regex matching on input text."""

    def __init__(self, rules_path: str | Path | None = None):
        self._rules: list[dict[str, Any]] = []
        self._compiled: list[tuple[dict[str, Any], list[re.Pattern]]] = []
        self._rules_path = Path(rules_path) if rules_path else SYSTEM_DIR / "input_guard_rules.yaml"
        self._load_rules(self._rules_path)

    def _load_rules(self, path: Path) -> None:
        if not path.exists():
            logger.info("input_guard: no rules file at %s, guardian disabled", path)
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
            if not isinstance(data, list):
                logger.warning("input_guard: rules file is not a list, skipping")
                return
            for rule in data:
                if not isinstance(rule, dict):
                    continue
                patterns = rule.get("patterns", [])
                compiled = []
                for p in patterns:
                    try:
                        compiled.append(re.compile(p, re.IGNORECASE))
                    except re.error as e:
                        logger.warning("input_guard: bad pattern in rule %s: %s", rule.get("id"), e)
                if compiled:
                    self._rules.append(rule)
                    self._compiled.append((rule, compiled))
            logger.info("input_guard: loaded %d rules from %s", len(self._rules), path)
        except Exception as e:
            logger.error("input_guard: failed to load rules: %s", e)

    def check(self, text: str) -> InputGuardResult:
        result = InputGuardResult()
        if not text or not text.strip():
            return result
        text_stripped = text.strip()
        for rule, patterns in self._compiled:
            for pat in patterns:
                m = pat.search(text_stripped)
                if m:
                    finding = InputGuardFinding(
                        id=str(uuid.uuid4())[:8],
                        rule_id=rule.get("id", "UNKNOWN"),
                        category=_CATEGORY_MAP.get(
                            rule.get("category", ""),
                            InputGuardThreatCategory.COMMAND_INJECTION,
                        ),
                        severity=_SEVERITY_MAP.get(
                            rule.get("severity", "HIGH"),
                            InputGuardSeverity.HIGH,
                        ),
                        title=rule.get("description", "Input guard rule triggered"),
                        description=rule.get("description", ""),
                        matched_pattern=pat.pattern,
                        snippet=m.group(0)[:200] if m.group(0) else None,
                    )
                    result.add_finding(finding)
                    break  # one match per rule is enough
        return result

    # ── Rule management methods ──

    def list_rules(self) -> list[dict[str, Any]]:
        """Return all loaded rules as dicts."""
        return [dict(r) for r in self._rules]

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        """Get a single rule by id."""
        for r in self._rules:
            if r.get("id") == rule_id:
                return dict(r)
        return None

    def add_rule(self, rule: dict[str, Any]) -> None:
        """Add a new rule and persist."""
        self._rules.append(rule)
        self._compile_single(rule)
        self._save_rules()

    def update_rule(self, rule_id: str, rule: dict[str, Any]) -> bool:
        """Update an existing rule by id. Returns True if found."""
        for i, r in enumerate(self._rules):
            if r.get("id") == rule_id:
                self._rules[i] = rule
                self._rebuild_compiled()
                self._save_rules()
                return True
        return False

    def delete_rule(self, rule_id: str) -> bool:
        """Delete a rule by id. Returns True if found."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.get("id") != rule_id]
        if len(self._rules) < before:
            self._rebuild_compiled()
            self._save_rules()
            return True
        return False

    def reload(self) -> int:
        """Reload rules from disk. Returns number of rules loaded."""
        self._rules.clear()
        self._compiled.clear()
        self._load_rules(self._rules_path)
        return len(self._rules)

    def _compile_single(self, rule: dict[str, Any]) -> None:
        """Compile patterns for a single rule and append to _compiled."""
        patterns = rule.get("patterns", [])
        compiled = []
        for p in patterns:
            try:
                compiled.append(re.compile(p, re.IGNORECASE))
            except re.error as e:
                logger.warning("input_guard: bad pattern in rule %s: %s", rule.get("id"), e)
        self._compiled.append((rule, compiled))

    def _rebuild_compiled(self) -> None:
        """Rebuild the entire _compiled list from _rules."""
        self._compiled.clear()
        for rule in self._rules:
            self._compile_single(rule)

    def _save_rules(self) -> None:
        """Persist current rules to YAML file."""
        try:
            with open(self._rules_path, "w", encoding="utf-8") as f:
                yaml.dump(self._rules, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            logger.info("input_guard: saved %d rules to %s", len(self._rules), self._rules_path)
        except Exception as e:
            logger.error("input_guard: failed to save rules: %s", e)
