# -*- coding: utf-8 -*-
"""Tests for PluginRegistry Router and Middleware extension."""

import pytest
from unittest.mock import Mock, AsyncMock
from fastapi import APIRouter

from coapis.plugins.registry import (
    PluginRegistry,
    RouterRegistration,
    MiddlewareRegistration,
)


class TestRouterRegistration:
    """Tests for router registration."""

    def test_router_registration_creation(self):
        """Test RouterRegistration dataclass."""
        router = APIRouter()
        
        reg = RouterRegistration(
            plugin_id="test_plugin",
            router=router,
            prefix="/api/test",
            tags=["Test"],
            priority=50,
        )
        
        assert reg.plugin_id == "test_plugin"
        assert reg.router == router
        assert reg.prefix == "/api/test"
        assert reg.tags == ["Test"]
        assert reg.priority == 50

    def test_router_registration_defaults(self):
        """Test RouterRegistration default values."""
        router = APIRouter()
        
        reg = RouterRegistration(
            plugin_id="test_plugin",
            router=router,
        )
        
        assert reg.prefix == ""
        assert reg.tags == []
        assert reg.priority == 100


class TestMiddlewareRegistration:
    """Tests for middleware registration."""

    def test_middleware_registration_creation(self):
        """Test MiddlewareRegistration dataclass."""
        async def test_middleware(request, call_next):
            return await call_next(request)
        
        reg = MiddlewareRegistration(
            plugin_id="test_plugin",
            middleware=test_middleware,
            priority=30,
        )
        
        assert reg.plugin_id == "test_plugin"
        assert reg.middleware == test_middleware
        assert reg.priority == 30

    def test_middleware_registration_default_priority(self):
        """Test MiddlewareRegistration default priority."""
        async def test_middleware(request, call_next):
            return await call_next(request)
        
        reg = MiddlewareRegistration(
            plugin_id="test_plugin",
            middleware=test_middleware,
        )
        
        assert reg.priority == 100


class TestPluginRegistryRouter:
    """Tests for PluginRegistry router methods."""

    def setup_method(self):
        """Reset registry before each test."""
        # Reset singleton
        PluginRegistry._instance = None

    def test_register_router(self):
        """Test registering a router."""
        registry = PluginRegistry()
        router = APIRouter()
        
        registry.register_router(
            plugin_id="test_plugin",
            router=router,
            prefix="/api/test",
            tags=["Test"],
            priority=10,
        )
        
        routers = registry.get_routers()
        assert len(routers) == 1
        assert routers[0].plugin_id == "test_plugin"
        assert routers[0].router == router
        assert routers[0].prefix == "/api/test"

    def test_register_multiple_routers_priority_sorting(self):
        """Test that routers are sorted by priority."""
        registry = PluginRegistry()
        
        router1 = APIRouter()
        router2 = APIRouter()
        router3 = APIRouter()
        
        # Register in random order
        registry.register_router("plugin1", router1, priority=100)
        registry.register_router("plugin2", router2, priority=10)  # Should be first
        registry.register_router("plugin3", router3, priority=50)
        
        routers = registry.get_routers()
        assert len(routers) == 3
        
        # Should be sorted by priority (lower = earlier)
        assert routers[0].plugin_id == "plugin2"  # priority=10
        assert routers[1].plugin_id == "plugin3"  # priority=50
        assert routers[2].plugin_id == "plugin1"  # priority=100

    def test_get_routers_returns_copy(self):
        """Test that get_routers returns a copy."""
        registry = PluginRegistry()
        router = APIRouter()
        
        registry.register_router("test_plugin", router)
        
        routers1 = registry.get_routers()
        routers2 = registry.get_routers()
        
        assert routers1 is not routers2
        assert len(routers1) == len(routers2)


class TestPluginRegistryMiddleware:
    """Tests for PluginRegistry middleware methods."""

    def setup_method(self):
        """Reset registry before each test."""
        PluginRegistry._instance = None

    def test_register_middleware(self):
        """Test registering a middleware."""
        registry = PluginRegistry()
        
        async def test_middleware(request, call_next):
            return await call_next(request)
        
        registry.register_middleware(
            plugin_id="test_plugin",
            middleware=test_middleware,
            priority=20,
        )
        
        middleware = registry.get_middleware()
        assert len(middleware) == 1
        assert middleware[0].plugin_id == "test_plugin"
        assert middleware[0].middleware == test_middleware
        assert middleware[0].priority == 20

    def test_register_multiple_middleware_priority_sorting(self):
        """Test that middleware is sorted by priority."""
        registry = PluginRegistry()
        
        async def mid1(request, call_next):
            return await call_next(request)
        
        async def mid2(request, call_next):
            return await call_next(request)
        
        async def mid3(request, call_next):
            return await call_next(request)
        
        # Register in random order
        registry.register_middleware("plugin1", mid1, priority=100)
        registry.register_middleware("plugin2", mid2, priority=10)
        registry.register_middleware("plugin3", mid3, priority=50)
        
        middleware = registry.get_middleware()
        assert len(middleware) == 3
        
        # Should be sorted by priority
        assert middleware[0].plugin_id == "plugin2"  # priority=10
        assert middleware[1].plugin_id == "plugin3"  # priority=50
        assert middleware[2].plugin_id == "plugin1"  # priority=100

    def test_get_middleware_returns_copy(self):
        """Test that get_middleware returns a copy."""
        registry = PluginRegistry()
        
        async def test_middleware(request, call_next):
            return await call_next(request)
        
        registry.register_middleware("test_plugin", test_middleware)
        
        mid1 = registry.get_middleware()
        mid2 = registry.get_middleware()
        
        assert mid1 is not mid2


class TestPluginRegistryIntegration:
    """Integration tests for mixed registrations."""

    def setup_method(self):
        """Reset registry before each test."""
        PluginRegistry._instance = None

    def test_mixed_registrations(self):
        """Test registering providers, hooks, routers, and middleware together."""
        registry = PluginRegistry()
        
        # Register provider
        registry.register_provider(
            plugin_id="plugin1",
            provider_id="provider1",
            provider_class=Mock(),
            label="Test Provider",
            base_url="https://api.test.com",
            metadata={},
        )
        
        # Register hook
        registry.register_startup_hook(
            plugin_id="plugin1",
            hook_name="startup",
            callback=lambda: None,
        )
        
        # Register router
        router = APIRouter()
        registry.register_router(
            plugin_id="plugin1",
            router=router,
            prefix="/api/test",
        )
        
        # Register middleware
        async def test_middleware(request, call_next):
            return await call_next(request)
        
        registry.register_middleware(
            plugin_id="plugin1",
            middleware=test_middleware,
        )
        
        # Verify all registrations
        assert len(registry.get_all_providers()) == 1
        assert len(registry.get_startup_hooks()) == 1
        assert len(registry.get_routers()) == 1
        assert len(registry.get_middleware()) == 1
