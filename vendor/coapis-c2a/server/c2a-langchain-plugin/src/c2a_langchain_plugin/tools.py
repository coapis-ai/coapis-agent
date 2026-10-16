"""
C2A (Chat-to-Action) Protocol - LangChain Tools

This module provides LangChain tool implementations for C2A message generation and validation.
"""

from typing import Dict, Any, List
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class C2AGeneratorInput(BaseModel):
    """Input for C2A Generator Tool"""
    content_type: str = Field(..., description="Type of content to generate (text_markdown, data_table, data_list, form_definition)")
    content_data: Dict[str, Any] = Field(..., description="Data payload for the content type")


class C2AGeneratorTool(BaseTool):
    """LangChain tool for generating C2A messages"""
    
    name: str = "c2a_generator"
    description: str = "Generate a Chat-to-Action (C2A) interactive message structure"
    args_schema: type[BaseModel] = C2AGeneratorInput
    
    def _run(self, content_type: str, content_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the C2A generator tool"""
        # Generate basic C2A message structure
        c2a_message = {
            "protocol_version": "c2a-v1.0",
            "message_id": f"msg_{hash(str(content_data)) % 100000}",
            "context_ref": {"session_id": "langchain_session"},
            "metadata": {
                "generated_by": "c2a-langchain-plugin",
                "generated_at": "2024-01-01T00:00:00Z"
            },
            "blocks": [
                {
                    "block_id": f"block_{content_type}_001",
                    "type": content_type,
                    "content": {"data": content_data}
                }
            ],
            "actions": [],
            "state": {"status": "rendered"},
            "extensions": {}
        }
        
        return c2a_message
    
    async def _arun(self, content_type: str, content_data: Dict[str, Any]) -> Dict[str, Any]:
        """Async execution of the C2A generator tool"""
        return self._run(content_type, content_data)


class C2AValidatorInput(BaseModel):
    """Input for C2A Validator Tool"""
    c2a_message: Dict[str, Any] = Field(..., description="C2A message to validate")


class C2AValidatorTool(BaseTool):
    """LangChain tool for validating C2A messages against protocol specification"""
    
    name: str = "c2a_validator"
    description: str = "Validate a Chat-to-Action (C2A) message against the c2a-v1.0 protocol specification"
    args_schema: type[BaseModel] = C2AValidatorInput
    
    def _run(self, c2a_message: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the C2A validator tool"""
        # Basic validation logic (in production, use c2a_protocol.validator.validate_c2a_message)
        is_valid = True
        errors = []
        
        # Check required fields
        required_fields = ["protocol_version", "message_id", "context_ref", "metadata", "blocks", "actions", "state"]
        for field in required_fields:
            if field not in c2a_message:
                is_valid = False
                errors.append(f"Missing required field: {field}")
        
        return {
            "is_valid": is_valid,
            "errors": errors if not is_valid else []
        }
    
    async def _arun(self, c2a_message: Dict[str, Any]) -> Dict[str, Any]:
        """Async execution of the C2A validator tool"""
        return self._run(c2a_message)
