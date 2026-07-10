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

"""
P2-2 SSO 集成 - 企业级单点登录

功能：
- OIDC (OpenID Connect) 协议适配
- SAML 2.0 协议适配（企业版）
- 多 Identity Provider 管理
- 自动用户创建/映射

开源版：OIDC 基础支持
企业版：SAML + 多 IdP + 高级映射规则
"""

from .oidc_provider import OIDCProvider
from .router import router as sso_router

__all__ = ["OIDCProvider", "sso_router"]
