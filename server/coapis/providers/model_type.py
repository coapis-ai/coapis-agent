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

"""Model type inference utilities.

Single source of truth for inferring a model's primary type
(``chat`` / ``embedding`` / ``rerank`` / ``audio`` / ``vision``)
from its ID or name.

Inference only applies to *new* models entering the system for the
first time. User-explicit choices always take precedence and can be
changed at any time via the UI/API.
"""

from __future__ import annotations

from typing import Optional

from .provider import ModelType

VALID_MODEL_TYPES: tuple[str, ...] = (
    "chat",
    "embedding",
    "rerank",
    "audio",
    "vision",
)

# Keyword rules, checked in order; first match wins.
_RERANK_KEYWORDS: tuple[str, ...] = ("rerank",)
_EMBEDDING_KEYWORDS: tuple[str, ...] = ("embed", "bge", "e5-")
_AUDIO_KEYWORDS: tuple[str, ...] = (
    "whisper",
    "asr",
    "tts",
    "speech",
    "speak",
)
_VISION_KEYWORDS: tuple[str, ...] = (
    "vision",
    "omni",
    "llava",
    "clip",
    "-vl",
    "_vl",
    "vl-",
)
_VISION_SUFFIXES: tuple[str, ...] = ("vl",)


def is_valid_model_type(value: Optional[str]) -> bool:
    """Whether *value* is one of the five supported model types."""
    return value in VALID_MODEL_TYPES


def infer_model_type(model_id: str, model_name: str = "") -> ModelType:
    """Infer the primary model type from a model's ID and/or name.

    Rules (case-insensitive, matched against ``"{id} {name}"``):

    1. contains ``rerank``                    -> ``rerank``
    2. contains ``embed`` / ``bge`` / ``e5-`` -> ``embedding``
    3. contains ``whisper`` / ``asr`` / ``tts`` / ``speech`` / ``speak``
                                             -> ``audio``
    4. contains ``vision`` / ``omni`` / ``llava`` / ``clip`` / ``-vl`` /
       ``_vl`` / ``vl-`` or ends with ``vl``  -> ``vision``
    5. otherwise                              -> ``chat``

    Args:
        model_id: Model identifier (e.g. ``qwen3-embedding:0.6b``).
        model_name: Human-readable name (optional, also matched).

    Returns:
        The inferred model type.
    """
    haystack = f"{model_id} {model_name}".strip().lower()
    if not haystack:
        return "chat"

    if any(kw in haystack for kw in _RERANK_KEYWORDS):
        return "rerank"
    if any(kw in haystack for kw in _EMBEDDING_KEYWORDS):
        return "embedding"
    if any(kw in haystack for kw in _AUDIO_KEYWORDS):
        return "audio"
    if any(kw in haystack for kw in _VISION_KEYWORDS):
        return "vision"
    if any(haystack.endswith(suffix) for suffix in _VISION_SUFFIXES):
        return "vision"
    return "chat"
