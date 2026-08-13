# -*- coding: utf-8 -*-
"""Tool for rendering C2A cards (Card-to-Action / Context-to-Application)."""

import json
from typing import Dict, Any
from pydantic import ValidationError

from ...app.cards.protocol import CardData
from ..registry import register_tool


@register_tool(
    name="render_card",
    description="Render a standardized C2A card for display in the chat interface. Use this to create action links, data tables, file previews, notifications, or approval cards."
)
def render_card(card_data: Dict[str, Any]) -> str:
    """
    Render a standardized C2A card for display in the chat interface.
    
    This tool allows LLMs to generate structured cards such as action links, 
    data tables, file previews, notifications, or approval cards.
    
    Args:
        card_data: A dictionary representing the CardData model structure.
        
    Returns:
        A JSON string of the validated CardData if successful, 
        or an error message if validation fails.
    """
    try:
        # Validate and parse CardData
        card = CardData.model_validate(card_data)
        
        # Return the JSON representation to be parsed by frontend
        return json.dumps(card.model_dump(), ensure_ascii=False, indent=2)
    except ValidationError as e:
        return f"Card validation error: {str(e)}"
    except Exception as e:
        return f"Error rendering card: {str(e)}"
