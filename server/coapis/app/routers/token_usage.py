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

"""Token usage router - Token usage endpoints (CoApis console compatible)."""

import logging
from datetime import date
from typing import Dict, Any

from ..permissions.decorators import require_permission
from fastapi import APIRouter, Query
from fastapi.requests import Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["token-usage"])


@router.get("/token-usage")
@require_permission("admin:admin")
async def get_token_usage(
    request: Request,
    start_date: str = Query("2026-01-01"),
    end_date: str = Query("2026-12-31"),
    model_name: str = Query(None),
    provider_id: str = Query(None),
) -> Dict[str, Any]:
    """Get token usage summary from TokenUsageManager."""
    try:
        from ...token_usage import get_token_usage_manager

        mgr = get_token_usage_manager()

        # Parse date strings
        sd = date.fromisoformat(start_date) if start_date else date.today()
        ed = date.fromisoformat(end_date) if end_date else date.today()

        summary = await mgr.get_summary(
            start_date=sd,
            end_date=ed,
            model_name=model_name,
            provider_id=provider_id,
        )

        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_tokens": summary.total_prompt_tokens + summary.total_completion_tokens,
            "prompt_tokens": summary.total_prompt_tokens,
            "completion_tokens": summary.total_completion_tokens,
            "call_count": summary.total_calls,
            "by_model": {
                m: {"prompt": v.prompt_tokens, "completion": v.completion_tokens, "calls": v.call_count}
                for m, v in summary.by_model.items()
            },
            "by_provider": {
                p: {"prompt": v.prompt_tokens, "completion": v.completion_tokens, "calls": v.call_count}
                for p, v in summary.by_provider.items()
            },
        }
    except Exception as e:
        logger.warning(f"Failed to get token usage: {e}")
        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "call_count": 0,
            "by_model": {},
            "by_provider": {},
            "error": str(e),
        }
