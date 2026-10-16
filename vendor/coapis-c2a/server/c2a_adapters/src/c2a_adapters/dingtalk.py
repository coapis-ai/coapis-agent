"""
C2A (Chat-to-Action) Interactive Message Protocol - DingTalk Action Card Adapter

This module provides the adapter to transform C2A messages into DingTalk Action Card format.
"""

import json
from typing import Dict, Any, List
from c2a_protocol.models import C2AMessage, Block, Action


class DingTalkActionCardAdapter:
    """Adapter for transforming C2A messages to DingTalk Multi-Action-Card format."""
    
    @staticmethod
    def transform(c2a_msg: C2AMessage) -> Dict[str, Any]:
        """Transform a C2AMessage to DingTalk Action Card JSON structure."""
        
        # Extract main title and description from text_markdown blocks
        markdown_text = "# 交互式消息\n请查看以下操作选项：\n"
        title = "C2A Interactive Message"
        
        for block in c2a_msg.blocks:
            if block.type == "text_markdown":
                md_content = block.content.get("markdown", "")
                lines = md_content.split('\n')
                if len(lines) > 0:
                    title = lines[0].replace('# ', '').strip() or title
                markdown_text = md_content
        
        # Build action list for actions (DingTalk supports up to 4 buttons in multiActionCard)
        click_list = []
        for action in c2a_msg.actions[:4]:
            # Map style to DingTalk button color
            color = "green" if action.style in ["primary", "success"] else ("red" if action.style == "danger" else "blue")
            
            # Build callback URL with action parameters
            callback_url = f"https://your-backend.com/c2a/callback/dingtalk?action={action.action_id}&intent={action.intent}"
            
            click_list.append({
                "text": action.label,
                "color": color,
                "actionURL": callback_url
            })
        
        # Build the DingTalk Action Card structure
        dingtalk_card = {
            "msgtype": "action_card",
            "action_card": {
                "markdown": markdown_text,
                "title": title,
                "single_title": "查看详情",
                "single_url": "https://your-backend.com/c2a/redirect",
                "btn_orientation": 2, # 2 for horizontal layout
                "action_list": {
                    "click_list": click_list if click_list else [
                        {"text": "确认", "color": "blue", "actionURL": "https://your-backend.com/c2a/callback/dingtalk?action=confirm"}
                    ]
                }
            }
        }
        
        return dingtalk_card
