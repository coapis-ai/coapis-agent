"""Plugin-style tool registration system.

Usage:
    1. Decorate any async tool function with @register_tool:
       ```python
       from .registry import register_tool

       @register_tool(name="my_tool", description="Does something")
       async def my_tool(param: str) -> ToolResponse:
           ...
       ```

    2. The tool is automatically discovered by CoApisAgent._create_toolkit()
       via get_registered_tools().

    3. Tools can also be registered from external plugins by importing
       the module containing @register_tool decorators.

    4. Tools can be enabled/disabled via agent config (builtin_tools).
       If a tool is not in config, it's enabled by default.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ToolRegistration:
    """Metadata for a registered tool."""
    name: str
    func: Callable
    description: str = ""
    async_execution: bool = False
    category: str = "builtin"  # builtin, plugin, custom
    tags: list[str] = field(default_factory=list)
    scene: str = "general"  # coding/ops/data/security/ai/collaboration/general


# Global registry
_registry: dict[str, ToolRegistration] = {}


def register_tool(
    func: Callable | None = None,
    *,
    name: str | None = None,
    description: str = "",
    async_execution: bool = False,
    category: str = "builtin",
    tags: list[str] | None = None,
    scene: str = "general",
) -> Callable:
    """Decorator to register a tool function.

    Can be used as:
        @register_tool
        async def my_tool(...): ...

    Or with options:
        @register_tool(name="custom_name", description="...")
        async def my_tool(...): ...
    """
    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        reg = ToolRegistration(
            name=tool_name,
            func=fn,
            description=description or fn.__doc__ or "",
            async_execution=async_execution,
            category=category,
            tags=tags or [],
            scene=scene,
        )
        _registry[tool_name] = reg
        logger.debug("Registered tool: %s (category=%s)", tool_name, category)
        return fn

    if func is not None:
        # @register_tool without parentheses
        return decorator(func)
    # @register_tool(...) with arguments
    return decorator


def get_registered_tools(
    category: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, ToolRegistration]:
    """Return registered tools, optionally filtered by category or tags.

    Args:
        category: If set, only return tools in this category.
        tags: If set, only return tools that have ALL of these tags.

    Returns:
        Dict of tool_name -> ToolRegistration
    """
    result = {}
    for name, reg in _registry.items():
        if category and reg.category != category:
            continue
        if tags and not all(t in reg.tags for t in tags):
            continue
        result[name] = reg
    return result


def get_tool_names() -> list[str]:
    """Return all registered tool names."""
    return list(_registry.keys())


def is_registered(tool_name: str) -> bool:
    """Check if a tool is registered."""
    return tool_name in _registry


def unregister_tool(tool_name: str) -> bool:
    """Remove a tool from the registry. Returns True if it existed."""
    return _registry.pop(tool_name, None) is not None


def clear_registry() -> None:
    """Clear all registered tools (mainly for testing)."""
    _registry.clear()


def auto_discover_tools(module_paths: list[str]) -> int:
    """Import modules to trigger @register_tool decorators.

    Args:
        module_paths: List of dotted module paths to import.

    Returns:
        Number of newly registered tools.
    """
    import importlib
    before = len(_registry)
    for path in module_paths:
        try:
            importlib.import_module(path)
            logger.debug("Auto-discovered tools from: %s", path)
        except Exception as e:
            logger.warning("Failed to import tool module '%s': %s", path, e)
    return len(_registry) - before
