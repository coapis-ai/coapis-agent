"""
C2A Tools - Executor for C2A Generation Tool

This module provides the execution logic for the generate_c2a_card tool.
"""

import logging
from c2a_protocol.models import (
    C2AMessage, ContextRef, Metadata, Block, BlockContent, 
    Action, ActionSecurity, State
)
from c2a_protocol.validator import validate_c2a_message, C2AValidationError

logger = logging.getLogger(__name__)


def execute_c2a_generation(blocks: list, actions: list, session_id: str = "default_session") -> dict:
    """
    Execute the generate_c2a_card tool: assemble blocks and actions into a C2AMessage, 
    validate it, and return JSON representation.
    
    Args:
        blocks: List of block dictionaries from LLM tool call parameters.
        actions: List of action dictionaries from LLM tool call parameters.
        session_id: The conversation session ID for context reference.
        
    Returns:
        A dictionary with 'success' flag and either 'c2a_json' or 'error'.
    """
    try:
        # 1. Assemble C2AMessage
        ctx_ref = ContextRef(session_id=session_id)
        meta = Metadata(generated_by="agent_c2a_generator")
        
        c2a_blocks = []
        for b in blocks:
            block_type = b.get("type")
            content = b.get("content", {})
            c2a_blocks.append(Block(type=block_type, content=BlockContent(data=content)))

        c2a_actions = []
        for a in actions:
            security_data = a.get("security", {})
            sec = ActionSecurity(
                requires_auth=security_data.get("requires_auth", False),
                required_permissions=security_data.get("required_permissions", []),
                confirmation_prompt=security_data.get("confirmation_prompt")
            )
            c2a_actions.append(Action(
                action_id=a["action_id"],
                label=a["label"],
                style=a.get("style", "secondary"),
                intent=a["intent"],
                payload=a.get("payload", {}),
                security=sec
            ))

        c2a_msg = C2AMessage(
            context_ref=ctx_ref,
            metadata=meta,
            blocks=c2a_blocks,
            actions=c2a_actions,
            state=State(status="rendered")
        )

        # 2. Validate: protocol version, block type enums, action intent
        #    enums, state status. (No action whitelist here — passing the
        #    message's own action ids would be a vacuous self-check.)
        validate_c2a_message(c2a_msg)

        # 3. Return JSON representation
        return {
            "success": True,
            "c2a_json": c2a_msg.to_json(indent=2),
            "message": "C2A card generated successfully."
        }

    except C2AValidationError as e:
        logger.error(f"C2A validation failed: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"Unexpected error in c2a_generation executor: {e}")
        return {"success": False, "error": f"Internal error: {str(e)}"}
