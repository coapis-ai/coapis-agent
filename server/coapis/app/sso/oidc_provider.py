# -*- coding: utf-8 -*-
"""OIDC Provider configuration and client."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class OIDCProviderConfig(BaseModel):
    """OIDC Identity Provider configuration."""
    name: str = Field(..., description="Provider display name (e.g., 'Google', 'Azure AD')")
    issuer: str = Field(..., description="OIDC issuer URL (e.g., 'https://accounts.google.com')")
    client_id: str = Field(..., description="OIDC client ID")
    client_secret: str = Field(..., description="OIDC client secret")
    authorization_endpoint: str = Field("", description="Authorization endpoint (auto from discovery)")
    token_endpoint: str = Field("", description="Token endpoint (auto from discovery)")
    userinfo_endpoint: str = Field("", description="Userinfo endpoint (auto from discovery)")
    jwks_uri: str = Field("", description="JWKS URI (auto from discovery)")
    scopes: List[str] = Field(default_factory=lambda: ["openid", "profile", "email"])
    enabled: bool = Field(default=True, description="Whether this provider is enabled")
    auto_provision: bool = Field(default=True, description="Auto-create users on first login")
    role_mapping: Dict[str, str] = Field(
        default_factory=dict,
        description="Map IdP roles to CoApis roles (e.g., {'admin': 'admin', 'user': 'user'})",
    )
    default_role: str = Field(default="user", description="Default role for auto-provisioned users")


class OIDCDiscoveryDoc(BaseModel):
    """OIDC Provider Configuration (from .well-known/openid-configuration)."""
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str = ""
    jwks_uri: str
    scopes_supported: List[str] = Field(default_factory=list)
    subject_types_supported: List[str] = Field(default_factory=list)
    id_token_signing_alg_values_supported: List[str] = Field(default_factory=list)


class OIDCProvider:
    """Manages OIDC Identity Provider connections.
    
    Open-source version: basic OIDC flow (authorization code + PKCE).
    Enterprise version: SAML 2.0, multi-IdP, advanced mapping, Just-In-Time provisioning.
    """

    def __init__(self):
        self._providers: Dict[str, OIDCProviderConfig] = {}
        self._discovery_cache: Dict[str, OIDCDiscoveryDoc] = {}

    # ── Provider management ────────────────────────────────────────

    def add_provider(self, config: OIDCProviderConfig) -> None:
        """Register an OIDC provider."""
        self._providers[config.name.lower()] = config
        logger.info(f"OIDC provider '{config.name}' registered")

    def remove_provider(self, name: str) -> bool:
        """Remove an OIDC provider."""
        key = name.lower()
        if key in self._providers:
            del self._providers[key]
            self._discovery_cache.pop(key, None)
            logger.info(f"OIDC provider '{name}' removed")
            return True
        return False

    def get_provider(self, name: str) -> Optional[OIDCProviderConfig]:
        """Get provider config by name."""
        return self._providers.get(name.lower())

    def list_providers(self) -> List[Dict[str, Any]]:
        """List all configured providers (secrets redacted)."""
        result = []
        for name, cfg in self._providers.items():
            result.append({
                "name": cfg.name,
                "issuer": cfg.issuer,
                "enabled": cfg.enabled,
                "auto_provision": cfg.auto_provision,
                "scopes": cfg.scopes,
                "default_role": cfg.default_role,
                "has_secrets": bool(cfg.client_secret),
            })
        return result

    # ── Discovery ──────────────────────────────────────────────────

    async def discover(self, name: str) -> Optional[OIDCDiscoveryDoc]:
        """Fetch OIDC discovery document and update config."""
        cfg = self._providers.get(name.lower())
        if not cfg:
            return None

        if name.lower() in self._discovery_cache:
            return self._discovery_cache[name.lower()]

        try:
            import httpx
            discovery_url = f"{cfg.issuer}/.well-known/openid-configuration"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(discovery_url)
                resp.raise_for_status()
                data = resp.json()

            doc = OIDCDiscoveryDoc(**data)

            # Update config with discovered endpoints
            if not cfg.authorization_endpoint:
                cfg.authorization_endpoint = doc.authorization_endpoint
            if not cfg.token_endpoint:
                cfg.token_endpoint = doc.token_endpoint
            if not cfg.userinfo_endpoint:
                cfg.userinfo_endpoint = doc.userinfo_endpoint
            if not cfg.jwks_uri:
                cfg.jwks_uri = doc.jwks_uri

            self._discovery_cache[name.lower()] = doc
            logger.info(f"OIDC discovery completed for '{cfg.name}'")
            return doc
        except Exception as e:
            logger.error(f"OIDC discovery failed for '{cfg.name}': {e}")
            return None

    # ── Authorization flow ─────────────────────────────────────────

    def build_authorization_url(
        self,
        name: str,
        redirect_uri: str,
        state: str,
        code_challenge: str = "",
        code_challenge_method: str = "S256",
    ) -> str:
        """Build OIDC authorization URL with PKCE."""
        cfg = self._providers.get(name.lower())
        if not cfg or not cfg.enabled:
            raise ValueError(f"OIDC provider '{name}' not found or disabled")

        auth_url = cfg.authorization_endpoint
        if not auth_url:
            raise ValueError(f"Authorization endpoint not configured for '{name}'")

        from urllib.parse import urlencode, urlparse, urlunparse

        params = {
            "response_type": "code",
            "client_id": cfg.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(cfg.scopes),
            "state": state,
        }

        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = code_challenge_method

        # Append params to URL
        parsed = urlparse(auth_url)
        query = dict(urlparse(auth_url).query.split("&")) if parsed.query else {}
        query.update(params)
        new_query = urlencode(query)
        result = urlunparse(parsed._replace(query=new_query))

        return result

    # ── Stub: Token exchange (requires httpx + crypto in production) ──

    async def exchange_code(
        self,
        name: str,
        code: str,
        redirect_uri: str,
        code_verifier: str = "",
    ) -> Dict[str, Any]:
        """Exchange authorization code for tokens.
        
        NOTE: This is a stub. Full implementation requires:
        - httpx for HTTP requests
        - jwt/pyjwt for ID token verification
        - JWK set validation
        
        Enterprise version includes full implementation.
        """
        cfg = self._providers.get(name.lower())
        if not cfg:
            return {"error": "provider_not_found", "error_description": f"Provider '{name}' not configured"}

        return {
            "error": "not_implemented",
            "error_description": "OIDC token exchange requires enterprise license or external OIDC library",
            "preview": {
                "access_token": "***",
                "id_token": "***",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
            "upgrade_url": "https://coapis.com/upgrade",
        }

    # ── Stub: Userinfo ─────────────────────────────────────────────

    async def get_userinfo(self, name: str, access_token: str) -> Dict[str, Any]:
        """Fetch user profile from userinfo endpoint.
        
        NOTE: Stub - returns preview structure.
        """
        cfg = self._providers.get(name.lower())
        if not cfg:
            return {"error": "provider_not_found"}

        return {
            "error": "not_implemented",
            "error_description": "Userinfo fetch requires enterprise license",
            "preview": {
                "sub": "***",
                "email": "***@example.com",
                "name": "***",
                "picture": "***",
            },
            "upgrade_url": "https://coapis.com/upgrade",
        }


# Module-level singleton
oidc_manager = OIDCProvider()
