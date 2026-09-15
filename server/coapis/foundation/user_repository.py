# -*- coding: utf-8 -*-
"""User Repository abstraction layer.

This provides a clean abstraction for user storage operations,
allowing different implementations:
- Community: SqliteUserRepository (SQLite file)
- Enterprise: PostgresUserRepository (PostgreSQL)

P1: 23 abstract methods covering the full UserSystemDB public surface.
D-6: users.id is TEXT (UUID hex string), with deterministic int→uuid mapping for migration.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class User:
    """User entity - shared by Community and Enterprise editions.

    Core fields (Community + Enterprise):
        - id (UUID hex string), username, password_hash
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
    id: Optional[str] = None  # UUID hex string (e.g. "a1b2c3d4-...")
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
        """Convert to dictionary for serialization."""
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
        if self.created_at:
            result["created_at"] = self.created_at.isoformat()
        if self.updated_at:
            result["updated_at"] = self.updated_at.isoformat()
        if self.last_login_at:
            result["last_login_at"] = self.last_login_at.isoformat()
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
        """Create from dictionary (deserialization)."""
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

        # D-6: id may be int (legacy) or str (UUID)
        raw_id = data.get("id")
        if raw_id is not None and not isinstance(raw_id, str):
            raw_id = str(raw_id)

        return cls(
            id=raw_id,
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

    23 methods covering the full UserSystemDB public surface (P1).
    D-6: user_id is str (UUID hex string).
    """

    # ==================== User CRUD (1-14) ====================

    @abstractmethod
    def create_user(self, user_data: Dict[str, Any]) -> str:
        """Create a new user. Returns the user ID (UUID hex string)."""
        ...

    @abstractmethod
    def get_user_by_id(self, user_id: Any) -> Optional[Dict[str, Any]]:
        """Get user by ID. Accepts str (UUID) or int (legacy, mapped to UUID)."""
        ...

    @abstractmethod
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username."""
        ...

    @abstractmethod
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email. Returns None if email is empty."""
        ...

    @abstractmethod
    def update_user(self, username: str, update_data: Dict[str, Any]) -> bool:
        """Update user by username."""
        ...

    @abstractmethod
    def update_user_by_id(self, user_id: Any, update_data: Dict[str, Any]) -> bool:
        """Update user by ID."""
        ...

    @abstractmethod
    def delete_user(self, username: str) -> bool:
        """Delete user by username (hard delete)."""
        ...

    @abstractmethod
    def delete_user_by_id(self, user_id: Any) -> bool:
        """Delete user by ID (hard delete)."""
        ...

    @abstractmethod
    def list_users(self) -> List[Dict[str, Any]]:
        """List all users, sorted by created_at DESC."""
        ...

    @abstractmethod
    def list_users_page(
        self, page: int = 1, page_size: int = 20, search: Optional[str] = None
    ) -> tuple:
        """List users with pagination and optional search. Returns (users_list, total_count)."""
        ...

    @abstractmethod
    def user_exists(self, username: str) -> bool:
        """Check if a user with given username exists."""
        ...

    @abstractmethod
    def email_exists(self, email: str) -> bool:
        """Check if a user with given email exists. Returns False if email is empty."""
        ...

    @abstractmethod
    def count_users(self) -> int:
        """Count all users."""
        ...

    @abstractmethod
    def count_active_users(self) -> int:
        """Count active users."""
        ...

    # ==================== Audit / Points / Token (15-19) ====================

    @abstractmethod
    def insert_audit_log(
        self,
        user_id: Any,
        username: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
        user_agent: str = "",
    ) -> None:
        """Insert an audit log entry."""
        ...

    @abstractmethod
    def insert_point_transaction(
        self,
        user_id: Any,
        amount: int,
        balance_after: int,
        transaction_type: str,
        description: str = "",
        reference_id: str = "",
    ) -> None:
        """Insert a point transaction."""
        ...

    @abstractmethod
    def insert_token_usage(
        self,
        user_id: Any,
        username: str,
        agent_id: Optional[str],
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cost_cents: float = 0.0,
    ) -> None:
        """Insert a token usage record."""
        ...

    @abstractmethod
    def get_user_token_usage(
        self,
        username: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get token usage summary for a user."""
        ...

    @abstractmethod
    def get_agent_token_usage(
        self,
        agent_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get token usage summary for an agent."""
        ...

    # ==================== Preferences (20-23) ====================

    @abstractmethod
    def get_user_preferences(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user preferences (full dict) by username."""
        ...

    @abstractmethod
    def save_user_preferences(self, username: str, prefs_data: Dict[str, Any]) -> None:
        """Save user preferences (upsert by username)."""
        ...

    @abstractmethod
    def get_user_preference(self, user_id: Any, key: str) -> Optional[str]:
        """Get a single preference value by user_id and key."""
        ...

    @abstractmethod
    def set_user_preference(self, user_id: Any, key: str, value: str) -> bool:
        """Set a single preference value by user_id and key. Returns True on success."""
        ...
