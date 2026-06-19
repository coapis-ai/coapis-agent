# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
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

"""Abstract base class for all security analyzers.

Every analyzer must subclass :class:`BaseAnalyzer` and implement
:meth:`analyze`.  The interface is intentionally minimal so that
new detection engines (e.g. LLM-based, behavioural dataflow) can be
added as drop-in plugins without touching the scanner orchestrator.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from ..models import Finding, SkillFile

if TYPE_CHECKING:
    from ..scan_policy import ScanPolicy


class BaseAnalyzer(ABC):
    """Abstract base class for all security analyzers.

    Parameters
    ----------
    name:
        Human-readable analyzer name (used in :attr:`Finding.analyzer`).
    policy:
        Optional :class:`ScanPolicy` for org-specific rule scoping,
        severity overrides, and allowlists.  When *None*, analysers
        use their own built-in defaults.
    """

    def __init__(
        self,
        name: str,
        *,
        policy: "ScanPolicy | None" = None,
    ) -> None:
        self.name = name
        # Lazily import to avoid circular dependencies
        if policy is None:
            from ..scan_policy import ScanPolicy

            policy = ScanPolicy.default()
        self._policy = policy

    @property
    def policy(self) -> "ScanPolicy":
        """The active scan policy."""
        return self._policy

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def analyze(
        self,
        skill_dir: Path,
        files: list[SkillFile],
        *,
        skill_name: str | None = None,
    ) -> list[Finding]:
        """Analyze a skill package for security issues.

        Parameters
        ----------
        skill_dir:
            Root directory of the skill.
        files:
            Pre-discovered list of :class:`SkillFile` objects belonging
            to the skill.
        skill_name:
            Optional skill name for richer finding messages.

        Returns
        -------
        list[Finding]
            Findings discovered by this analyzer.
        """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_name(self) -> str:  # noqa: D401
        """Analyzer name."""
        return self.name
