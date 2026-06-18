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

"""User feedback router - submit bug reports and feature suggestions."""
from __future__ import annotations

import logging
import time
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Body, Request
from pydantic import BaseModel

from ....user_system.database import UserSystemDB

logger = logging.getLogger(__name__)

router = APIRouter(tags=["user/feedback"])


# ── Pydantic models ─────────────────────────────────────────────────────

class FeedbackCreate(BaseModel):
    type: str = "bug"  # bug / suggestion
    title: str
    description: str
    severity: str = "medium"  # low / medium / high / critical


class FeedbackResponse(BaseModel):
    id: int
    type: str
    title: str
    description: str
    severity: str
    status: str = "open"  # open / reviewing / resolved / closed
    created_at: Optional[float] = None


# ── Helper functions ─────────────────────────────────────────────────────

def _get_username(request: Request) -> str:
    """获取当前用户名."""
    username = getattr(request.state, "username", "anonymous")
    if username == "anonymous":
        raise HTTPException(status_code=401, detail="需要登录")
    return username


# ── Routes ───────────────────────────────────────────────────────────────

@router.post("/user/feedback")
async def submit_feedback(
    request: Request,
    payload: FeedbackCreate = Body(...),
) -> FeedbackResponse:
    """提交问题反馈或功能建议."""
    username = _get_username(request)
    db = UserSystemDB()
    
    # 确保 user_feedback 表存在
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'open',
            created_at REAL DEFAULT CURRENT_TIMESTAMP,
            updated_at REAL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()
    
    user = db.get_user_by_username(username)
    user_id = user["id"] if user else 0
    
    row = db.execute(
        "INSERT INTO user_feedback (user_id, type, title, description, severity) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, payload.type, payload.title, payload.description, payload.severity),
    )
    db.commit()
    
    return FeedbackResponse(
        id=row.lastrowid,
        type=payload.type,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        status="open",
        created_at=time.time(),
    )
