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

"""Central plugin registry."""

from typing import Any, Callable, Dict, List, Optional, Type
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProviderRegistration:
    """Provider registration record."""

    plugin_id: str
    provider_id: str
    provider_class: Type
    label: str
    base_url: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HookRegistration:
    """Hook registration record."""

    plugin_id: str
    hook_name: str
    callback: Callable
    priority: int = 100


@dataclass
class ControlCommandRegistration:
    """Control command registration record."""

    plugin_id: str
    handler: Any  # BaseControlCommandHandler
    priority_level: int = 10


@dataclass
class RouterRegistration:
    """Router registration record for FastAPI routers."""

    plugin_id: str
    router: Any  # APIRouter from FastAPI
    prefix: str = ""
    tags: List[str] = field(default_factory=list)
    priority: int = 100


@dataclass
class MiddlewareRegistration:
    """Middleware registration record."""

    plugin_id: str
    middleware: Callable
    priority: int = 100


class PluginRegistry:
    """Central plugin registry (Singleton).

    This registry manages all plugin registrations and provides
    a centralized way to access plugin capabilities.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # Initialize _initialized first to avoid pylint error
        if not hasattr(self, "_initialized"):
            self._initialized = False

        if self._initialized:
            return

        self._providers: Dict[str, ProviderRegistration] = {}
        self._startup_hooks: List[HookRegistration] = []
        self._shutdown_hooks: List[HookRegistration] = []
        self._control_commands: List[ControlCommandRegistration] = []
        self._routers: List[RouterRegistration] = []
        self._middleware: List[MiddlewareRegistration] = []
        self._runtime_helpers = None

        self._initialized = True

    def register_provider(
        self,
        plugin_id: str,
        provider_id: str,
        provider_class: Type,
        label: str,
        base_url: str,
        metadata: Dict[str, Any],
    ):
        """Register a provider.

        Args:
            plugin_id: Plugin identifier
            provider_id: Provider identifier
            provider_class: Provider class
            label: Display label
            base_url: API base URL
            metadata: Additional metadata

        Raises:
            ValueError: If provider_id already registered
        """
        if provider_id in self._providers:
            existing = self._providers[provider_id]
            raise ValueError(
                f"Provider '{provider_id}' already registered "
                f"by plugin '{existing.plugin_id}'",
            )

        self._providers[provider_id] = ProviderRegistration(
            plugin_id=plugin_id,
            provider_id=provider_id,
            provider_class=provider_class,
            label=label,
            base_url=base_url,
            metadata=metadata,
        )
        logger.info(
            f"Registered provider '{provider_id}' from plugin '{plugin_id}'",
        )

    def get_provider(self, provider_id: str) -> Optional[ProviderRegistration]:
        """Get provider registration.

        Args:
            provider_id: Provider identifier

        Returns:
            ProviderRegistration or None if not found
        """
        return self._providers.get(provider_id)

    def get_all_providers(self) -> Dict[str, ProviderRegistration]:
        """Get all provider registrations.

        Returns:
            Dictionary of provider_id -> ProviderRegistration
        """
        return self._providers.copy()

    def set_runtime_helpers(self, helpers):
        """Set runtime helpers.

        Args:
            helpers: RuntimeHelpers instance
        """
        self._runtime_helpers = helpers

    def get_runtime_helpers(self):
        """Get runtime helpers.

        Returns:
            RuntimeHelpers instance or None
        """
        return self._runtime_helpers

    def register_startup_hook(
        self,
        plugin_id: str,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register a startup hook.

        Args:
            plugin_id: Plugin identifier
            hook_name: Hook name
            callback: Callback function
            priority: Priority (lower = earlier execution)
        """
        hook = HookRegistration(
            plugin_id=plugin_id,
            hook_name=hook_name,
            callback=callback,
            priority=priority,
        )
        self._startup_hooks.append(hook)
        # Sort by priority (lower = earlier)
        self._startup_hooks.sort(key=lambda h: h.priority)
        logger.info(
            f"Registered startup hook '{hook_name}' from plugin '{plugin_id}' "
            f"(priority={priority})",
        )

    def register_shutdown_hook(
        self,
        plugin_id: str,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register a shutdown hook.

        Args:
            plugin_id: Plugin identifier
            hook_name: Hook name
            callback: Callback function
            priority: Priority (lower = earlier execution)
        """
        hook = HookRegistration(
            plugin_id=plugin_id,
            hook_name=hook_name,
            callback=callback,
            priority=priority,
        )
        self._shutdown_hooks.append(hook)
        # Sort by priority (lower = earlier)
        self._shutdown_hooks.sort(key=lambda h: h.priority)
        logger.info(
            f"Registered shutdown hook '{hook_name}' from plugin "
            f"'{plugin_id}' (priority={priority})",
        )

    def get_startup_hooks(self) -> List[HookRegistration]:
        """Get all startup hooks sorted by priority.

        Returns:
            List of HookRegistration
        """
        return self._startup_hooks.copy()

    def get_shutdown_hooks(self) -> List[HookRegistration]:
        """Get all shutdown hooks sorted by priority.

        Returns:
            List of HookRegistration
        """
        return self._shutdown_hooks.copy()

    def register_control_command(
        self,
        plugin_id: str,
        handler: Any,
        priority_level: int = 10,
    ):
        """Register a control command handler.

        Args:
            plugin_id: Plugin identifier
            handler: Control command handler instance
            priority_level: Command priority (default: 10 = high)
        """
        cmd_reg = ControlCommandRegistration(
            plugin_id=plugin_id,
            handler=handler,
            priority_level=priority_level,
        )
        self._control_commands.append(cmd_reg)
        logger.info(
            f"Registered control command '{handler.command_name}' "
            f"from plugin '{plugin_id}' (priority={priority_level})",
        )

    def get_control_commands(self) -> List[ControlCommandRegistration]:
        """Get all registered control command handlers.

        Returns:
            List of ControlCommandRegistration
        """
        return self._control_commands.copy()

    def register_router(
        self,
        plugin_id: str,
        router: Any,
        prefix: str = "",
        tags: Optional[List[str]] = None,
        priority: int = 100,
    ):
        """Register a FastAPI router.

        Args:
            plugin_id: Plugin identifier
            router: FastAPI APIRouter instance
            prefix: URL prefix for the router (e.g., "/ent")
            tags: OpenAPI tags for documentation
            priority: Priority (lower = earlier execution, default: 100)

        Example:
            >>> registry.register_router(
            ...     plugin_id="enterprise",
            ...     router=enterprise_router,
            ...     prefix="/api/ent",
            ...     tags=["Enterprise"],
            ...     priority=10,
            ... )
        """
        router_reg = RouterRegistration(
            plugin_id=plugin_id,
            router=router,
            prefix=prefix,
            tags=tags or [],
            priority=priority,
        )
        self._routers.append(router_reg)
        # Sort by priority (lower = earlier)
        self._routers.sort(key=lambda r: r.priority)
        logger.info(
            f"Registered router from plugin '{plugin_id}' "
            f"(prefix='{prefix}', priority={priority})",
        )

    def register_middleware(
        self,
        plugin_id: str,
        middleware: Callable,
        priority: int = 100,
    ):
        """Register a middleware function.

        Args:
            plugin_id: Plugin identifier
            middleware: Middleware callable (async function)
            priority: Priority (lower = earlier execution, default: 100)

        Example:
            >>> async def auth_middleware(request, call_next):
            ...     # Check authentication
            ...     response = await call_next(request)
            ...     return response
            >>> registry.register_middleware(
            ...     plugin_id="enterprise",
            ...     middleware=auth_middleware,
            ...     priority=10,
            ... )
        """
        mid_reg = MiddlewareRegistration(
            plugin_id=plugin_id,
            middleware=middleware,
            priority=priority,
        )
        self._middleware.append(mid_reg)
        # Sort by priority (lower = earlier)
        self._middleware.sort(key=lambda m: m.priority)
        logger.info(
            f"Registered middleware from plugin '{plugin_id}' (priority={priority})",
        )

    def get_routers(self) -> List[RouterRegistration]:
        """Get all registered routers sorted by priority.

        Returns:
            List of RouterRegistration
        """
        return self._routers.copy()

    def get_middleware(self) -> List[MiddlewareRegistration]:
        """Get all registered middleware sorted by priority.

        Returns:
            List of MiddlewareRegistration
        """
        return self._middleware.copy()
