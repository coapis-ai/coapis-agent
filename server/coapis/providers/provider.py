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

"""Definition of Provider."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Type
from pydantic import BaseModel, Field
from pydantic import ConfigDict

from agentscope.model import ChatModelBase
from coapis.exceptions import ProviderError

if TYPE_CHECKING:
    from .multimodal_prober import ProbeResult

# Model type enumeration
ModelType = Literal["chat", "embedding", "rerank", "audio", "vision"]


class ModelInfo(BaseModel):
    id: str = Field(..., description="Model identifier used in API calls")
    name: str = Field(..., description="Human-readable model name")
    
    # Model type (chat, embedding, rerank, audio, vision)
    model_type: ModelType = Field(
        default="chat",
        description="Model type: chat, embedding, rerank, audio, or vision",
    )
    
    # Embedding model specific fields
    embedding_dimension: int | None = Field(
        default=None,
        description="Embedding vector dimension (for embedding models)",
    )
    max_sequence_length: int | None = Field(
        default=None,
        description="Maximum sequence length (for embedding models)",
    )
    
    # Multimodal support (for chat/vision models)
    supports_multimodal: bool | None = Field(
        default=None,
        description="Whether this model supports multimodal input "
        "(image/audio/video). None means not yet probed.",
    )
    supports_image: bool | None = Field(
        default=None,
        description="Whether this model supports image input. "
        "None means not yet probed.",
    )
    supports_video: bool | None = Field(
        default=None,
        description="Whether this model supports video input. "
        "None means not yet probed.",
    )
    
    # Other metadata
    probe_source: str | None = Field(
        default=None,
        description=(
            "Probe result source: 'documentation' (from docs)"
            " or 'probed' (actual probe)"
        ),
    )
    is_free: bool = Field(
        default=False,
        description="Whether this model is free to use (e.g., no API cost)",
    )
    generate_kwargs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Per-model generation parameters that override "
        "provider-level generate_kwargs.",
    )
    source: str = Field(
        default="builtin",
        description="Model source: 'builtin' (defined in code) "
        "or 'added' (user-added via UI/API).",
    )


class ExtendedModelInfo(ModelInfo):
    """Extended model info with additional metadata for providers."""

    provider: str = Field(
        default="",
        description="Provider/series (e.g., 'openai', 'google')",
    )
    input_modalities: List[str] = Field(
        default_factory=list,
        description="Supported input modalities",
    )
    output_modalities: List[str] = Field(
        default_factory=list,
        description="Supported output modalities",
    )
    pricing: Dict[str, str] = Field(
        default_factory=dict,
        description="Pricing info (prompt/completion)",
    )


class ProviderInfo(BaseModel):
    """Provider configuration and metadata."""

    # Allow flexible typing for test environments where ModelInfo
    # may be reloaded (different object identity)
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_default=False,
    )

    id: str = Field(..., description="Provider identifier")
    name: str = Field(..., description="Human-readable provider name")
    base_url: str = Field(default="", description="API base URL")
    api_key: str = Field(default="", description="API key for authentication")
    chat_model: str = Field(
        default="OpenAIChatModel",
        description="AgentScope ChatModel name (e.g., 'OpenAIChatModel')",
    )
    models: List[ModelInfo] = Field(
        default_factory=list,
        description="All models (builtin + user-added). "
        "Use ModelInfo.source to distinguish.",
    )

    api_key_prefix: str = Field(
        default="",
        description="Expected prefix for the API key (e.g., 'sk-')",
    )
    is_local: bool = Field(
        default=False,
        description="Whether this provider is for a local hosting platform",
    )
    freeze_url: bool = Field(
        default=False,
        description="Whether the base_url should be frozen (not editable)",
    )
    require_api_key: bool = Field(
        default=True,
        description="Whether this provider requires an API key",
    )
    is_custom: bool = Field(
        default=False,
        description=("Whether this provider is user-created (not built-in)."),
    )
    owner: str = Field(
        default="",
        description=(
            "Username of the creator. Empty string means global/shared. "
            "Non-empty means the provider is private to this user."
        ),
    )
    support_model_discovery: bool = Field(
        default=False,
        description=(
            "Whether this provider supports fetching available models"
            " from the provider's API"
        ),
    )
    support_connection_check: bool = Field(
        default=True,
        description=(
            "Whether this provider supports checking connection to the API "
            "without model configuration"
        ),
    )
    generate_kwargs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Generation parameters for agentscope chat models.",
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for the provider "
        "(e.g., api_key_url, api_key_hint).",
    )


class Provider(ProviderInfo, ABC):
    """Represents a provider instance with its configuration."""

    @abstractmethod
    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        """Check if the provider is reachable with the current config."""

    @abstractmethod
    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch the list of available models from the provider."""

    @abstractmethod
    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,  # pylint: disable=unused-argument
    ) -> tuple[bool, str]:
        """Check if a specific model is reachable/usable."""

    async def add_model(
        self,
        model_info: ModelInfo,
        target: str = "models",
        timeout: float = 10,  # pylint: disable=unused-argument
    ) -> tuple[bool, str]:
        """Add a model to the provider's model list."""
        model_info.id = model_info.id.strip()
        if any(
            model.id.strip() == model_info.id
            for model in self.models
        ):
            return False, f"Model '{model_info.id}' already exists"
        model_info.source = "added"
        self.models.append(model_info)
        return True, ""

    async def delete_model(
        self,
        model_id: str,
        timeout: float = 10,  # pylint: disable=unused-argument
    ) -> tuple[bool, str]:
        """Delete a user-added model from the provider's model list.

        Only models with source='added' can be deleted.
        """
        model_id = model_id.strip()
        original_len = len(self.models)
        self.models = [
            model
            for model in self.models
            if not (model.id.strip() == model_id and model.source == "added")
        ]
        if len(self.models) == original_len:
            return False, f"Model '{model_id}' not found or not deletable"
        return True, ""

    def update_config(self, config: Dict) -> None:
        """Update provider configuration with the given dictionary."""
        if "name" in config and config["name"] is not None:
            self.name = str(config["name"]).strip()
        if (
            not self.freeze_url
            and "base_url" in config
            and config["base_url"] is not None
        ):
            self.base_url = str(config["base_url"]).strip()
        if "api_key" in config and config["api_key"] is not None:
            self.api_key = str(config["api_key"]).strip()
        if (
            self.is_custom
            and "chat_model" in config
            and config["chat_model"] is not None
        ):
            self.chat_model = str(config["chat_model"])
        if "api_key_prefix" in config and config["api_key_prefix"] is not None:
            self.api_key_prefix = str(config["api_key_prefix"])
        if "require_api_key" in config and config["require_api_key"] is not None:
            self.require_api_key = bool(config["require_api_key"])
        if (
            "generate_kwargs" in config
            and config["generate_kwargs"] is not None
            and isinstance(config["generate_kwargs"], dict)
        ):
            self.generate_kwargs = config["generate_kwargs"]

    def get_chat_model_cls(self) -> Type[ChatModelBase]:
        """Return the chat model class associated with this provider."""
        import agentscope.model

        chat_model_cls = getattr(
            agentscope.model,
            self.chat_model,
            None,
        )
        if chat_model_cls is None:
            raise ProviderError(
                message=(
                    f"Chat model class '{self.chat_model}' "
                    f"not found for provider '{self.name}'."
                ),
            )
        return chat_model_cls

    @staticmethod
    def _deep_merge(
        base: Dict[str, Any],
        override: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Recursively merge *override* into *base* (returns a new dict)."""
        result = dict(base)
        for key, val in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(val, dict)
            ):
                result[key] = Provider._deep_merge(result[key], val)
            else:
                result[key] = val
        return result

    def get_effective_generate_kwargs(self, model_id: str) -> Dict[str, Any]:
        """Return merged generate_kwargs: provider-level as base, model-level
        overrides on top (deep merge for nested dicts).

        Always returns a new dict so callers never mutate provider state.
        """
        for model in self.models:
            if model.id == model_id:
                if model.generate_kwargs:
                    return self._deep_merge(
                        self.generate_kwargs,
                        model.generate_kwargs,
                    )
                break
        return dict(self.generate_kwargs)

    def update_model_config(
        self,
        model_id: str,
        config: Dict,
    ) -> bool:
        """Update per-model configuration (e.g. generate_kwargs)."""
        for model in self.models:
            if model.id == model_id:
                if (
                    "generate_kwargs" in config
                    and config["generate_kwargs"] is not None
                    and isinstance(config["generate_kwargs"], dict)
                ):
                    model.generate_kwargs = config["generate_kwargs"]
                return True
        return False

    def has_model(self, model_id: str) -> bool:
        """Check if the provider has a model with the given ID."""
        return any(
            model.id == model_id for model in self.models
        )

    @abstractmethod
    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        """Return an instance of the chat model associated with this
        provider and model_id."""

    async def probe_model_multimodal(
        self,
        model_id: str,  # pylint: disable=unused-argument
        timeout: float = 10,  # pylint: disable=unused-argument
        image_only: bool = False,  # pylint: disable=unused-argument
    ) -> ProbeResult:
        """Probe if a model supports multimodal input.

        Args:
            model_id: Model identifier.
            timeout: Per-probe timeout in seconds.
            image_only: When True, skip the video probe and return after
                the image probe only.  Use this for fast checks (e.g.
                from ``view_image``) to avoid blocking on the slower
                video probe.

        Default implementation returns ProbeResult() (all False).
        Subclasses with API access should override.
        """
        from .multimodal_prober import ProbeResult

        return ProbeResult()

    async def get_info(self, mock_secret: bool = True) -> ProviderInfo:
        """Return a ProviderInfo instance with the provider's details."""
        api_key = (
            self.api_key_prefix + "*" * 6
            if mock_secret and self.api_key
            else self.api_key
        )
        # Serialize models to plain dicts so that
        # ProviderInfo constructs fresh ModelInfo instances using
        # the class in its own module scope.  This avoids pydantic
        # class-identity mismatches when the same module is loaded
        # via two different import paths (e.g. PYTHONPATH + pip install).
        return ProviderInfo(
            id=self.id,
            name=self.name,
            base_url=self.base_url,
            api_key=api_key,
            chat_model=self.chat_model,
            models=[m.model_dump() for m in self.models],
            api_key_prefix=self.api_key_prefix,
            is_local=self.is_local,
            is_custom=self.is_custom,
            support_model_discovery=self.support_model_discovery,
            # custom providers are assumed to not support connection check
            support_connection_check=self.support_connection_check
            and not self.is_custom,
            freeze_url=self.freeze_url,
            require_api_key=self.require_api_key,
            generate_kwargs=self.generate_kwargs,
        )


# ============================================================================
# Default Models Configuration
# ============================================================================


class DefaultModelSlot(BaseModel):
    """Default model configuration for a specific model type."""

    provider_id: str = Field(..., description="Provider ID")
    model_id: str = Field(..., description="Model ID")
    model_type: ModelType = Field(..., description="Model type")


class DefaultModelsConfig(BaseModel):
    """Default models configuration for all model types."""

    chat: DefaultModelSlot | None = Field(
        default=None, description="Default chat model"
    )
    embedding: DefaultModelSlot | None = Field(
        default=None, description="Default embedding model"
    )
    rerank: DefaultModelSlot | None = Field(
        default=None, description="Default rerank model"
    )
    audio: DefaultModelSlot | None = Field(
        default=None, description="Default audio model"
    )
    vision: DefaultModelSlot | None = Field(
        default=None, description="Default vision model"
    )

    def get_by_type(self, model_type: ModelType) -> DefaultModelSlot | None:
        """Get default model by type."""
        return getattr(self, model_type, None)

    def set_by_type(self, model_type: ModelType, slot: DefaultModelSlot) -> None:
        """Set default model by type."""
        if hasattr(self, model_type):
            setattr(self, model_type, slot)

    def to_dict(self) -> Dict[str, Dict]:
        """Export to dict format for JSON serialization."""
        result = {}
        for field in ["chat", "embedding", "rerank", "audio", "vision"]:
            slot = getattr(self, field)
            if slot:
                result[field] = {
                    "provider_id": slot.provider_id,
                    "model_id": slot.model_id,
                }
        return result
