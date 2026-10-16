"""
C2A (Chat-to-Action) Interactive Message Protocol - Slack Block Kit Adapter

This module provides the adapter to transform C2A messages into Slack Block Kit format.
"""

import json
from typing import Dict, Any, List
from c2a_protocol.models import C2AMessage, Block, Action


class SlackBlockKitAdapter:
    """Adapter for transforming C2A messages to Slack Block Kit format."""
    
    @staticmethod
    def transform(c2a_msg: C2AMessage) -> Dict[str, Any]:
        """Transform a C2AMessage to Slack Block Kit JSON structure."""
        
        blocks = []
        
        # Process blocks into Slack sections
        for block in c2a_msg.blocks:
            if block.type == "text_markdown":
                markdown_content = block.content.get("markdown", "")
                # Convert markdown headings to bold text for Slack mrkdwn
                slack_text = markdown_content.replace('# ', '*').replace('\n', '\n')
                
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": slack_text
                    }
                })
            elif block.type == "data_table":
                # For data tables, we can create a section with summary text
                table_summary = f"📊 数据表格已生成 (共 {len(block.content.get('rows', []))} 行记录)"
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{table_summary}*\n请查看聊天界面中的表格数据。"
                    }
                })
        
        # Process actions into Slack actions block
        if c2a_msg.actions:
            elements = []
            for action in c2a_msg.actions[:5]: # Slack supports up to 5 buttons in an actions block
                # Map style to Slack button style
                slack_style = "primary" if action.style in ["primary", "success"] else ("danger" if action.style == "danger" else "default")
                
                # Build callback URL with action parameters
                callback_url = f"https://your-backend.com/c2a/callback/slack?action={action.action_id}&intent={action.intent}"
                
                elements.append({
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": action.label,
                        "emoji": True
                    },
                    "style": slack_style,
                    "value": action.action_id,
                    "url": callback_url
                })
            
            if elements:
                blocks.append({
                    "type": "actions",
                    "elements": elements
                })
        
        # Build the Slack Message structure
        slack_message = {
            "text": c2a_msg.metadata.generated_by or "C2A Interactive Message",
            "blocks": blocks if blocks else [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*C2A Interactive Message*\n请查看聊天界面中的交互内容。"
                    }
                }
            ]
        }
        
        return slack_message
