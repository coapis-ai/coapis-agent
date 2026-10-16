"""
C2A (Chat-to-Action) Protocol - AutoGen Agent Extension

This module provides an extension for AutoGen agents to generate and process C2A messages.
"""

from typing import Dict, Any, List
from autogen_agentchat.base import TaskResult, Team


class C2AAgentExtension:
    """Extension class for AutoGen agents to support C2A message generation."""
    
    def __init__(self):
        self.c2a_capabilities = {
            "message_generation": True,
            "message_validation": True,
            "channel_transformation": ["wecom", "dingtalk", "slack"]
        }
    
    def generate_c2a_message(self, content_type: str, content_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a C2A message structure."""
        c2a_message = {
            "protocol_version": "c2a-v1.0",
            "message_id": f"msg_{hash(str(content_data)) % 100000}",
            "context_ref": {"session_id": "autogen_session"},
            "metadata": {
                "generated_by": "c2a-autogen-plugin",
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
    
    def process_c2a_result(self, task_result: TaskResult) -> Dict[str, Any]:
        """Process AutoGen task result and convert to C2A format if applicable."""
        # In a real implementation, this would parse the task result
        # and determine if it should be converted to a C2A message
        return {
            "status": "processed",
            "c2a_ready": True
        }


def register_c2a_capabilities(agent):
    """Register C2A capabilities with an AutoGen agent."""
    if not hasattr(agent, 'extensions'):
        agent.extensions = {}
    
    agent.extensions['c2a'] = C2AAgentExtension()
    
    # Add C2A generation method to the agent
    def generate_c2a(self, content_type: str, content_data: Dict[str, Any]):
        extension = self.extensions.get('c2a')
        if extension:
            return extension.generate_c2a_message(content_type, content_data)
        raise NotImplementedError("C2A capabilities not registered")
    
    agent.generate_c2a = generate_c2a.__get__(agent, agent.__class__)
    
    return agent
