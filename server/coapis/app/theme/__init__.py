# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
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

"""Theme management module - light/dark theme switching.

Solves P1-8: Light/dark theme switching for better user experience.

Features:
- Theme preference storage per user
- System theme detection support
- Theme configuration API
- CSS variable generation for frontend
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

# Available themes
AVAILABLE_THEMES = {
    "light": {
        "name": "Light",
        "description": "Default light theme",
        "css_variables": {
            "--bg-primary": "#ffffff",
            "--bg-secondary": "#f5f5f5",
            "--bg-tertiary": "#e8e8e8",
            "--text-primary": "#1a1a1a",
            "--text-secondary": "#666666",
            "--text-tertiary": "#999999",
            "--border-color": "#e0e0e0",
            "--accent-color": "#1890ff",
            "--accent-hover": "#40a9ff",
            "--success-color": "#52c41a",
            "--warning-color": "#faad14",
            "--error-color": "#ff4d4f",
        },
    },
    "dark": {
        "name": "Dark",
        "description": "Dark theme for low-light environments",
        "css_variables": {
            "--bg-primary": "#1a1a1a",
            "--bg-secondary": "#2a2a2a",
            "--bg-tertiary": "#3a3a3a",
            "--text-primary": "#e8e8e8",
            "--text-secondary": "#b0b0b0",
            "--text-tertiary": "#808080",
            "--border-color": "#3a3a3a",
            "--accent-color": "#1890ff",
            "--accent-hover": "#40a9ff",
            "--success-color": "#52c41a",
            "--warning-color": "#faad14",
            "--error-color": "#ff4d4f",
        },
    },
    "system": {
        "name": "System",
        "description": "Follow system theme preference",
        "css_variables": {},  # Determined at runtime
    },
}


class ThemeManager:
    """Manages theme preferences for users."""

    def __init__(self):
        self._user_preferences: Dict[str, str] = {}  # user_id -> theme

    def get_available_themes(self) -> Dict[str, Dict[str, Any]]:
        """Get list of available themes."""
        return AVAILABLE_THEMES

    def get_user_theme(self, user_id: str) -> str:
        """Get user's preferred theme."""
        return self._user_preferences.get(user_id, "light")

    def set_user_theme(self, user_id: str, theme: str):
        """Set user's preferred theme."""
        if theme not in AVAILABLE_THEMES:
            raise ValueError(f"Unsupported theme: {theme}")
        self._user_preferences[user_id] = theme

    def get_theme_config(self, theme: str) -> Dict[str, Any]:
        """Get theme configuration."""
        if theme not in AVAILABLE_THEMES:
            raise ValueError(f"Unsupported theme: {theme}")
        return AVAILABLE_THEMES[theme]

    def get_user_theme_config(self, user_id: str) -> Dict[str, Any]:
        """Get theme configuration for user."""
        theme = self.get_user_theme(user_id)
        return self.get_theme_config(theme)


# Global theme manager
theme_manager = ThemeManager()


# ---- API Router ----

router = APIRouter(prefix="/api/theme", tags=["Theme"])


@router.get("/available")
async def get_available_themes():
    """Get list of available themes."""
    return theme_manager.get_available_themes()


@router.get("/current")
async def get_current_theme(request: Request):
    """Get user's current theme."""
    user_info = getattr(request.state, "user_info", None)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = user_info.get("username") or user_info.get("sub", "anonymous")
    theme = theme_manager.get_user_theme(user_id)
    config = theme_manager.get_theme_config(theme)

    return {
        "theme": theme,
        "config": config,
    }


@router.post("/set")
async def set_theme(request: Request):
    """Set user's preferred theme."""
    user_info = getattr(request.state, "user_info", None)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    body = await request.json()
    theme = body.get("theme", "light")

    try:
        theme_manager.set_user_theme(
            user_info.get("username") or user_info.get("sub", "anonymous"),
            theme,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    config = theme_manager.get_theme_config(theme)

    return {
        "ok": True,
        "theme": theme,
        "config": config,
    }


@router.get("/config/{theme}")
async def get_theme_config(theme: str):
    """Get configuration for a specific theme."""
    try:
        config = theme_manager.get_theme_config(theme)
        return config
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
