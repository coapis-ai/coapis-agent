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

"""Tool to query token usage statistics."""

from datetime import date, timedelta

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...token_usage import get_token_usage_manager

from .registry import register_tool


@register_tool(
    name="get_token_usage",
    description="查询 LLM token 用量",
    category="builtin",
    tags=['token', 'usage'],
    scene="core",
)
async def get_token_usage(
    days: int = 30,
    model_name: str | None = None,
    provider_id: str | None = None,
) -> ToolResponse:
    """Query LLM token usage over the past N days.

    Use this when the user asks about token consumption, API usage,
    or how many tokens have been used.

    Args:
        days: Number of days to look back (default: 30).
        model_name: Optional model name to filter by.
        provider_id: Optional provider ID to filter by.

    Returns:
        ToolResponse with a formatted summary of token usage.
    """
    end = date.today()
    start = end - timedelta(days=max(1, min(days, 365)))
    summary = await get_token_usage_manager().get_summary(
        start_date=start,
        end_date=end,
        model_name=model_name,
        provider_id=provider_id,
    )

    lines: list[str] = []
    filter_desc = []
    if model_name:
        filter_desc.append(f"model={model_name}")
    if provider_id:
        filter_desc.append(f"provider={provider_id}")
    if not filter_desc:
        filter_desc.append("all models")
    lines.append(f"Token usage ({start} ~ {end}, {', '.join(filter_desc)}):")
    lines.append("")
    total_tokens = (
        summary.total_prompt_tokens + summary.total_completion_tokens
    )
    lines.append(f"- Total tokens: {total_tokens:,}")
    lines.append(f"- Prompt tokens: {summary.total_prompt_tokens:,}")
    lines.append(
        f"- Completion tokens: {summary.total_completion_tokens:,}",
    )
    lines.append(f"- Total calls: {summary.total_calls:,}")
    lines.append("")

    if summary.by_model:
        lines.append("By model:")
        for model, stats in summary.by_model.items():
            tokens = stats.prompt_tokens + stats.completion_tokens
            lines.append(
                f"  - {model}: {tokens:,} tokens ({stats.call_count} calls)",
            )
        lines.append("")

    if summary.by_date and len(summary.by_date) <= 14:
        lines.append("By date:")
        for dt, stats in list(summary.by_date.items())[-7:]:
            tokens = stats.prompt_tokens + stats.completion_tokens
            lines.append(
                f"  - {dt}: {tokens:,} tokens ({stats.call_count} calls)",
            )
    elif summary.by_date:
        lines.append(
            f"By date: {len(summary.by_date)} days with usage "
            "(see console for details)",
        )

    text = "\n".join(lines) if lines else "No token usage data in this period."
    return ToolResponse(
        content=[TextBlock(type="text", text=text)],
    )
