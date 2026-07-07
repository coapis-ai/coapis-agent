# -*- coding: utf-8 -*-
"""Unified Tool Guard data models.

Merges three data sources into one YAML config:
  1. access_control — tool guarding (guarded/denied tools + custom rules)
  2. commands — L0-L4 command classification (124 commands with sub_commands + demotion)
  3. global_rules — cross-command pattern detection (10 rules)
  4. evasion_checks — evasion detection toggles (11 checks)

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


class SubCommandEntry(BaseModel):
    """Sub-command risk level override.

    When a command has sub-commands (e.g. ``git status``, ``git push``),
    the sub-command entry overrides the parent command's level/action.
    """

    level: str = Field(description="L0/L1/L2/L3/L4")
    action: str = Field(
        default="allow",
        description="allow / audit / confirm / block",
    )
    desc: str = ""


class CommandRule(BaseModel):
    """Context-aware command rule (replaces DemotionRule).

    Supports both promotion and demotion of risk levels.
    Rules are evaluated in order; first match wins.
    """

    id: str = Field(description="Rule unique identifier, e.g. 'rm_system_critical'")
    desc: str = ""
    level: str = Field(description="Target level when matched: L0/L1/L2/L3/L4")
    action: str = Field(description="Target action when matched: allow / audit / confirm / block")
    # ── Match conditions (all optional, AND logic between groups) ──
    patterns: list[str] = Field(
        default_factory=list,
        description="Regex: command must match at least one (OR logic)",
    )
    exclude_patterns: list[str] = Field(
        default_factory=list,
        description="Regex: command must NOT match any (OR logic)",
    )
    safe_paths: list[str] = Field(
        default_factory=list,
        description="Path prefixes: all absolute paths must fall under these",
    )
    scope: str | None = Field(
        default=None,
        description="Special scope: 'workspace' = only match paths within user workspace",
    )


class DemotionRule(BaseModel):
    """[DEPRECATED] Use CommandRule via 'rules' field instead.

    Kept for backward compatibility. Engine prefers 'rules' over 'demotion'.
    """

    level: str = Field(description="Demoted level: L0/L1/L2/L3/L4")
    action: str = Field(description="Demoted action: allow / audit / confirm / block")
    desc: str = ""
    patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    safe_paths: list[str] = Field(default_factory=list)


class CommandEntry(BaseModel):
    """A single command with its risk level, default action, and optional
    sub-command / demotion configuration."""

    level: str = Field(description="L0/L1/L2/L3/L4")
    desc: str = ""
    action: str = Field(
        default="allow",
        description="Default action: allow / audit / confirm / block",
    )
    # ── Sub-command overrides ──
    sub_commands: dict[str, SubCommandEntry] = Field(
        default_factory=dict,
        description="Sub-command level overrides, e.g. git.status → L0",
    )
    # ── Exceptions: rules stricter than default action (↑ upgrade) ──
    exceptions: list[CommandRule] = Field(
        default_factory=list,
        description="Rules that upgrade action (e.g. confirm→block for dangerous params). "
                    "First-match-wins. Only used when matched rule is stricter than default.",
    )
    # ── Demotion rules: rules more lenient than default action (↓ downgrade) ──
    demotion_rules: list[CommandRule] = Field(
        default_factory=list,
        description="Rules that downgrade action (e.g. confirm→allow for safe paths). "
                    "First-match-wins. Only used when matched rule is more lenient than default.",
    )
    # ── Deprecated: old 'rules' field, migrated to exceptions/demotion_rules ──
    rules: list[CommandRule] = Field(
        default_factory=list,
        description="[DEPRECATED] Migrate to exceptions + demotion_rules. "
                    "Kept for backward compat; engine reads exceptions/demotion_rules first.",
    )
    # ── Deprecated: old demotion dict ──
    demotion: dict[str, DemotionRule] = Field(
        default_factory=dict,
        description="[DEPRECATED] Use demotion_rules instead.",
    )


# ---------------------------------------------------------------------------
# Pattern Rules
# ---------------------------------------------------------------------------


class PatternRule(BaseModel):
    """A cross-command detection rule with regex patterns.

    These rules apply globally across all commands and detect
    dangerous patterns that command-level classification cannot express
    (e.g., fork bombs, reverse shells, pipe-to-shell).
    """

    id: str
    severity: str = Field(description="CRITICAL / HIGH / MEDIUM / LOW")
    category: str = ""
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
    global_rules: list[PatternRule] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_command_level(self, cmd_name: str) -> str | None:
        """Return the level of a command, or ``None`` if unknown."""
        entry = self.commands.get(cmd_name)
        return entry.level if entry else None

    def get_cross_command_rules(self) -> list[PatternRule]:
        """Return all global cross-command rules."""
        return list(self.global_rules)

    def get_commands_by_level(self, level: str) -> dict[str, CommandEntry]:
        """Return all commands at the given level."""
        return {k: v for k, v in self.commands.items() if v.level == level}
