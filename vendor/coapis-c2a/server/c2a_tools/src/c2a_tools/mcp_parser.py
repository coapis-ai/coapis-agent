# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""MCP → C2A message parser.

Parses MCP tool return results (including ``metadata.action_templates``)
and generates C2A protocol messages with data_table blocks, row-level
links (row_actions) and suggestions.

This is the SINGLE SOURCE OF TRUTH for MCP→C2A parsing. The copy that
used to live in coapis-agent (``coapis/app/services/mcp_c2a_parser.py``)
was removed in the c2a consolidation; everything below was merged back
from that fork (id-field detection, row_link/export/more inference,
header exclusion, suggestion generation).

Row-link contract (fixes the "row link never opens" bug family):
  * ``row_actions.<key>.url_template`` uses single-brace placeholders
    (``{approval_id}``) — the renderer fills them from ``row_values``.
  * ``data_table.content.id_field`` names the id field, and
    ``data_table.content.row_values`` is a per-row list of
    ``{id_field: value}`` dicts so the renderer can build a real URL
    for every row even though the id column is hidden from the table.
"""

import json
import re
from typing import Any, Dict, List, Optional

from c2a_protocol import (
    PROTOCOL_VERSION,
    Block,
    BlockContent,
    Button,
    C2AMessage,
    ContextRef,
    Metadata,
    Suggestion,
    State,
)

# Candidate id field names, in priority order.
ID_FIELD_CANDIDATES = ("id", "approval_id", "order_id", "task_id", "record_id", "_id")

# P1-B: URL field candidates for row links.
# When MCP data provides a per-row detail URL, the converter/parser uses it
# for clickable row links instead of generating a fake path.
_URL_FIELD_CANDIDATES = (
    "detail_url", "view_url", "page_url", "url", "link",
    "detail_link", "view_link", "href", "detail_href",
)


def find_url_field(item: Dict[str, Any]) -> Optional[str]:
    """Find a URL-like field in a data item that can be used for row links.

    Returns the field name if found, or ``None``.

    Strategy:
      1. Exact match against known candidate names (deterministic).
      2. Heuristic: any field whose name contains "url" / "link" / "href"
         and whose value is a string starting with http/https or /.
    """
    for field in _URL_FIELD_CANDIDATES:
        val = item.get(field)
        if val and isinstance(val, str) and (val.startswith("http") or val.startswith("/")):
            return field
    for key, value in item.items():
        k = str(key).lower()
        if ("url" in k or "link" in k or "href" in k):
            if isinstance(value, str) and (value.startswith("http") or value.startswith("/")):
                return str(key)
    return None


# Single-brace placeholder in a URL template, e.g. ``{processInstanceId}``.
_URL_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def url_template_fields(
    url_template: Any,
    params_mapping: Any,
    first_item: Dict[str, Any],
) -> List[str]:
    """Row-field names needed to fill every placeholder in ``url_template``.

    ``params_mapping`` maps *placeholder name* → *row field name* (OA servers
    declare it as ``{"processInstanceId": "processInstanceId", "id": "id"}``).
    Placeholders absent from the mapping fall back to identity (placeholder
    name == field name). Only fields that actually exist in ``first_item``
    are returned (unknown fields would leave dead ``{x}`` tokens in the URL).
    """
    if not url_template or not isinstance(url_template, str):
        return []
    mapping = params_mapping if isinstance(params_mapping, dict) else {}
    fields: List[str] = []
    for placeholder in _URL_PLACEHOLDER_RE.findall(url_template):
        field_name = str(mapping.get(placeholder, placeholder))
        if field_name and field_name in first_item and field_name not in fields:
            fields.append(field_name)
    return fields


def extract_row_link_template(metadata: Any) -> Optional[Dict[str, Any]]:
    """Pick the ``action_templates`` entry that declares a per-row URL.

    Servers are not consistent about the key: OA uses ``row_link`` for some
    tools and ``view_detail`` for others (both carry a ``url_template`` with
    row placeholders). Priority: explicit ``row_link`` → ``view_detail`` →
    any template whose ``url_template`` contains ``{placeholder}`` tokens.

    Returns the template dict with its original key injected as ``_key``,
    or ``None`` when no usable template exists.
    """
    if not isinstance(metadata, dict):
        return None
    templates = metadata.get("action_templates")
    if not isinstance(templates, dict):
        return None
    for key in (ActionTemplateTypes.ROW_LINK, ActionTemplateTypes.VIEW_DETAIL):
        template = templates.get(key)
        if isinstance(template, dict) and template.get("url_template"):
            return {"_key": key, **template}
    for key, template in templates.items():
        if isinstance(template, dict) and _URL_PLACEHOLDER_RE.search(
            str(template.get("url_template", ""))
        ):
            return {"_key": key, **template}
    return None


def unwrap_mcp_response(mcp_result: Any) -> tuple:
    """Normalise the two MCP response shapes into ``(business, metadata)``.

    Shape A — raw tool-call response (what CoApis's MCP wrapper returns)::

        {"result": "<json string>" | {...}, "is_error": false,
         "metadata": {...}}

    Shape B — canonical MCP result::

        {"content": [{"type": "text", "text": "<json>"}], "metadata": {...}}

    Returns ``(business_dict_or_None, metadata_dict_or_empty)``.  ``metadata``
    is taken from the top level of either shape; ``business`` is the parsed
    JSON payload (from ``result`` in shape A, from ``content[0].text`` in
    shape B).
    """
    metadata: Dict[str, Any] = {}
    business: Optional[Dict[str, Any]] = None
    if not isinstance(mcp_result, dict):
        return None, metadata

    meta = mcp_result.get("metadata")
    if isinstance(meta, dict):
        metadata = meta
    elif isinstance(meta, str):
        try:
            parsed = json.loads(meta)
            if isinstance(parsed, dict):
                metadata = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    if "result" in mcp_result:
        result = mcp_result["result"]
        if isinstance(result, dict):
            business = result
        elif isinstance(result, str):
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    business = parsed
                elif isinstance(parsed, list):
                    # Top-level JSON array payload (e.g. OA mock returns a bare row list).
                    # Wrap so _find_data_list can locate it under the known "data" key.
                    business = {"data": parsed}
            except (json.JSONDecodeError, TypeError):
                pass
    for item in mcp_result.get("content", []) or []:
        if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
            try:
                parsed = json.loads(item["text"])
                if isinstance(parsed, dict):
                    business = parsed
                elif isinstance(parsed, list):
                    # Top-level JSON array payload (same as shape A). Wrap for _find_data_list.
                    business = {"data": parsed}
                else:
                    continue
                break
            except (json.JSONDecodeError, TypeError):
                continue
    return business, metadata


# ============================================================================
# Standard Action Template Types (standardized action_templates keys)
# ============================================================================
class ActionTemplateTypes:
    """Standardized action_templates type definitions.

    MCP tools use these keys in ``metadata.action_templates`` to declare
    available actions.
    """
    # Single record detail view (for single-record data or card-level actions)
    VIEW_DETAIL = "view_detail"
    # Row-level hyperlink in data table (click row to open detail)
    ROW_LINK = "row_link"
    # Export current list to file (Excel/CSV)
    EXPORT_LIST = "export_list"
    # Open full list page in external system
    MORE = "more"


class ActionTemplateValidator:
    """Validates and normalizes action_templates to standard format."""

    @staticmethod
    def normalize(template_data: Dict[str, Any], template_type: str) -> Dict[str, Any]:
        """Normalize action template data to standard format based on template_type."""
        normalized = dict(template_data)
        normalized.setdefault("type", template_type)
        normalized.setdefault("label", ActionTemplateValidator._default_label(template_type))
        return normalized

    @staticmethod
    def _default_label(template_type: str) -> str:
        """Return default label for standard template types."""
        defaults = {
            ActionTemplateTypes.VIEW_DETAIL: "查看详情",
            ActionTemplateTypes.ROW_LINK: "查看详情",
            ActionTemplateTypes.EXPORT_LIST: "导出列表",
            ActionTemplateTypes.MORE: "更多",
        }
        return defaults.get(template_type, "操作")


class MCPC2AParser:
    """MCP Tool Return Parser for C2A Message Generation."""

    # ------------------------------------------------------------------
    # Inference helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _find_list(business_data: Dict[str, Any]) -> Optional[tuple]:
        """Find the first (key, list-of-dicts) in business data."""
        for key, value in business_data.items():
            if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                return key, value
        return None

    @staticmethod
    def _find_id_field(first_item: Dict[str, Any]) -> Optional[str]:
        # 1) Exact high-priority candidates (deterministic, stable order).
        for field_name in ID_FIELD_CANDIDATES:
            if field_name in first_item:
                return field_name
        # 2) Heuristic fallback: a field literally named "id" or ending in "_id"
        #    (covers user_id / doc_id / product_id etc. that MCP outputs commonly
        #    use). Without this, auto-converted data lists get no row links.
        for key in first_item.keys():
            k = str(key).lower()
            if k == "id" or k.endswith("_id"):
                return str(key)
        return None

    @staticmethod
    def _infer_link_column(headers: List[str]) -> Optional[str]:
        """Pick the header to render as an inline hyperlink.

        1) First header whose name matches a "name/title" pattern
           (名称/标题/title/subject/summary/name, case-insensitive).
        2) Otherwise the first column (fallback).
        """
        patterns = ("名称", "标题", "title", "subject", "summary", "name")
        for header in headers:
            h = str(header).lower()
            if any(p in h for p in patterns):
                return str(header)
        return str(headers[0]) if headers else None

    @staticmethod
    def _infer_default_action_templates(
        business_data: Dict[str, Any], base_url: str = ""
    ) -> Dict[str, Any]:
        """Infer default action templates from business data structure.

        Used when ``metadata.action_templates`` is missing.

        - multi-record list  → row_link + export_list + more
        - single-record list → view_detail
        """
        inferred: Dict[str, Any] = {}
        found = MCPC2AParser._find_list(business_data)
        if not found:
            return inferred
        list_key, list_items = found
        first_item = list_items[0]
        id_field = MCPC2AParser._find_id_field(first_item)

        if len(list_items) > 1:
            # Multi-record list: row links (NOT view_detail — that's single-record).
            # P1-B: only add row_link when the data actually has a URL field;
            # a fake /{list_key}/{id} path is worse than no link at all.
            url_field = find_url_field(first_item)
            if id_field and url_field:
                inferred["row_link"] = {
                    "type": ActionTemplateTypes.ROW_LINK,
                    "label": "查看详情",
                    "url_template": f"{{{url_field}}}",
                    "business_intent": "view_detail",
                    "link_column": str(url_field),
                }
            inferred["export_list"] = {
                "type": ActionTemplateTypes.EXPORT_LIST,
                "label": "导出列表为Excel",
                "api_endpoint": f"/api/v1/{list_key}/export",
                "business_intent": "export_list_to_excel",
            }
            inferred["more"] = {
                "type": ActionTemplateTypes.MORE,
                "label": "查看更多",
                "url_template": (base_url.rstrip("/") if base_url else "") + f"/{list_key}?page=1",
                "business_intent": "open_full_list",
                "context_data": {},
            }
        elif len(list_items) == 1:
            # P1-B: single record — only add view_detail with a real URL.
            url_field = find_url_field(first_item)
            if id_field and url_field:
                inferred["view_detail"] = {
                    "type": ActionTemplateTypes.VIEW_DETAIL,
                    "label": "查看详情",
                    "url_template": f"{{{url_field}}}",
                    "business_intent": "view_detail",
                }
        return inferred

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @staticmethod
    def parse_mcp_return(mcp_result: Dict[str, Any]) -> Dict[str, Any]:
        """Parse an MCP tool return and extract business data + action templates.

        Args:
            mcp_result: MCP tool return dict with 'content', optional 'metadata'.

        Returns:
            ``{'business_data', 'resource_type', 'external_system', 'action_templates'}``
        """
        parsed: Dict[str, Any] = {
            "business_data": None,
            "resource_type": None,
            "external_system": None,
            "action_templates": {},
            "summary": None,
            "buttons": [],
        }

        # Extract business data. Two shapes are accepted:
        #  * canonical MCP result: content[0].text (JSON)
        #  * CoApis wrapper response: {"result": "<json>" | {...}, ...}
        #    (the LLM often forwards the whole wrapper dict as tool_output)
        business, _ = unwrap_mcp_response(mcp_result)
        if business is not None:
            parsed["business_data"] = business

        # Extract metadata (may be absent entirely).
        metadata = mcp_result.get("metadata", {}) or {}
        parsed["resource_type"] = metadata.get("resource_type")
        parsed["external_system"] = metadata.get("external_system")
        parsed["summary"] = metadata.get("summary")
        # Buttons: pure navigation (label + url + scope). Only keep dict entries
        # that have a non-empty url_template (a button without a URL is not
        # renderable — the AI does not execute business logic).
        buttons_raw = metadata.get("buttons", [])
        if isinstance(buttons_raw, list):
            parsed["buttons"] = [
                b for b in buttons_raw
                if isinstance(b, dict) and b.get("url_template")
            ]
        base_url = metadata.get("base_url", "")
        action_templates = metadata.get("action_templates", {})

        if action_templates:
            parsed["action_templates"] = {
                key: ActionTemplateValidator.normalize(
                    template, template.get("type", key)
                )
                for key, template in action_templates.items()
                if isinstance(template, dict)
            }
        elif parsed["business_data"]:
            # Fault tolerance: infer from data structure whenever explicit
            # templates are missing — regardless of whether metadata exists.
            parsed["action_templates"] = MCPC2AParser._infer_default_action_templates(
                parsed["business_data"], base_url
            )

        return parsed

    @staticmethod
    def generate_c2a_message_from_mcp(
        mcp_result: Dict[str, Any],
        message_id: str,
        session_id: str,
    ) -> C2AMessage:
        """Generate a C2AMessage from an MCP tool return.

        Args:
            mcp_result: MCP tool return dictionary.
            message_id: Unique message identifier.
            session_id: Session ID for context reference.

        Returns:
            A C2AMessage (protocol_version == PROTOCOL_VERSION).
        """
        parsed = MCPC2AParser.parse_mcp_return(mcp_result)
        business_data = parsed.get("business_data")
        action_templates = parsed.get("action_templates", {}) or {}

        # Build buttons from metadata (pure navigation: label + url + scope).
        buttons_list: Optional[List[Button]] = None
        raw_buttons = parsed.get("buttons", [])
        if raw_buttons:
            buttons_list = [
                Button(
                    id=b.get("id", f"btn_{i}"),
                    label=b.get("label", "操作"),
                    scope=b.get("scope", "card"),
                    url_template=b.get("url_template", ""),
                    style=b.get("style", "secondary"),
                )
                for i, b in enumerate(raw_buttons)
            ]

        msg = C2AMessage(
            protocol_version=PROTOCOL_VERSION,
            message_id=message_id,
            context_ref=ContextRef(
                session_id=session_id,
                scene_id=parsed.get("resource_type") or "default_scene",
            ),
            metadata=Metadata(
                generated_by="mcp-tool-parser",
                source_system=parsed.get("external_system") or "mcp-system",
                summary=parsed.get("summary"),
                buttons=buttons_list,
            ),
            state=State(status="rendered"),
        )

        found = MCPC2AParser._find_list(business_data) if isinstance(business_data, dict) else None
        list_key, list_items = (found if found else (None, []))

        if list_items and list_key:
            msg.blocks.append(
                MCPC2AParser._build_data_table_block(message_id, list_key, list_items, action_templates)
            )

        msg.suggestions.extend(
            MCPC2AParser._build_suggestions(list_key, list_items, action_templates)
        )
        return msg

    # ------------------------------------------------------------------
    # Block / suggestion builders
    # ------------------------------------------------------------------
    @staticmethod
    def _build_data_table_block(
        message_id: str,
        list_key: str,
        list_items: List[Dict[str, Any]],
        action_templates: Dict[str, Any],
    ) -> Block:
        first_item = list_items[0]
        id_field = MCPC2AParser._find_id_field(first_item)

        # Display headers: hide internal id fields for a clean table
        if id_field:
            headers = [
                str(k) for k in first_item.keys()
                if k != id_field and not str(k).startswith("_")
            ]
            if not headers:
                headers = [str(k) for k in first_item.keys()]
        else:
            headers = [str(k) for k in first_item.keys() if not str(k).startswith("_")]

        rows = [[str(item.get(h, "")) for h in headers] for item in list_items]

        table_content: Dict[str, Any] = {"data": {"headers": headers, "rows": rows}}

        # Row-link plumbing: the id column is hidden from the table, so the
        # renderer needs row_values to fill url_template placeholders.
        # Beyond the id field, a template's {placeholders} (mapped via
        # params_mapping) may reference other hidden fields (e.g.
        # processInstanceId) — include them too so every row builds a full URL.
        link_fields: List[str] = []
        for template in action_templates.values():
            if not isinstance(template, dict):
                continue
            ttype = template.get("type", "")
            if ttype in (
                ActionTemplateTypes.ROW_LINK,
                ActionTemplateTypes.VIEW_DETAIL,
            ) and template.get("url_template"):
                link_fields = url_template_fields(
                    template.get("url_template"),
                    template.get("params_mapping"),
                    first_item,
                )
                break
        rv_fields: List[str] = []
        if id_field and id_field not in link_fields:
            rv_fields.append(id_field)
        rv_fields.extend(link_fields)
        if id_field:
            table_content["id_field"] = id_field
        if rv_fields:
            table_content["row_values"] = [
                {f: item.get(f, "") for f in rv_fields} for item in list_items
            ]

        # Row actions (row_link = clickable rows, view_detail = button under table)
        row_actions: Dict[str, Any] = {}
        for template_key, template in action_templates.items():
            template_type = template.get("type", template_key)
            if template_type in (ActionTemplateTypes.ROW_LINK, ActionTemplateTypes.VIEW_DETAIL):
                entry: Dict[str, Any] = {
                    "action_id": f"btn_{template_key}",
                    "label": template.get("label", "查看详情"),
                    "style": "link" if template_type == ActionTemplateTypes.ROW_LINK else "button",
                    "business_intent": template.get("business_intent", template_key),
                    "url_template": template.get("url_template"),
                }
                # Inline link column for row_link: explicit declaration wins,
                # otherwise infer from headers (name/title pattern → first col).
                if template_type == ActionTemplateTypes.ROW_LINK:
                    link_column = template.get("link_column") or MCPC2AParser._infer_link_column(headers)
                    if link_column:
                        entry["link_column"] = link_column
                row_actions[template_key] = entry
        if row_actions:
            table_content["row_actions"] = row_actions

        return Block(
            block_id=f"block_table_{message_id}",
            type="data_table",
            content=BlockContent(data=table_content),
        )

    @staticmethod
    def _build_suggestions(
        list_key: Optional[str],
        list_items: List[Dict[str, Any]],
        action_templates: Dict[str, Any],
    ) -> List[Suggestion]:
        suggestions: List[Suggestion] = []
        for template_key, template in action_templates.items():
            template_type = template.get("type", template_key)
            if template_type == ActionTemplateTypes.VIEW_DETAIL and len(list_items) == 1:
                first_item = list_items[0]
                id_field = MCPC2AParser._find_id_field(first_item)
                display = str(first_item.get(id_field, list_key)) if id_field else str(first_item)
                suggestions.append(Suggestion(
                    suggestion_id=f"sug_view_detail_{list_key}_01",
                    label=f"👁️ 查看 {display} 详情",
                    business_intent=template.get("business_intent", "view_detail"),
                    context_data=(
                        {id_field: first_item.get(id_field)} if id_field else {}
                    ),
                ))
            elif template_type == ActionTemplateTypes.EXPORT_LIST:
                suggestions.append(Suggestion(
                    suggestion_id="sug_export_list",
                    label=template.get("label", "📤 导出当前列表为Excel"),
                    business_intent=template.get("business_intent", "export_list_to_excel"),
                    context_data={"api_endpoint": template.get("api_endpoint")},
                ))
            elif template_type == ActionTemplateTypes.MORE:
                suggestions.append(Suggestion(
                    suggestion_id="sug_more",
                    label=template.get("label", "📋 查看更多"),
                    business_intent=template.get("business_intent", "open_full_list"),
                    context_data={
                        "url_template": template.get("url_template"),
                        **template.get("context_data", {}),
                    },
                ))
        return suggestions
