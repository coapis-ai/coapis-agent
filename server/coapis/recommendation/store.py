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

"""Recommendation data storage.

Manages user preferences, feedback history, and recommendation statistics.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class RecommendationStore:
    """Storage for recommendation system data."""
    
    def __init__(self, data_dir: Optional[str] = None):
        """Initialize recommendation store.
        
        Args:
            data_dir: Data directory path
        """
        self.data_dir = Path(data_dir or os.environ.get(
            "COAPIS_DATA", os.path.expanduser("~/.coapis/data")
        ))
        self._ensure_data_dir()
        
        # File paths
        self.user_prefs_file = self.data_dir / "user_preferences.json"
        self.feedback_file = self.data_dir / "feedback_history.json"
        self.stats_file = self.data_dir / "recommendation_stats.json"
    
    def _ensure_data_dir(self):
        """Ensure data directory exists."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_json(self, file_path: Path, default: Any = None) -> Any:
        """Load JSON file."""
        if file_path.exists():
            try:
                return json.loads(file_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to load {file_path}: {e}")
        return default or {}
    
    def _save_json(self, file_path: Path, data: Any):
        """Save JSON file."""
        try:
            file_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to save {file_path}: {e}")
    
    # ──────────────────────────────────────────────
    # User Preferences
    # ──────────────────────────────────────────────
    
    def get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """Get user preferences."""
        prefs = self._load_json(self.user_prefs_file, {})
        return prefs.get(user_id, {
            "hidden_categories": [],
            "dismissed_recommendations": [],
            "preferred_layout": "grid",
            "last_updated": None,
        })
    
    def save_user_preferences(self, user_id: str, preferences: Dict[str, Any]):
        """Save user preferences."""
        prefs = self._load_json(self.user_prefs_file, {})
        preferences["last_updated"] = datetime.now().isoformat()
        prefs[user_id] = preferences
        self._save_json(self.user_prefs_file, prefs)
    
    def hide_category(self, user_id: str, category: str):
        """Hide a recommendation category for a user."""
        prefs = self.get_user_preferences(user_id)
        if category not in prefs["hidden_categories"]:
            prefs["hidden_categories"].append(category)
            self.save_user_preferences(user_id, prefs)
    
    def dismiss_recommendation(self, user_id: str, recommendation_id: str):
        """Dismiss a specific recommendation."""
        prefs = self.get_user_preferences(user_id)
        if recommendation_id not in prefs["dismissed_recommendations"]:
            prefs["dismissed_recommendations"].append(recommendation_id)
            # Keep only last 50 dismissed
            prefs["dismissed_recommendations"] = prefs["dismissed_recommendations"][-50:]
            self.save_user_preferences(user_id, prefs)
    
    # ──────────────────────────────────────────────
    # Feedback History
    # ──────────────────────────────────────────────
    
    def record_feedback(
        self,
        user_id: str,
        recommendation_id: str,
        action: str,
        scene: Optional[str] = None,
    ):
        """Record user feedback on a recommendation."""
        feedback = self._load_json(self.feedback_file, {"entries": []})
        
        entry = {
            "user_id": user_id,
            "recommendation_id": recommendation_id,
            "action": action,
            "scene": scene,
            "timestamp": datetime.now().isoformat(),
        }
        
        feedback["entries"].append(entry)
        
        # Keep only last 1000 entries
        feedback["entries"] = feedback["entries"][-1000:]
        
        self._save_json(self.feedback_file, feedback)
        
        # Update stats
        self._update_stats(recommendation_id, action)
    
    def _update_stats(self, recommendation_id: str, action: str):
        """Update recommendation statistics."""
        stats = self._load_json(self.stats_file, {
            "clicks": {},
            "dismissals": {},
            "hides": {},
        })
        
        if action == "click":
            stats["clicks"][recommendation_id] = stats["clicks"].get(recommendation_id, 0) + 1
        elif action == "dismiss":
            stats["dismissals"][recommendation_id] = stats["dismissals"].get(recommendation_id, 0) + 1
        elif action == "hide":
            stats["hides"][recommendation_id] = stats["hides"].get(recommendation_id, 0) + 1
        
        self._save_json(self.stats_file, stats)
    
    def get_recommendation_stats(self) -> Dict[str, Any]:
        """Get recommendation statistics."""
        return self._load_json(self.stats_file, {
            "clicks": {},
            "dismissals": {},
            "hides": {},
        })
    
    def get_recommendation_effectiveness(self, recommendation_id: str) -> Dict[str, float]:
        """Get effectiveness metrics for a recommendation."""
        stats = self.get_recommendation_stats()
        
        clicks = stats["clicks"].get(recommendation_id, 0)
        dismissals = stats["dismissals"].get(recommendation_id, 0)
        hides = stats["hides"].get(recommendation_id, 0)
        
        total = clicks + dismissals + hides
        
        if total == 0:
            return {"click_rate": 0, "dismiss_rate": 0, "hide_rate": 0}
        
        return {
            "click_rate": clicks / total,
            "dismiss_rate": dismissals / total,
            "hide_rate": hides / total,
        }
    
    # ──────────────────────────────────────────────
    # Analytics
    # ──────────────────────────────────────────────
    
    def get_user_activity_summary(self, user_id: str) -> Dict[str, Any]:
        """Get summary of user's recommendation activity."""
        feedback = self._load_json(self.feedback_file, {"entries": []})
        
        user_entries = [e for e in feedback["entries"] if e["user_id"] == user_id]
        
        if not user_entries:
            return {
                "total_interactions": 0,
                "clicks": 0,
                "dismissals": 0,
                "hides": 0,
                "last_interaction": None,
            }
        
        clicks = sum(1 for e in user_entries if e["action"] == "click")
        dismissals = sum(1 for e in user_entries if e["action"] == "dismiss")
        hides = sum(1 for e in user_entries if e["action"] == "hide")
        
        return {
            "total_interactions": len(user_entries),
            "clicks": clicks,
            "dismissals": dismissals,
            "hides": hides,
            "last_interaction": user_entries[-1]["timestamp"] if user_entries else None,
        }
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Get global recommendation statistics."""
        stats = self.get_recommendation_stats()
        feedback = self._load_json(self.feedback_file, {"entries": []})
        
        total_clicks = sum(stats["clicks"].values())
        total_dismissals = sum(stats["dismissals"].values())
        total_hides = sum(stats["hides"].values())
        total_interactions = total_clicks + total_dismissals + total_hides
        
        # Get unique users
        unique_users = set(e["user_id"] for e in feedback.get("entries", []))
        
        # Get most clicked recommendations
        most_clicked = sorted(
            stats["clicks"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        return {
            "total_interactions": total_interactions,
            "total_clicks": total_clicks,
            "total_dismissals": total_dismissals,
            "total_hides": total_hides,
            "unique_users": len(unique_users),
            "most_clicked_recommendations": most_clicked,
            "click_rate": total_clicks / total_interactions if total_interactions > 0 else 0,
        }


# Global store instance
_store: Optional[RecommendationStore] = None


def get_store() -> RecommendationStore:
    """Get or create the global recommendation store."""
    global _store
    if _store is None:
        _store = RecommendationStore()
    return _store
