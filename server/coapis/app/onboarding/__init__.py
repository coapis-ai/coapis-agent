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

"""User onboarding module - interactive tutorials and feature guides.

Provides:
- Interactive feature tours (step-by-step walkthroughs)
- Contextual tips and hints
- Progress tracking per user
- Dismissable tips with "don't show again" option
- Multiple tour categories: basics, advanced, skills, tools
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)


class TourStep:
    """A single step in a feature tour."""

    def __init__(
        self,
        element: str,
        title: str,
        description: str,
        position: str = "bottom",
        modal: bool = False,
    ):
        self.element = element  # CSS selector
        self.title = title
        self.description = description
        self.position = position  # top, bottom, left, right
        self.modal = modal  # dark overlay

    def to_dict(self) -> Dict[str, Any]:
        return {
            "element": self.element,
            "title": self.title,
            "description": self.description,
            "position": self.position,
            "modal": self.modal,
        }


class FeatureTour:
    """A feature tour with multiple steps."""

    def __init__(self, tour_id: str, name: str, category: str, steps: List[TourStep]):
        self.tour_id = tour_id
        self.name = name
        self.category = category
        self.steps = steps

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tour_id": self.tour_id,
            "name": self.name,
            "category": self.category,
            "steps": [s.to_dict() for s in self.steps],
        }


class OnboardingManager:
    """Manages user onboarding state and tours."""

    # Built-in tours
    TOURS: Dict[str, FeatureTour] = {
        "basics": FeatureTour(
            tour_id="basics",
            name="Basic Features Tour",
            category="basics",
            steps=[
                TourStep(
                    element="#sidebar",
                    title="Navigation Sidebar",
                    description="Use the sidebar to navigate between different sections of CoApis.",
                    position="right",
                ),
                TourStep(
                    element="#chat-input",
                    title="Chat Input",
                    description="Type your messages here and press Enter to send. Supports markdown formatting.",
                    position="top",
                ),
                TourStep(
                    element="#skills-panel",
                    title="Skills Panel",
                    description="Browse and manage AI skills. Click to install or configure skills.",
                    position="left",
                ),
                TourStep(
                    element="#settings-btn",
                    title="Settings",
                    description="Access system settings, LLM configuration, and user preferences.",
                    position="bottom",
                ),
            ],
        ),
        "skills": FeatureTour(
            tour_id="skills",
            name="Skills Deep Dive",
            category="advanced",
            steps=[
                TourStep(
                    element="#skills-list",
                    title="Installed Skills",
                    description="View all your installed skills. Each skill adds new capabilities to the AI agent.",
                    position="bottom",
                ),
                TourStep(
                    element="#skill-search",
                    title="Search Skills",
                    description="Search for new skills in the marketplace. Type keywords to find what you need.",
                    position="bottom",
                ),
                TourStep(
                    element="#skill-install-btn",
                    title="Install Skill",
                    description="Click to install a new skill. The agent will automatically learn to use it.",
                    position="left",
                ),
            ],
        ),
        "tools": FeatureTour(
            tour_id="tools",
            name="Browser Tools Tour",
            category="advanced",
            steps=[
                TourStep(
                    element="#browser-panel",
                    title="Browser Control",
                    description="Control a real browser instance. Navigate, click, type, and extract data.",
                    position="right",
                ),
                TourStep(
                    element="#browser-url",
                    title="URL Navigation",
                    description="Enter a URL to navigate. The browser will load the page for you.",
                    position="bottom",
                ),
                TourStep(
                    element="#browser-actions",
                    title="Browser Actions",
                    description="Perform actions like click, type, screenshot, and more on the current page.",
                    position="top",
                ),
            ],
        ),
        "inbox": FeatureTour(
            tour_id="inbox",
            name="Inbox & Notifications",
            category="basics",
            steps=[
                TourStep(
                    element="#inbox-icon",
                    title="Inbox",
                    description="View notifications, task results, and system messages.",
                    position="bottom",
                ),
                TourStep(
                    element="#unread-badge",
                    title="Unread Count",
                    description="The badge shows how many unread messages you have.",
                    position="left",
                ),
            ],
        ),
    }

    def __init__(self):
        # user_id -> {tour_id: completed_at}
        self._completed_tours: Dict[str, Dict[str, datetime]] = {}
        # user_id -> [dismissed_tip_ids]
        self._dismissed_tips: Dict[str, List[str]] = {}

    def get_tours(self, category: Optional[str] = None) -> List[FeatureTour]:
        """Get available tours, optionally filtered by category."""
        if category:
            return [t for t in self.TOURS.values() if t.category == category]
        return list(self.TOURS.values())

    def get_tour(self, tour_id: str) -> Optional[FeatureTour]:
        """Get a specific tour by ID."""
        return self.TOURS.get(tour_id)

    def get_tour_categories(self) -> List[str]:
        """Get list of available tour categories."""
        categories = set(t.category for t in self.TOURS.values())
        return sorted(categories)

    def mark_tour_completed(self, user_id: str, tour_id: str):
        """Mark a tour as completed for a user."""
        if user_id not in self._completed_tours:
            self._completed_tours[user_id] = {}
        self._completed_tours[user_id][tour_id] = datetime.utcnow()

    def get_user_progress(self, user_id: str) -> Dict[str, Any]:
        """Get onboarding progress for a user."""
        completed = self._completed_tours.get(user_id, {})
        dismissed = self._dismissed_tips.get(user_id, [])

        total_tours = len(self.TOURS)
        completed_count = len(completed)

        return {
            "user_id": user_id,
            "completed_tours": list(completed.keys()),
            "dismissed_tips": dismissed,
            "progress": {
                "total_tours": total_tours,
                "completed": completed_count,
                "percentage": round(completed_count / total_tours * 100, 1) if total_tours > 0 else 0,
            },
        }

    def dismiss_tip(self, user_id: str, tip_id: str):
        """Dismiss a tip (don't show again)."""
        if user_id not in self._dismissed_tips:
            self._dismissed_tips[user_id] = []
        if tip_id not in self._dismissed_tips[user_id]:
            self._dismissed_tips[user_id].append(tip_id)

    def reset_onboarding(self, user_id: str):
        """Reset all onboarding progress for a user."""
        self._completed_tours.pop(user_id, None)
        self._dismissed_tips.pop(user_id, None)


# Global onboarding manager
onboarding_manager = OnboardingManager()


# ---- Contextual Tips Database ----

CONTEXTUAL_TIPS = {
    "chat_empty": {
        "id": "chat_empty_tip",
        "title": "Need inspiration?",
        "content": "Try asking the AI to analyze data, write a report, or browse the web for you.",
        "action": "Start a conversation",
    },
    "skills_empty": {
        "id": "skills_empty_tip",
        "title": "No skills installed yet",
        "content": "Install skills to extend the AI's capabilities. Browse the marketplace to get started.",
        "action": "Browse Skills",
    },
    "first_login": {
        "id": "first_login_tip",
        "title": "Welcome to CoApis!",
        "content": "Take a quick tour to learn about the main features.",
        "action": "Start Tour",
    },
}


# ---- API Router ----

router = APIRouter(prefix="/api/onboarding", tags=["Onboarding"])


@router.get("/tours")
async def get_tours(category: Optional[str] = None):
    """Get available feature tours."""
    tours = onboarding_manager.get_tours(category)
    return {
        "tours": [t.to_dict() for t in tours],
        "categories": onboarding_manager.get_tour_categories(),
    }


@router.get("/tours/{tour_id}")
async def get_tour(tour_id: str):
    """Get a specific tour."""
    tour = onboarding_manager.get_tour(tour_id)
    if not tour:
        raise HTTPException(status_code=404, detail=f"Tour not found: {tour_id}")
    return tour.to_dict()


@router.post("/tours/{tour_id}/complete")
async def complete_tour(request: Request, tour_id: str):
    """Mark a tour as completed."""
    user_info = getattr(request.state, "user_info", None)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = user_info.get("username") or user_info.get("sub", "anonymous")
    onboarding_manager.mark_tour_completed(user_id, tour_id)

    return {"ok": True}


@router.get("/progress")
async def get_progress(request: Request):
    """Get user's onboarding progress."""
    user_info = getattr(request.state, "user_info", None)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = user_info.get("username") or user_info.get("sub", "anonymous")
    progress = onboarding_manager.get_user_progress(user_id)

    return progress


@router.get("/tips")
async def get_contextual_tips(context: Optional[str] = None):
    """Get contextual tips based on current context."""
    if context:
        tip = CONTEXTUAL_TIPS.get(context)
        if tip:
            return {"tips": [tip]}
        return {"tips": []}

    return {"tips": list(CONTEXTUAL_TIPS.values())}


@router.post("/tips/{tip_id}/dismiss")
async def dismiss_tip(request: Request, tip_id: str):
    """Dismiss a tip (don't show again)."""
    user_info = getattr(request.state, "user_info", None)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = user_info.get("username") or user_info.get("sub", "anonymous")
    onboarding_manager.dismiss_tip(user_id, tip_id)

    return {"ok": True}


@router.post("/reset")
async def reset_onboarding(request: Request):
    """Reset all onboarding progress."""
    user_info = getattr(request.state, "user_info", None)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = user_info.get("username") or user_info.get("sub", "anonymous")
    onboarding_manager.reset_onboarding(user_id)

    return {"ok": True}
