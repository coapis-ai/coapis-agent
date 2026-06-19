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

"""Agent statistics models."""

from __future__ import annotations

from pydantic import BaseModel


class ChannelStats(BaseModel):
    channel: str
    session_count: int
    user_messages: int
    assistant_messages: int
    total_messages: int


class DailyStats(BaseModel):
    date: str
    chats: int
    active_sessions: int
    user_messages: int
    assistant_messages: int
    total_messages: int
    prompt_tokens: int
    completion_tokens: int
    llm_calls: int
    tool_calls: int


class AgentStatsSummary(BaseModel):
    total_active_sessions: int
    total_messages: int
    total_user_messages: int
    total_assistant_messages: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_llm_calls: int
    total_tool_calls: int
    by_date: list[DailyStats]
    channel_stats: list[ChannelStats]
    start_date: str
    end_date: str
