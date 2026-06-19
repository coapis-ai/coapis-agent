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

"""Models router - Provider and model management (CoApis console compatible)."""

import logging
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.requests import Request
from pydantic import BaseModel

from ..permissions.decorators import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


class ModelInfo(BaseModel):
    id: str
    name: str
    supports_multimodal: Optional[bool] = None
    supports_image: Optional[bool] = None
    supports_video: Optional[bool] = None
    probe_source: Optional[str] = None
    is_free: bool = False
    generate_kwargs: Dict[str, Any] = {}


class ProviderInfo(BaseModel):
    id: str
    name: str
    api_key_prefix: str = ""
    chat_model: str = ""
    models: List[Dict[str, Any]] = []
    extra_models: List[Dict[str, Any]] = []
    is_custom: bool = False
    is_local: bool = False
    support_model_discovery: bool = False
    support_connection_check: bool = False
    freeze_url: bool = False
    require_api_key: bool = True
    api_key: str = ""
    base_url: str = ""
    generate_kwargs: Dict[str, Any] = {}


class ModelSlotConfig(BaseModel):
    provider_id: str
    model: str


class ActiveModelsInfo(BaseModel):
    active_llm: Optional[ModelSlotConfig] = None


class GetActiveModelsRequest(BaseModel):
    scope: str = "effective"
    agent_id: Optional[str] = None


class ModelSlotRequest(BaseModel):
    provider_id: str
    model: str
    scope: str
    agent_id: Optional[str] = None


class ProviderConfigRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    chat_model: Optional[str] = None
    generate_kwargs: Optional[Dict[str, Any]] = None


def _get_providers(request: Request) -> List[Dict[str, Any]]:
    """Get providers from global config."""
    from ...config.utils import load_config
    config = load_config()
    providers_config = config.get("providers", {})

    result = []
    for provider_id, provider_conf in providers_config.items():
        if not isinstance(provider_conf, dict):
            continue

        # Extract model info
        model = provider_conf.get("model", "")
        models = []
        if model:
            models.append({
                "id": model,
                "name": model,
                "supports_multimodal": None,
                "supports_image": None,
                "supports_video": None,
                "is_free": False,
                "generate_kwargs": {},
            })

        result.append({
            "id": provider_id,
            "name": provider_id,
            "api_key_prefix": "",
            "chat_model": model,
            "models": models,
            "extra_models": [],
            "is_custom": False,
            "is_local": "local" in provider_id.lower(),
            "support_model_discovery": False,
            "support_connection_check": True,
            "freeze_url": False,
            "require_api_key": bool(provider_conf.get("api_key", "")),
            "api_key": provider_conf.get("api_key", ""),
            "base_url": provider_conf.get("base_url", ""),
            "generate_kwargs": provider_conf.get("generate_kwargs", {}),
        })

    return result


@router.get("/models")
@require_permission("admin:admin")
async def list_providers(request: Request) -> List[Dict[str, Any]]:
    """List all providers (returns ProviderInfo array)."""
    return _get_providers(request)


@router.get("/models/active")
@require_permission("admin:admin")
async def get_active_models(
    request: Request,
    scope: str = Query("effective"),
    agent_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Get active model configuration."""
    providers = _get_providers(request)
    if not providers:
        return {"active_llm": None}

    # Get first available provider as active
    for provider in providers:
        if provider["models"]:
            return {
                "active_llm": {
                    "provider_id": provider["id"],
                    "model": provider["models"][0]["id"],
                }
            }

    return {"active_llm": None}


@router.put("/models/active")
@require_permission("admin:admin")
async def set_active_model(
    request: Request,
    payload: ModelSlotRequest = Body(...),
) -> Dict[str, Any]:
    """Set active model configuration."""
    return {
        "active_llm": {
            "provider_id": payload.provider_id,
            "model": payload.model,
        }
    }


@router.put("/models/{provider_id}/config")
@require_permission("admin:admin")
async def configure_provider(
    request: Request,
    provider_id: str,
    payload: ProviderConfigRequest = Body(...),
) -> Dict[str, Any]:
    """Configure a provider."""
    from ...config.utils import load_config, save_config
    config = load_config()
    providers = config.get("providers", {})

    if provider_id not in providers:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Update provider config
    if payload.api_key is not None:
        providers[provider_id]["api_key"] = payload.api_key
    if payload.base_url is not None:
        providers[provider_id]["base_url"] = payload.base_url
    if payload.chat_model is not None:
        providers[provider_id]["model"] = payload.chat_model

    # Save back to config
    config["providers"] = providers
    save_config(config)

    return _get_providers(request)[0]  # Return updated provider


@router.get("/models/custom-providers")
@require_permission("admin:admin")
async def list_custom_providers(request: Request) -> List[Dict[str, Any]]:
    """List custom providers (returns ProviderInfo array)."""
    providers = _get_providers(request)
    return [p for p in providers if p.get("is_custom", False)]


@router.post("/models/custom-providers")
@require_permission("admin:admin")
async def create_custom_provider(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Create a custom provider."""
    # For now, just return success (CoApis doesn't support custom providers yet)
    return {
        "id": payload.get("id", ""),
        "name": payload.get("name", ""),
        "models": [],
        "is_custom": True,
    }


@router.delete("/models/custom-providers/{provider_id}")
@require_permission("admin:admin")
async def delete_custom_provider(
    request: Request,
    provider_id: str,
) -> List[Dict[str, Any]]:
    """Delete a custom provider."""
    return _get_providers(request)


@router.post("/models/{provider_id}/models")
@require_permission("admin:admin")
async def add_model(
    request: Request,
    provider_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Add a model to a provider."""
    return _get_providers(request)[0] if _get_providers(request) else {}


@router.delete("/models/{provider_id}/models/{model_id}")
@require_permission("admin:admin")
async def remove_model(
    request: Request,
    provider_id: str,
    model_id: str,
) -> Dict[str, Any]:
    """Remove a model from a provider."""
    return _get_providers(request)[0] if _get_providers(request) else {}


@router.put("/models/{provider_id}/models/{model_id}/config")
async def configure_model(
    request: Request,
    provider_id: str,
    model_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Configure a model."""
    return _get_providers(request)[0] if _get_providers(request) else {}
