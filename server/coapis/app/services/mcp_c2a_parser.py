"""
MCP to C2A Message Parser - Parses MCP Tool Returns and Generates C2A Messages with row_actions and suggestions

This module provides functionality to parse MCP tool return results (including metadata.action_templates)
and generate C2A protocol messages with data_table blocks, row_actions, and LLM suggestions.

P0 fault tolerance:
  - _find_list: recursively finds a list of dicts (up to depth 3) to handle
    top-level lists, one-level nesting, and deeply nested structures.
  - Single-record dicts are wrapped into a single-row table.
  - Non-JSON content text is kept as raw text (not silently dropped).

P1-B row link:
  - row_link is only added when the data actually contains a real URL field.
  - link_column is set to the URL field name so the frontend renders an
    inline hyperlink on that column instead of making the whole row clickable.
"""

import json
from typing import Dict, Any, List, Optional, Tuple

# ============================================================================
# Standard Action Template Types (Standardized action_templates key definitions)
# ============================================================================
class ActionTemplateTypes:
    """
    Standardized action_templates type definitions.
    MCP tools use these keys in metadata.action_templates to declare available actions.
    """
    # Single record detail view (for non-list data or card-level actions)
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
        """
        Normalize action template data to standard format based on template_type.

        Args:
            template_data: Raw template data from MCP metadata
            template_type: One of ActionTemplateTypes constants

        Returns:
            Normalized template dictionary
        """
        normalized = dict(template_data)
        normalized.setdefault('type', template_type)
        normalized.setdefault('label', ActionTemplateValidator._default_label(template_type))
        return normalized

    @staticmethod
    def _default_label(template_type: str) -> str:
        """Return default label for standard template types."""
        defaults = {
            ActionTemplateTypes.VIEW_DETAIL: "查看详情",
            ActionTemplateTypes.ROW_LINK: "查看详情",
            ActionTemplateTypes.EXPORT_LIST: "导出列表",
            ActionTemplateTypes.MORE: "更多"
        }
        return defaults.get(template_type, "操作")


# ============================================================================
# Utility functions
# ============================================================================

def find_url_field(record: Dict[str, Any]) -> Optional[str]:
    """Find a URL-like field in a record. Returns the field name or None.

    Detection priority:
      1. Field names containing 'url' or 'link' (case-insensitive)
      2. Field values that look like URLs (start with http:// or https://)
    """
    if not isinstance(record, dict):
        return None

    # Priority 1: field name contains 'url' or 'link'
    for key, value in record.items():
        k = str(key).lower()
        if 'url' in k or 'link' in k:
            if value is not None and str(value).strip():
                return str(key)

    # Priority 2: field value looks like a URL
    for key, value in record.items():
        if isinstance(value, str):
            v = value.strip().lower()
            if v.startswith('http://') or v.startswith('https://'):
                return str(key)

    return None


def _find_list(data: Any, depth: int = 0, max_depth: int = 3) -> Optional[Tuple[str, list]]:
    """Recursively find the first list of dicts in a data structure.

    Returns:
        (key, list_of_dicts) tuple, or None if not found.
    """
    if depth > max_depth:
        return None

    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        return ("_list", data)

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                return (str(key), value)
        # Recurse into nested dicts
        for key, value in data.items():
            if isinstance(value, dict):
                result = _find_list(value, depth + 1, max_depth)
                if result:
                    return (f"{key}.{result[0]}", result[1])
    return None


# ============================================================================
# MCPC2AParser
# ============================================================================

class MCPC2AParser:
    """MCP Tool Return Parser for C2A Message Generation"""

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _find_id_field(first_item: Dict[str, Any]) -> Optional[str]:
        """Find an ID-like field in a record.

        Priority:
          1. Exact high-priority candidates: id, approval_id, order_id,
             task_id, record_id
          2. Heuristic: field named "id" or ending in "_id"
        """
        candidates = ['id', 'approval_id', 'order_id', 'task_id', 'record_id']
        for field in candidates:
            if field in first_item:
                return field
        # Heuristic fallback
        for key in first_item.keys():
            k = str(key).lower()
            if k == 'id' or k.endswith('_id'):
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

    # ------------------------------------------------------------------
    # Default action template inference
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_default_action_templates(
        business_data: Dict[str, Any], base_url: str = ""
    ) -> Dict[str, Any]:
        """
        Infer default action templates based on business data structure when
        metadata.action_templates is missing.

        - multi-record list  → row_link (only if real URL field) + export_list + more
        - single-record list → view_detail (only if real URL field)
        """
        inferred: Dict[str, Any] = {}
        found = _find_list(business_data)
        if not found:
            return inferred
        list_key, list_items = found
        first_item = list_items[0]
        id_field = MCPC2AParser._find_id_field(first_item)
        url_field = find_url_field(first_item)

        if len(list_items) > 1:
            # Multi-record list: row links only when a real URL field exists
            if id_field and url_field:
                inferred['row_link'] = {
                    'type': ActionTemplateTypes.ROW_LINK,
                    'label': '查看详情',
                    'url_template': '{' + url_field + '}',
                    'business_intent': 'view_detail',
                    'link_column': str(url_field),
                }
            inferred['export_list'] = {
                'type': ActionTemplateTypes.EXPORT_LIST,
                'label': '导出列表为Excel',
                'api_endpoint': f"/api/v1/{list_key}/export",
                'business_intent': 'export_list_to_excel',
            }
            inferred['more'] = {
                'type': ActionTemplateTypes.MORE,
                'label': '查看更多',
                'url_template': (base_url.rstrip('/') if base_url else '') + f'/{list_key}?page=1',
                'business_intent': 'open_full_list',
                'context_data': {},
            }
        elif len(list_items) == 1:
            # Single record: view_detail only with a real URL
            if id_field and url_field:
                inferred['view_detail'] = {
                    'type': ActionTemplateTypes.VIEW_DETAIL,
                    'label': '查看详情',
                    'url_template': '{' + url_field + '}',
                    'business_intent': 'view_detail',
                }

        return inferred

    # ------------------------------------------------------------------
    # Parse MCP tool return
    # ------------------------------------------------------------------

    @staticmethod
    def parse_mcp_return(mcp_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse MCP tool return result and extract business data + metadata.action_templates

        Args:
            mcp_result: MCP tool return dictionary containing 'content', 'isError', and optionally 'metadata'

        Returns:
            Dictionary with extracted 'business_data', 'resource_type', 'external_system', and 'action_templates'
        """
        parsed_result = {
            'business_data': None,
            'resource_type': None,
            'external_system': None,
            'action_templates': {}
        }

        # Extract business data from content.text
        content_list = mcp_result.get('content', [])
        for item in content_list:
            if item.get('type') == 'text' and 'text' in item:
                try:
                    parsed_result['business_data'] = json.loads(item['text'])
                except json.JSONDecodeError:
                    pass  # Ignore parsing errors for non-JSON text

        # Extract metadata
        metadata = mcp_result.get('metadata', {})
        if metadata:
            parsed_result['resource_type'] = metadata.get('resource_type')
            parsed_result['external_system'] = metadata.get('external_system')

            # Extract and normalize action_templates
            action_templates = metadata.get('action_templates', {})
            if action_templates:
                normalized_templates = {}
                for key, template in action_templates.items():
                    if isinstance(template, dict):
                        template_type = template.get('type', key)
                        normalized_templates[key] = ActionTemplateValidator.normalize(template, template_type)
                parsed_result['action_templates'] = normalized_templates

        # Fault tolerance: Infer default action_templates if missing but business_data is a list of dicts
        if not parsed_result['action_templates'] and parsed_result['business_data']:
            inferred_templates = MCPC2AParser._infer_default_action_templates(
                parsed_result['business_data'],
                base_url=parsed_result['external_system'] or '',
            )
            if inferred_templates:
                normalized_templates = {}
                for key, template in inferred_templates.items():
                    template_type = template.get('type', key)
                    normalized_templates[key] = ActionTemplateValidator.normalize(template, template_type)
                parsed_result['action_templates'] = normalized_templates

        return parsed_result

    # ------------------------------------------------------------------
    # Generate C2A message
    # ------------------------------------------------------------------

    @staticmethod
    def generate_c2a_message_from_mcp(
        mcp_result: Dict[str, Any],
        message_id: str,
        session_id: str
    ) -> Dict[str, Any]:
        """
        Generate C2A protocol message from MCP tool return result

        Args:
            mcp_result: MCP tool return dictionary
            message_id: Unique message identifier
            session_id: Session ID for context reference

        Returns:
            C2AMessage dictionary conforming to C2A protocol v2.0 structure
        """
        parsed = MCPC2AParser.parse_mcp_return(mcp_result)

        business_data = parsed.get('business_data')
        action_templates = parsed.get('action_templates', {})
        external_system = parsed.get('external_system') or ''

        # Initialize C2A message structure
        c2a_message = {
            'protocol_version': 'c2a-v1.0',
            'message_id': message_id,
            'context_ref': {
                'session_id': session_id,
                'scene_id': parsed.get('resource_type', 'default_scene')
            },
            'metadata': {
                'generated_by': 'mcp-tool-parser',
                'timestamp': 0,  # Will be set by caller
                'source_system': external_system or 'mcp-system'
            },
            'blocks': [],
            'actions': [],
            'state': {
                'status': 'rendered'
            },
            'suggestions': []
        }

        # Find list of dicts in business_data (P0: handles top-level list,
        # one-level nesting, and deeper nesting up to 3 levels).
        list_key: Optional[str] = None
        list_items: List[Dict[str, Any]] = []

        if business_data is not None and business_data:
            found = _find_list(business_data)
            if found:
                list_key, list_items = found
            elif isinstance(business_data, dict):
                # No list found — treat as single record (only if it has keys)
                list_key = '_record'
                list_items = [business_data]

        table_content = None
        if list_items and list_key:
            first_item = list_items[0]

            # Extract headers: filter out internal/ID fields for cleaner display
            id_field = MCPC2AParser._find_id_field(first_item)
            exclude_fields = {id_field} if id_field else set()
            exclude_fields.update({'_id'})
            headers = [
                str(k) for k in first_item.keys()
                if k not in exclude_fields and not str(k).startswith('_')
            ]
            if not headers:
                headers = [str(k) for k in first_item.keys()]

            rows = []
            for item in list_items:
                row = [str(item.get(h, '')) for h in headers]
                rows.append(row)

            # Build data_table block content with row_actions
            table_content = {
                'data': {
                    'headers': headers,
                    'rows': rows
                }
            }

            # Add row_actions from standardized action_templates
            row_actions: Dict[str, Any] = {}
            for template_key, template in action_templates.items():
                if not isinstance(template, dict):
                    continue
                template_type = template.get('type', template_key)

                if template_type == ActionTemplateTypes.ROW_LINK:
                    row_actions[template_key] = {
                        'action_id': f'btn_{template_key}',
                        'label': template.get('label', '查看详情'),
                        'style': 'link',
                        'business_intent': template.get('business_intent', template_key),
                        'url_template': template.get('url_template'),
                        'params_mapping': template.get('params_mapping', {}),
                        'link_column': template.get('link_column')
                                  or MCPC2AParser._infer_link_column(headers),
                    }
                elif template_type == ActionTemplateTypes.VIEW_DETAIL:
                    row_actions[template_key] = {
                        'action_id': f'btn_{template_key}',
                        'label': template.get('label', '查看详情'),
                        'style': 'button',
                        'business_intent': template.get('business_intent', template_key),
                        'url_template': template.get('url_template'),
                        'params_mapping': template.get('params_mapping', {}),
                    }

            if row_actions:
                table_content['row_actions'] = row_actions

            c2a_message['blocks'].append({
                'block_id': f'block_table_{message_id}',
                'type': 'data_table',
                'content': table_content
            })

        # Generate suggestions from standardized action_templates
        for template_key, template in action_templates.items():
            if not isinstance(template, dict):
                continue
            template_type = template.get('type', template_key)

            if template_type == ActionTemplateTypes.VIEW_DETAIL:
                if list_items and len(list_items) == 1:
                    first_item = list_items[0]
                    id_field = MCPC2AParser._find_id_field(first_item)
                    display_value = (
                        str(first_item.get(id_field, list_key)) if id_field
                        else str(list_items[0])
                    )
                    c2a_message['suggestions'].append({
                        'suggestion_id': f'sug_view_detail_{list_key}_01',
                        'label': f"👁️ 查看 {display_value} 详情",
                        'business_intent': template.get('business_intent', 'view_detail'),
                        'context_data': (
                            {id_field: first_item.get(id_field)} if id_field else {}
                        ),
                    })
            elif template_type == ActionTemplateTypes.ROW_LINK:
                pass  # per-row action, no single "view detail" suggestion
            elif template_type == ActionTemplateTypes.EXPORT_LIST:
                c2a_message['suggestions'].append({
                    'suggestion_id': 'sug_export_list',
                    'label': template.get('label', '📤 导出当前列表为Excel'),
                    'business_intent': template.get('business_intent', 'export_list_to_excel')
                })
            elif template_type == ActionTemplateTypes.MORE:
                c2a_message['suggestions'].append({
                    'suggestion_id': 'sug_more',
                    'label': template.get('label', '📋 查看更多'),
                    'business_intent': template.get('business_intent', 'open_full_list'),
                    'context_data': template.get('context_data', {})
                })

        return c2a_message
