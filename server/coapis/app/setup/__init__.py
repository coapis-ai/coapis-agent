# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Setup wizard module - interactive configuration for first-time users.

Provides:
- Multi-step setup wizard: Network → LLM → Agent → User
- Configuration validation and real-time feedback
- Progress tracking and state persistence
- Skip and resume support
- Config import/export
"""

import json
import logging
import os
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_current_user

logger = logging.getLogger(__name__)


class SetupStep(str, Enum):
    """Setup wizard steps."""
    NETWORK = "network"
    LLM = "llm"
    AGENT = "agent"
    USER = "user"
    COMPLETE = "complete"


class SetupState:
    """Tracks setup wizard progress and data."""

    def __init__(self):
        self.current_step: SetupStep = SetupStep.NETWORK
        self.completed_steps: List[SetupStep] = []
        self.data: Dict[str, Any] = {
            "network": {},
            "llm": {},
            "agent": {},
            "user": {},
        }
        self.is_complete: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_step": self.current_step.value,
            "completed_steps": [s.value for s in self.completed_steps],
            "data": self.data,
            "is_complete": self.is_complete,
        }


# Global setup state (in-memory)
setup_state = SetupState()


# ---- Validation Functions ----

def validate_network_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate network configuration."""
    errors = []

    # Check server URL
    server_url = config.get("server_url", "")
    if server_url:
        if not server_url.startswith(("http://", "https://")):
            errors.append("server_url must start with http:// or https://")

    # Check port
    port = config.get("port", 8000)
    if not isinstance(port, int) or port < 1 or port > 65535:
        errors.append("port must be between 1 and 65535")

    return {"valid": len(errors) == 0, "errors": errors}


def validate_llm_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate LLM provider configuration."""
    errors = []

    # Check provider
    provider = config.get("provider", "")
    if not provider:
        errors.append("provider is required")

    # Check API key
    api_key = config.get("api_key", "")
    if provider and not api_key:
        errors.append("api_key is required for selected provider")

    # Check model
    model = config.get("model", "")
    if provider and not model:
        errors.append("model is required")

    return {"valid": len(errors) == 0, "errors": errors}


def validate_agent_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate agent configuration."""
    errors = []

    # Check agent name
    name = config.get("name", "")
    if not name:
        errors.append("agent name is required")
    elif len(name) < 2 or len(name) > 50:
        errors.append("agent name must be between 2 and 50 characters")

    # Check system prompt
    prompt = config.get("system_prompt", "")
    if prompt and len(prompt) > 10000:
        errors.append("system prompt too long (max 10000 characters)")

    return {"valid": len(errors) == 0, "errors": errors}


def validate_user_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate user configuration."""
    errors = []

    # Check username
    username = config.get("username", "")
    if not username:
        errors.append("username is required")
    elif len(username) < 3 or len(username) > 30:
        errors.append("username must be between 3 and 30 characters")

    # Check password
    password = config.get("password", "")
    if not password:
        errors.append("password is required")
    elif len(password) < 6:
        errors.append("password must be at least 6 characters")

    # Check password confirmation
    if password and password != config.get("password_confirm", ""):
        errors.append("passwords do not match")

    return {"valid": len(errors) == 0, "errors": errors}


# ---- API Router ----

router = APIRouter(prefix="/api/setup", tags=["Setup Wizard"])


@router.get("/status")
async def get_setup_status():
    """Get current setup progress."""
    return setup_state.to_dict()


@router.get("/steps")
async def get_available_steps():
    """Get list of available setup steps."""
    return {
        "steps": [
            {
                "id": SetupStep.NETWORK.value,
                "name": "Network Configuration",
                "description": "Configure server URL and port",
                "completed": SetupStep.NETWORK in setup_state.completed_steps,
            },
            {
                "id": SetupStep.LLM.value,
                "name": "LLM Provider",
                "description": "Configure AI model provider",
                "completed": SetupStep.LLM in setup_state.completed_steps,
            },
            {
                "id": SetupStep.AGENT.value,
                "name": "Agent Settings",
                "description": "Configure agent name and behavior",
                "completed": SetupStep.AGENT in setup_state.completed_steps,
            },
            {
                "id": SetupStep.USER.value,
                "name": "User Account",
                "description": "Create admin user account",
                "completed": SetupStep.USER in setup_state.completed_steps,
            },
        ],
        "current_step": setup_state.current_step.value,
        "is_complete": setup_state.is_complete,
    }


@router.get("/step/{step_id}")
async def get_step_data(step_id: str):
    """Get data for a specific step."""
    try:
        step = SetupStep(step_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid step: {step_id}")

    return {
        "step": step.value,
        "data": setup_state.data.get(step.value, {}),
    }


@router.post("/step/{step_id}/validate")
async def validate_step(step_id: str, request: Request):
    """Validate data for a specific step."""
    try:
        step = SetupStep(step_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid step: {step_id}")

    body = await request.json()
    config = body.get("config", {})

    # Validate based on step
    if step == SetupStep.NETWORK:
        result = validate_network_config(config)
    elif step == SetupStep.LLM:
        result = validate_llm_config(config)
    elif step == SetupStep.AGENT:
        result = validate_agent_config(config)
    elif step == SetupStep.USER:
        result = validate_user_config(config)
    else:
        result = {"valid": False, "errors": ["Unknown step"]}

    return result


@router.post("/step/{step_id}/save")
async def save_step(step_id: str, request: Request):
    """Save and validate data for a specific step, then advance."""
    try:
        step = SetupStep(step_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid step: {step_id}")

    body = await request.json()
    config = body.get("config", {})

    # Validate
    if step == SetupStep.NETWORK:
        result = validate_network_config(config)
    elif step == SetupStep.LLM:
        result = validate_llm_config(config)
    elif step == SetupStep.AGENT:
        result = validate_agent_config(config)
    elif step == SetupStep.USER:
        result = validate_user_config(config)
    else:
        raise HTTPException(status_code=400, detail="Unknown step")

    if not result["valid"]:
        raise HTTPException(
            status_code=422,
            detail={"errors": result["errors"]},
        )

    # Save data
    setup_state.data[step.value] = config

    # Mark step as completed
    if step not in setup_state.completed_steps:
        setup_state.completed_steps.append(step)

    # Advance to next step
    step_order = [
        SetupStep.NETWORK,
        SetupStep.LLM,
        SetupStep.AGENT,
        SetupStep.USER,
    ]

    current_idx = step_order.index(step)
    if current_idx < len(step_order) - 1:
        setup_state.current_step = step_order[current_idx + 1]
    else:
        # All steps completed
        setup_state.is_complete = True
        setup_state.current_step = SetupStep.COMPLETE

        # Apply configuration
        await _apply_setup_config()

    logger.info(
        "Setup step completed: %s (total: %d/%d)",
        step.value,
        len(setup_state.completed_steps),
        len(step_order),
    )

    return {
        "ok": True,
        "step": step.value,
        "next_step": setup_state.current_step.value,
        "is_complete": setup_state.is_complete,
    }


@router.post("/skip")
async def skip_step():
    """Skip current step and advance."""
    step_order = [
        SetupStep.NETWORK,
        SetupStep.LLM,
        SetupStep.AGENT,
        SetupStep.USER,
    ]

    current_idx = step_order.index(setup_state.current_step)
    if current_idx < len(step_order) - 1:
        setup_state.current_step = step_order[current_idx + 1]

    return {
        "ok": True,
        "current_step": setup_state.current_step.value,
    }


@router.post("/reset")
async def reset_setup():
    """Reset setup wizard to beginning."""
    setup_state.current_step = SetupStep.NETWORK
    setup_state.completed_steps.clear()
    setup_state.data = {
        "network": {},
        "llm": {},
        "agent": {},
        "user": {},
    }
    setup_state.is_complete = False

    logger.info("Setup wizard reset")

    return {"ok": True}


@router.post("/export")
async def export_config():
    """Export current setup configuration as JSON."""
    return {
        "ok": True,
        "config": setup_state.data,
        "is_complete": setup_state.is_complete,
    }


@router.post("/import")
async def import_config(request: Request):
    """Import setup configuration from JSON."""
    body = await request.json()
    config = body.get("config", {})

    # Validate structure
    required_keys = ["network", "llm", "agent", "user"]
    for key in required_keys:
        if key not in config:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required key: {key}",
            )

    # Update setup state
    setup_state.data = config

    # Mark all steps as completed if data is present
    for step in SetupStep:
        if step != SetupStep.COMPLETE and config.get(step.value):
            if step not in setup_state.completed_steps:
                setup_state.completed_steps.append(step)

    # Check if complete
    if len(setup_state.completed_steps) >= len(required_keys):
        setup_state.is_complete = True
        setup_state.current_step = SetupStep.COMPLETE

    return {
        "ok": True,
        "is_complete": setup_state.is_complete,
    }


async def _apply_setup_config():
    """Apply saved configuration to system."""
    # TODO: Apply LLM provider config to environment
    # TODO: Apply agent config to agent settings
    # TODO: Create user account from user config
    # For now, just log the config
    logger.info("Setup complete. Configuration saved:")
    for step, config in setup_state.data.items():
        logger.info("  %s: %s", step, json.dumps(config, ensure_ascii=False))
