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
        path = Path(rules_path) if rules_path else SYSTEM_DIR / "input_guard_rules.yaml"
        self._load_rules(path)

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
