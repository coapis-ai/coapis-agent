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

"""
P2-2 SSO 集成 API 端点

端点列表：
- GET   /api/sso/providers          - 列出已配置的 IdP
- POST  /api/sso/providers          - 添加 IdP 配置
- PUT   /api/sso/providers/{name}   - 更新 IdP 配置
- DELETE /api/sso/providers/{name}  - 删除 IdP
- POST  /api/sso/providers/{name}/discover  - 发现 OIDC 配置
- GET   /api/sso/authorize/{name}   - 获取授权 URL（含 PKCE）
- POST  /api/sso/callback/{name}    - SSO 回调处理
- GET   /api/sso/status             - SSO 功能状态

权限：admin 角色可访问全部端点
"""
from __future__ import annotations

import logging
import secrets
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import require_admin
from .oidc_provider import OIDCProviderConfig, OIDCProvider, oidc_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sso", tags=["sso"])


# ── Request/Response Models ────────────────────────────────────────

class ProviderCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="Provider display name")
    issuer: str = Field(..., min_length=1, description="OIDC issuer URL")
    client_id: str = Field(..., min_length=1, description="OIDC client ID")
    client_secret: str = Field(..., min_length=1, description="OIDC client secret")
    scopes: Optional[list[str]] = Field(default=None, description="OIDC scopes")
    auto_provision: bool = Field(default=True, description="Auto-create users on first login")
    role_mapping: Optional[Dict[str, str]] = Field(default=None, description="Role mapping")
    default_role: str = Field(default="user", description="Default role for new users")


class ProviderUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    auto_provision: Optional[bool] = None
    scopes: Optional[list[str]] = None
    role_mapping: Optional[Dict[str, str]] = None
    default_role: Optional[str] = None
    client_secret: Optional[str] = None  # Allow secret rotation


class AuthorizationResponse(BaseModel):
    authorization_url: str
    state: str
    code_challenge: str


class SSOStatusResponse(BaseModel):
    oidc_enabled: bool = True
    saml_enabled: bool = False  # Enterprise only
    providers_count: int = 0
    providers: list[Dict[str, Any]] = []
    enterprise_features: list[str] = [
        "SAML 2.0 support",
        "Multi-IdP routing",
        "Advanced role mapping",
        "Just-In-Time provisioning",
        "Attribute-based access control",
    ]


# ── Endpoints ──────────────────────────────────────────────────────

@router.get("/status")
async def get_sso_status(request: Request) -> SSOStatusResponse:
    """SSO 功能状态（含企业版功能预览）."""
    require_admin(request)
    providers = oidc_manager.list_providers()
    return SSOStatusResponse(
        providers_count=len(providers),
        providers=providers,
    )


@router.get("/providers")
async def list_providers(request: Request) -> list[Dict[str, Any]]:
    """列出已配置的 Identity Provider."""
    require_admin(request)
    return oidc_manager.list_providers()


@router.post("/providers", status_code=201)
async def add_provider(request: Request, body: ProviderCreateRequest) -> Dict[str, Any]:
    """添加新的 Identity Provider 配置."""
    require_admin(request)

    # Check for duplicate
    if oidc_manager.get_provider(body.name):
        raise HTTPException(status_code=409, detail=f"Provider '{body.name}' already exists")

    config = OIDCProviderConfig(
        name=body.name,
        issuer=body.issuer,
        client_id=body.client_id,
        client_secret=body.client_secret,
        scopes=body.scopes or ["openid", "profile", "email"],
        auto_provision=body.auto_provision,
        role_mapping=body.role_mapping or {},
        default_role=body.default_role,
    )

    oidc_manager.add_provider(config)

    # Try auto-discovery
    try:
        import asyncio
        await oidc_manager.discover(body.name)
    except Exception as e:
        logger.warning(f"Auto-discovery failed for '{body.name}': {e}")

    return {
        "success": True,
        "name": body.name,
        "message": f"Provider '{body.name}' added successfully",
    }


@router.put("/providers/{name}")
async def update_provider(request: Request, name: str, body: ProviderUpdateRequest) -> Dict[str, Any]:
    """更新 Identity Provider 配置."""
    require_admin(request)

    config = oidc_manager.get_provider(name)
    if not config:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    # Apply updates
    if body.enabled is not None:
        config.enabled = body.enabled
    if body.auto_provision is not None:
        config.auto_provision = body.auto_provision
    if body.scopes is not None:
        config.scopes = body.scopes
    if body.role_mapping is not None:
        config.role_mapping = body.role_mapping
    if body.default_role is not None:
        config.default_role = body.default_role
    if body.client_secret is not None:
        config.client_secret = body.client_secret

    return {
        "success": True,
        "name": name,
        "message": f"Provider '{name}' updated successfully",
    }


@router.delete("/providers/{name}")
async def remove_provider(request: Request, name: str) -> Dict[str, Any]:
    """删除 Identity Provider 配置."""
    require_admin(request)

    if not oidc_manager.remove_provider(name):
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    return {
        "success": True,
        "name": name,
        "message": f"Provider '{name}' removed successfully",
    }


@router.post("/providers/{name}/discover")
async def discover_provider(request: Request, name: str) -> Dict[str, Any]:
    """发现并加载 OIDC Provider 配置（从 .well-known 端点）."""
    require_admin(request)

    config = oidc_manager.get_provider(name)
    if not config:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    try:
        import asyncio
        doc = await oidc_manager.discover(name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Discovery failed: {e}")

    if not doc:
        raise HTTPException(status_code=502, detail="Discovery returned no data")

    return {
        "success": True,
        "name": name,
        "discovery": doc.model_dump(),
    }


@router.get("/authorize/{name}")
async def get_authorization_url(
    request: Request,
    name: str,
    redirect_uri: str = "",
) -> AuthorizationResponse:
    """生成 OIDC 授权 URL（含 PKCE 参数）.
    
    前端重定向此 URL 开始 SSO 登录流程。
    """
    require_admin(request)

    config = oidc_manager.get_provider(name)
    if not config or not config.enabled:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found or disabled")

    # Generate PKCE parameters
    import hashlib
    import base64

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")

    # Generate state (for CSRF protection)
    state = secrets.token_urlsafe(32)

    # Build redirect_uri if not provided
    if not redirect_uri:
        # Default to callback endpoint
        redirect_uri = f"/api/sso/callback/{name}"

    # Build authorization URL
    auth_url = oidc_manager.build_authorization_url(
        name=name,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
    )

    return AuthorizationResponse(
        authorization_url=auth_url,
        state=state,
        code_challenge=code_verifier,  # Return verifier for callback validation
    )


@router.post("/callback/{name}")
async def handle_callback(
    request: Request,
    name: str,
    code: str = "",
    state: str = "",
) -> Dict[str, Any]:
    """处理 OIDC 授权回调.
    
    NOTE: This is a stub. Full implementation requires:
    - Token exchange with IdP
    - ID token verification
    - Userinfo fetch
    - User provisioning/mapping
    
    Enterprise version includes full implementation.
    """
    require_admin(request)

    config = oidc_manager.get_provider(name)
    if not config:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    return {
        "error": "not_implemented",
        "error_description": "SSO callback handling requires enterprise license",
        "preview": {
            "sub": "***",
            "email": "***@example.com",
            "name": "***",
            "role": config.default_role,
        },
        "upgrade_url": "https://coapis.com/upgrade",
    }
