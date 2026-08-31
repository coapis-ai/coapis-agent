"""
C2A (Chat-to-Action) Protocol - AutoGen Agent Extension

This extension provides C2A message generation capabilities for AutoGen agents.
"""

from .agent_extension import C2AAgentExtension, register_c2a_capabilities

__all__ = [
    "C2AAgentExtension",
    "register_c2a_capabilities",
]
