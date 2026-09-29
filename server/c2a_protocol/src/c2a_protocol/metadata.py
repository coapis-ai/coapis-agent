"""
C2A MCP tool-metadata extraction.

Host applications (e.g. coapis-agent) register MCP tools whose *definitions*
carry C2A card metadata (``action_templates`` with ``url_template`` +
``params_mapping``). Such servers declare the metadata in non-uniform places
— OA puts it inside ``inputSchema["metadata"]``, others use a top-level
``metadata`` field. This helper checks the common carriers in priority order
and returns the first non-empty dict (or ``None``).
"""

from typing import Any, Dict, Optional


def extract_tool_metadata(mcp_tool: Any) -> Optional[Dict[str, Any]]:
    """Extract C2A card metadata from an MCP tool definition.

    Args:
        mcp_tool: An MCP tool object (pydantic model, dataclass-like, or a
            raw dict). May expose ``inputSchema`` and/or ``model_extra``.

    Returns:
        The first non-empty ``metadata`` dict found among the common
        carriers, or ``None`` when the tool declares no C2A metadata.
    """
    carriers: list = []

    input_schema = getattr(mcp_tool, "inputSchema", None)
    if isinstance(input_schema, dict):
        carriers.append(input_schema)
    model_extra = getattr(mcp_tool, "model_extra", None)
    if isinstance(model_extra, dict):
        carriers.append(model_extra)
    if isinstance(mcp_tool, dict):  # raw-dict tool (defensive)
        carriers.append(mcp_tool)

    for carrier in carriers:
        meta = carrier.get("metadata")
        if isinstance(meta, dict) and meta:
            return meta
    return None
