"""
C2A Gateway FastAPI Service - Example Backend for Enterprise Channel Integration

This service demonstrates how to:
1. Receive C2A messages from LLM Agents
2. Validate C2A message format using c2a_protocol validator
3. Transform C2A messages to enterprise channel formats (WeCom, DingTalk, Slack)
4. Push transformed messages to enterprise Webhook/Bot APIs
5. Provide MCP-to-C2A conversion and lifecycle management APIs
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, HTTPException, Request, Header
from pydantic import BaseModel, ConfigDict, Field

# Import C2A protocol and adapters
try:
    from c2a_protocol.models import C2AMessage
    from c2a_protocol.validator import validate_c2a_message
    from c2a_adapters.wecom import transform_to_wecom_template_card
    from c2a_adapters.dingtalk import transform_to_dingtalk_action_card
    from c2a_adapters.slack import transform_to_slack_block_kit
except ImportError:
    # Fallback for development without installed packages
    C2AMessage = Any
    validate_c2a_message = None
    transform_to_wecom_template_card = None
    transform_to_dingtalk_action_card = None
    transform_to_slack_block_kit = None

# Import MCP to C2A Parser
try:
    from c2a_tools.mcp_parser import MCPC2AParser, ActionTemplateTypes, ActionTemplateValidator
except ImportError:
    MCPC2AParser = None
    ActionTemplateTypes = None
    ActionTemplateValidator = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="C2A Gateway Service",
    description="Gateway service for receiving C2A messages and transforming to enterprise channels",
    version="1.0.0-alpha"
)


class C2AGatewayRequest(BaseModel):
    """Request model for C2A gateway"""
    c2a_message: Dict[str, Any]
    target_channels: list[str] = ["wecom", "dingtalk", "slack"]


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
            from c2a_tools.mcp_parser import MCPC2AParser as ParserClass
            _mcp_c2a_parser_service = ParserClass()
        except Exception as e:
            logger.error(f"Failed to initialize MCP to C2A parser: {e}")
            raise HTTPException(status_code=500, detail=f"MCP parser initialization failed: {str(e)}")
    return _mcp_c2a_parser_service


def reset_mcp_c2a_parser_service():
    """Reset the MCP to C2A parser service cache."""
    global _mcp_c2a_parser_service
    _mcp_c2a_parser_service = None



@app.post("/api/c2a/receive")
async def receive_c2a_message(request: Request):
    """
    Receive C2A message from LLM Agent and validate format.
    
    This endpoint accepts C2A messages generated by LLM agents and validates
    them against the c2a-message-v1.jsonschema protocol specification.
    """
    try:
        body = await request.json()
        c2a_msg_dict = body.get("c2a_message")
        
        if not c2a_msg_dict:
            raise HTTPException(status_code=400, detail="Missing c2a_message in request")
        
        # Validate C2A message format (if validator is available)
        if validate_c2a_message:
            is_valid, errors = validate_c2a_message(c2a_msg_dict)
            if not is_valid:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid C2A message format: {errors}"
                )
        
        logger.info(f"Received valid C2A message: {c2a_msg_dict.get('message_id')}")
        
        return {
            "status": "received",
            "message_id": c2a_msg_dict.get("message_id"),
            "protocol_version": c2a_msg_dict.get("protocol_version")
        }
        
    except Exception as e:
        logger.error(f"Error receiving C2A message: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/api/c2a/transform/{channel}")
async def transform_c2a_message(channel: str, request: C2AGatewayRequest):
    """
    Transform C2A message to specific enterprise channel format.
    
    Supported channels: wecom, dingtalk, slack
    
    Args:
        channel: Target channel name (wecom, dingtalk, or slack)
        request: C2AGatewayRequest containing c2a_message and target_channels
        
    Returns:
        Transformed message format specific to the channel
    """
    try:
        c2a_msg_dict = request.c2a_message
        
        # Transform based on channel type
        if channel == "wecom":
            if transform_to_wecom_template_card:
                wecom_format = transform_to_wecom_template_card(c2a_msg_dict)
                return {
                    "channel": "wecom",
                    "format": "template_card",
                    "message": wecom_format
                }
            else:
                # Fallback mock transformation
                return {
                    "channel": "wecom",
                    "format": "template_card",
                    "message": {
                        "msgtype": "template_card",
                        "template_card": {
                            "card_type": "text_notice_with_action_btn",
                            "main_title": {"title": "C2A Message"},
                            "horizontal_content_list": []
                        }
                    }
                
        elif channel == "dingtalk":
            if transform_to_dingtalk_action_card:
                dingtalk_format = transform_to_dingtalk_action_card(c2a_msg_dict)
                return {
                    "channel": "dingtalk",
                    "format": "action_card",
                    "message": dingtalk_format
                }
            else:
                # Fallback mock transformation
                return {
                    "channel": "dingtalk",
                    "format": "action_card",
                    "message": {
                        "msgtype": "action_card",
                        "action_card": {
                            "markdown": "# C2A Message",
                            "action_list": {"click_list": []}
                        }
                }
                
        elif channel == "slack":
            if transform_to_slack_block_kit:
                slack_format = transform_to_slack_block_kit(c2a_msg_dict)
                return {
                    "channel": "slack",
                    "format": "block_kit",
                    "message": slack_format
                }
            else:
                # Fallback mock transformation
                return {
                    "channel": "slack",
                    "format": "block_kit",
                    "message": {
                        "text": "C2A Message",
                        "blocks": [
                            {"type": "section", "text": {"type": "mrkdwn", "text": "*C2A Message*"}}
                        ]
                }
                
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported channel: {channel}")
            
    except Exception as e:
        logger.error(f"Error transforming C2A message to {channel}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Transformation error: {str(e)}")


@app.post("/api/c2a/push/{channel}")
async def push_to_channel(channel: str, request: C2AGatewayRequest):
    """
    Push transformed C2A message to enterprise channel Webhook/Bot API.
    
    This endpoint demonstrates how to push messages to enterprise channels.
    In production, this would include actual webhook calls with authentication.
    """
    try:
        # First transform the message
        transform_result = await transform_c2a_message(channel, request)
        
        # Simulate pushing to channel (in production, make actual HTTP requests)
        logger.info(f"Pushing C2A message to {channel}: {transform_result['message']}")
        
        return {
            "status": "pushed",
            "channel": channel,
            "format": transform_result["format"],
            "timestamp": "2024-01-01T00:00:00Z"
        }
        
    except Exception as e:
        logger.error(f"Error pushing to {channel}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Push error: {str(e)}")


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
            import httpx
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
# Core C2A API Endpoints
# ============================================================================

@app.post("/messages/c2a/send", response_model=C2ASendResponse)
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
    """
    # Validate authorization (basic token check for community edition)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Missing or invalid Authorization header",
        )

    # Generate message ID
    message_id = f"msg_c2a_{uuid.uuid4().hex[:12]}"

    # Log the C2A send request
    payload_dict = request.c2a_payload.model_dump()
    logger.info(
        "API c2a_send_message: channel=%s source=%s payload_keys=%s",
        request.target_channel,
        x_system_source or "unknown",
        list(payload_dict.keys()),
    )

    # Build standardized C2A message structure for serialization and deserialization
    standardized_c2a_message = {
        "id": message_id,
        "role": "system",
        "content": [
            {
                "type": "c2a_protocol",
                "data": request.c2a_payload.model_dump()
            }
        ],
        "meta": {
            "system_source": x_system_source,
            "message_id": message_id
        } if x_system_source else {"message_id": message_id}
    }

    # Simulate C2A message send (in production, this would push to channel adapters)
    try:
        logger.info(f"C2A message sent successfully: channel={request.target_channel} message_id={message_id}")
        
        return C2ASendResponse(
            status="success",
            message_id=message_id,
            timestamp=int(time.time()),
        )

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


@app.post("/messages/c2a/{message_id}/action", response_model=C2AActionResponse)
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

    # Log the C2A action request
    logger.info(
        "API c2a_process_action: message_id=%s action_id=%s user_id=%s input_data_keys=%s",
        message_id,
        request.action_id,
        request.user_id[:40] if request.user_id else "",
        list(request.input_data.keys()) if request.input_data else [],
    )

    # Simulate successful C2A action processing
    import time
    return C2AActionResponse(
        status="success",
        message_id=message_id,
        action_id=request.action_id,
        timestamp=int(time.time()),
    )


@app.put("/messages/c2a/{message_id}/update", response_model=C2AUpdateResponse)
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

    # Log the C2A update request
    update_fields = [k for k, v in request.model_dump().items() if v is not None]
    logger.info(
        "API c2a_update_message: message_id=%s source=%s update_fields=%s",
        message_id,
        x_system_source or "unknown",
        update_fields,
    )

    # Simulate successful C2A message update
    import time
    return C2AUpdateResponse(
        status="success",
        message_id=message_id,
        timestamp=int(time.time()),
    )


@app.post("/messages/c2a/mcp/convert", response_model=MCPConvertResponse)
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
            protocol_version=c2a_message.get("protocol_version", "c2a-v2.0")
        )
        
    except Exception as e:
        logger.error(f"Error converting MCP to C2A: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"MCP to C2A conversion error: {str(e)}")


@app.get("/api/health")
async def health_check():
    """Health check endpoint for the C2A gateway service."""
    return {"status": "healthy", "service": "c2a-gateway-fastapi"}
