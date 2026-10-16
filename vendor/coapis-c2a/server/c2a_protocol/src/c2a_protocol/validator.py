"""
C2A (Chat-to-Action) Interactive Message Protocol - Python Validator

This module provides validation utilities for the C2A protocol.
"""

from typing import List, Optional
from .models import C2AMessage, PROTOCOL_VERSION, BLOCK_TYPES, ACTION_INTENTS

# Canonical version plus tolerated aliases. LLMs frequently emit shorthand
# ("1.0", "v1.0", "c2a-1.0", ...) instead of the canonical "c2a-v1.0"; accept
# these so hand-built payloads don't fail validation on a cosmetic mismatch.
_ACCEPTED_VERSIONS = {
    PROTOCOL_VERSION,
    "1.0",
    "v1.0",
    "c2a-1.0",
    "c2a_1.0",
    "c2a_v1.0",
}


class C2AValidationError(Exception):
    """Exception raised when C2A protocol validation fails."""
    pass


def validate_c2a_message(
    c2a_msg: C2AMessage,
    allowed_actions: Optional[List[str]] = None,
    allowed_domains: Optional[List[str]] = None,
) -> bool:
    """
    Validate a C2AMessage against protocol rules and security whitelists.

    Args:
        c2a_msg: The C2AMessage instance to validate.
        allowed_actions: Optional whitelist of allowed action_id values.
            (NOTE: passing the message's *own* action ids here is a no-op
            by design — the whitelist must come from the caller's policy.)
        allowed_domains: Optional whitelist of domains for web_redirect intents.
            Relative URLs (``/...``) are treated as internal links and skip
            the domain check.

    Returns:
        True if validation passes.

    Raises:
        C2AValidationError: If validation fails.
    """
    # 1. Protocol version (canonical + tolerated aliases)
    if c2a_msg.protocol_version not in _ACCEPTED_VERSIONS:
        raise C2AValidationError(
            f"Unsupported protocol version: {c2a_msg.protocol_version} "
            f"(expected {PROTOCOL_VERSION})"
        )

    # 2. Block types
    for block in c2a_msg.blocks:
        if block.type not in BLOCK_TYPES:
            raise C2AValidationError(
                f"Invalid block type in {block.block_id}: {block.type!r} "
                f"(allowed: {', '.join(BLOCK_TYPES)})"
            )

    # 3. Action intents + optional whitelist
    if allowed_actions:
        action_ids = [a.action_id for a in c2a_msg.actions]
        for aid in action_ids:
            if aid not in allowed_actions:
                raise C2AValidationError(f"Action not allowed (whitelist violation): {aid}")

    for action in c2a_msg.actions:
        if action.intent not in ACTION_INTENTS:
            raise C2AValidationError(
                f"Invalid action intent in {action.action_id}: {action.intent!r} "
                f"(allowed: {', '.join(ACTION_INTENTS)})"
            )

    # 4. web_redirect URL domain whitelist (relative URLs = internal, allowed)
    if allowed_domains:
        for action in c2a_msg.actions:
            if action.intent != "web_redirect":
                continue
            url = action.payload.get("url", "")
            if url.startswith(("/", "#")):
                continue  # internal link — no domain to check
            if url.startswith("http://"):
                domain = url.split("//", 1)[1].split("/", 1)[0]
            elif url.startswith("https://"):
                domain = url.split("//", 1)[1].split("/", 1)[0]
            else:
                raise C2AValidationError(
                    f"Invalid URL format in web_redirect action {action.action_id}: {url!r}"
                )
            is_allowed = any(
                domain == d or domain.endswith("." + d) for d in allowed_domains
            )
            if not is_allowed:
                raise C2AValidationError(
                    f"Domain not allowed (whitelist violation): {domain} in action {action.action_id}"
                )

    # 5. State status enum
    valid_states = ["idle", "generating", "rendered", "interactive", "executing", "completed", "failed"]
    if c2a_msg.state.status not in valid_states:
        raise C2AValidationError(f"Invalid state status: {c2a_msg.state.status}")

    return True
