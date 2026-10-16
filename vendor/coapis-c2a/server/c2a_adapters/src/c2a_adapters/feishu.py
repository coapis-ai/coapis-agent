"""
C2A (Chat-to-Action) Interactive Message Protocol - Feishu/Lark Interactive Message Adapter

This module provides the adapter to transform C2A messages into Feishu Interactive Message format.
"""

import json
from typing import Dict, Any, List
from c2a_protocol.models import C2AMessage, Block, Action


class FeishuInteractiveMessageAdapter:
    """Adapter for transforming C2A messages to Feishu Interactive Message format."""
    
    @staticmethod
    def transform(c2a_msg: C2AMessage) -> Dict[str, Any]:
        """Transform a C2AMessage to Feishu Interactive Message JSON structure."""
        
        # Extract main title and description from text_markdown blocks or metadata
        title = "C2A Interactive Message"
        content_text = ""
        
        for block in c2a_msg.blocks:
            if block.type == "text_markdown":
                markdown_content = block.content.get("markdown", "")
                lines = markdown_content.split('\n')
                if len(lines) > 0:
                    title = lines[0].replace('# ', '').strip() or title
                if len(lines) > 1:
                    content_text = '\n'.join(lines[1:]).strip()
        
        # Build Feishu Interactive Message blocks structure
        blocks = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"# {title}\n{content_text}" if content_text else f"# {title}"
                }
            }
        ]
        
        # Build action buttons for Feishu Interactive Message
        actions = []
        for action in c2a_msg.actions:
            # Map style to Feishu button type
            # primary/success -> "primary", danger/warning -> "danger", secondary/text -> "default"
            btn_type = "primary" if action.style in ["primary", "success"] else ("danger" if action.style == "danger" else "default")
            
            # Build callback URL with action parameters
            callback_url = f"https://your-backend.com/c2a/callback/feishu?action={action.action_id}&intent={action.intent}"
            
            actions.append({
                "tag": "button",
                "text": {
                    "tag": "lark_md",
                    "content": action.label
                },
                "type": btn_type,
                "url": callback_url if action.intent == "external_redirect" else None,
                "value": {
                    "action_id": action.action_id,
                    "intent": action.intent,
                    **getattr(action, 'payload', {})
                } if action.intent in ["api_call", "workflow_trigger"] else None
            })
        
        # Add actions block if there are actions
        if actions:
            blocks.append({
                "tag": "action",
                "actions": actions[:4] # Feishu supports up to 4 buttons in action block
            })
        
        # Build the Feishu Interactive Message structure
        feishu_msg = {
            "msg_type": "interactive",
            "card": {
                "config": {
                    "wide_screen_mode": True,
                    "enable_forward": True
                },
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": title
                    }
                },
                "elements": blocks
            }
        }
        
        return feishu_msg
