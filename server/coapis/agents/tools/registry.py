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

    5. ``@register_tool`` now merges automatically inferred top-level imports
       into ``dependencies`` so that :class:`RuntimeDependencyManager` can
       pre-install missing packages without requiring manual declarations.
"""

from __future__ import annotations

import ast
import importlib.util
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auto-inference helpers
# ---------------------------------------------------------------------------

_INTERNAL_PACKAGES = {
    "agentscope",
    "coapis",
    "fastapi",
    "pydantic",
    "starlette",
    "uvicorn",
    "aiohttp",
    "sqlalchemy",
    "redis",
    "weaviate",
    "chromadb",
    "qdrant",
    "sentence_transformers",
    "transformers",
    "torch",
    "tensorrt",
    "vllm",
    "accelerate",
    "bitsandbytes",
    "xformers",
    "flash_attn",
    "deepspeed",
    "peft",
    "trl",
}

_IMPORT_TO_PIP = {
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "pymupdf": "pymupdf",
    "pymupdf4llm": "pymupdf4llm",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "xlsx": "openpyxl",
    "mss": "mss",
    "psutil": "psutil",
    "aiofiles": "aiofiles",
    "httpx": "httpx",
    "httpcore": "httpcore",
    "tiktoken": "tiktoken",
    "numpy": "numpy",
    "pandas": "pandas",
    "soundfile": "soundfile",
    "librosa": "librosa",
    "pydub": "pydub",
    "speech_recognition": "SpeechRecognition",
    "openpyxl": "openpyxl",
}


def _is_stdlib(module_name: str) -> bool:
    top = module_name.split(".")[0]
    if top in sys.stdlib_module_names:
        return True
    if top in _INTERNAL_PACKAGES:
        return True
    return False


def _infer_requirements_from_source(source: str) -> list[dict[str, Any]]:
    reqs: dict[str, dict[str, Any]] = {}
    try:
        tree = ast.parse(source)
    except Exception:
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if _is_stdlib(top):
                    continue
                pkg = _IMPORT_TO_PIP.get(top, top)
                reqs[pkg] = {
                    "name": pkg,
                    "manager": "pip",
                    "required": True,
                    "reason": f"auto-inferred from import {top!r}",
                }
        elif isinstance(node, ast.ImportFrom):
            # Skip relative imports (from .xxx import ...)
            if getattr(node, "level", 0) > 0:
                continue
            if node.module is None:
                continue
            top = node.module.split(".")[0]
            if _is_stdlib(top):
                continue
            pkg = _IMPORT_TO_PIP.get(top, top)
            reqs[pkg] = {
                "name": pkg,
                "manager": "pip",
                "required": True,
                "reason": f"auto-inferred from from {top!r} import",
            }
    return list(reqs.values())


def _infer_requirements_from_file(file_path: str) -> list[dict[str, Any]]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return _infer_requirements_from_source(f.read())
    except Exception:
        return []


def _normalize_dependencies(
    declared: list[dict[str, Any]] | None,
    inferred: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for dep in (declared or []) + inferred:
        key = dep.get("manager", "pip") + ":" + str(dep.get("name", ""))
        if key not in merged or dep.get("reason", "").startswith("auto-inferred"):
            merged[key] = dep
    return list(merged.values())


# ---------------------------------------------------------------------------
# Core registration dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ToolRegistration:
    """Metadata for a registered tool."""
    name: str
    func: Callable
    description: str = ""
    async_execution: bool = False
    category: str = "builtin"  # builtin, plugin, custom
    tags: list[str] = field(default_factory=list)
    requires_modes: list[str] = field(default_factory=list)
    requires_skills: list[str] = field(default_factory=list)
    requires_features: list[str] = field(default_factory=list)
    requires_sandbox: bool = False
    governance: dict[str, Any] = field(default_factory=dict)
    dependencies: list[dict[str, Any]] = field(default_factory=list)


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
    requires_modes: list[str] | None = None,
    requires_skills: list[str] | None = None,
    requires_features: list[str] | None = None,
    requires_sandbox: bool = False,
    governance: dict[str, Any] | None = None,
    dependencies: list[dict[str, Any]] | None = None,
) -> Callable:
    """Decorator to register a tool function.

    Can be used as:
        @register_tool
        async def my_tool(...): ...

    Or with options:
        @register_tool(name="custom_name", description="...")
        async def my_tool(...): ...

    Dependencies are merged with automatically inferred top-level imports so
    :class:`RuntimeDependencyManager` can pre-install missing packages.
    """
    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        inferred = []
        try:
            mod_name = getattr(fn, "__module__", None)
            if mod_name:
                spec = importlib.util.find_spec(mod_name)
                if spec and spec.origin and spec.origin.endswith(".py"):
                    inferred = _infer_requirements_from_file(spec.origin)
        except Exception:
            inferred = []

        merged_deps = _normalize_dependencies(dependencies, inferred)
        reg = ToolRegistration(
            name=tool_name,
            func=fn,
            description=description or fn.__doc__ or "",
            async_execution=async_execution,
            category=category,
            tags=tags or [],
            requires_modes=requires_modes or [],
            requires_skills=requires_skills or [],
            requires_features=requires_features or [],
            requires_sandbox=requires_sandbox,
            governance=governance or {},
            dependencies=merged_deps,
        )
        _registry[tool_name] = reg
        logger.debug("Registered tool: %s (category=%s, deps=%s)", tool_name, category, merged_deps)
        return fn

    if func is not None:
        return decorator(func)
    return decorator


def apply_tool_descriptions(language: str = "zh") -> int:
    """从数据包加载工具描述并覆盖注册表中的硬编码描述.

    Args:
        language: 语言代码

    Returns:
        覆盖的工具数量
    """
    try:
        from coapis.system.data_loader import load_tool_descriptions
        descriptions = load_tool_descriptions(language)
    except Exception:
        return 0

    count = 0
    for name, desc in descriptions.items():
        if name in _registry and desc:
            _registry[name].description = desc
            count += 1
    if count:
        logger.info("Applied %d tool descriptions from data pack (lang=%s)", count, language)
    return count


def get_registered_tools(
    category: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, ToolRegistration]:
    """Return registered tools, optionally filtered by category or tags."""
    result = {}
    for name, reg in _registry.items():
        if category and reg.category != category:
            continue
        if tags and not all(t in reg.tags for t in tags):
            continue
        result[name] = reg
    return result


def get_registered_tool(tool_name: str) -> ToolRegistration | None:
    """Return a single tool registration by name."""
    return _registry.get(tool_name)


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
