"""
C2A (Chat-to-Action) Interactive Message Protocol - LLM Tool Integration SDK

This package provides tools and utilities for activating C2A protocols in LLM Agent frameworks.
"""
from .schema import C2A_GENERATOR_TOOL_SCHEMA, get_structured_output_schema
from .executor import execute_c2a_generation
from .converter import convert_tool_output_to_c2a
from .mcp_parser import MCPC2AParser, ActionTemplateTypes, ActionTemplateValidator

__all__ = [
    "C2A_GENERATOR_TOOL_SCHEMA",
    "get_structured_output_schema",
    "execute_c2a_generation",
    "convert_tool_output_to_c2a",
    "MCPC2AParser",
    "ActionTemplateTypes",
    "ActionTemplateValidator",
]
