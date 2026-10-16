# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Shared helpers for the tool-guard framework."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ToolGuardResult

logger = logging.getLogger("coapis.tool_guard")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log_findings(tool_name: str, result: "ToolGuardResult") -> None:
    """Emit structured logs for each finding."""
    from .models import GuardSeverity

    _HIGH_SEVERITIES = (GuardSeverity.CRITICAL, GuardSeverity.HIGH)

    for finding in result.findings:
        if finding.severity in _HIGH_SEVERITIES:
            log_fn = logger.warning
        else:
            log_fn = logger.info

        log_fn(
            "[TOOL GUARD] %s | tool=%s param=%s rule=%s | %s | matched=%r",
            finding.severity.value,
            tool_name,
            finding.param_name or "*",
            finding.rule_id,
            finding.description,
            finding.matched_value,
        )

    summary_fn = (
        logger.warning
        if result.max_severity in _HIGH_SEVERITIES
        else logger.info
    )
    summary_fn(
        "[TOOL GUARD] Summary for tool '%s': %d finding(s), "
        "max_severity=%s, duration=%.3fs",
        tool_name,
        result.findings_count,
        result.max_severity.value,
        result.guard_duration_seconds,
    )


# ---------------------------------------------------------------------------
# Retired (C2/C5)
# ---------------------------------------------------------------------------
#
# ``resolve_guarded_tools`` / ``resolve_denied_tools`` / ``_load_config_tool_guard``
# used to merge three sources (constructor arg → env var → config.json →
# built-in defaults) for the legacy engine.  Access control now lives only in
# ``access_control`` of the single YAML source and is read by
# ``UnifiedToolGuardEngine`` directly, so the resolvers are gone.
