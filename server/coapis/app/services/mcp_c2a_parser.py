"""
MCP to C2A Message Parser - Parses MCP Tool Returns and Generates C2A Messages with row_actions and suggestions

This module provides functionality to parse MCP tool return results (including metadata.action_templates)
and generate C2A protocol messages with data_table blocks, row_actions, and LLM suggestions.
"""

import json
from typing import Dict, Any, List, Optional


class MCPC2AParser:
    """MCP Tool Return Parser for C2A Message Generation"""
    
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
            
            # Extract action_templates
            action_templates = metadata.get('action_templates', {})
            if action_templates:
                parsed_result['action_templates'] = action_templates
                
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
        
        # Generate data_table block if business_data is a list/dict with items
        if business_data and isinstance(business_data, dict) and 'orders' in business_data:
            orders = business_data.get('orders', [])
            
            # Extract headers from first order's keys
            headers = ['订单号', '金额', '状态']
            rows = []
            for order in orders:
                row = [
                    str(order.get('order_id', '')),
                    str(order.get('amount', '')),
                    str(order.get('status', ''))
                ]
                rows.append(row)
            
            # Build data_table block content with row_actions
            table_content = {
                'data': {
                    'headers': headers,
                    'rows': rows
                }
            }
            
            # Add row_actions from action_templates
            if 'view_detail' in action_templates:
                view_detail_template = action_templates['view_detail']
                table_content['row_actions'] = {
                    'view_detail_action': {
                        'action_id': 'btn_view_detail',
                        'label': view_detail_template.get('label', '查看详情'),
                        'style': 'link',
                        'business_intent': 'view_order_detail',
                        'url_template': view_detail_template.get('url_template'),
                        'params_mapping': view_detail_template.get('params_mapping', {})
                    }
                }
            
            c2a_message['blocks'].append({
                'block_id': f'block_table_{message_id}',
                'type': 'data_table',
                'content': table_content
            })
        
        # Generate suggestions from action_templates
        for template_key, template_data in action_templates.items():
            if template_key == 'view_detail':
                # For view_detail, generate suggestion for first item if available
                if business_data and isinstance(business_data, dict) and 'orders' in business_data:
                    orders = business_data.get('orders', [])
                    if orders and len(orders) > 0:
                        first_order = orders[0]
                        c2a_message['suggestions'].append({
                            'suggestion_id': f'sug_view_detail_{first_order.get("order_id", "ord_001")}',
                            'label': f"👁️ 查看 {first_order.get('order_id', 'ORD-001')} 详情",
                            'business_intent': 'view_order_detail',
                            'context_data': {'order_id': first_order.get('order_id')}
                        })
            elif template_key == 'export_list':
                c2a_message['suggestions'].append({
                    'suggestion_id': 'sug_export_list',
                    'label': "📤 导出当前列表为Excel",
                    'business_intent': 'export_list_to_excel'
                })
                
        return c2a_message
