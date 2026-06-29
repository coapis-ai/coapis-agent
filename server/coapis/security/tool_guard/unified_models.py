# -*- coding: utf-8 -*-
"""Unified Tool Guard data models.

Merges three data sources into one YAML config:
  1. access_control — tool guarding (guarded/denied tools + custom rules)
  2. commands — L0-L4 command classification (109 commands)
  3. rules — pattern-based detection (29 rules, command-specific + cross-command)
  4. evasion_checks — evasion detection toggles (7 checks)

Config file: system/tool_guard.yaml
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Access Control
# ---------------------------------------------------------------------------


class CustomRule(BaseModel):
    """User-defined custom rule for tool guarding."""

    id: str
    pattern: str
    action: str = "block"
    description: str = ""
    enabled: bool = True


class AccessControlConfig(BaseModel):
    """Tool access control settings."""

    enabled: bool = True
    guarded_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    custom_rules: list[CustomRule] = Field(default_factory=list)
    disabled_rules: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Command Classification (L0-L4)
# ---------------------------------------------------------------------------


class CommandEntry(BaseModel):
    """A single command with its risk level and default action."""

    level: str = Field(description="L0/L1/L2/L3/L4")
    desc: str = ""
    action: str = Field(
        default="allow",
        description="Default action: allow / audit / confirm / block",
    )


# ---------------------------------------------------------------------------
# Pattern Rules
# ---------------------------------------------------------------------------


class PatternRule(BaseModel):
    """A detection rule with regex patterns.

    ``commands`` links the rule to specific L0-L4 command entries.
    When empty, the rule is a cross-command pattern that applies globally.
    """

    id: str
    severity: str = Field(description="CRITICAL / HIGH / MEDIUM / LOW")
    category: str = ""
    commands: list[str] = Field(
        default_factory=list,
        description="Linked command names ([] = cross-command rule)",
    )
    patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    description: str = ""
    remediation: str = ""
    action: str = Field(
        default="block",
        description="Action when matched: block / audit / warn",
    )


# ---------------------------------------------------------------------------
# Unified Config
# ---------------------------------------------------------------------------


class ToolGuardConfig(BaseModel):
    """Root config model for ``system/tool_guard.yaml``."""

    version: str = "1.0"
    description: str = ""

    access_control: AccessControlConfig = Field(
        default_factory=AccessControlConfig,
    )
    evasion_checks: dict[str, bool] = Field(
        default_factory=lambda: {
            "command_substitution": True,
            "obfuscated_flags": True,
            "backslash_escaped_whitespace": True,
            "backslash_escaped_operators": True,
            "newlines": True,
            "comment_quote_desync": True,
            "quoted_newline": True,
        },
    )
    commands: dict[str, CommandEntry] = Field(default_factory=dict)
    rules: list[PatternRule] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_command_level(self, cmd_name: str) -> str | None:
        """Return the level of a command, or ``None`` if unknown."""
        entry = self.commands.get(cmd_name)
        return entry.level if entry else None

    def get_rules_for_command(self, cmd_name: str) -> list[PatternRule]:
        """Return rules linked to *cmd_name* **plus** all cross-command rules."""
        result: list[PatternRule] = []
        for rule in self.rules:
            if not rule.commands or cmd_name in rule.commands:
                result.append(rule)
        return result

    def get_command_specific_rules(self, cmd_name: str) -> list[PatternRule]:
        """Return only rules explicitly linked to *cmd_name*."""
        return [r for r in self.rules if cmd_name in r.commands]

    def get_cross_command_rules(self) -> list[PatternRule]:
        """Return rules that apply globally (commands list is empty)."""
        return [r for r in self.rules if not r.commands]

    def get_commands_by_level(self, level: str) -> dict[str, CommandEntry]:
        """Return all commands at the given level."""
        return {k: v for k, v in self.commands.items() if v.level == level}
