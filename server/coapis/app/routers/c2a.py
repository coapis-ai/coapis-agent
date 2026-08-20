# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""API router for C2A (Chat-to-Action) message sending and integration."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Optional, Dict, Any, List

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages/c2a", tags=["c2a_messages"])


# ============================================================================
# MCP to C2A Conversion Models and Service Integration
# ============================================================================

class MCPConvertRequest(BaseModel):
    """Request model for converting MCP data to C2A format."""
    mcp_metadata: Optional[Dict[str, Any]] = Field(None, description="MCP tool metadata or schema")
    mcp_data: Optional[Dict[str, Any]] = Field(None, description="MCP execution result data")
    suggestions: Optional[List[Any]] = Field(None, description="LLM generated suggestions for user actions")


class MCPConvertResponse(BaseModel):
    """Response model for MCP to C2A conversion."""
    success: bool = Field(..., description="Whether the conversion was successful")
    c2a_payload: Optional[Dict[str, Any]] = Field(None, description="Generated C2A protocol payload")
    protocol_version: str = Field("c2a-v2.0", description="C2A protocol version used")


# MCP to C2A Parser Service Reference (lazy import to avoid circular dependencies)
_mcp_c2a_parser_service = None

def get_mcp_c2a_parser():
    """Get or initialize the MCP to C2A parser service."""
    global _mcp_c2a_parser_service
    if _mcp_c2a_parser_service is None:
        try:
            from ...app.services.mcp_c2a_parser import MCPC2AParser
            _mcp_c2a_parser_service = MCPC2AParser()
        except Exception as e:
            logger.error(f"Failed to initialize MCP to C2A parser: {e}")
            raise HTTPException(status_code=500, detail=f"MCP parser initialization failed: {str(e)}")
    return _mcp_c2a_parser_service


def reset_mcp_c2a_parser_service():
    """Reset the MCP to C2A parser service cache."""
    global _mcp_c2a_parser_service
    _mcp_c2a_parser_service = None


# ============================================================================
# Phase 2: Callback Webhook Sender with HMAC-SHA256 Signature and Retry Mechanism
# ============================================================================

async def send_c2a_callback_webhook(
    webhook_url: str,
    event_type: str,
    message_id: str,
    payload: Dict[str, Any],
    secret_key: str,
    retry_policy: Optional[RetryPolicyModel] = None,
) -> bool:
    """
    Send a C2A callback webhook with HMAC-SHA256 signature and retry mechanism.
    
    Args:
        webhook_url: The webhook URL to send the callback to
        event_type: The type of event (e.g., 'action_approved', 'timeout_expired')
        message_id: The C2A message ID
        payload: The callback payload data
        secret_key: The secret key for HMAC-SHA256 signature generation
        retry_policy: Retry policy configuration
        
    Returns:
        True if the webhook was successfully sent, False otherwise
    """
    # Generate HMAC-SHA256 signature
    timestamp = str(int(time.time()))
    payload_str = json.dumps(payload, sort_keys=True)
    
    # Create signature string: timestamp + payload
    sign_string = f"{timestamp}.{payload_str}"
    signature = hmac.new(
        secret_key.encode('utf-8'),
        sign_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Prepare webhook headers and request data
    headers = {
        "Content-Type": "application/json",
        "X-C2A-Event": event_type,
        "X-C2A-Timestamp": timestamp,
        "X-C2A-Signature": f"sha256={signature}",
        "X-C2A-Message-ID": message_id
    }
    
    request_data = {
        "event_type": event_type,
        "message_id": message_id,
        "timestamp": timestamp,
        "payload": payload
    }
    
    # Retry mechanism
    retry_policy = retry_policy or RetryPolicyModel()
    max_retries = retry_policy.max_retries
    backoff_seconds = retry_policy.backoff_seconds
    
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(webhook_url, json=request_data, headers=headers)
                
                if response.status_code >= 200 and response.status_code < 300:
                    logger.info("C2A callback webhook sent successfully: event=%s message_id=%s", event_type, message_id)
                    return True
                
                logger.warning(
                    "C2A callback webhook failed with status %s: attempt %d/%d",
                    response.status_code, attempt + 1, max_retries + 1
                )
                
        except Exception as e:
            logger.error(
                "C2A callback webhook exception: event=%s message_id=%s error=%s attempt=%d/%d",
                event_type, message_id, str(e), attempt + 1, max_retries + 1
            )
        
        # Backoff before retry (don't wait after the last attempt)
        if attempt < max_retries:
            await asyncio.sleep(backoff_seconds * (2 ** attempt))  # Exponential backoff
            
    logger.error("C2A callback webhook failed after all retries: event=%s message_id=%s", event_type, message_id)
    return False


# ============================================================================
# Phase 2: Timeout Checker Background Task
# ============================================================================

async def check_and_process_expired_c2a_messages():
    """
    Background task to check and process expired C2A messages based on timeout_seconds or expires_at.
    
    This function would typically be run as a periodic cron job or background task.
    It scans stored C2A messages, identifies those that have exceeded their timeout or expiration,
    and triggers the appropriate callback webhooks (e.g., 'timeout_expired').
    """
    logger.info("Starting C2A timeout checker background task...")
    
    # In a full implementation, this would:
    # 1. Query the storage for C2A messages with status='pending' and (timeout_seconds or expires_at) set
    # 2. Filter out messages where current_time > expires_at or current_time > created_at + timeout_seconds
    # 3. For each expired message, trigger the callback webhook with event_type='timeout_expired'
    # 4. Update the C2A message state to 'expired'
    
    # Simulation for community edition:
    logger.info("C2A timeout checker background task completed (simulation mode).")


# ============================================================================
# Enterprise C2A Protocol Models (Phase 1: Base architecture & protocol definition)
# ============================================================================

class WorkflowStateModel(BaseModel):
    """Workflow state model for multi-step C2A cards."""
    current_node: Optional[str] = None
    next_nodes: List[str] = Field(default_factory=list)
    completion_ratio: Optional[str] = None


class RetryPolicyModel(BaseModel):
    """Retry policy for callback webhooks."""
    max_retries: int = 3
    backoff_seconds: int = 60


class CallbackConfigModel(BaseModel):
    """Callback configuration for C2A lifecycle events."""
    webhook_url: str
    auth_method: str = "signature_hmac"
    events: List[str] = Field(
        default_factory=lambda: [
            "action_approved", 
            "action_rejected", 
            "timeout_expired", 
            "escalated", 
            "revoked"
        ]
    )
    retry_policy: Optional[RetryPolicyModel] = None


class C2AActionModel(BaseModel):
    """C2A action model for user interactions."""
    id: str
    label: str
    type: str
    requires_input: bool = False
    input_type: Optional[str] = None


class AttachmentModel(BaseModel):
    """Attachment model for C2A cards with presigned URLs."""
    id: str
    name: str
    url: str
    type: str


class C2APayloadEnterpriseModel(BaseModel):
    """Enterprise-grade C2A payload protocol model."""
    c2a_version: str = "1.0"
    card_type: str
    title: str
    description: Optional[str] = None
    status: str = "pending"
    
    workflow_state: Optional[WorkflowStateModel] = None
    timeout_seconds: Optional[int] = None
    expires_at: Optional[int] = None
    
    callback_config: Optional[CallbackConfigModel] = None
    
    actions: List[C2AActionModel] = Field(default_factory=list)
    
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata including doc_version, permissions_required, attachments"
    )


class C2APayloadRequest(BaseModel):
    """Request model for sending a C2A message."""

    model_config = ConfigDict(populate_by_name=True)

    target_channel: str = Field(
        "console",
        description="Target channel (e.g., console, wecom, dingtalk, feishu). Defaults to 'console'.",
    )
    c2a_payload: C2APayloadEnterpriseModel = Field(
        ...,
        description="C2A protocol structured message payload (enterprise-grade model)",
    )


class C2ASendResponse(BaseModel):
    """Response model for C2A send endpoint."""

    status: str = Field(
        ...,
        description="Status of the C2A message send operation (success/failed)",
    )
    message_id: Optional[str] = Field(
        None,
        description="Message ID if successfully sent",
    )
    timestamp: int = Field(
        ...,
        description="Timestamp of the operation",
    )


# ============================================================================
# Phase 2: Core APIs and Lifecycle Management Models
# ============================================================================

class C2AActionRequest(BaseModel):
    """Request model for processing a C2A action."""
    
    message_id: str = Field(..., description="C2A message ID")
    action_id: str = Field(..., description="Action ID to execute")
    input_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Input data if the action requires user input",
    )
    user_id: str = Field(..., description="User ID executing the action")


class C2AActionResponse(BaseModel):
    """Response model for C2A action processing endpoint."""

    status: str = Field(
        ...,
        description="Status of the C2A action operation (success/failed/processing)",
    )
    message_id: str = Field(..., description="C2A message ID")
    action_id: str = Field(..., description="Executed action ID")
    timestamp: int = Field(..., description="Timestamp of the operation")


class C2AUpdateRequest(BaseModel):
    """Request model for updating a C2A message."""
    
    status: Optional[str] = None
    workflow_state: Optional[WorkflowStateModel] = None
    timeout_seconds: Optional[int] = None
    expires_at: Optional[int] = None


class C2AUpdateResponse(BaseModel):
    """Response model for C2A update endpoint."""

    status: str = Field(
        ...,
        description="Status of the C2A update operation (success/failed)",
    )
    message_id: str = Field(..., description="C2A message ID")
    timestamp: int = Field(..., description="Timestamp of the operation")


@router.post("/send", response_model=C2ASendResponse)
async def send_c2a_message(
    request: C2APayloadRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_system_source: Optional[str] = Header(None, alias="X-System-Source"),
) -> C2ASendResponse:
    """Send a C2A (Chat-to-Action) message to a channel.

    This endpoint allows external systems or internal services to send
    structured C2A messages to CoApis channels.

    Args:
        request: C2A payload request with target_channel and c2a_payload
        http_request: FastAPI request object (for accessing app state)
        authorization: Authorization header with Bearer token
        x_system_source: External system identifier from X-System-Source header

    Returns:
        C2ASendResponse with status, message_id, and timestamp

    Raises:
        HTTPException: If auth fails, channel not found, or send fails

    Example:
        ```bash
        curl -X POST "http://localhost:4308/api/messages/c2a/send" \\
          -H "Content-Type: application/json" \\
          -H "Authorization: Bearer <your_api_token>" \\
          -H "X-System-Source: OA-SYSTEM" \\
          -d '{
            "target_channel": "console",
            "c2a_payload": {
              "c2a_version": "1.0",
              "card_type": "approval",
              "title": "采购审批单 #PO-2026-0813",
              ...
            }
          }'
        ```
    """
    # Validate authorization (basic token check for community edition)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Missing or invalid Authorization header",
        )

    # Get multi-agent manager from app state
    if not hasattr(http_request.app.state, "multi_agent_manager"):
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )
    
    multi_agent_manager = http_request.app.state.multi_agent_manager

    # Get workspace for the admin agent (or external system agent)
    try:
        # For C2A external system integration, we use the admin agent's workspace
        workspace = await multi_agent_manager.get_agent("user:admin")
    except Exception as e:
        logger.error("Failed to get agent workspace for C2A send: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get agent workspace: {str(e)}",
        ) from e

    # Get channel manager from workspace
    channel_manager = workspace.channel_manager
    if not channel_manager:
        raise HTTPException(
            status_code=500,
            detail="Channel manager not initialized for C2A messages",
        )

    # Log the C2A send request
    payload_dict = request.c2a_payload.model_dump()
    logger.info(
        "API c2a_send_message: channel=%s source=%s payload_keys=%s",
        request.target_channel,
        x_system_source or "unknown",
        list(payload_dict.keys()),
    )

    # Generate message ID
    import uuid
    message_id = f"msg_c2a_{uuid.uuid4().hex[:12]}"

    # Build standardized C2A message structure for serialization and deserialization
    standardized_c2a_message = {
        "id": message_id,
        "role": "system",
        "content": [
            {
                "type": "c2a_protocol",
                "data": request.c2a_payload
            }
        ],
        "meta": {
            "system_source": x_system_source,
            "message_id": message_id
        } if x_system_source else {"message_id": message_id}
    }

    # Send the C2A message via channel manager (convert c2a_payload to text or structured format)
    try:
        # For community edition, we store the C2A payload as a structured message in standard session
        # The actual C2A rendering and adapter conversion will be handled by the SEM/runner
        
        # Store the C2A message in the channel/session with standard session_id format {channel}:console
        await channel_manager.send_c2a(
            channel=request.target_channel,
            user_id="console",
            session_id=f"{request.target_channel}:console",
            c2a_payload=standardized_c2a_message,
            meta={
                "system_source": x_system_source,
                "message_id": message_id
            } if x_system_source else {"message_id": message_id}
        )

        import time
        return C2ASendResponse(
            status="success",
            message_id=message_id,
            timestamp=int(time.time()),
        )

    except KeyError as e:
        logger.warning("C2A channel not found: %s", e)
        raise HTTPException(
            status_code=404,
            detail=f"Channel not found for C2A send: {request.target_channel}",
        ) from e

    except Exception as e:
        logger.error(
            "Failed to send C2A message to %s: %s",
            request.target_channel,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send C2A message: {str(e)}",
        ) from e


@router.post("/{message_id}/action", response_model=C2AActionResponse)
async def process_c2a_action(
    message_id: str,
    request: C2AActionRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> C2AActionResponse:
    """Process a user action on a C2A (Chat-to-Action) card.

    This endpoint allows processing actions triggered by users interacting with C2A cards,
    including approvals, rejections, and input submissions.

    Args:
        message_id: The C2A message ID
        request: C2A action request with action_id, input_data, and user_id
        http_request: FastAPI request object (for accessing app state)
        authorization: Authorization header with Bearer token

    Returns:
        C2AActionResponse with status, message_id, action_id, and timestamp

    Raises:
        HTTPException: If auth fails, message not found, or action processing fails
    """
    # Validate authorization (basic token check for community edition)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Missing or invalid Authorization header",
        )

    # Get multi-agent manager from app state
    if not hasattr(http_request.app.state, "multi_agent_manager"):
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )
    
    multi_agent_manager = http_request.app.state.multi_agent_manager

    # Get workspace for the admin agent (or external system agent)
    try:
        workspace = await multi_agent_manager.get_agent("user:admin")
    except Exception as e:
        logger.error("Failed to get agent workspace for C2A action processing: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get agent workspace: {str(e)}",
        ) from e

    # Get channel manager from workspace
    channel_manager = workspace.channel_manager
    if not channel_manager:
        raise HTTPException(
            status_code=500,
            detail="Channel manager not initialized for C2A actions",
        )

    # Log the C2A action request
    logger.info(
        "API c2a_process_action: message_id=%s action_id=%s user_id=%s input_data_keys=%s",
        message_id,
        request.action_id,
        request.user_id[:40] if request.user_id else "",
        list(request.input_data.keys()) if request.input_data else [],
    )

    # Validate that the action exists in the C2A card (simulation for community edition)
    # In a full implementation, this would fetch the C2A message from storage and validate the action_id
    
    # For community edition, we simulate successful action processing
    # The actual callback webhook sending will be handled by the background task or SEM/runner
    
    import time
    return C2AActionResponse(
        status="success",
        message_id=message_id,
        action_id=request.action_id,
        timestamp=int(time.time()),
    )


@router.put("/{message_id}/update", response_model=C2AUpdateResponse)
async def update_c2a_message(
    message_id: str,
    request: C2AUpdateRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_system_source: Optional[str] = Header(None, alias="X-System-Source"),
) -> C2AUpdateResponse:
    """Update an existing C2A (Chat-to-Action) message.

    This endpoint allows external systems to update the status or workflow state of a C2A card,
    such as changing from 'pending' to 'approved', 'rejected', or updating the workflow_state.

    Args:
        message_id: The C2A message ID
        request: C2A update request with status, workflow_state, timeout_seconds, expires_at
        http_request: FastAPI request object (for accessing app state)
        authorization: Authorization header with Bearer token
        x_system_source: External system identifier from X-System-Source header

    Returns:
        C2AUpdateResponse with status, message_id, and timestamp

    Raises:
        HTTPException: If auth fails, message not found, or update fails
    """
    # Validate authorization (basic token check for community edition)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Missing or invalid Authorization header",
        )

    # Get multi-agent manager from app state
    if not hasattr(http_request.app.state, "multi_agent_manager"):
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )
    
    multi_agent_manager = http_request.app.state.multi_agent_manager

    # Get workspace for the admin agent (or external system agent)
    try:
        workspace = await multi_agent_manager.get_agent("user:admin")
    except Exception as e:
        logger.error("Failed to get agent workspace for C2A update: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get agent workspace: {str(e)}",
        ) from e

    # Get channel manager from workspace
    channel_manager = workspace.channel_manager
    if not channel_manager:
        raise HTTPException(
            status_code=500,
            detail="Channel manager not initialized for C2A updates",
        )

    # Log the C2A update request
    update_fields = [k for k, v in request.model_dump().items() if v is not None]
    logger.info(
        "API c2a_update_message: message_id=%s source=%s update_fields=%s",
        message_id,
        x_system_source or "unknown",
        update_fields,
    )

    # For community edition, we simulate successful C2A message update
    # The actual storage update and callback webhook sending will be handled by the background task
    
    import time
    return C2AUpdateResponse(
        status="success",
        message_id=message_id,
        timestamp=int(time.time()),
    )


@router.post("/mcp/convert", response_model=MCPConvertResponse)
async def convert_mcp_to_c2a(
    request: MCPConvertRequest,
) -> MCPConvertResponse:
    """Convert MCP tool metadata and execution data to C2A protocol format.

    This endpoint uses the MCPC2AParser to generate C2A messages from MCP data,
    including blocks (text_markdown, data_table) and actions (row_actions, suggestions).

    Args:
        request: MCP conversion request with mcp_metadata, mcp_data, and suggestions

    Returns:
        MCPConvertResponse with success status, c2a_payload, and protocol_version

    Raises:
        HTTPException: If MCP to C2A conversion fails
    """
    try:
        # Get the MCP to C2A parser service
        parser = get_mcp_c2a_parser()
        
        # Construct mcp_result from request data
        mcp_result = {
            "content": [
                {"type": "text", "text": "MCP execution result"}
            ],
            "isError": False,
            "metadata": {}
        }
        
        if request.mcp_metadata:
            mcp_result["metadata"]["action_templates"] = request.mcp_metadata.get("action_templates", {})
        
        import uuid
        message_id = f"msg_mcp_c2a_{uuid.uuid4().hex[:12]}"
        session_id = "console:test1"  # Default session ID
        
        # Generate C2A message from MCP result
        c2a_message = parser.generate_c2a_message_from_mcp(
            mcp_result=mcp_result,
            message_id=message_id,
            session_id=session_id
        )
        
        # Add suggestions to the c2a_message if provided
        if request.suggestions:
            c2a_message['suggestions'] = request.suggestions
        
        logger.info(f"MCP data converted to C2A successfully, blocks={len(c2a_message.get('blocks', []))}, actions={len(c2a_message.get('actions', []))}")
        
        return MCPConvertResponse(
            success=True,
            c2a_payload=c2a_message,
            protocol_version=c2a_message.get("protocol_version", "c2a-v1.0")
        )
        
    except Exception as e:
        logger.error(f"Error converting MCP to C2A: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"MCP to C2A conversion error: {str(e)}")
