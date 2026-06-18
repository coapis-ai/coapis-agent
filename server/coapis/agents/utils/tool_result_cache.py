"""Tool result cache — LRU with TTL for idempotent tools.

Only caches tools in the IDEMPOTENT_TOOLS set.
Key: (tool_name, params_hash) → cached output string.
"""

import hashlib
import json
import time
import threading
from collections import OrderedDict
from typing import Any

# Tools that are safe to cache (read-only, deterministic)
IDEMPOTENT_TOOLS = {
    "read_file",
    "grep_search",
    "glob_search",
    "get_current_time",
    "view_image",
}

# Cache settings
_DEFAULT_TTL_SECONDS = 120   # 2 minutes
_DEFAULT_MAX_SIZE = 200      # max entries
_DEFAULT_MAX_VALUE_SIZE = 64 * 1024  # 64KB — don't cache huge outputs


class ToolResultLRUCache:
    """Thread-safe LRU cache with TTL for tool results."""

    def __init__(
        self,
        max_size: int = _DEFAULT_MAX_SIZE,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        max_value_size: int = _DEFAULT_MAX_VALUE_SIZE,
    ):
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._max_value_size = max_value_size
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _make_key(tool_name: str, params: dict[str, Any] | None) -> str:
        """Build cache key from tool name + serialized params."""
        raw = json.dumps(params or {}, sort_keys=True, default=str)[:1024]
        param_hash = hashlib.md5(raw.encode()).hexdigest()[:16]
        return f"{tool_name}:{param_hash}"

    def get(self, tool_name: str, params: dict[str, Any] | None) -> str | None:
        """Return cached output or None if miss/expired."""
        key = self._make_key(tool_name, params)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            ts, value = entry
            if time.monotonic() - ts > self._ttl:
                # Expired
                del self._cache[key]
                self._misses += 1
                return None
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def put(self, tool_name: str, params: dict[str, Any] | None, output: str) -> None:
        """Store tool output in cache."""
        if not output or len(output) > self._max_value_size:
            return
        key = self._make_key(tool_name, params)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (time.monotonic(), output)
            # Evict oldest if over capacity
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self, tool_name: str | None = None) -> int:
        """Invalidate cache entries. If tool_name given, only that tool."""
        with self._lock:
            if tool_name is None:
                count = len(self._cache)
                self._cache.clear()
                return count
            keys_to_remove = [k for k in self._cache if k.startswith(f"{tool_name}:")]
            for k in keys_to_remove:
                del self._cache[k]
            return len(keys_to_remove)

    def stats(self) -> dict:
        """Return cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total > 0 else 0,
                "ttl_seconds": self._ttl,
            }

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        now = time.monotonic()
        removed = 0
        with self._lock:
            expired_keys = [
                k for k, (ts, _) in self._cache.items()
                if now - ts > self._ttl
            ]
            for k in expired_keys:
                del self._cache[k]
                removed += 1
        return removed


# Global singleton
_cache = ToolResultLRUCache()


def get_cache() -> ToolResultLRUCache:
    """Return the global tool result cache."""
    return _cache


def is_idempotent(tool_name: str) -> bool:
    """Check if a tool is safe to cache."""
    return tool_name in IDEMPOTENT_TOOLS
