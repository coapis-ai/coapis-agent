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

"""Learned model capability cache.

When the system discovers model capabilities through trial-and-error
(e.g. a model requires ``reasoning_content`` on every assistant message,
or rejects multimodal input despite being marked as supporting it),
those findings are cached here by ``provider_id:model_name`` key.

This avoids repeated first-call failures when the same model is used
again after a model switch.  The cache is process-scoped (not persisted)
and deliberately conservative: entries are only written after a confirmed
failure-then-recovery cycle.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class ModelCapabilityCache:
    """Thread-safe, process-scoped cache for learned model capabilities.

    Capabilities are stored as ``{model_key: {capability_name: value}}``.

    Known capability keys:
        ``needs_reasoning_content`` (bool):
            The model requires every assistant message to carry
            ``reasoning_content`` when thinking mode is active.
        ``rejects_media`` (bool):
            The model rejects multimodal (image/audio/video) input
            despite being marked as supporting it.
    """

    _instance: ModelCapabilityCache | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._learned: dict[str, dict[str, Any]] = {}
        self._data_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> ModelCapabilityCache:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def learn(self, model_key: str, capability: str, value: Any) -> None:
        """Record a learned capability for *model_key*."""
        with self._data_lock:
            bucket = self._learned.setdefault(model_key, {})
            if bucket.get(capability) != value:
                bucket[capability] = value
                logger.info(
                    "Learned capability for %s: %s=%r",
                    model_key,
                    capability,
                    value,
                )

    def get(
        self,
        model_key: str,
        capability: str,
        default: Any = None,
    ) -> Any:
        """Return the cached value, or *default* if not learned yet."""
        with self._data_lock:
            return self._learned.get(model_key, {}).get(
                capability,
                default,
            )

    def clear(self, model_key: str | None = None) -> None:
        """Clear learned capabilities.

        If *model_key* is given, only that model's entries are cleared.
        Otherwise, **all** entries are dropped.
        """
        with self._data_lock:
            if model_key is None:
                self._learned.clear()
            else:
                self._learned.pop(model_key, None)


def get_capability_cache() -> ModelCapabilityCache:
    """Return the global :class:`ModelCapabilityCache` singleton."""
    return ModelCapabilityCache.get_instance()
