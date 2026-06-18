# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Approval helpers for tool-guard mediated tool execution."""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ToolGuardResult


class ApprovalDecision(str, Enum):
    """Possible approval outcomes for a guarded tool call."""

    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"


def format_findings_summary(
    result: "ToolGuardResult",
    *,
    max_items: int = 3,
) -> str:
    """Format findings into a concise markdown summary."""
    if not result.findings:
        return "No specific risk rules matched."

    lines = []
    for finding in result.findings[:max_items]:
        lines.append(
            f"- [{finding.severity.value}] {finding.description}",
        )
        # Don't add remediation here - it will be added separately at the end

    # Calculate remaining based on findings processed, not lines added
    processed_count = min(max_items, len(result.findings))
    remaining = result.findings_count - processed_count
    if remaining > 0:
        lines.append(f"- ... and {remaining} more finding(s) omitted")
    return "\n".join(lines)
