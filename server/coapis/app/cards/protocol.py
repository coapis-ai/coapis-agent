# -*- coding: utf-8 -*-
"""C2A Card Protocol - Standardized card data models for Card-to-Action / Context-to-Application system."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class CardAction(BaseModel):
    """Card action button definition."""
    
    label: str = Field(..., description="Button display text")
    type: Literal["primary", "secondary", "danger", "success"] = Field(
        default="secondary", 
        description="Button style type"
    )
    action: str = Field(..., description="Action identifier (e.g., 'approve', 'view_details', 'external_link')")
    params: Dict[str, Any] = Field(default_factory=dict, description="Action parameters")


class CardContent(BaseModel):
    """Card content payload - varies by card_type."""
    
    # For data_table cards
    columns: Optional[List[Dict[str, Any]]] = None
    rows: Optional[List[Dict[str, Any]]] = None
    
    # For file_preview cards
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    preview_url: Optional[str] = None
    
    # For notification cards
    message: Optional[str] = None
    priority: Literal["low", "medium", "high"] = Field(default="medium")


class CardMetadata(BaseModel):
    """Card metadata for lifecycle and security management."""
    
    session_id: str = Field(..., description="Chat session ID for isolation")
    timeout_seconds: int = Field(default=0, description="Timeout in seconds (0 means no timeout)")
    requires_auth: bool = Field(default=False, description="Whether authentication is required for actions")
    created_at: float = Field(default_factory=lambda: __import__('time').time(), description="Creation timestamp")


class CardData(BaseModel):
    """Standardized C2A card data protocol."""
    
    card_id: str = Field(..., description="Unique card identifier")
    card_type: Literal[
        "approval", 
        "action_link", 
        "data_table", 
        "notification", 
        "file_preview", 
        "execution_result"
    ] = Field(..., description="Card type for frontend rendering")
    
    title: str = Field(..., description="Card title")
    description: Optional[str] = Field(default=None, description="Card subtitle or summary")
    
    content: Optional[CardContent] = Field(default=None, description="Card specific content payload")
    actions: List[CardAction] = Field(default_factory=list, description="Available action buttons")
    
    metadata: CardMetadata = Field(default_factory=CardMetadata, description="Lifecycle and security metadata")
