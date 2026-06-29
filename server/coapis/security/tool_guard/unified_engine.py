# -*- coding: utf-8 -*-
"""Unified Tool Guard Engine.

Single entry point for all tool-call security checks.
Loads from ``system/tool_guard.yaml`` and implements a three-layer pipeline:

  Layer 1: Access Control — guarded / denied tools
  Layer 2: Command Classification — L0-L4 levels, L0 skips rule matching
  Layer 3: Pattern Rules — regex matching (command-specific + cross-command)
  Layer 4: Evasion Detection — obfuscation / quote-state analysis

Usage::

    from coapis.security.tool_guard.unified_engine import get_unified_engine

    engine = get_unified_engine()
    result = engine.process_command("execute_shell_command", {"command": "rm -rf /"})
    if result["action"] == "block":
        logger.warning("Blocked: %s", result["reason"])
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

import yaml

from .unified_models import (
    AccessControlConfig,
    CommandEntry,
    PatternRule,
    ToolGuardConfig,
)
from .models import GuardFinding, GuardSeverity, GuardThreatCategory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "system" / "tool_guard.yaml"


def _load_config() -> ToolGuardConfig:
    """Load and parse ``system/tool_guard.yaml``."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return ToolGuardConfig(**(data or {}))
    except FileNotFoundError:
        logger.warning("tool_guard.yaml not found at %s, using defaults", _CONFIG_PATH)
        return ToolGuardConfig()
    except Exception as exc:
        logger.error("Failed to load tool_guard.yaml: %s", exc)
        return ToolGuardConfig()


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "INFO": 0,
}

_SEVERITY_MAP = {
    "CRITICAL": GuardSeverity.CRITICAL,
    "HIGH": GuardSeverity.HIGH,
    "MEDIUM": GuardSeverity.MEDIUM,
    "LOW": GuardSeverity.LOW,
    "INFO": GuardSeverity.INFO,
}

_CATEGORY_MAP = {
    "command_injection": GuardThreatCategory.COMMAND_INJECTION,
    "code_execution": GuardThreatCategory.CODE_EXECUTION,
    "network_abuse": GuardThreatCategory.NETWORK_ABUSE,
    "privilege_escalation": GuardThreatCategory.PRIVILEGE_ESCALATION,
    "sensitive_file_access": GuardThreatCategory.SENSITIVE_FILE_ACCESS,
    "data_exfiltration": GuardThreatCategory.DATA_EXFILTRATION,
    "resource_abuse": GuardThreatCategory.RESOURCE_ABUSE,
    "prompt_injection": GuardThreatCategory.PROMPT_INJECTION,
    "path_traversal": GuardThreatCategory.PATH_TRAVERSAL,
    "credential_exposure": GuardThreatCategory.CREDENTIAL_EXPOSURE,
    "package_management": GuardThreatCategory.RESOURCE_ABUSE,
    "container_management": GuardThreatCategory.RESOURCE_ABUSE,
}


def _max_severity(findings: list[GuardFinding]) -> GuardSeverity:
    """Return the highest severity from findings, or SAFE."""
    if not findings:
        return GuardSeverity.SAFE
    best = -1
    result = GuardSeverity.SAFE
    for f in findings:
        val = _SEVERITY_ORDER.get(f.severity.value, -1)
        if val > best:
            best = val
            result = f.severity
    return result


# ---------------------------------------------------------------------------
# Command parser
# ---------------------------------------------------------------------------

def _extract_command_name(command_str: str) -> str | None:
    """Extract the first command name from a shell command string.

    Handles: ``sudo rm ...`` → ``rm``, ``env VAR=val cmd ...`` → ``cmd``,
    ``bash -c "..."`` → ``bash``.
    """
    import shlex
    try:
        tokens = shlex.split(command_str, posix=True)
    except ValueError:
        tokens = command_str.split()

    skip_prefixes = {"sudo", "doas", "pkexec", "time", "nice", "nohup"}
    skip_env_prefixes = {"env", "export"}

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in skip_prefixes:
            i += 1
            continue
        if tok in skip_env_prefixes:
            # skip `env VAR=val` pairs
            i += 1
            while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
                i += 1
            continue
        # skip env assignments like `FOO=bar cmd`
        if "=" in tok and not tok.startswith("-") and tok[0].isalpha():
            i += 1
            continue
        return tok
    return None


# ---------------------------------------------------------------------------
# Result dict
# ---------------------------------------------------------------------------

def _make_result(
    *,
    action: str,
    level: str | None = None,
    command: str | None = None,
    matched_rules: list[dict[str, Any]] | None = None,
    evasion_flags: list[str] | None = None,
    reason: str = "",
    duration_ms: float = 0,
) -> dict[str, Any]:
    return {
        "action": action,  # "allow" / "block" / "audit"
        "level": level,    # L0/L1/L2/L3/L4 or None
        "command": command,
        "matched_rules": matched_rules or [],
        "evasion_flags": evasion_flags or [],
        "reason": reason,
        "duration_ms": round(duration_ms, 2),
    }


# ===================================================================
# Unified Tool Guard Engine
# ===================================================================


class UnifiedToolGuardEngine:
    """Three-layer tool-call security engine.

    Layers executed in order:
      1. Access Control  — is the tool guarded / denied?
      2. Command Level   — L0→allow immediately, L1+→continue
      3. Pattern Rules   — regex matching (command-specific + cross-command)
      4. Evasion Check   — obfuscation / quote-state detection

    Configuration is loaded from ``system/tool_guard.yaml``.
    """

    def __init__(self, config: ToolGuardConfig | None = None) -> None:
        self._config = config or _load_config()
        self._compiled_rules: list[tuple[PatternRule, list[re.Pattern], list[re.Pattern]]] = []
        self._compile_rules()
        self._load_evasion_guardian()
        logger.info(
            "UnifiedToolGuardEngine loaded: %d commands, %d rules, %d evasion checks",
            len(self._config.commands),
            len(self._config.rules),
            len(self._config.evasion_checks),
        )

    # ------------------------------------------------------------------
    # Config management
    # ------------------------------------------------------------------

    @property
    def config(self) -> ToolGuardConfig:
        return self._config

    def reload(self) -> None:
        """Reload config from YAML and recompile rules."""
        self._config = _load_config()
        self._compile_rules()
        self._load_evasion_guardian()
        logger.info("UnifiedToolGuardEngine reloaded")

    def _compile_rules(self) -> None:
        """Pre-compile all regex patterns for fast matching."""
        self._compiled_rules = []
        for rule in self._config.rules:
            compiled_includes = []
            compiled_excludes = []
            for p in rule.patterns:
                try:
                    compiled_includes.append(re.compile(p, re.IGNORECASE))
                except re.error as exc:
                    logger.warning("Bad pattern in rule %s: %s — %s", rule.id, p, exc)
            for p in rule.exclude_patterns:
                try:
                    compiled_excludes.append(re.compile(p, re.IGNORECASE))
                except re.error as exc:
                    logger.warning("Bad exclude pattern in rule %s: %s — %s", rule.id, p, exc)
            self._compiled_rules.append((rule, compiled_includes, compiled_excludes))

    def _load_evasion_guardian(self) -> None:
        """Load the shell evasion guardian if available."""
        self._evasion_guardian = None
        try:
            from .guardians.shell_evasion_guardian import ShellEvasionGuardian
            self._evasion_guardian = ShellEvasionGuardian()
        except Exception as exc:
            logger.warning("Failed to load ShellEvasionGuardian: %s", exc)

    # ------------------------------------------------------------------
    # Layer 1: Access Control
    # ------------------------------------------------------------------

    def is_denied(self, tool_name: str) -> bool:
        ac = self._config.access_control
        return tool_name in ac.denied_tools

    def is_guarded(self, tool_name: str) -> bool:
        ac = self._config.access_control
        if not ac.guarded_tools:
            return True  # None/empty = guard all
        return tool_name in ac.guarded_tools

    # ------------------------------------------------------------------
    # Layer 2: Command Classification
    # ------------------------------------------------------------------

    def get_command_level(self, command_str: str) -> tuple[str | None, str | None]:
        """Return (level, cmd_name) for the command string."""
        cmd_name = _extract_command_name(command_str)
        if cmd_name is None:
            return None, None
        entry = self._config.commands.get(cmd_name)
        if entry:
            return entry.level, cmd_name
        return None, cmd_name

    # ------------------------------------------------------------------
    # Layer 3: Pattern Rules
    # ------------------------------------------------------------------

    def match_rules(
        self,
        command_str: str,
        cmd_name: str | None,
    ) -> list[tuple[PatternRule, re.Match]]:
        """Match rules against the command string.

        Returns only rules that actually match.  For L0 commands,
        returns empty list (optimization).
        """
        # L0 optimization: skip rule matching
        if cmd_name:
            entry = self._config.commands.get(cmd_name)
            if entry and entry.level == "L0":
                return []

        # Also skip if command is disabled
        disabled = set(self._config.access_control.disabled_rules)

        matches = []
        for rule, compiled_in, compiled_ex in self._compiled_rules:
            if rule.id in disabled:
                continue

            # Check rule scope: command-specific or cross-command
            if rule.commands and cmd_name and cmd_name not in rule.commands:
                continue

            # Try each include pattern
            for pat in compiled_in:
                m = pat.search(command_str)
                if m is None:
                    continue
                # Check exclude patterns
                excluded = False
                for ex_pat in compiled_ex:
                    if ex_pat.search(command_str):
                        excluded = True
                        break
                if not excluded:
                    matches.append((rule, m))
                    break  # one match per rule is enough

        return matches

    # ------------------------------------------------------------------
    # Layer 4: Evasion Detection
    # ------------------------------------------------------------------

    def check_evasion(self, command_str: str) -> list[GuardFinding]:
        """Run evasion detection if the guardian is loaded."""
        if self._evasion_guardian is None:
            return []
        try:
            return self._evasion_guardian.guard(
                "execute_shell_command",
                {"command": command_str},
            )
        except Exception as exc:
            logger.warning("Evasion guardian failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Core: process_command
    # ------------------------------------------------------------------

    def process_command(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the full three-layer pipeline on a tool call.

        Parameters
        ----------
        tool_name:
            Name of the tool (e.g. ``execute_shell_command``).
        params:
            Tool call parameters.

        Returns
        -------
        dict with keys: action, level, command, matched_rules,
        evasion_flags, reason, duration_ms.
        """
        t0 = time.monotonic()

        # Extract command string from params
        command_str = params.get("command", "")
        if not command_str:
            # Non-shell tool — just check access control
            if self.is_denied(tool_name):
                return _make_result(
                    action="block",
                    reason=f"Tool '{tool_name}' is denied",
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
            return _make_result(action="allow", duration_ms=(time.monotonic() - t0) * 1000)

        # ── Layer 1: Access Control ──
        if self.is_denied(tool_name):
            return _make_result(
                action="block",
                command=command_str,
                reason=f"Tool '{tool_name}' is denied",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # ── Layer 2: Command Classification ──
        level, cmd_name = self.get_command_level(command_str)

        # L0 → allow immediately (skip rules + evasion)
        if level == "L0":
            return _make_result(
                action="allow",
                level=level,
                command=cmd_name or command_str,
                reason="L0 command — read-only, zero risk",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # ── Layer 3: Pattern Rules ──
        rule_matches = self.match_rules(command_str, cmd_name)
        matched_rules = []
        for rule, match in rule_matches:
            matched_rules.append({
                "id": rule.id,
                "severity": rule.severity,
                "category": rule.category,
                "description": rule.description,
                "action": rule.action,
                "matched_text": match.group(0)[:200],
            })

        # Check if any rule demands blocking
        blocked_rule = None
        for mr in matched_rules:
            if mr["action"] == "block":
                blocked_rule = mr
                break

        # ── Layer 4: Evasion Detection ──
        evasion_findings = self.check_evasion(command_str)
        evasion_flags = []
        for ef in evasion_findings:
            evasion_flags.append({
                "id": ef.rule_id,
                "severity": ef.severity.value,
                "description": ef.description,
            })

        # ── Decision ──
        # If evasion detected + L3/L4 → block
        # If rule matched with action=block → block
        # If rule matched with action=audit → audit
        # Otherwise → use command-level default action

        def _audit_log(action: str, reason: str) -> None:
            """Write audit log for audit/confirm/block actions."""
            if action in ("audit", "confirm", "block"):
                try:
                    from coapis.security.audit_logger import SecurityAuditLogger
                    audit = SecurityAuditLogger.get_instance()
                    if audit:
                        audit.log_command_block(
                            user="system",
                            command=cmd_name or command_str,
                            level=level or "L0",
                            action=action,
                            reason=reason,
                            matched_rules=matched_rules,
                        )
                except Exception:
                    pass

        if blocked_rule:
            _audit_log("block", f"Rule {blocked_rule['id']}: {blocked_rule['description']}")
            return _make_result(
                action="block",
                level=level,
                command=cmd_name or command_str,
                matched_rules=matched_rules,
                evasion_flags=evasion_flags,
                reason=f"Rule {blocked_rule['id']}: {blocked_rule['description']}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        if evasion_flags and level in ("L3", "L4"):
            _audit_log("block", f"Evasion detected on {level} command")
            return _make_result(
                action="block",
                level=level,
                command=cmd_name or command_str,
                matched_rules=matched_rules,
                evasion_flags=evasion_flags,
                reason=f"Evasion detected on {level} command",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        if matched_rules or evasion_flags:
            # Some findings but no block → audit
            _audit_log("audit", "Findings detected but no block condition met")
            return _make_result(
                action="audit",
                level=level,
                command=cmd_name or command_str,
                matched_rules=matched_rules,
                evasion_flags=evasion_flags,
                reason="Findings detected but no block condition met",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # No rules matched — use command-level default action
        cmd_entry = self._config.commands.get(cmd_name) if cmd_name else None
        default_action = cmd_entry.action if cmd_entry else "allow"
        if default_action in ("audit", "confirm"):
            _audit_log(default_action, f"Command-level default: {default_action}")
        return _make_result(
            action=default_action,
            level=level,
            command=cmd_name or command_str,
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    # ------------------------------------------------------------------
    # Compatibility: old guard() interface
    # ------------------------------------------------------------------

    def guard(
        self,
        tool_name: str,
        params: dict[str, Any],
        *,
        only_always_run: bool = False,
    ) -> "ToolGuardCompatResult":
        """Compatibility wrapper that returns a ToolGuardResult-like object."""
        result_dict = self.process_command(tool_name, params)

        # Build GuardFinding list
        findings: list[GuardFinding] = []
        for mr in result_dict.get("matched_rules", []):
            findings.append(GuardFinding(
                id=f"rule-{mr['id']}-{int(time.time()*1000)}",
                rule_id=mr["id"],
                category=_CATEGORY_MAP.get(mr.get("category", ""), GuardThreatCategory.COMMAND_INJECTION),
                severity=_SEVERITY_MAP.get(mr.get("severity", "HIGH"), GuardSeverity.HIGH),
                title=mr["id"],
                description=mr.get("description", ""),
                tool_name=tool_name,
                param_name="command",
                matched_value=result_dict.get("command", ""),
                matched_pattern=mr.get("matched_text", ""),
            ))
        for ef in result_dict.get("evasion_flags", []):
            findings.append(GuardFinding(
                id=f"evasion-{ef['id']}-{int(time.time()*1000)}",
                rule_id=ef["id"],
                category=GuardThreatCategory.CODE_EXECUTION,
                severity=_SEVERITY_MAP.get(ef.get("severity", "HIGH"), GuardSeverity.HIGH),
                title=ef["id"],
                description=ef.get("description", ""),
                tool_name=tool_name,
                param_name="command",
                matched_value=result_dict.get("command", ""),
            ))

        return ToolGuardCompatResult(
            tool_name=tool_name,
            params=params,
            findings=findings,
            action=result_dict["action"],
            level=result_dict.get("level"),
            duration_ms=result_dict.get("duration_ms", 0),
        )


class ToolGuardCompatResult:
    """Compatibility result that quacks like ToolGuardResult."""

    def __init__(
        self,
        tool_name: str,
        params: dict[str, Any],
        findings: list[GuardFinding],
        action: str,
        level: str | None,
        duration_ms: float,
    ) -> None:
        self.tool_name = tool_name
        self.params = params
        self.findings = findings
        self.action = action
        self.level = level
        self.guard_duration_seconds = duration_ms / 1000
        self.guardians_used = ["unified_engine"]
        self.guardians_failed: list[dict[str, str]] = []
        self.timestamp = None

    @property
    def is_safe(self) -> bool:
        return self.action == "allow"

    @property
    def max_severity(self) -> GuardSeverity:
        if not self.findings:
            return GuardSeverity.SAFE
        return _max_severity(self.findings)

    @property
    def findings_count(self) -> int:
        return len(self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "is_safe": self.is_safe,
            "action": self.action,
            "level": self.level,
            "max_severity": self.max_severity.value,
            "findings_count": self.findings_count,
            "guard_duration_seconds": self.guard_duration_seconds,
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: UnifiedToolGuardEngine | None = None


def get_unified_engine() -> UnifiedToolGuardEngine:
    """Return a lazily-initialised :class:`UnifiedToolGuardEngine` singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = UnifiedToolGuardEngine()
    return _engine_instance


def reset_engine() -> None:
    """Reset the singleton (useful for testing / reload)."""
    global _engine_instance
    _engine_instance = None
