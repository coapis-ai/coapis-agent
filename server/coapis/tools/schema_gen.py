# -*- coding: utf-8 -*-
"""Auto-generate OpenAI function calling JSON schema from Python function docstring + signature.

Inspired by CoApis's _parse_tool_function in agentscope._utils._common.
"""

import inspect
import re
from typing import Any, Dict, Optional, get_type_hints


# Python type → JSON schema type mapping
_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _parse_docstring(docstring: str) -> dict:
    """Parse Google-style docstring into structured parts.

    Returns:
        {
            "summary": "short description",
            "description": "long description",
            "params": [{"name": "arg", "type": "str", "description": "...", "default": ...}],
        }
    """
    if not docstring:
        return {"summary": "", "description": "", "params": []}

    lines = docstring.strip().split("\n")
    summary = ""
    description_lines = []
    params = []
    section = "summary"

    for line in lines:
        stripped = line.strip()

        # Detect sections
        if stripped in ("Args:", "Parameters:", "Arguments:", "Params:"):
            section = "args"
            continue
        if stripped in ("Returns:", "Return:", "Yields:", "Yield:"):
            section = "returns"
            continue
        if stripped.startswith("Examples:"):
            section = "examples"
            continue

        if section == "summary":
            if stripped:
                summary = stripped
                section = "description"
        elif section == "description":
            if stripped:
                description_lines.append(stripped)
            else:
                # Empty line might separate description from args
                pass
        elif section == "args":
            if not stripped:
                continue
            # Parse "name (type): description" or "name: description"
            # Also handle "name: type\n    description" multi-line format
            m = re.match(
                r"^\*{0,2}(\w+)\s*(?:\(([^)]+)\))?\s*[:：]\s*(.*)",
                stripped,
            )
            if m:
                param_name = m.group(1).lstrip("*")
                param_type = (m.group(2) or "").strip()
                param_desc = (m.group(3) or "").strip()
                params.append({
                    "name": param_name,
                    "type_hint": param_type,
                    "description": param_desc,
                })
            elif params and not stripped.startswith(("Returns", "Yields")):
                # Continuation of previous param description
                if params:
                    params[-1]["description"] += " " + stripped

    description = "\n".join(description_lines).strip()
    return {
        "summary": summary,
        "description": description,
        "params": params,
    }


def _python_type_to_json_schema(type_hint) -> str:
    """Convert Python type hint to JSON schema type string."""
    if type_hint is inspect.Parameter.empty or type_hint is None:
        return "string"  # Default to string

    # Handle string annotations
    if isinstance(type_hint, str):
        type_str = type_hint.lower()
        if "int" in type_str:
            return "integer"
        if "float" in type_str or "number" in type_str:
            return "number"
        if "bool" in type_str:
            return "boolean"
        if "list" in type_str or "array" in type_str:
            return "array"
        if "dict" in type_str or "object" in type_str:
            return "object"
        return "string"

    # Handle actual types
    if type_hint in _TYPE_MAP:
        return _TYPE_MAP[type_hint]

    # Handle Optional[X]
    origin = getattr(type_hint, "__origin__", None)
    if origin is not None:
        if str(origin).startswith("typing.Union"):
            args = getattr(type_hint, "__args__", ())
            non_none = [a for a in args if a is not type(None)]
            if non_none:
                return _python_type_to_json_schema(non_none[0])
        if origin is list:
            return "array"
        if origin is dict:
            return "object"

    return "string"  # Fallback


def auto_generate_schema(
    func: callable,
    *,
    include_long_description: bool = True,
    extra_description: Optional[str] = None,
) -> Dict[str, Any]:
    """Auto-generate OpenAI function calling JSON schema from a Python function.

    Extracts:
    - Function description from docstring
    - Parameter descriptions from docstring Args section
    - Parameter types from type annotations
    - Default values from function signature

    Args:
        func: The Python function to generate schema for
        include_long_description: Whether to include the long description
        extra_description: Extra text to append to the description

    Returns:
        OpenAI function calling format dict:
        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            }
        }
    """
    docstring_info = _parse_docstring(func.__doc__)
    sig = inspect.signature(func)

    # Build description
    description = docstring_info["summary"]
    if include_long_description and docstring_info["description"]:
        if description:
            description += "\n" + docstring_info["description"]
        else:
            description = docstring_info["description"]
    if extra_description:
        description = (description + "\n" + extra_description).strip()

    # Build params doc lookup
    params_doc = {p["name"]: p for p in docstring_info["params"]}

    # Build properties and required
    properties = {}
    required = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue

        # Get type from annotation, fallback to docstring type hint
        annotation = param.annotation
        json_type = _python_type_to_json_schema(annotation)

        # Get description from docstring
        param_info = params_doc.get(name, {})
        param_desc = param_info.get("description", "")

        # Build property schema
        prop: Dict[str, Any] = {"type": json_type}
        if param_desc:
            prop["description"] = param_desc

        # Handle default value
        if param.default is not inspect.Parameter.empty:
            if param.default is not None:
                prop["default"] = param.default
        else:
            required.append(name)

        properties[name] = prop

    # Build complete schema
    schema = {
        "type": "function",
        "function": {
            "name": func.__name__,
            "parameters": {
                "type": "object",
                "properties": properties,
            },
        },
    }

    if description:
        schema["function"]["description"] = description

    if required:
        schema["function"]["parameters"]["required"] = required

    return schema


def merge_with_manual_schema(
    auto_schema: Dict[str, Any],
    manual_description: Optional[str] = None,
    manual_parameters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge auto-generated schema with manual overrides.

    Manual values take precedence when provided, allowing incremental
    migration: functions can start with auto-generated schema and
    gradually add manual descriptions where needed.

    Args:
        auto_schema: The auto-generated schema
        manual_description: Manual description to override (None = keep auto)
        manual_parameters: Manual parameters to override (None = keep auto)

    Returns:
        Merged schema dict
    """
    result = dict(auto_schema)
    func = dict(result.get("function", {}))

    if manual_description:
        func["description"] = manual_description

    if manual_parameters:
        func["parameters"] = manual_parameters

    result["function"] = func
    return result
