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

"""Simplified plan mode for CoApis."""

from .hints import (
    SimplePlanToHint,
    set_plan_gate,
    check_plan_tool_gate,
    should_skip_auto_continue,
)

__all__ = [
    "SimplePlanToHint",
    "set_plan_gate",
    "check_plan_tool_gate",
    "should_skip_auto_continue",
]
