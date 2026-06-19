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
