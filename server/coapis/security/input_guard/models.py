# -*- coding: utf-8 -*-
"""Data models for input content guarding."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class InputGuardSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    SAFE = "SAFE"


class InputGuardThreatCategory(str, Enum):
    COMMAND_INJECTION = "command_injection"
    PROMPT_INJECTION = "prompt_injection"
    DATA_EXFILTRATION = "data_exfiltration"
    CREDENTIAL_EXPOSURE = "credential_exposure"


@dataclass
class InputGuardFinding:
    id: str
    rule_id: str
    category: InputGuardThreatCategory
    severity: InputGuardSeverity
    title: str
    description: str
    matched_pattern: str | None = None
    snippet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "matched_pattern": self.matched_pattern,
            "snippet": self.snippet,
        }


@dataclass
class InputGuardResult:
    is_safe: bool = True
    findings: list[InputGuardFinding] = field(default_factory=list)
    max_severity: InputGuardSeverity = InputGuardSeverity.SAFE

    def add_finding(self, finding: InputGuardFinding) -> None:
        self.findings.append(finding)
        self.is_safe = False
        severity_order = {
            InputGuardSeverity.CRITICAL: 4,
            InputGuardSeverity.HIGH: 3,
            InputGuardSeverity.MEDIUM: 2,
            InputGuardSeverity.LOW: 1,
            InputGuardSeverity.SAFE: 0,
        }
        if severity_order.get(finding.severity, 0) > severity_order.get(self.max_severity, 0):
            self.max_severity = finding.severity

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_safe": self.is_safe,
            "max_severity": self.max_severity.value,
            "findings": [f.to_dict() for f in self.findings],
        }

    @property
    def block_message(self) -> str:
        """User-facing message when input is blocked."""
        cats = list({f.category.value for f in self.findings})
        return (
            f"⚠️ 输入内容安全检测未通过（{', '.join(cats)}），"
            f"请修改后重试。如有疑问请联系管理员。"
        )
