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
from .mcp_parser import MCPC2AParser, find_url_field

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
        usable data list (or the conversion failed — it never raises).
    """
    try:
        return _convert_inner(tool_name, tool_output, session_id)
    except Exception as e:  # never crash the host agent — degrade to "skipped"
        logger.warning(
            "c2a converter failed for tool %r: %s", tool_name, e, exc_info=True
        )
        return None


def _convert_inner(
    tool_name: str,
    tool_output: Dict[str, Any],
    session_id: str,
) -> Optional[C2AMessage]:
    """(internal) conversion logic — may raise; the wrapper catches it."""
    # Locate a list-of-dicts recursively (depth ≤ 3), preferring known keys.
    found = _find_data_list(tool_output)
    if found is None:
        return None
    list_key, list_items = found
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

    # P1-B: Row links only when MCP data actually provides a URL field.
    # Without a real URL, the old code generated a fake /{list_key}/{id}
    # path that never resolved — better to show a plain table.
    url_field = find_url_field(first_item)
    if url_field:
        # Make sure the URL column is visible in the table.
        if url_field not in headers:
            headers.append(str(url_field))
            rows = [[str(item.get(h, "")) for h in headers] for item in list_items]
            table_content["data"]["headers"] = headers
            table_content["data"]["rows"] = rows

        row_action: Dict[str, Any] = {
            "action_id": f"btn_view_{tool_name}",
            "label": "查看详情",
            "style": "link",
            "business_intent": "view_detail",
            # Use the column value directly as the URL.
            "url_template": f"{{{url_field}}}",
            "link_column": str(url_field),
        }
        table_content["row_actions"] = {"view_detail": row_action}
    # If no url_field: no row_actions — the table is just a plain table.

    c2a_block = Block(type="data_table", content=BlockContent(data=table_content))

    # P1-B: No fake top-level "查看详情" button.  Row links (when present)
    # serve as the detail entry point; a button pointing at a non-existent
    # endpoint only confuses the user.
    return C2AMessage(
        context_ref=ContextRef(session_id=session_id),
        metadata=Metadata(generated_by=f"tool_{tool_name}_converter"),
        blocks=[c2a_block],
        actions=[],
        state=State(status="rendered"),
    )


def _is_dict_list(value: Any) -> bool:
    """True only for a non-empty list whose *every* element is a dict.

    Requiring all-dict (not just the first) keeps row-building from crashing
    on mixed lists like ``[{"id":1}, "str", ...]``.
    """
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(x, dict) for x in value)
    )


def _find_data_list(
    tool_output: Any,
    _depth: int = 0,
    _max_depth: int = 3,
) -> Optional[tuple]:
    """Find a ``(key, list-of-dicts)`` in tool_output, searching recursively.

    Priority at each level: known data-list keys first, then any list-of-dicts;
    then descend into nested dicts (depth ≤ ``_max_depth``) so data wrapped in
    e.g. ``{"result": {"items": [...]}}`` is still found.  Returns
    ``(key, items)`` or ``None``.
    """
    if not isinstance(tool_output, dict):
        return None
    # 1. known keys at this level (strongest signal).
    for key in _DATA_LIST_KEYS:
        value = tool_output.get(key)
        if _is_dict_list(value):
            return key, value
    # 2. any list-of-dicts at this level.
    for key, value in tool_output.items():
        if _is_dict_list(value):
            return key, value
    # 3. recurse into dict values, bounded depth.
    if _depth < _max_depth:
        for key, value in tool_output.items():
            if isinstance(value, dict):
                found = _find_data_list(value, _depth + 1, _max_depth)
                if found is not None:
                    return key, found[1]
    return None
