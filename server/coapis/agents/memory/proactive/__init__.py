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

"""Proactive memory submodule for CoApis agents."""

from .proactive_types import (
    ProactiveConfig,
    ProactiveTask,
    ProactiveQueryResult,
)
from .proactive_trigger import (
    enable_proactive_for_session,
    proactive_trigger_loop,
    proactive_tasks,
    proactive_configs,
)
from .proactive_responder import generate_proactive_response
from .proactive_utils import extract_content

__all__ = [
    "ProactiveConfig",
    "ProactiveTask",
    "ProactiveQueryResult",
    "enable_proactive_for_session",
    "proactive_trigger_loop",
    "proactive_tasks",
    "proactive_configs",
    "generate_proactive_response",
    "extract_content",
]
