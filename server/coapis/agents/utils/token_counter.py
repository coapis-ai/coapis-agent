# -*- coding: utf-8 -*-
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

"""Token counting utilities."""

from typing import TYPE_CHECKING

from .estimate_token_counter import EstimatedTokenCounter

if TYPE_CHECKING:
    from coapis.config.config import AgentProfileConfig


def get_token_counter(
    agent_config: "AgentProfileConfig",
) -> EstimatedTokenCounter:
    """Get token counter for the given agent config.

    Args:
        agent_config: Agent profile configuration containing running settings.

    Returns:
        An EstimatedTokenCounter instance with the configured divisor.
    """
    divisor = (
        agent_config.running.light_context_config.token_count_estimate_divisor
    )
    return EstimatedTokenCounter(estimate_divisor=divisor)
