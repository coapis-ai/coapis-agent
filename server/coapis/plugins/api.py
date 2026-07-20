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

"""Plugin API for plugin developers."""

from typing import Any, Callable, Dict, List, Optional, Type
import logging

logger = logging.getLogger(__name__)


class PluginApi:
    """Plugin API - Interface for plugin developers.

    This class provides the API that plugins use to register their
    capabilities.
    """

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        manifest: Dict[str, Any] = None,
    ):
        """Initialize plugin API.

        Args:
            plugin_id: Unique plugin identifier
            config: Plugin configuration dictionary
            manifest: Plugin manifest dictionary (from plugin.json)
        """
        self.plugin_id = plugin_id
        self.config = config
        self.manifest = manifest or {}
        self._registry = None

    def set_registry(self, registry):
        """Set registry reference (called by loader).

        Args:
            registry: PluginRegistry instance
        """
        self._registry = registry

    def register_provider(
        self,
        provider_id: str,
        provider_class: Type,
        label: str = "",
        base_url: str = "",
        **metadata,
    ):
        """Register a custom LLM Provider.

        Args:
            provider_id: Unique provider identifier
            provider_class: Provider class (inherits from BaseProvider)
            label: Display name for the provider
            base_url: API base URL
            **metadata: Additional metadata (chat_model, require_api_key, etc.)

        Example:
            >>> api.register_provider(
            ...     provider_id="my-provider",
            ...     provider_class=MyProvider,
            ...     label="My Custom Provider",
            ...     base_url="https://api.example.com/v1",
            ...     chat_model="OpenAIChatModel",
            ...     require_api_key=True,
            ... )
        """
        if self._registry:
            # Merge plugin manifest meta with provider metadata
            merged_metadata = dict(metadata)
            if "meta" in self.manifest:
                merged_metadata["meta"] = self.manifest["meta"]

            self._registry.register_provider(
                plugin_id=self.plugin_id,
                provider_id=provider_id,
                provider_class=provider_class,
                label=label or provider_id,
                base_url=base_url,
                metadata=merged_metadata,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered provider "
                f"'{provider_id}'",
            )

    def register_startup_hook(
        self,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register a startup hook.

        Args:
            hook_name: Unique hook identifier
            callback: Async or sync function to call on startup
            priority: Execution priority (lower = earlier, default=100)

        Example:
            >>> api.register_startup_hook(
            ...     hook_name="init_sdk",
            ...     callback=self.on_startup,
            ...     priority=0,  # Execute first
            ... )
        """
        if self._registry:
            self._registry.register_startup_hook(
                plugin_id=self.plugin_id,
                hook_name=hook_name,
                callback=callback,
                priority=priority,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered startup hook "
                f"'{hook_name}' (priority={priority})",
            )

    def register_shutdown_hook(
        self,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register a shutdown hook.

        Args:
            hook_name: Unique hook identifier
            callback: Async or sync function to call on shutdown
            priority: Execution priority (lower = earlier, default=100)

        Example:
            >>> api.register_shutdown_hook(
            ...     hook_name="cleanup_sdk",
            ...     callback=self.on_shutdown,
            ...     priority=100,
            ... )
        """
        if self._registry:
            self._registry.register_shutdown_hook(
                plugin_id=self.plugin_id,
                hook_name=hook_name,
                callback=callback,
                priority=priority,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered shutdown hook "
                f"'{hook_name}' (priority={priority})",
            )

    def register_control_command(
        self,
        handler: Any,
        priority_level: int = 10,
    ):
        """Register a control command handler.

        Args:
            handler: Control command handler instance
                (BaseControlCommandHandler)
            priority_level: Command priority (default: 10 = high)
        """
        if self._registry:
            self._registry.register_control_command(
                plugin_id=self.plugin_id,
                handler=handler,
                priority_level=priority_level,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered control command "
                f"'{handler.command_name}' (priority={priority_level})",
            )

    def register_router(
        self,
        router: Any,
        prefix: str = "",
        tags: Optional[List[str]] = None,
        priority: int = 100,
    ):
        """Register a FastAPI router.

        This allows plugins to add new API endpoints to the application.

        Args:
            router: FastAPI APIRouter instance
            prefix: URL prefix for the router (e.g., "/api/ent")
            tags: OpenAPI tags for documentation
            priority: Priority (lower = earlier execution, default: 100)

        Example:
            >>> from fastapi import APIRouter
            >>> router = APIRouter()
            >>> @router.get("/custom-endpoint")
            ... async def custom_endpoint():
            ...     return {"message": "Hello from plugin"}
            >>> api.register_router(
            ...     router=router,
            ...     prefix="/api/custom",
            ...     tags=["Custom"],
            ...     priority=10,
            ... )
        """
        if self._registry:
            self._registry.register_router(
                plugin_id=self.plugin_id,
                router=router,
                prefix=prefix,
                tags=tags,
                priority=priority,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered router "
                f"(prefix='{prefix}', priority={priority})",
            )

    def register_middleware(
        self,
        middleware: Callable,
        priority: int = 100,
    ):
        """Register a middleware function.

        This allows plugins to add custom middleware to the application.

        Args:
            middleware: Middleware callable (async function)
            priority: Priority (lower = earlier execution, default: 100)

        Example:
            >>> async def auth_middleware(request, call_next):
            ...     # Custom authentication logic
            ...     response = await call_next(request)
            ...     return response
            >>> api.register_middleware(
            ...     middleware=auth_middleware,
            ...     priority=10,
            ... )
        """
        if self._registry:
            self._registry.register_middleware(
                plugin_id=self.plugin_id,
                middleware=middleware,
                priority=priority,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered middleware (priority={priority})",
            )

    @property
    def runtime(self):
        """Access runtime helper functions.

        Returns:
            RuntimeHelpers instance or None
        """
        if self._registry:
            return self._registry.get_runtime_helpers()
        return None
