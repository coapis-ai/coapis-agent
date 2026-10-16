"""
C2A Tools - LLM Tool Schemas and Structured Output Mappings

This module provides the tool schemas for C2A generation (Path 1) and structured output mappings (Path 3).
"""

import json
import os
from pathlib import Path


# Path 1: Explicit Tool Call Schema for 'generate_c2a_card'
C2A_GENERATOR_TOOL_SCHEMA = {
    "name": "generate_c2a_card",
    "description": "Generate and render an interactive C2A (Chat-to-Action) message card to present data tables, forms, or action buttons to the user. Do not return plain text when interactive UI is needed.",
    "parameters": {
        "type": "object",
        "properties": {
            "blocks": {
                "type": "array",
                "description": "Content blocks for the C2A message (e.g., text_markdown, data_table, form_definition).",
                "items": {
                    "type": "object",
                    "properties": {
                        "block_id": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["text_markdown", "data_table", "data_list", "form_definition", "custom_component"]
                        },
                        "content": {"type": "object"}
                    },
                    "required": ["type", "content"]
                }
            },
            "actions": {
                "type": "array",
                "description": "Interactive actions (buttons, links, form submissions) for the C2A message.",
                "items": {
                    "type": "object",
                    "properties": {
                        "action_id": {"type": "string"},
                        "label": {"type": "string"},
                        "style": {
                            "type": "string",
                            "enum": ["primary", "secondary", "danger", "success", "warning", "text"]
                        },
                        "intent": {
                            "type": "string",
                            "enum": [
                                "api_call", "function_invoke", "web_redirect",
                                "workflow_trigger", "form_submit", "custom_extension"
                            ]
                        },
                        "payload": {"type": "object"},
                        "security": {
                            "type": "object",
                            "properties": {
                                "requires_auth": {"type": "boolean", "default": False},
                                "required_permissions": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "confirmation_prompt": {"type": ["string", "null"]}
                            }
                        }
                    },
                    "required": ["action_id", "label", "intent", "payload"]
                }
            }
        },
        "required": ["blocks", "actions"]
    }
}


_SCHEMA_FILENAME = "c2a-message-v1.jsonschema"


def _locate_jsonschema() -> Path:
    """Locate the C2A jsonschema file.

    The schema lives in the repository root ``schemas/`` directory.
    Candidate locations, tried in order:
      1. ``$C2A_SCHEMA_DIR`` env var (explicit override, used in Docker)
      2. upward search from this file (repo layout: server/c2a_tools/src/…)
      3. ``~/coapis-c2a`` and common sibling layouts (editable installs)
    """
    env_dir = os.environ.get("C2A_SCHEMA_DIR")
    if env_dir:
        p = Path(env_dir) / _SCHEMA_FILENAME
        if p.exists():
            return p

    here = Path(__file__).resolve()
    # Walk up looking for <root>/schemas/c2a-message-v1.jsonschema
    for parent in [here] + list(here.parents):
        candidate = parent / "schemas" / _SCHEMA_FILENAME
        if candidate.exists():
            return candidate

    # Editable / site-packages install — look for the repo as a sibling
    for base in (Path.home(), Path("/apps/ai/tool-dev/dev-coapis"), Path("/app")):
        candidate = base / "coapis-c2a" / "schemas" / _SCHEMA_FILENAME
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"{_SCHEMA_FILENAME} not found. Set C2A_SCHEMA_DIR to the schemas "
        f"directory of the coapis-c2a repository."
    )


# Path 3: Structured Output Schema Mapper (reads from jsonschema)
def get_structured_output_schema(provider: str = "openai") -> dict:
    """
    Maps c2a-message-v1.jsonschema to provider-specific structured output format.

    Args:
        provider: The LLM provider name ('openai', 'anthropic', etc.)

    Returns:
        Provider-specific schema structure for structured output / function calling.
    """
    with open(_locate_jsonschema(), 'r', encoding='utf-8') as f:
        c2a_schema = json.load(f)

    if provider == "openai":
        # OpenAI response_format expects a JSON schema object
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "c2a_message",
                "description": "Chat-to-Action Interactive Message Protocol Standard v1.0",
                "schema": c2a_schema
            }
        }
    elif provider == "anthropic":
        # Anthropic tool use schema mapping (simplified to input_schema format)
        return {
            "name": "render_c2a_message",
            "description": "Render a C2A interactive message according to the C2A protocol standard.",
            "input_schema": c2a_schema
        }
    else:
        raise ValueError(f"Unsupported provider for structured output mapping: {provider}")
