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
    CommandRule,
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


def _extract_sub_command(command_str: str, cmd_name: str | None) -> str | None:
    """Extract the sub-command from a shell command string.

    For ``git status`` → ``status``, ``npm install --save`` → ``install``.
    Skips flags (``-v``, ``--help``) to find the first positional arg
    after the command name.
    """
    if not cmd_name:
        return None
    import shlex
    try:
        tokens = shlex.split(command_str, posix=True)
    except ValueError:
        tokens = command_str.split()

    skip_prefixes = {"sudo", "doas", "pkexec", "time", "nice", "nohup"}
    skip_env_prefixes = {"env", "export"}

    found_cmd = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in skip_prefixes:
            i += 1
            continue
        if tok in skip_env_prefixes:
            i += 1
            while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
                i += 1
            continue
        if "=" in tok and not tok.startswith("-") and tok[0].isalpha():
            i += 1
            continue
        if not found_cmd:
            # This should be cmd_name
            if tok == cmd_name:
                found_cmd = True
            i += 1
            continue
        # After cmd_name, skip flags to find sub-command
        if tok.startswith("-"):
            # Flags with values: -X POST, --data '...'
            if tok in ("-X", "-d", "-F", "-T", "-o", "-O", "-L", "-e", "-A", "-H"):
                i += 2  # skip flag + value
                continue
            i += 1
            continue
        # First non-flag token after cmd_name = sub-command
        return tok
    return None


def _extract_paths_from_command(command_str: str) -> list[str]:
    """Extract file/directory paths from a command string.

    Returns paths that look like absolute or relative file references.
    """
    import shlex
    try:
        tokens = shlex.split(command_str, posix=True)
    except ValueError:
        tokens = command_str.split()

    paths = []
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        # Skip flags
        if tok.startswith("-"):
            # flags that take a value argument
            if tok in ("-X", "-d", "-F", "-T", "-o", "-O", "-e", "-A", "-H", "--output",
                        "--data", "--data-raw", "--data-binary", "--data-urlencode",
                        "--form", "--upload-file", "--post-data", "--post-file", "--body-file"):
                skip_next = True
            continue
        # Skip env assignments
        if "=" in tok and not tok.startswith("-") and tok[0].isalpha():
            continue
        # Skip URLs (http://, https://, ftp://)
        if "://" in tok:
            continue
        # Skip command names (single word, no slashes or dots)
        if "/" not in tok and "." not in tok and not tok.startswith("."):
            continue
        paths.append(tok)
    return paths


def _match_rule(
    command_str: str,
    paths: list[str],
    rule: CommandRule,
    workspace_dir: str | None,
) -> bool:
    """Check if a single CommandRule matches the command.

    Conditions are AND logic:
      1. scope=workspace → all absolute paths must be within workspace
      2. safe_paths → all absolute paths must match at least one prefix
      3. patterns → command must match at least one regex (OR)
      4. exclude_patterns → command must NOT match any regex (OR)
    """
    # 1. scope: workspace
    if rule.scope == "workspace":
        if not workspace_dir:
            return False
        for p in paths:
            if p.startswith("/") and not p.startswith(workspace_dir):
                return False
        # If no paths found, still match (relative commands are in-workspace)

    # 2. safe_paths — must have at least one absolute path that matches
    if rule.safe_paths:
        abs_paths = [p for p in paths if p.startswith("/")]
        if not abs_paths:
            return False  # No absolute paths → can't verify safety → don't match
        for p in abs_paths:
            if not any(p.startswith(sp) for sp in rule.safe_paths):
                return False

    # 3. patterns (OR: at least one must match)
    if rule.patterns:
        pat_matched = False
        for pat in rule.patterns:
            try:
                if re.search(pat, command_str, re.IGNORECASE):
                    pat_matched = True
                    break
            except re.error:
                continue
        if not pat_matched:
            return False

    # 4. exclude_patterns (OR: none must match)
    if rule.exclude_patterns:
        for ep in rule.exclude_patterns:
            try:
                if re.search(ep, command_str, re.IGNORECASE):
                    return False
            except re.error:
                continue

    return True


def _apply_command_rules(
    command_str: str,
    cmd_name: str | None,
    current_level: str,
    current_action: str,
    command_rules: list[CommandRule],
    workspace_dir: str | None = None,
) -> tuple[str, str, str]:
    """Apply command rules (exceptions or demotion_rules) with first-match-wins semantics.

    Returns (new_level, new_action, reason).
    """
    if not command_rules:
        return current_level, current_action, ""

    paths = _extract_paths_from_command(command_str)

    for rule in command_rules:
        if _match_rule(command_str, paths, rule, workspace_dir):
            return rule.level, rule.action, f"rule:{rule.id} — {rule.desc}"

    return current_level, current_action, ""


def _apply_demotion_rules(
    command_str: str,
    cmd_name: str | None,
    current_level: str,
    current_action: str,
    demotion_rules: dict[str, Any],
) -> tuple[str, str, str]:
    """Apply demotion rules to potentially lower the risk level.

    Returns (new_level, new_action, reason).
    """
    if not demotion_rules:
        return current_level, current_action, ""

    paths = _extract_paths_from_command(command_str)

    # Level priority: L0 < L1 < L2 < L3 < L4
    _LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4}

    best_match: tuple[str, str, str] | None = None
    best_level_val = _LEVEL_ORDER.get(current_level, 99)

    for rule_name, rule in demotion_rules.items():
        matched = False

        # ── Check safe_paths condition ──
        if rule.safe_paths and paths:
            # All paths must fall under at least one safe prefix.
            # Relative paths (not starting with '/') are considered in-workspace.
            all_safe = True
            for p in paths:
                if not p.startswith("/"):
                    continue  # relative → in-workspace → safe
                if not any(p.startswith(prefix) for prefix in rule.safe_paths):
                    all_safe = False
                    break
            if all_safe:
                matched = True

        else:
            # ── patterns + exclude_patterns are AND logic ──
            # Step 1: if patterns defined, command MUST match at least one
            if rule.patterns:
                pat_matched = False
                for p in rule.patterns:
                    try:
                        if re.search(p, command_str, re.IGNORECASE):
                            pat_matched = True
                            break
                    except re.error:
                        continue
                if not pat_matched:
                    # patterns defined but none matched → skip this rule
                    pass
                else:
                    # Step 2: if exclude_patterns also defined, command must NOT match any
                    if rule.exclude_patterns:
                        excluded = False
                        for ep in rule.exclude_patterns:
                            try:
                                if re.search(ep, command_str, re.IGNORECASE):
                                    excluded = True
                                    break
                            except re.error:
                                continue
                        if not excluded:
                            matched = True
                    else:
                        matched = True

            elif rule.exclude_patterns:
                # Only exclude_patterns (no patterns) → demote unless excluded
                excluded = False
                for ep in rule.exclude_patterns:
                    try:
                        if re.search(ep, command_str, re.IGNORECASE):
                            excluded = True
                            break
                    except re.error:
                        continue
                if not excluded:
                    matched = True

            elif not rule.safe_paths and not rule.patterns and not rule.exclude_patterns:
                # No conditions → unconditional demotion
                matched = True

        if matched:
            rule_level_val = _LEVEL_ORDER.get(rule.level, 99)
            if rule_level_val < best_level_val:
                best_level_val = rule_level_val
                best_match = (rule.level, rule.action, f"demotion:{rule_name} — {rule.desc}")

    if best_match:
        return best_match
    return current_level, current_action, ""


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
            "UnifiedToolGuardEngine loaded: %d commands, %d global_rules, %d evasion checks",
            len(self._config.commands),
            len(self._config.global_rules),
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
        for rule in self._config.global_rules:
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
        # Fallback: if _extract_command_name returned None (e.g. bare "env"),
        # check if the raw command string itself is a known L0 command.
        if not cmd_name:
            entry = self._config.commands.get(command_str.strip())
            if entry and entry.level == "L0":
                return []

        # Also skip if command is disabled
        disabled = set(self._config.access_control.disabled_rules)

        matches = []
        for rule, compiled_in, compiled_ex in self._compiled_rules:
            if rule.id in disabled:
                continue

            # Global rules apply to all commands (no command-specific filter)

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
    # Audit helper
    # ------------------------------------------------------------------

    def _audit_log_safely(
        self,
        action: str,
        cmd_name: str | None,
        command_str: str,
        level: str,
        reason: str,
        matched_rules: list[dict[str, Any]],
        evasion_flags: list[dict[str, Any]],
    ) -> None:
        """Write audit log for audit/confirm/block actions."""
        if action not in ("audit", "confirm", "block"):
            return
        try:
            from coapis.security.audit_logger import SecurityAuditLogger
            audit = SecurityAuditLogger.get_instance()
            if audit:
                audit.log_command_block(
                    user="system",
                    command=cmd_name or command_str,
                    level=level,
                    action=action,
                    reason=reason,
                    matched_rules=matched_rules,
                )
        except Exception:
            pass

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
        demotion_reason = ""
        # effective_action: the action that will actually be used (may be overridden by sub-command/demotion)
        effective_action: str | None = None

        # ── Layer 2.5: Sub-command Lookup + Rules/Demotion ──
        # Command rules (new) take PRIORITY over demotion (deprecated).
        # Both take PRIORITY over sub-command lookup because they
        # match on specific parameters (e.g. `git branch -D` vs `git branch`).
        if cmd_name and cmd_name in self._config.commands:
            entry = self._config.commands[cmd_name]

            # ── Build workspace_dir once for scope:workspace rules ──
            ws_dir = None
            owner = self._context.get("owner") if hasattr(self, "_context") else None
            if owner:
                from coapis.agents.config import derive_workspace_dir
                ws_dir = str(derive_workspace_dir(owner))

            # ── Merge all rule sources into one list (priority: exceptions > demotion_rules > deprecated) ──
            # New fields take precedence; fall back to deprecated 'rules' for backward compat.
            all_exceptions = entry.exceptions if entry.exceptions else []
            all_demotion = entry.demotion_rules if entry.demotion_rules else []
            if not all_exceptions and not all_demotion and entry.rules:
                # Backward compat: old 'rules' field treated as exceptions (strict-first)
                all_exceptions = entry.rules

            # Step 1: Try demotion_rules first (↓ more lenient)
            if all_demotion:
                new_level, new_action, reason = _apply_command_rules(
                    command_str, cmd_name, level or "L0", entry.action,
                    all_demotion, workspace_dir=ws_dir,
                )
                if reason:
                    level = new_level
                    effective_action = new_action
                    demotion_reason = reason

            # Step 2: Try exceptions (↑ stricter) — overrides demotion
            if all_exceptions:
                new_level, new_action, reason = _apply_command_rules(
                    command_str, cmd_name, level or "L0", entry.action,
                    all_exceptions, workspace_dir=ws_dir,
                )
                if reason:
                    level = new_level
                    effective_action = new_action
                    demotion_reason = reason

            # Step 3: Sub-command override (only if no exceptions/demotion matched)
            if not demotion_reason:
                sub_cmd = _extract_sub_command(command_str, cmd_name)
                if sub_cmd and sub_cmd in entry.sub_commands:
                    sc = entry.sub_commands[sub_cmd]
                    level = sc.level
                    effective_action = sc.action if sc.action else entry.action
                    demotion_reason = f"sub_command:{sub_cmd}"

        # ── Layer 2.6: Sub-command / demotion fast-path ──
        # If Layer 2.5 produced a result, still run global_rules (Layer 3)
        # before returning — dangerous patterns like curl|bash must not be
        # skipped by demotion.
        if demotion_reason:
            # Always check global_rules first — dangerous patterns like
            # curl|bash must not be skipped by demotion, even L0.
            # Non-L0 demotion: check global rules first
            rule_matches = self.match_rules(command_str, cmd_name)
            if rule_matches:
                # Global rule matched → override demotion
                matched_rules = []
                findings = []
                for rule, match in rule_matches:
                    matched_rules.append({"rule_id": rule.id, "match": match.group()})
                    findings.append(GuardFinding(
                        id=rule.id,
                        rule_id=rule.id,
                        category=_CATEGORY_MAP.get(rule.category, GuardThreatCategory.SENSITIVE_FILE_ACCESS),
                        severity=_SEVERITY_MAP.get(rule.severity.upper(), GuardSeverity.MEDIUM),
                        title=rule.description,
                        description=rule.description,
                        tool_name="execute_shell_command",
                        param_name="command",
                        matched_value=command_str[:200],
                        matched_pattern=match.group(),
                        remediation=rule.remediation,
                        guardian="global_rule",
                    ))
                final_action = "block"
                self._audit_log_safely(
                    final_action, cmd_name, command_str, level or "L0",
                    "global_rule_override", matched_rules, findings,
                )
                return _make_result(
                    action=final_action,
                    level=level,
                    command=cmd_name or command_str,
                    reason="global_rule_override",
                    matched_rules=matched_rules,
                    duration_ms=(time.monotonic() - t0) * 1000,
                )

            # No global rule matched → safe to return demoted result
            final_action = effective_action or "allow"
            if final_action in ("audit", "confirm"):
                self._audit_log_safely(
                    final_action, cmd_name, command_str, level or "L0",
                    demotion_reason, [], [],
                )
            return _make_result(
                action=final_action,
                level=level,
                command=cmd_name or command_str,
                reason=demotion_reason,
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # ── Layer 3: Pattern Rules (only for non-demoted commands) ──
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

        # ── Decision (for non-demoted commands) ──

        if blocked_rule:
            self._audit_log_safely(
                "block", cmd_name, command_str, level or "L0",
                f"Rule {blocked_rule['id']}: {blocked_rule['description']}",
                matched_rules, evasion_flags,
            )
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
            self._audit_log_safely(
                "block", cmd_name, command_str, level or "L0",
                f"Evasion detected on {level} command",
                matched_rules, evasion_flags,
            )
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
            self._audit_log_safely(
                "audit", cmd_name, command_str, level or "L0",
                "Findings detected but no block condition met",
                matched_rules, evasion_flags,
            )
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
            self._audit_log_safely(
                default_action, cmd_name, command_str, level or "L0",
                f"Command-level default: {default_action}",
                [], [],
            )
        return _make_result(
            action=default_action,
            level=level,
            command=cmd_name or command_str,
            reason=f"Command-level default: {default_action}",
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
