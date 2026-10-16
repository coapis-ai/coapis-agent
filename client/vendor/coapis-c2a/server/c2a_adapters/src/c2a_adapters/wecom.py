"""
C2A (Chat-to-Action) Interactive Message Protocol - WeCom Template Card Adapter

This module provides the adapter to transform C2A messages into WeCom Template Card format.
"""

import json
from typing import Dict, Any, List
from c2a_protocol.models import C2AMessage, Block, Action


class WecomTemplateCardAdapter:
    """Adapter for transforming C2A messages to WeCom Template Card format."""
    
    @staticmethod
    def transform(c2a_msg: C2AMessage) -> Dict[str, Any]:
        """Transform a C2AMessage to WeCom Template Card JSON structure."""
        
        # Extract main title and description from text_markdown blocks or metadata
        main_title = "C2A Interactive Message"
        sub_description = ""
        
        for block in c2a_msg.blocks:
            if block.type == "text_markdown":
                markdown_content = block.content.get("markdown", "")
                lines = markdown_content.split('\n')
                if len(lines) > 0:
                    main_title = lines[0].replace('# ', '').strip() or main_title
                if len(lines) > 1:
                    sub_description = '\n'.join(lines[1:]).strip()
        
        # Build horizontal content list for actions
        horizontal_content_list = []
        for action in c2a_msg.actions:
            # Map style to WeCom button type
            # primary/success -> type 1 (blue), danger/warning -> type 3 (red)
            btn_type = 1 if action.style in ["primary", "success"] else 3
            
            # Build callback URL with action parameters
            callback_url = f"https://your-backend.com/c2a/callback/wecom?action={action.action_id}&intent={action.intent}"
            
            horizontal_content_list.append({
                "title": action.label,
                "desc": "",
                "type": btn_type,
                "url": callback_url
            })
        
        # Build the WeCom Template Card structure
        wecom_card = {
            "msgtype": "template_card",
            "template_card": {
                "card_type": "text_notice_with_action_btn" if len(horizontal_content_list) > 0 else "text_notice",
                "source": {
                    "icon_url": "https://coapis.ai/favicon.ico",
                    "desc": "CoApis C2A Agent"
                },
                "main_title": {
                    "title": main_title,
                    "desc": sub_description if sub_description else None
                },
                "sub_title_text": "请做出您的决策：" if len(horizontal_content_list) > 0 else None,
                "horizontal_content_list": horizontal_content_list[:4], # WeCom supports up to 4 buttons in horizontal list
                "card_action": {
                    "type": 1,
                    "url": "https://your-backend.com/c2a/callback/wecom",
                    "replace_text": "点击处理"
                } if len(horizontal_content_list) > 0 else None
            }
        }
        
        # Remove None values
        wecom_card = {k: v for k, v in wecom_card.items() if v is not None}
        if "template_card" in wecom_card:
            wecom_card["template_card"] = {k: v for k, v in wecom_card["template_card"].items() if v is not None}
            
        return wecom_card
