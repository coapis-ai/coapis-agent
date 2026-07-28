# -*- coding: utf-8 -*-
"""User Repository abstraction layer.

This provides a clean abstraction for user storage operations,
allowing different implementations:
- Community: JsonUserRepository (JSON file storage)
- Enterprise: PostgresUserRepository (PostgreSQL storage)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any


@dataclass
class User:
    """User entity - shared by Community and Enterprise editions.

    Core fields (Community + Enterprise):
        - id, username, password_hash
        - display_name, email, avatar_url
        - role, is_active
        - created_at, updated_at, last_login_at

    Enterprise-only fields:
        - org_id, dept_id: Organization structure
        - tenant_id: Multi-tenant isolation
        - quota, points: Resource management
        - settings, preferences: User configuration
    """
    # Core fields
    id: Optional[int] = None
    username: str = ""
    password_hash: str = ""
    salt: str = ""
    display_name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str = "user"
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None

    # Enterprise-only fields (None in Community)
    org_id: Optional[str] = None
    dept_id: Optional[str] = None
    tenant_id: Optional[str] = None
    quota: Optional[Dict[str, Any]] = None
    points: Optional[int] = None
    settings: Optional[Dict[str, Any]] = None
    preferences: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "id": self.id,
            "username": self.username,
            "password_hash": self.password_hash,
            "salt": self.salt,
            "display_name": self.display_name,
            "email": self.email,
            "avatar_url": self.avatar_url,
            "role": self.role,
            "is_active": self.is_active,
        }

        # Optional datetime fields
        if self.created_at:
            result["created_at"] = self.created_at.isoformat()
        if self.updated_at:
            result["updated_at"] = self.updated_at.isoformat()
        if self.last_login_at:
            result["last_login_at"] = self.last_login_at.isoformat()

        # Enterprise fields (only include if not None)
        if self.org_id is not None:
            result["org_id"] = self.org_id
        if self.dept_id is not None:
            result["dept_id"] = self.dept_id
        if self.tenant_id is not None:
            result["tenant_id"] = self.tenant_id
        if self.quota is not None:
            result["quota"] = self.quota
        if self.points is not None:
            result["points"] = self.points
        if self.settings is not None:
            result["settings"] = self.settings
        if self.preferences is not None:
            result["preferences"] = self.preferences

        return result

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """Create from dictionary (JSON deserialization)."""
        # Parse datetime strings
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif isinstance(created_at, (int, float)):
            created_at = datetime.fromtimestamp(created_at)

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif isinstance(updated_at, (int, float)):
            updated_at = datetime.fromtimestamp(updated_at)

        last_login_at = data.get("last_login_at") or data.get("last_login")
        if isinstance(last_login_at, str):
            last_login_at = datetime.fromisoformat(last_login_at)
        elif isinstance(last_login_at, (int, float)):
            last_login_at = datetime.fromtimestamp(last_login_at)

        return cls(
            id=data.get("id"),
            username=data.get("username", ""),
            password_hash=data.get("password_hash", ""),
            salt=data.get("salt", ""),
            display_name=data.get("display_name"),
            email=data.get("email"),
            avatar_url=data.get("avatar_url"),
            role=data.get("role", "user"),
            is_active=data.get("is_active", True),
            created_at=created_at,
            updated_at=updated_at,
            last_login_at=last_login_at,
            # Enterprise fields
            org_id=data.get("org_id"),
            dept_id=data.get("dept_id"),
            tenant_id=data.get("tenant_id"),
            quota=data.get("quota"),
            points=data.get("points"),
            settings=data.get("settings"),
            preferences=data.get("preferences"),
        )


class UserRepository(ABC):
    """Abstract base class for user repositories.

    This provides the interface that all user repositories must implement,
    allowing seamless switching between storage backends.

    Community edition: JsonUserRepository (JSON files)
    Enterprise edition: PostgresUserRepository (PostgreSQL)
    """

    @abstractmethod
    async def create_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new user.

        Args:
            user_data: User data including username, password, email, etc.

        Returns:
            Created user as dictionary

        Raises:
            ValueError: If username already exists or invalid data
        """
        pass

    @abstractmethod
    async def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID.

        Args:
            user_id: User ID

        Returns:
            User as dictionary, or None if not found
        """
        pass

    @abstractmethod
    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username.

        Args:
            username: Username

        Returns:
            User as dictionary, or None if not found
        """
        pass

    @abstractmethod
    async def update_user(self, user_id: int, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update user.

        Args:
            user_id: User ID
            user_data: Updated user data

        Returns:
            Updated user as dictionary

        Raises:
            ValueError: If user not found
        """
        pass

    @abstractmethod
    async def delete_user(self, user_id: int) -> bool:
        """Delete user (soft delete by setting is_active=False).

        Args:
            user_id: User ID

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def list_users(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> tuple[List[Dict[str, Any]], int]:
        """List users with pagination and filters.

        Args:
            page: Page number (1-based)
            page_size: Number of users per page
            search: Search string for username/display_name/email
            role: Filter by role
            is_active: Filter by active status

        Returns:
            Tuple of (users list, total count)
        """
        pass
