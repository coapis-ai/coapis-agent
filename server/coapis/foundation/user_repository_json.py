# -*- coding: utf-8 -*-
"""JSON-based user repository implementation for Community edition.

This wraps the existing user_store.py functionality into a Repository interface,
allowing seamless transition to Enterprise edition's PostgreSQL storage.
"""

import logging
from typing import Dict, List, Optional, Any

from .user_repository import UserRepository, User

logger = logging.getLogger(__name__)


class JsonUserRepository(UserRepository):
    """JSON-based user repository for Community edition.

    This implementation wraps the existing user_store.py functions,
    providing a clean Repository interface while maintaining backward compatibility.
    """

    def __init__(self):
        """Initialize JSON user repository."""
        # Import user_store functions here to avoid circular imports
        from ..app.user_store import (
            get_user,
            create_user as store_create_user,
            update_user as store_update_user,
            delete_user as store_delete_user,
            list_users as store_list_users,
        )
        self._get_user = get_user
        self._create_user = store_create_user
        self._update_user = store_update_user
        self._delete_user = store_delete_user
        self._list_users = store_list_users

    async def create_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new user in JSON storage.

        Args:
            user_data: User data including username, password, email, etc.

        Returns:
            Created user as dictionary
        """
        try:
            # Call existing user_store function
            result = self._create_user(
                username=user_data.get("username"),
                password=user_data.get("password"),
                display_name=user_data.get("display_name"),
                email=user_data.get("email"),
                role=user_data.get("role", "user"),
            )

            if not result:
                raise ValueError(f"Failed to create user: {user_data.get('username')}")

            logger.info(f"Created user: {user_data.get('username')} (JSON storage)")
            return result

        except Exception as e:
            logger.error(f"Error creating user: {e}")
            raise

    async def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID from JSON storage.

        Note: JSON storage doesn't have efficient ID lookup, so we need to scan.
        This is one reason why Enterprise uses PostgreSQL.
        """
        try:
            users = await self._list_all_users()
            for user in users:
                if user.get("id") == user_id:
                    return user
            return None
        except Exception as e:
            logger.error(f"Error getting user by ID {user_id}: {e}")
            return None

    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username from JSON storage."""
        try:
            user = self._get_user(username)
            if user:
                logger.debug(f"Found user: {username} (JSON storage)")
            return user
        except Exception as e:
            logger.error(f"Error getting user {username}: {e}")
            return None

    async def update_user(self, user_id: int, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update user in JSON storage.

        Args:
            user_id: User ID (converted to username for JSON storage)
            user_data: Updated user data

        Returns:
            Updated user as dictionary
        """
        try:
            # JSON storage uses username, not ID, so we need to find the user first
            user = await self.get_user_by_id(user_id)
            if not user:
                raise ValueError(f"User not found: {user_id}")

            username = user.get("username")

            # Update using existing function
            result = self._update_user(username, user_data)

            if not result:
                raise ValueError(f"Failed to update user: {username}")

            logger.info(f"Updated user: {username} (JSON storage)")
            return result

        except Exception as e:
            logger.error(f"Error updating user {user_id}: {e}")
            raise

    async def delete_user(self, user_id: int) -> bool:
        """Delete user from JSON storage (soft delete by setting is_active=False)."""
        try:
            # Find user first
            user = await self.get_user_by_id(user_id)
            if not user:
                return False

            username = user.get("username")

            # Use update to set is_active=False (soft delete)
            result = self._update_user(username, {"is_active": False})

            if result:
                logger.info(f"Deleted user: {username} (JSON storage, soft delete)")
                return True
            return False

        except Exception as e:
            logger.error(f"Error deleting user {user_id}: {e}")
            return False

    async def list_users(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> tuple[List[Dict[str, Any]], int]:
        """List users from JSON storage with pagination and filters.

        Note: JSON storage doesn't support efficient filtering/pagination,
        so we load all users and filter in memory.
        This is one reason why Enterprise uses PostgreSQL.
        """
        try:
            # Load all users
            all_users = await self._list_all_users()

            # Apply filters
            filtered_users = []
            for user in all_users:
                # Search filter
                if search:
                    search_lower = search.lower()
                    if not (
                        search_lower in user.get("username", "").lower() or
                        search_lower in (user.get("display_name") or "").lower() or
                        search_lower in (user.get("email") or "").lower()
                    ):
                        continue

                # Role filter
                if role and user.get("role") != role:
                    continue

                # Active status filter
                if is_active is not None and user.get("is_active") != is_active:
                    continue

                filtered_users.append(user)

            # Pagination
            total = len(filtered_users)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            page_users = filtered_users[start_idx:end_idx]

            logger.debug(f"Listed {len(page_users)}/{total} users (JSON storage)")
            return page_users, total

        except Exception as e:
            logger.error(f"Error listing users: {e}")
            return [], 0

    async def _list_all_users(self) -> List[Dict[str, Any]]:
        """List all users from JSON storage (internal helper)."""
        try:
            # Import here to avoid circular dependency
            from ..app.user_store import _load_users

            data = _load_users()
            users_data = data.get("users", {})

            # Convert to list of user dicts
            users = []
            for username, user_data in users_data.items():
                user_dict = {"username": username, **user_data}
                users.append(user_dict)

            # Sort by created_at descending (newest first)
            users.sort(key=lambda u: u.get("created_at", 0) or 0, reverse=True)

            return users

        except Exception as e:
            logger.error(f"Error loading all users: {e}")
            return []
