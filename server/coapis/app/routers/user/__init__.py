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

"""User routers - personal settings endpoints.

个人设置相关 API，包括：
- /user/me — 个人信息
- /user/preferences — 个人偏好设置
- /user/points — 积分信息
- /user/tokens — Token 用量
- /user/feedback — 反馈/建议
"""
from fastapi import APIRouter

from .user_me import router as user_me_router
from .user_preferences import router as user_preferences_router
from .user_feedback import router as user_feedback_router

router = APIRouter()

router.include_router(user_me_router)
router.include_router(user_preferences_router)
router.include_router(user_feedback_router)
