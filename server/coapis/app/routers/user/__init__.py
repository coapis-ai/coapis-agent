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
