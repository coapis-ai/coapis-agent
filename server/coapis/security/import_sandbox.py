"""Import sandbox - module-level import restriction for cross-platform use.

Blocks dangerous Python module imports (os, subprocess, socket, etc.)
and allows only safe modules (json, pathlib, asyncio, etc.).

Pure Python, zero external dependencies.
"""

import builtins
import sys
import logging
from typing import Optional, Set, Callable

logger = logging.getLogger(__name__)

# Default blocked modules (dangerous for tool execution)
DEFAULT_BLOCKED_MODULES: Set[str] = {
    # System access
    "os", "subprocess", "shutil", "sys", "importlib",
    # Network
    "socket", "http", "urllib", "requests", "aiohttp",
    # Low-level
    "ctypes", "struct", "mmap",
    # Code execution
    "code", "codeop", "compileall",
    # Threading (resource concern)
    "multiprocessing", "threading",
}

# Default allowed modules (safe for tool execution)
DEFAULT_ALLOWED_MODULES: Set[str] = {
    # Standard library - safe
    "json", "pathlib", "asyncio", "logging", "time", "datetime",
    "re", "hashlib", "base64", "uuid", "collections",
    "typing", "dataclasses", "enum", "abc",
    "io", "csv", "configparser", "glob", "fnmatch",
    "textwrap", "string", "difflib", "unicodedata",
    "tempfile", "shlex", "platform",
    # CoApis internal
    "coapis",
}


class ImportSandbox:
    """Module-level import sandbox.

    Intercepts Python __import__ calls and blocks access to
    dangerous modules. Works on all platforms (Linux/macOS/Windows).

    Usage:
        sandbox = ImportSandbox()
        sandbox.activate()
        # Now os, subprocess, socket etc. are blocked
        # ...
        sandbox.deactivate()
    """

    def __init__(
        self,
        blocked: Optional[Set[str]] = None,
        allowed: Optional[Set[str]] = None,
        on_block: Optional[Callable[[str], None]] = None,
    ):
        self.blocked = blocked or DEFAULT_BLOCKED_MODULES.copy()
        self.allowed = allowed or DEFAULT_ALLOWED_MODULES.copy()
        self.on_block = on_block or self._default_on_block
        self._original_import: Optional[Callable] = None
        self._active = False
        self._block_count = 0

    def _default_on_block(self, module_name: str):
        """Default handler when a module import is blocked."""
        self._block_count += 1
        logger.warning(
            "Import blocked: %s (total blocks: %d)",
            module_name, self._block_count,
        )

    def _sandboxed_import(
        self,
        name: str,
        globals=None,
        locals=None,
        fromlist=(),
        level=0,
    ):
        """Sandboxed __import__ replacement."""
        # Get top-level module name
        top_level = name.split(".")[0]

        # Check blocked list
        if top_level in self.blocked:
            self.on_block(name)
            raise ImportError(
                f"Module '{name}' is blocked by security policy. "
                f"Contact administrator if this is a false positive."
            )

        # Check allowed list (if configured)
        if self.allowed and top_level not in self.allowed:
            # Check if it's a submodule of an allowed module
            if not any(top_level.startswith(a + ".") for a in self.allowed):
                self.on_block(name)
                raise ImportError(
                    f"Module '{name}' is not in the allowed list. "
                    f"Contact administrator to add it."
                )

        # Allow the import
        return self._original_import(name, globals, locals, fromlist, level)

    def activate(self):
        """Activate the import sandbox."""
        if self._active:
            return

        self._original_import = builtins.__import__
        builtins.__import__ = self._sandboxed_import
        self._active = True
        logger.debug("ImportSandbox activated (blocked=%d, allowed=%d)",
                     len(self.blocked), len(self.allowed))

    def deactivate(self):
        """Deactivate the import sandbox."""
        if not self._active:
            return

        builtins.__import__ = self._original_import
        self._original_import = None
        self._active = False
        logger.debug("ImportSandbox deactivated (total blocks: %d)",
                     self._block_count)

    def is_active(self) -> bool:
        """Check if sandbox is currently active."""
        return self._active

    def get_stats(self) -> dict:
        """Get sandbox statistics."""
        return {
            "active": self._active,
            "blocked_count": len(self.blocked),
            "allowed_count": len(self.allowed),
            "total_blocks": self._block_count,
        }

    def add_blocked(self, module_name: str):
        """Add a module to the blocked list."""
        self.blocked.add(module_name)

    def remove_blocked(self, module_name: str):
        """Remove a module from the blocked list."""
        self.blocked.discard(module_name)

    def __enter__(self):
        self.activate()
        return self

    def __exit__(self, *args):
        self.deactivate()
