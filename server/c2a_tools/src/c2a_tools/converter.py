"""
C2A Tools - Implicit Converter for Tool Output to C2A Message (Path 2)

Detects standard tool output containing interactive features (data
lists/tables) and wraps it into a C2A Message with a well-formed
``data_table`` block (``headers`` + ``rows``) plus a view-details action.
"""

import logging
from typing import Any, Dict, List, Optional

from c2a_protocol.models import (
    C2AMessage,
    ContextRef,
    Metadata,
    Block,
    BlockContent,
    Action,
    ActionSecurity,
    State,
)
from .mcp_parser import MCPC2AParser

logger = logging.getLogger(__name__)


# Keys that indicate "this tool output contains a data collection".
_DATA_LIST_KEYS = ("data_list", "users", "records", "items", "rows", "data_table")


def convert_tool_output_to_c2a(
    tool_name: str,
    tool_output: Dict[str, Any],
    session_id: str = "implicit_c2a_session",
) -> Optional[C2AMessage]:
    """Detect interactive data in a tool output and wrap it into a C2A message.

    Args:
        tool_name: The tool that produced the output.
        tool_output: The dictionary output from the tool.
        session_id: Session id for the context reference.

    Returns:
        A C2AMessage with a data_table block, or None if the output has no
        interactive data list.
    """
    # Locate a list-of-dicts anywhere at the top level of tool_output.
    list_key, list_items = _find_data_list(tool_output)
    if not list_items:
        return None

    first_item = list_items[0]
    id_field = MCPC2AParser._find_id_field(first_item)

    # Build a proper data_table content: headers + rows (+ id plumbing).
    headers = [
        str(k) for k in first_item.keys()
        if (id_field is None or k != id_field) and not str(k).startswith("_")
    ]
    if not headers:
        headers = [str(k) for k in first_item.keys()]
    rows = [[str(item.get(h, "")) for h in headers] for item in list_items]

    table_content: Dict[str, Any] = {"data": {"headers": headers, "rows": rows}}
    if id_field:
        table_content["id_field"] = id_field
        table_content["row_values"] = [{id_field: item.get(id_field, "")} for item in list_items]
        table_content["row_actions"] = {
            "view_detail": {
                "action_id": f"btn_view_{tool_name}",
                "label": "查看详情",
                "style": "link",
                "business_intent": "view_detail",
                "url_template": f"/{list_key}/{{{id_field}}}",
            }
        }

    c2a_block = Block(type="data_table", content=BlockContent(data=table_content))

    c2a_action = Action(
        action_id=f"btn_view_details_{tool_name}",
        label="查看详情",
        style="primary",
        intent="api_call",
        payload={
            "method": "GET",
            "endpoint": f"/api/v1/{tool_name}/details",
            "params": {},
        },
        security=ActionSecurity(requires_auth=True),
    )

    return C2AMessage(
        context_ref=ContextRef(session_id=session_id),
        metadata=Metadata(generated_by=f"tool_{tool_name}_converter"),
        blocks=[c2a_block],
        actions=[c2a_action],
        state=State(status="rendered"),
    )


def _find_data_list(tool_output: Dict[str, Any]) -> Optional[tuple]:
    """Find a (key, list-of-dicts) in tool_output, preferring known keys."""
    # Prefer explicit data-list keys.
    for key in _DATA_LIST_KEYS:
        value = tool_output.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return key, value
    # Fall back to any list-of-dicts value.
    for key, value in tool_output.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return key, value
    return None
