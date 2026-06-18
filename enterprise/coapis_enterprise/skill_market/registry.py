# -*- coding: utf-8 -*-
"""Enterprise Skill Registry with curation and review system.

Provides enhanced skill marketplace features:
- Skill curation and verification
- Review and rating system
- Enterprise-only skills
- Version management
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EnterpriseSkill(BaseModel):
    """Enterprise skill with curation metadata."""
    name: str
    display_name: str
    description: str
    version: str
    author: str
    category: str
    tags: List[str] = []
    rating: float = Field(0.0, ge=0.0, le=5.0)
    rating_count: int = 0
    install_count: int = 0
    featured: bool = False
    verified: bool = False
    pricing: str = Field("free", description="free|paid|enterprise")
    price_usd: float = Field(0.0, ge=0.0)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    
    # Enterprise fields
    review_status: str = Field("pending", description="pending|approved|rejected")
    reviewer_notes: str = ""
    enterprise_only: bool = False


class EnterpriseSkillRegistry:
    """Enterprise skill registry with curation features.
    
    Provides:
    - Skill submission and review workflow
    - Verification badges for approved skills
    - Enterprise-only skill management
    - Advanced search and filtering
    """
    
    def __init__(self):
        self._skills: Dict[str, EnterpriseSkill] = {}
        self._reviews: Dict[str, List[Dict[str, Any]]] = {}
        self._categories: List[str] = ["general", "utility", "ai", "integration", "security"]
        logger.info("Enterprise skill registry initialized")
    
    def add_skill(self, skill: EnterpriseSkill) -> bool:
        """Add skill to registry (requires review for public listing)."""
        self._skills[skill.name] = skill
        logger.info(f"Skill '{skill.name}' v{skill.version} added to registry")
        return True
    
    def approve_skill(self, name: str, notes: str = "") -> bool:
        """Approve a skill for public listing.
    
        Enterprise feature: Skill curation workflow.
        """
        if name not in self._skills:
            return False
        
        self._skills[name].review_status = "approved"
        self._skills[name].verified = True
        self._skills[name].reviewer_notes = notes
        logger.info(f"Skill '{name}' approved for public listing")
        return True
    
    def reject_skill(self, name: str, reason: str) -> bool:
        """Reject a skill submission.
    
        Enterprise feature: Skill curation workflow.
        """
        if name not in self._skills:
            return False
        
        self._skills[name].review_status = "rejected"
        self._skills[name].reviewer_notes = reason
        logger.info(f"Skill '{name}' rejected: {reason}")
        return True
    
    def list_skills(
        self,
        category: Optional[str] = None,
        verified_only: bool = False,
        enterprise_only: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """List skills with filtering.
    
        Enterprise feature: Advanced filtering and pagination.
        """
        skills = list(self._skills.values())
        
        # Apply filters
        if category:
            skills = [s for s in skills if s.category == category]
        
        if verified_only:
            skills = [s for s in skills if s.verified]
        
        if enterprise_only:
            skills = [s for s in skills if s.enterprise_only]
        
        # Pagination
        total = len(skills)
        start = (page - 1) * page_size
        end = start + page_size
        skills = skills[start:end]
        
        return {
            "items": [s.model_dump() for s in skills],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    
    def add_review(self, skill_name: str, rating: float, comment: str, author: str) -> bool:
        """Add review for a skill.
    
        Enterprise feature: Review and rating system.
        """
        if skill_name not in self._skills:
            return False
        
        if skill_name not in self._reviews:
            self._reviews[skill_name] = []
        
        self._reviews[skill_name].append({
            "rating": rating,
            "comment": comment,
            "author": author,
            "created_at": time.time(),
        })
        
        # Update skill rating
        reviews = self._reviews[skill_name]
        avg_rating = sum(r["rating"] for r in reviews) / len(reviews)
        self._skills[skill_name].rating = avg_rating
        self._skills[skill_name].rating_count = len(reviews)
        
        logger.info(f"Review added for '{skill_name}': {rating}/5")
        return True
    
    def get_skill(self, name: str) -> Optional[EnterpriseSkill]:
        """Get skill by name."""
        return self._skills.get(name)
    
    def get_reviews(self, skill_name: str) -> List[Dict[str, Any]]:
        """Get reviews for a skill."""
        return self._reviews.get(skill_name, [])
    
    def get_categories(self) -> List[str]:
        """Get available categories."""
        return self._categories.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get marketplace statistics.
    
        Enterprise feature: Analytics and reporting.
        """
        skills = list(self._skills.values())
        
        return {
            "total_skills": len(skills),
            "verified_skills": sum(1 for s in skills if s.verified),
            "enterprise_skills": sum(1 for s in skills if s.enterprise_only),
            "total_reviews": sum(len(r) for r in self._reviews.values()),
            "avg_rating": sum(s.rating for s in skills) / len(skills) if skills else 0,
            "total_installs": sum(s.install_count for s in skills),
        }
