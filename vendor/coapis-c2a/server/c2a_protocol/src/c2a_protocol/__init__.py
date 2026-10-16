"""
C2A (Chat-to-Action) Interactive Message Protocol - Python Core SDK

This package provides the data models and validation utilities for the C2A protocol.
"""

from .models import (
    PROTOCOL_VERSION,
    BLOCK_TYPES,
    ACTION_INTENTS,
    C2AMessage,
    ContextRef,
    Metadata,
    Button,
    Block,
    BlockContent,
    Action,
    ActionSecurity,
    Suggestion,
    State,
)
from .validator import validate_c2a_message, C2AValidationError
from .converters import c2a_payload_from_llm
from .metadata import extract_tool_metadata

__all__ = [
    "PROTOCOL_VERSION",
    "BLOCK_TYPES",
    "ACTION_INTENTS",
    "C2AMessage",
    "ContextRef",
    "Metadata",
    "Button",
    "Block",
    "BlockContent",
    "Action",
    "ActionSecurity",
    "Suggestion",
    "State",
    "validate_c2a_message",
    "C2AValidationError",
    "c2a_payload_from_llm",
    "extract_tool_metadata",
]
