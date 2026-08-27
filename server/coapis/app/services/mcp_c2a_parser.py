"""
MCP to C2A Message Parser - Parses MCP Tool Returns and Generates C2A Messages with row_actions and suggestions

This module provides functionality to parse MCP tool return results (including metadata.action_templates)
and generate C2A protocol messages with data_table blocks, row_actions, and LLM suggestions.
"""

import json
from typing import Dict, Any, List, Optional


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


class MCPC2AParser:
    """MCP Tool Return Parser for C2A Message Generation"""
    
    @staticmethod
    def _infer_default_action_templates(business_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Infer default action templates based on business data structure when metadata.action_templates is missing.
        
        Args:
            business_data: The parsed business data from MCP tool
            
        Returns:
            Dictionary of inferred action_templates
        """
        inferred_templates = {}
        
        # Check if business_data contains a list of items (e.g., 'orders', 'approvals', etc.)
        list_key = None
        list_items = []
        for key, value in business_data.items():
            if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                list_key = key
                list_items = value
                break
        
        if not list_items:
            return inferred_templates
        
        # Check if there's an ID field in the first item
        first_item = list_items[0]
        id_field = None
        for field in ['id', 'approval_id', 'order_id', 'task_id', 'record_id']:
            if field in first_item:
                id_field = field
                break
        
        # If it's a list data, infer row_link and more templates, but NOT view_detail (since it's multiple records)
        if list_items and len(list_items) > 1:
            # For multi-record lists, do not generate view_detail (single record detail)
            # Generate row_link if id_field exists
            if id_field:
                inferred_templates['row_link'] = {
                    'type': ActionTemplateTypes.ROW_LINK,
                    'label': '查看详情',
                    'url_template': f"https://oa.example.com/{{{list_key}}}/{{{id_field}}}",
                    'params_mapping': {id_field: id_field},
                    'business_intent': 'view_detail'
                }
            
            # Generate export_list
            inferred_templates['export_list'] = {
                'type': ActionTemplateTypes.EXPORT_LIST,
                'label': '导出列表为Excel',
                'api_endpoint': f"/api/v1/{list_key}/export",
                'business_intent': 'export_list_to_excel'
            }
            
            # Generate more (open full list page)
            inferred_templates['more'] = {
                'type': ActionTemplateTypes.MORE,
                'label': '查看更多',
                'url_template': f"https://oa.example.com/{list_key}?page=1",
                'business_intent': 'open_full_list',
                'context_data': {}
            }
        elif list_items and len(list_items) == 1:
            # For single record, generate view_detail
            if id_field:
                inferred_templates['view_detail'] = {
                    'type': ActionTemplateTypes.VIEW_DETAIL,
                    'label': '查看详情',
                    'url_template': f"https://oa.example.com/{list_key}/{{{id_field}}}",
                    'params_mapping': {id_field: id_field},
                    'business_intent': 'view_detail'
                }
        
        return inferred_templates

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
                    template_type = template.get('type', key)
                    normalized_templates[key] = ActionTemplateValidator.normalize(template, template_type)
                parsed_result['action_templates'] = normalized_templates
        
        # Fault tolerance: Infer default action_templates if missing but business_data is a list of dicts
        if not parsed_result['action_templates'] and parsed_result['business_data']:
            inferred_templates = MCPC2AParser._infer_default_action_templates(parsed_result['business_data'])
            if inferred_templates:
                normalized_templates = {}
                for key, template in inferred_templates.items():
                    template_type = template.get('type', key)
                    normalized_templates[key] = ActionTemplateValidator.normalize(template, template_type)
                parsed_result['action_templates'] = normalized_templates
                
        return parsed_result

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
                'source_system': parsed.get('external_system', 'mcp-system')
            },
            'blocks': [],
            'actions': [],
            'state': {
                'status': 'rendered'
            },
            'suggestions': []
        }
        
        # Generate data_table block if business_data is a list/dict with items (generic handling for any list key like 'orders', 'approvals', etc.)
        list_key = None
        list_items = []
        if business_data and isinstance(business_data, dict):
            for key, value in business_data.items():
                if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                    list_key = key
                    list_items = value
                    break
        
        table_content = None
        if list_items and list_key:
            # Extract headers from first item's keys (filter out internal/ID fields for cleaner display)
            first_item = list_items[0]
            # Common non-ID fields to include as headers
            exclude_fields = {'id', 'approval_id', 'order_id', 'task_id', 'record_id', '_id'}
            headers = [str(k) for k in first_item.keys() if k not in exclude_fields and not str(k).startswith('_')]
            if not headers:
                # Fallback to all keys if no non-ID fields found
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
            row_actions = {}
            for template_key, template in action_templates.items():
                template_type = template.get('type', template_key)
                
                # ROW_LINK: row-level hyperlink (style='link' makes cells clickable)
                if template_type == ActionTemplateTypes.ROW_LINK:
                    row_actions[template_key] = {
                        'action_id': f'btn_{template_key}',
                        'label': template.get('label', '查看详情'),
                        'style': 'link',
                        'business_intent': template.get('business_intent', template_key),
                        'url_template': template.get('url_template'),
                        'params_mapping': template.get('params_mapping', {})
                    }
                # VIEW_DETAIL: row-level action button below table
                elif template_type == ActionTemplateTypes.VIEW_DETAIL:
                    row_actions[template_key] = {
                        'action_id': f'btn_{template_key}',
                        'label': template.get('label', '查看详情'),
                        'style': 'button',
                        'business_intent': template.get('business_intent', template_key),
                        'url_template': template.get('url_template'),
                        'params_mapping': template.get('params_mapping', {})
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
            template_type = template.get('type', template_key)
            
            if template_type == ActionTemplateTypes.VIEW_DETAIL:
                # For view_detail, generate suggestion for first item if available (only for single-item lists)
                if list_items and len(list_items) == 1:
                    first_item = list_items[0]
                    # Find the ID field to use in suggestion
                    id_field = None
                    for field in ['id', 'approval_id', 'order_id', 'task_id', 'record_id']:
                        if field in first_item:
                            id_field = field
                            break
                    
                    display_value = str(first_item.get(id_field, list_key)) if id_field else str(list_items[0])
                    c2a_message['suggestions'].append({
                        'suggestion_id': f'sug_view_detail_{list_key}_01',
                        'label': f"👁️ 查看 {display_value} 详情",
                        'business_intent': template.get('business_intent', 'view_detail'),
                        'context_data': {id_field: first_item.get(id_field) if id_field else None} if id_field else {}
                    })
            elif template_type == ActionTemplateTypes.ROW_LINK:
                # For row_link, do not generate a single "view detail" suggestion for the list, 
                # as it's meant for per-row actions in the data_table
                pass
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
