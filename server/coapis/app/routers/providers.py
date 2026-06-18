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

"""API routes for LLM providers and models."""

from __future__ import annotations

import logging
from typing import List, Literal, Optional
from copy import deepcopy

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
)
from pydantic import BaseModel, Field

from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)

from ..permissions.decorators import require_permission
from ..agent_context import get_agent_for_request
from ..utils import schedule_agent_reload
from ...config.config import load_agent_config, save_agent_config
from ...providers.provider import ProviderInfo, ModelInfo
from ...config.config import ActiveModelsInfo
from ...providers.provider_manager import ProviderManager
from ...providers.openrouter_provider import OpenRouterProvider
from ...config.config import ModelSlotConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

ChatModelName = Literal[
    "OpenAIChatModel",
    "AnthropicChatModel",
    "GeminiChatModel",
]

# effective: agent-specific if set, otherwise global
# global: the global model only, ignoring any agent-specific setting
# agent: a specific agent's model only, error if not set
ActiveModelReadScope = Literal["effective", "global", "agent"]
ActiveModelWriteScope = Literal["global", "agent"]


def get_provider_manager(request: Request) -> ProviderManager:
    """Get the provider manager from app state.

    Args:
        request: FastAPI request object
    """
    provider_manager = getattr(request.app.state, "provider_manager", None)
    if provider_manager is None:
        provider_manager = ProviderManager.get_instance()
    return provider_manager


class ProviderConfigRequest(BaseModel):
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Chat model class name for protocol selection",
    )
    generate_kwargs: Optional[dict] = Field(
        default_factory=dict,
        description=(
            "Configuration in json format, will be expanded "
            "and passed to generation calls "
            "(e.g., openai.chat.completions, anthropic.messages)."
        ),
    )


class ModelSlotRequest(BaseModel):
    provider_id: str = Field(..., description="Provider to use")
    model: str = Field(..., description="Model identifier")
    scope: ActiveModelWriteScope = Field(
        ...,
        description="Whether to update the global model or a specific agent",
    )
    agent_id: Optional[str] = Field(
        default=None,
        description="Target agent ID when scope is 'agent'",
    )


class CreateCustomProviderRequest(BaseModel):
    id: str = Field(...)
    name: str = Field(...)
    default_base_url: str = Field(default="")
    api_key_prefix: str = Field(default="")
    chat_model: ChatModelName = Field(default="OpenAIChatModel")
    models: List[ModelInfo] = Field(default_factory=list)


class AddModelRequest(BaseModel):
    id: str = Field(...)
    name: str = Field(...)
    is_free: bool = Field(
        default=False,
        description="Whether this model is free to use",
    )
    supports_multimodal: Optional[bool] = Field(
        default=None,
        description="Whether the model supports multimodal input",
    )
    supports_image: Optional[bool] = Field(
        default=None,
        description="Whether the model supports image input",
    )
    supports_video: Optional[bool] = Field(
        default=None,
        description="Whether the model supports video input",
    )
    probe_source: Optional[str] = Field(
        default=None,
        description="Source of capability metadata",
    )


class ModelConfigRequest(BaseModel):
    generate_kwargs: Optional[dict] = Field(
        default_factory=dict,
        description=(
            "Per-model generation parameters in JSON format. "
            "These override provider-level generate_kwargs."
        ),
    )


def _validate_model_slot(
    manager: ProviderManager,
    provider_id: str,
    model_id: str,
) -> None:
    """Validate that the provider and model exist without mutating state."""
    provider = manager.get_provider(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found.",
        )
    if not provider.has_model(model_id):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Model '{model_id}' not found in provider '{provider_id}'."
            ),
        )


async def _load_agent_model(
    request: Request,
    agent_id: str,
) -> ModelSlotConfig | None:
    """Load the model configured for a specific agent."""
    workspace = await get_agent_for_request(request, agent_id=agent_id)
    agent_config = load_agent_config(workspace.agent_id)
    return agent_config.active_model


@router.get(
    "",
    response_model=List[ProviderInfo],
    summary="List all providers",
)
@require_permission("models:read")
async def list_all_providers(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
) -> List[ProviderInfo]:
    all_providers = await manager.list_provider_info()
    role = getattr(request.state, "role", "user")
    username = getattr(request.state, "username", "anonymous")
    if role == "admin":
        return all_providers
    return [
        p for p in all_providers
        if not p.is_custom or p.owner == "" or p.owner == username
    ]


@router.put(
    "/{provider_id}/config",
    response_model=ProviderInfo,
    summary="Configure a provider",
)
@require_permission("models:write")
async def configure_provider(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: ProviderConfigRequest = Body(...),
) -> ProviderInfo:
    # Ownership check: non-admin users can only modify their own or global providers
    role = getattr(request.state, "role", "user")
    username = getattr(request.state, "username", "anonymous")
    if role != "admin":
        provider_info = await manager.get_provider_info(provider_id)
        if provider_info and provider_info.is_custom and provider_info.owner and provider_info.owner != username:
            raise HTTPException(status_code=403, detail="无权修改他人的 Provider")

    ok = manager.update_provider(
        provider_id,
        {
            "api_key": body.api_key,
            "base_url": body.base_url,
            "chat_model": body.chat_model,
            "generate_kwargs": body.generate_kwargs,
        },
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found",
        )

    # Invalidate cached workspaces that reference this provider.
    # When base_url or api_key changes, cached AgentCore instances still
    # hold the old connection config, causing requests to fail or hit
    # the wrong endpoint.
    multi_agent_manager = getattr(request.app.state, "multi_agent_manager", None)
    if multi_agent_manager:
        evicted = await multi_agent_manager.invalidate_workspaces_by_provider(provider_id)
        if evicted:
            logger.info(
                f"Evicted {evicted} workspace(s) after updating provider '{provider_id}'"
            )

    provider_info = await manager.get_provider_info(provider_id)
    if provider_info is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found after update",
        )
    return provider_info


@router.post(
    "/custom-providers",
    response_model=ProviderInfo,
    summary="Create a custom provider",
    status_code=201,
)
@require_permission("models:write")
async def create_custom_provider_endpoint(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    body: CreateCustomProviderRequest = Body(...),
) -> ProviderInfo:
    # Tag the custom provider with the creator's username for isolation.
    username = getattr(request.state, "username", "anonymous")
    try:
        provider_info = await manager.add_custom_provider(
            ProviderInfo(
                id=body.id,
                name=body.name,
                base_url=body.default_base_url,
                api_key_prefix=body.api_key_prefix,
                chat_model=body.chat_model,
                extra_models=body.models,
                owner=username,
            ),
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return provider_info


class TestConnectionResponse(BaseModel):
    success: bool = Field(..., description="Whether the test passed")
    message: str = Field(..., description="Human-readable result message")


class TestProviderRequest(BaseModel):
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key to test",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Optional Base URL to test",
    )
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Optional chat model class to test protocol behavior",
    )


class TestModelRequest(BaseModel):
    model_id: str = Field(..., description="Model ID to test")


class DiscoverModelsRequest(BaseModel):
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key to use for discovery",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Optional Base URL to use for discovery",
    )
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Optional chat model class to use for discovery",
    )


class DiscoverModelsResponse(BaseModel):
    success: bool = Field(..., description="Whether discovery succeeded")
    models: List[ModelInfo] = Field(
        default_factory=list,
        description="Discovered models",
    )
    message: str = Field(
        default="",
        description="Human-readable result message",
    )
    added_count: int = Field(
        default=0,
        description="How many new models were added into provider config",
    )


@router.post(
    "/{provider_id}/test",
    response_model=TestConnectionResponse,
    summary="Test provider connection",
)
@require_permission("models:write")
async def test_provider(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: Optional[TestProviderRequest] = Body(default=None),
) -> TestConnectionResponse:
    """Test if a provider's URL and API key are valid."""
    try:
        provider = manager.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider '{provider_id}' not found")
        # Ensure we don't accidentally modify provider config during test
        tmp_provider = deepcopy(provider)
        if body and body.api_key:
            tmp_provider.api_key = body.api_key
        if body and body.base_url:
            tmp_provider.base_url = body.base_url
        ok, msg = await tmp_provider.check_connection()
        return TestConnectionResponse(
            success=ok,
            message=(
                "Connection successful" if ok else f"Connection failed: {msg}"
            ),
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{provider_id}/discover",
    response_model=DiscoverModelsResponse,
    summary="Discover available models from provider",
)
@require_permission("models:write")
async def discover_models(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: Optional[DiscoverModelsRequest] = Body(default=None),
    save: bool = Query(
        default=True,
        description="Save discovered models to provider",
    ),
) -> DiscoverModelsResponse:
    try:
        provider = manager.get_provider(provider_id)
        if provider is None:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_id}' not found",
            )

        existing_model_ids = {
            model.id for model in provider.models + provider.extra_models
        }

        ok = manager.update_provider(
            provider_id,
            {
                "api_key": body.api_key if body else None,
                "base_url": body.base_url if body else None,
            },
        )
        if not ok:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_id}' not found",
            )
        try:
            result = await manager.fetch_provider_models(
                provider_id,
                save=save,
            )
            success = True
        except Exception:
            result = []
            success = False

        added_count = 0
        if save and success:
            added_count = sum(
                1 for model in result if model.id not in existing_model_ids
            )

        return DiscoverModelsResponse(
            success=success,
            models=result,
            added_count=added_count,
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{provider_id}/models/test",
    response_model=TestConnectionResponse,
    summary="Test a specific model",
)
@require_permission("models:write")
async def test_model(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: TestModelRequest = Body(...),
) -> TestConnectionResponse:
    """Test if a specific model works with the configured provider."""
    try:
        provider = manager.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider '{provider_id}' not found")
        ok, msg = await provider.check_model_connection(model_id=body.model_id)
        return TestConnectionResponse(
            success=ok,
            message=(
                "Model connection successful"
                if ok
                else f"Model connection failed: {msg}"
            ),
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/custom-providers/{provider_id}",
    response_model=List[ProviderInfo],
    summary="Delete a custom provider",
)
@require_permission("models:write")
async def delete_custom_provider_endpoint(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
) -> List[ProviderInfo]:
    try:
        ok = manager.remove_custom_provider(provider_id)
        if not ok:
            raise ValueError(f"Custom Provider '{provider_id}' not found")
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Invalidate cached workspaces that reference the deleted provider.
    # Without this, workspaces keep using the old (now-deleted) provider
    # config from memory cache, causing 401/404 errors on chat requests.
    multi_agent_manager = getattr(request.app.state, "multi_agent_manager", None)
    if multi_agent_manager:
        evicted = await multi_agent_manager.invalidate_workspaces_by_provider(provider_id)
        if evicted:
            logger.info(
                f"Evicted {evicted} workspace(s) referencing deleted provider '{provider_id}'"
            )

    return await manager.list_provider_info()


@router.post(
    "/{provider_id}/models",
    response_model=ProviderInfo,
    summary="Add a model to a provider",
    status_code=201,
)
@require_permission("models:write")
async def add_model_endpoint(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: AddModelRequest = Body(...),
) -> ProviderInfo:
    try:
        provider = await manager.add_model_to_provider(
            provider_id=provider_id,
            model_info=ModelInfo(
                id=body.id,
                name=body.name,
                supports_multimodal=body.supports_multimodal,
                supports_image=body.supports_image,
                supports_video=body.supports_video,
                probe_source=body.probe_source,
                is_free=body.is_free,
            ),
        )  # Validate provider exists and add model
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return provider


class ProbeMultimodalResponse(BaseModel):
    supports_image: bool = Field(
        default=False,
        description="Whether the model supports image input",
    )
    supports_video: bool = Field(
        default=False,
        description="Whether the model supports video input",
    )
    supports_multimodal: bool = Field(
        default=False,
        description="Whether the model supports any multimodal input",
    )
    image_message: str = Field(
        default="",
        description="Probe result message for image support",
    )
    video_message: str = Field(
        default="",
        description="Probe result message for video support",
    )


@router.post(
    "/{provider_id}/models/{model_id:path}/probe-multimodal",
    response_model=ProbeMultimodalResponse,
    summary="Probe model multimodal capability",
)
@require_permission("models:write")
async def probe_model_multimodal(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
) -> ProbeMultimodalResponse:
    """Probe image and video support by sending lightweight test requests."""
    result = await manager.probe_model_multimodal(provider_id, model_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return ProbeMultimodalResponse(**result)


@router.delete(
    "/{provider_id}/models/{model_id:path}",
    response_model=ProviderInfo,
    summary="Remove a model from a provider",
)
@require_permission("models:write")
async def remove_model_endpoint(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
) -> ProviderInfo:
    try:
        provider = await manager.delete_model_from_provider(
            provider_id=provider_id,
            model_id=model_id,
        )  # Validate provider and model exist and delete
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return provider


@router.put(
    "/{provider_id}/models/{model_id:path}/config",
    response_model=ProviderInfo,
    summary="Configure per-model generation parameters",
)
@require_permission("models:write")
async def configure_model(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
    body: ModelConfigRequest = Body(...),
) -> ProviderInfo:
    """Update per-model generate_kwargs that override provider-level
    settings."""
    try:
        provider_info = await manager.update_model_config(
            provider_id=provider_id,
            model_id=model_id,
            config={"generate_kwargs": body.generate_kwargs},
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return provider_info


@router.get(
    "/active",
    response_model=ActiveModelsInfo,
    summary="Get effective active LLM",
)
@require_permission("models:read")
async def get_active_models(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    scope: ActiveModelReadScope = Query(default="effective"),
    agent_id: Optional[str] = Query(default=None),
) -> ActiveModelsInfo:
    """Get active model by scope.

    - effective: agent-specific first, otherwise global fallback
    - global: ProviderManager global model only
    - agent: a specific agent's configured model only
    """
    if scope == "global":
        return ActiveModelsInfo(active_llm=manager.get_active_model())

    if scope == "agent":
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="agent_id is required when scope is 'agent'",
            )
        return ActiveModelsInfo(
            active_llm=await _load_agent_model(request, agent_id),
        )

    try:
        target_agent_id = agent_id
        if target_agent_id is None:
            workspace = await get_agent_for_request(request)
            target_agent_id = workspace.agent_id

        agent_model = await _load_agent_model(request, target_agent_id)
        if agent_model:
            logger.info(
                "Returning agent-specific model for %s: %s",
                target_agent_id,
                agent_model,
            )
            return ActiveModelsInfo(active_llm=agent_model)
    except (
        HTTPException,
        OSError,
        ValueError,
        TypeError,
        AppBaseException,
    ) as exc:
        logger.warning(
            "Failed to get agent-specific model: %s",
            exc,
            exc_info=True,
        )

    global_model = manager.get_active_model()
    logger.info("Returning global model: %s", global_model)
    return ActiveModelsInfo(active_llm=global_model)


@router.put(
    "/active",
    response_model=ActiveModelsInfo,
    summary="Set active LLM",
)
@require_permission("models:read")
async def set_active_model(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    body: ModelSlotRequest = Body(...),
) -> ActiveModelsInfo:
    """Set active model by scope.

    - scope="global": requires models:write (admin only)
    - scope="agent":  requires models:read (all users can select for own agent)
    """
    # Global model change requires write permission
    if body.scope == "global":
        role = getattr(request.state, "role", "user")
        username = getattr(request.state, "username", None)
        try:
            from ..permissions.manager import PermissionManager
            pm = PermissionManager.get_instance()
            if not pm.has_permission(username, "models:write", role):
                raise HTTPException(
                    status_code=403,
                    detail="需要权限: models:write",
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="Permission system unavailable.",
            )
        try:
            await manager.activate_model(body.provider_id, body.model)
        except (
            FileNotFoundError,
            RuntimeError,
            ValueError,
            AppBaseException,
        ) as exc:
            message = str(exc)
            lower_msg = message.lower()
            if "provider" in lower_msg and "not found" in lower_msg:
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        return ActiveModelsInfo(active_llm=manager.get_active_model())

    if not body.agent_id:
        raise HTTPException(
            status_code=400,
            detail="agent_id is required when scope is 'agent'",
        )

    _validate_model_slot(manager, body.provider_id, body.model)

    try:
        workspace = await get_agent_for_request(
            request,
            agent_id=body.agent_id,
        )
        agent_config = load_agent_config(workspace.agent_id)
        agent_config.active_model = ModelSlotConfig(
            provider_id=body.provider_id,
            model=body.model,
        )
        save_agent_config(workspace.agent_id, agent_config)
        # Hot reload agent (async, non-blocking)
        schedule_agent_reload(request, workspace.agent_id)

    except (
        HTTPException,
        OSError,
        ValueError,
        TypeError,
        AppBaseException,
    ) as exc:
        logger.warning(
            "Failed to save active model to agent config: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to save active model to agent config",
        ) from exc

    manager.maybe_probe_multimodal(body.provider_id, body.model)

    return ActiveModelsInfo(
        active_llm=ModelSlotConfig(
            provider_id=body.provider_id,
            model=body.model,
        ),
    )


# =============================================================================
# OpenRouter-specific endpoints for model discovery with filtering
# =============================================================================


class FilterModelsRequest(BaseModel):
    """Request model for filtering OpenRouter models."""

    providers: List[str] = Field(
        default_factory=list,
        description="Filter by provider/series (e.g., ['openai', 'google'])",
    )
    input_modalities: List[str] = Field(
        default_factory=list,
        description="Required input modalities (e.g., ['image'])",
    )
    output_modalities: List[str] = Field(
        default_factory=list,
        description="Required output modalities (e.g., ['text'])",
    )
    max_prompt_price: Optional[float] = Field(
        default=None,
        description="Maximum prompt price per 1M tokens (e.g., 0.000001)",
    )
    is_free: Optional[bool] = Field(
        default=None,
        description="Whether to return only free models",
    )


class SeriesResponse(BaseModel):
    """Response model for available series/providers."""

    series: List[str] = Field(
        default_factory=list,
        description="Provider series (e.g., ['openai', 'google'])",
    )


class DiscoverExtendedResponse(BaseModel):
    """Response model for extended model discovery."""

    success: bool = Field(..., description="Whether discovery succeeded")
    models: List[dict] = Field(
        default_factory=list,
        description="Discovered models with extended metadata",
    )
    providers: List[str] = Field(
        default_factory=list,
        description="Available provider series",
    )
    total_count: int = Field(
        default=0,
        description="Total number of models discovered",
    )


class FilterModelsResponse(BaseModel):
    """Response model for filtered models."""

    success: bool = Field(..., description="Whether filtering succeeded")
    models: List[dict] = Field(
        default_factory=list,
        description="Filtered models with extended metadata",
    )
    total_count: int = Field(
        default=0,
        description="Total number of models matching filters",
    )


@router.get(
    "/openrouter/series",
    response_model=SeriesResponse,
    summary="Get available OpenRouter provider series",
)
@require_permission("models:read")
async def get_openrouter_series(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
) -> SeriesResponse:
    """Get list of available provider/series from OpenRouter."""
    provider = manager.get_provider("openrouter")
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail="OpenRouter provider not found",
        )

    if not isinstance(provider, OpenRouterProvider):
        raise HTTPException(
            status_code=400,
            detail="Provider is not an OpenRouter provider",
        )

    try:
        series = await provider.get_available_providers()
        return SeriesResponse(series=series)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch series: {str(exc)}",
        ) from exc


@router.post(
    "/openrouter/discover-extended",
    response_model=DiscoverExtendedResponse,
    summary="Discover OpenRouter models with extended metadata",
)
@require_permission("models:write")
async def discover_openrouter_extended(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    body: Optional[DiscoverModelsRequest] = Body(default=None),
) -> DiscoverExtendedResponse:
    """Discover available models from OpenRouter with full metadata."""
    provider = manager.get_provider("openrouter")
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail="OpenRouter provider not found",
        )

    if not isinstance(provider, OpenRouterProvider):
        raise HTTPException(
            status_code=400,
            detail="Provider is not an OpenRouter provider",
        )

    if body and body.api_key:
        manager.update_provider("openrouter", {"api_key": body.api_key})

    try:
        models = await provider.fetch_extended_models()
        providers = await provider.get_available_providers()

        models_dict = [
            {
                "id": m.id,
                "name": m.name,
                "supports_multimodal": m.supports_multimodal,
                "supports_image": m.supports_image,
                "supports_video": m.supports_video,
                "probe_source": m.probe_source,
                "is_free": m.is_free,
                "provider": m.provider,
                "input_modalities": m.input_modalities,
                "output_modalities": m.output_modalities,
                "pricing": m.pricing,
            }
            for m in models
        ]

        return DiscoverExtendedResponse(
            success=True,
            models=models_dict,
            providers=providers,
            total_count=len(models_dict),
        )
    except Exception:
        return DiscoverExtendedResponse(
            success=False,
            models=[],
            providers=[],
            total_count=0,
        )


@router.post(
    "/openrouter/models/filter",
    response_model=FilterModelsResponse,
    summary="Filter OpenRouter models by criteria",
)
@require_permission("models:read")
async def filter_openrouter_models(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    body: FilterModelsRequest = Body(...),
) -> FilterModelsResponse:
    """Filter OpenRouter models by provider, modalities, and price."""
    provider = manager.get_provider("openrouter")
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail="OpenRouter provider not found",
        )

    if not isinstance(provider, OpenRouterProvider):
        raise HTTPException(
            status_code=400,
            detail="Provider is not an OpenRouter provider",
        )

    try:
        models = await provider.fetch_extended_models()

        filtered_models = provider.filter_models(
            models=models,
            providers=body.providers if body.providers else None,
            input_modalities=(
                body.input_modalities if body.input_modalities else None
            ),
            output_modalities=(
                body.output_modalities if body.output_modalities else None
            ),
            max_prompt_price=body.max_prompt_price,
            is_free=body.is_free,
        )

        models_dict = [
            {
                "id": m.id,
                "name": m.name,
                "supports_multimodal": m.supports_multimodal,
                "supports_image": m.supports_image,
                "supports_video": m.supports_video,
                "probe_source": m.probe_source,
                "is_free": m.is_free,
                "provider": m.provider,
                "input_modalities": m.input_modalities,
                "output_modalities": m.output_modalities,
                "pricing": m.pricing,
            }
            for m in filtered_models
        ]

        return FilterModelsResponse(
            success=True,
            models=models_dict,
            total_count=len(models_dict),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to filter models: {str(exc)}",
        ) from exc
