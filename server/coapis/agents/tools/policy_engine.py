"""Two-layer tool governance: builtin rules + user rules."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .registry import ToolRegistration

logger = logging.getLogger(__name__)


@dataclass
class PolicyRule:
    """A single governance rule."""
    name: str
    when: str = "always"  # always | never | whitelist | blacklist
    values: list[str] = field(default_factory=list)
    message: str = ""
    source: str = "builtin"  # builtin | user


@dataclass
class PolicyContext:
    """Context evaluated during a tool call."""
    registration: ToolRegistration
    user_modes: list[str] = field(default_factory=list)
    user_skills: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    sandbox_enabled: bool = False


class ToolPolicyEngine:
    """Evaluate governance rules and allowed-tool filters.

    Rules are evaluated in order:
        1. Builtin rules (hard constraints, e.g. sandbox-only tools).
        2. User rules (preferences, e.g. persona whitelist).

    Tool registry already supports `tags`, `requires_modes`, `requires_skills`,
    `requires_features`, `requires_sandbox`, and `governance`. This engine
    consumes those fields.
    """

    def __init__(self) -> None:
        self._builtin_rules: list[PolicyRule] = []
        self._user_rules: list[PolicyRule] = []

    def register_builtin_rule(self, rule: PolicyRule) -> None:
        rule.source = "builtin"
        self._builtin_rules.append(rule)

    def register_user_rule(self, rule: PolicyRule) -> None:
        rule.source = "user"
        self._user_rules.append(rule)

    def evaluate(self, ctx: PolicyContext) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        reg = ctx.registration

        # Requires_features
        if reg.requires_features:
            missing = sorted(set(reg.requires_features) - set(ctx.features))
            if missing:
                return False, f"missing_features={','.join(missing)}"

        # Requires_modes
        if reg.requires_modes:
            missing = sorted(set(reg.requires_modes) - set(ctx.user_modes))
            if missing:
                return False, f"missing_modes={','.join(missing)}"

        # Requires_skills
        if reg.requires_skills:
            missing = sorted(set(reg.requires_skills) - set(ctx.user_skills))
            if missing:
                return False, f"missing_skills={','.join(missing)}"

        # Requires_sandbox
        if reg.requires_sandbox and not ctx.sandbox_enabled:
            return False, "requires_sandbox_not_enabled"

        # Builtin rules
        for rule in self._builtin_rules:
            ok, reason = self._evaluate_rule(rule, ctx)
            if not ok:
                return ok, reason

        # User rules
        for rule in self._user_rules:
            ok, reason = self._evaluate_rule(rule, ctx)
            if not ok:
                return ok, reason

        return True, ""

    def _evaluate_rule(self, rule: PolicyRule, ctx: PolicyContext) -> tuple[bool, str]:
        reg = ctx.registration
        matched = reg.name in rule.values

        if rule.when == "always":
            return (False, rule.message or f"builtin_deny:{reg.name}") if matched else (True, "")
        if rule.when == "never":
            return False, rule.message or f"builtin_deny:{reg.name}"
        if rule.when == "whitelist":
            if matched:
                return True, ""
            return False, rule.message or f"not_in_whitelist:{reg.name}"
        if rule.when == "blacklist":
            if matched:
                return False, rule.message or f"blacklisted:{reg.name}"
            return True, ""
        return True, ""
