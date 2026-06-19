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

"""User Synchronization Service.

Implements bidirectional synchronization between CoApis's user system
and Seafile's user system.

CoApis User System (AI-specific attributes):
- Token quota/usage
- Points/level system
- API Key management
- AI preferences (theme, language, chat_display, default_model)
- Detailed audit logs
- Rate limiting by level

Seafile User System (Basic auth + groups):
- User CRUD (email as primary identifier)
- 2-level roles (admin/user/auditor)
- Group management
- Department management (Pro)
- Storage quota
- User activity logs

Synchronization Strategy:
- CoApis → Seafile: On register, create Seafile user
- Seafile → CoApis: On login, update CoApis user metadata
- Conflict Resolution: Timestamp-based with manual override option
"""
from __future__ import annotations

import logging
import time
import hashlib
import secrets
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

@dataclass
class UserSyncConfig:
    """Configuration for user synchronization."""
    # Email domain for Seafile users
    email_domain: str = "coapis.local"
    
    # Sync direction
    sync_on_register: bool = True
    sync_on_login: bool = True
    sync_on_update: bool = True
    sync_on_delete: bool = True
    
    # Password sync
    sync_password: bool = True
    
    # Conflict resolution
    conflict_strategy: str = "timestamp"  # "timestamp", "coapis", "seafile"
    
    # Retry settings
    retry_attempts: int = 3
    retry_delay: float = 1.0


@dataclass
class SyncResult:
    """Result of a synchronization operation."""
    success: bool
    operation: str
    username: str
    message: str = ""
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    
    @classmethod
    def ok(cls, operation: str, username: str, message: str = "") -> 'SyncResult':
        return cls(True, operation, username, message)
    
    @classmethod
    def fail(cls, operation: str, username: str, error: str) -> 'SyncResult':
        return cls(False, operation, username, error=error)


# ═══════════════════════════════════════════════════════════
# User Sync Service
# ═══════════════════════════════════════════════════════════

class UserSyncService:
    """User synchronization service between CoApis and Seafile.
    
    Usage:
        from coapis.app.services import SeafileClient, SeafileConfig
        from coapis.app.services.user_sync_service import UserSyncService
        
        # Initialize
        seafile_config = SeafileConfig(
            service_url="http://localhost:9000",
            admin_username="admin",
            admin_password="CoApis2026!"
        )
        seafile_client = SeafileClient(seafile_config)
        sync_service = UserSyncService(seafile_client)
        
        # Sync on register
        await sync_service.sync_on_register("username", "password", {...})
        
        # Sync on login
        await sync_service.sync_on_login("username")
    """
    
    def __init__(
        self,
        seafile_client: 'SeafileClient',  # noqa: F821
        config: Optional[UserSyncConfig] = None
    ):
        self.seafile = seafile_client
        self.config = config or UserSyncConfig()
        self._sync_locks: Dict[str, bool] = {}  # Prevent concurrent sync
    
    def _get_seafile_email(self, username: str) -> str:
        """Convert CoApis username to Seafile email."""
        if "@" in username:
            return username
        return f"{username}@{self.config.email_domain}"
    
    def _get_coapis_username(self, email: str) -> str:
        """Convert Seafile email to CoApis username."""
        if "@" in email:
            domain = email.split("@")[1]
            if domain == self.config.email_domain:
                return email.split("@")[0]
        return email
    
    async def _acquire_lock(self, username: str) -> bool:
        """Acquire sync lock for username."""
        if self._sync_locks.get(username):
            return False
        self._sync_locks[username] = True
        return True
    
    def _release_lock(self, username: str):
        """Release sync lock for username."""
        self._sync_locks[username] = False
    
    # ─── CoApis → Seafile Sync ────────────────────────
    
    async def sync_on_register(
        self,
        username: str,
        password: str,
        profile: Dict[str, Any]
    ) -> SyncResult:
        """Sync user to Seafile on registration.
        
        Creates a new user in Seafile with the same credentials.
        
        Args:
            username: CoApis username
            password: User password
            profile: User profile data
            
        Returns:
            SyncResult
        """
        if not self.config.sync_on_register:
            return SyncResult.ok("register_skip", username, "Sync disabled")
        
        if not await self._acquire_lock(username):
            return SyncResult.fail("register", username, "Sync in progress")
        
        try:
            email = self._get_seafile_email(username)
            name = profile.get("display_name", username)
            
            # Check if user already exists in Seafile
            existing = await self.seafile.get_user(email)
            if existing:
                # Update existing user
                if self.config.sync_password:
                    await self.seafile.reset_user_password(email, password)
                return SyncResult.ok("register_update", username, "Updated existing Seafile user")
            
            # Create new user in Seafile
            await self.seafile.create_user(
                email=email,
                password=password,
                name=name,
                is_staff=profile.get("is_admin", False),
                contact_email=profile.get("email", ""),
                affiliation=profile.get("affiliation", "")
            )
            
            # Create user repo for files
            await self.seafile.create_repo(
                name=f"{username}-files",
                username=email,
                description=f"Files for user {username}"
            )
            
            logger.info(f"User {username} synced to Seafile")
            return SyncResult.ok("register", username, "User created in Seafile")
            
        except Exception as e:
            logger.error(f"Failed to sync user {username} to Seafile: {e}")
            return SyncResult.fail("register", username, str(e))
        finally:
            self._release_lock(username)
    
    async def sync_on_update(
        self,
        username: str,
        profile: Dict[str, Any]
    ) -> SyncResult:
        """Sync user updates to Seafile.
        
        Updates user information in Seafile.
        
        Args:
            username: CoApis username
            profile: Updated profile data
            
        Returns:
            SyncResult
        """
        if not self.config.sync_on_update:
            return SyncResult.ok("update_skip", username, "Sync disabled")
        
        if not await self._acquire_lock(username):
            return SyncResult.fail("update", username, "Sync in progress")
        
        try:
            email = self._get_seafile_email(username)
            
            # Check if user exists in Seafile
            existing = await self.seafile.get_user(email)
            if not existing:
                return SyncResult.fail("update", username, "User not found in Seafile")
            
            # Update user information
            name = profile.get("display_name")
            is_active = profile.get("is_active")
            is_staff = profile.get("is_admin")
            
            await self.seafile.update_user(
                email=email,
                name=name,
                is_active=is_active,
                is_staff=is_staff
            )
            
            # Sync password if changed
            if self.config.sync_password and "password" in profile:
                await self.seafile.reset_user_password(email, profile["password"])
            
            logger.info(f"User {username} updated in Seafile")
            return SyncResult.ok("update", username, "User updated in Seafile")
            
        except Exception as e:
            logger.error(f"Failed to update user {username} in Seafile: {e}")
            return SyncResult.fail("update", username, str(e))
        finally:
            self._release_lock(username)
    
    async def sync_on_delete(
        self,
        username: str
    ) -> SyncResult:
        """Sync user deletion to Seafile.
        
        Deletes user from Seafile.
        
        Args:
            username: CoApis username
            
        Returns:
            SyncResult
        """
        if not self.config.sync_on_delete:
            return SyncResult.ok("delete_skip", username, "Sync disabled")
        
        if not await self._acquire_lock(username):
            return SyncResult.fail("delete", username, "Sync in progress")
        
        try:
            email = self._get_seafile_email(username)
            
            # Check if user exists in Seafile
            existing = await self.seafile.get_user(email)
            if not existing:
                return SyncResult.ok("delete", username, "User not found in Seafile")
            
            # Delete user's repos first
            repos = await self.seafile.list_repos(email)
            for repo in repos:
                # Note: Seafile doesn't have a direct delete repo API
                # We'll just delete the user
                pass
            
            # Delete user
            await self.seafile.delete_user(email)
            
            logger.info(f"User {username} deleted from Seafile")
            return SyncResult.ok("delete", username, "User deleted from Seafile")
            
        except Exception as e:
            logger.error(f"Failed to delete user {username} from Seafile: {e}")
            return SyncResult.fail("delete", username, str(e))
        finally:
            self._release_lock(username)
    
    # ─── Seafile → CoApis Sync ────────────────────────
    
    async def sync_on_login(
        self,
        username: str
    ) -> SyncResult:
        """Sync user from Seafile on login.
        
        Updates CoApis user metadata from Seafile.
        
        Args:
            username: CoApis username
            
        Returns:
            SyncResult
        """
        if not self.config.sync_on_login:
            return SyncResult.ok("login_skip", username, "Sync disabled")
        
        if not await self._acquire_lock(username):
            return SyncResult.fail("login", username, "Sync in progress")
        
        try:
            email = self._get_seafile_email(username)
            
            # Get user from Seafile
            seafile_user = await self.seafile.get_user(email)
            if not seafile_user:
                return SyncResult.fail("login", username, "User not found in Seafile")
            
            # Update CoApis user metadata
            from ..user_store import update_user
            
            # Update last login time
            update_user(username, {
                "seafile_last_sync": time.time(),
                "seafile_last_login": seafile_user.last_login,
            })
            
            logger.info(f"User {username} synced from Seafile on login")
            return SyncResult.ok("login", username, "User synced from Seafile")
            
        except Exception as e:
            logger.error(f"Failed to sync user {username} from Seafile: {e}")
            return SyncResult.fail("login", username, str(e))
        finally:
            self._release_lock(username)
    
    # ─── Bidirectional Sync ──────────────────────────────
    
    async def full_sync(
        self,
        username: str
    ) -> SyncResult:
        """Perform full bidirectional sync.
        
        Syncs user data in both directions.
        
        Args:
            username: CoApis username
            
        Returns:
            SyncResult
        """
        if not await self._acquire_lock(username):
            return SyncResult.fail("full_sync", username, "Sync in progress")
        
        try:
            email = self._get_seafile_email(username)
            
            # Get users from both systems
            from ..user_store import get_user
            
            coapis_user = get_user(username)
            seafile_user = await self.seafile.get_user(email)
            
            if not coapis_user:
                return SyncResult.fail("full_sync", username, "User not found in CoApis")
            
            if not seafile_user:
                return SyncResult.fail("full_sync", username, "User not found in Seafile")
            
            # Resolve conflicts based on strategy
            if self.config.conflict_strategy == "timestamp":
                # Use timestamp to determine which is newer
                coapis_time = coapis_user.get("updated_at", 0)
                seafile_time = seafile_user.last_login or seafile_user.created_at
                
                if coapis_time > seafile_time:
                    # CoApis is newer, sync to Seafile
                    result = await self.sync_on_update(username, coapis_user)
                else:
                    # Seafile is newer, sync to CoApis
                    result = await self._sync_seafile_to_coapis(username, seafile_user)
            elif self.config.conflict_strategy == "coapis":
                # CoApis always wins
                result = await self.sync_on_update(username, coapis_user)
            else:  # seafile
                # Seafile always wins
                result = await self._sync_seafile_to_coapis(username, seafile_user)
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to full sync user {username}: {e}")
            return SyncResult.fail("full_sync", username, str(e))
        finally:
            self._release_lock(username)
    
    async def _sync_seafile_to_coapis(
        self,
        username: str,
        seafile_user: 'UserInfo'  # noqa: F821
    ) -> SyncResult:
        """Sync user from Seafile to CoApis."""
        try:
            from ..user_store import update_user
            
            # Update CoApis user with Seafile data
            update_user(username, {
                "display_name": seafile_user.name,
                "is_active": seafile_user.is_active,
                "seafile_last_sync": time.time(),
            })
            
            return SyncResult.ok("seafile_to_coapis", username, "User synced from Seafile")
            
        except Exception as e:
            logger.error(f"Failed to sync user {username} from Seafile: {e}")
            return SyncResult.fail("seafile_to_coapis", username, str(e))
    
    # ─── Password Sync ───────────────────────────────────
    
    async def sync_password(
        self,
        username: str,
        old_password: str,
        new_password: str
    ) -> SyncResult:
        """Sync password change to Seafile.
        
        Args:
            username: CoApis username
            old_password: Old password (for verification)
            new_password: New password
            
        Returns:
            SyncResult
        """
        if not self.config.sync_password:
            return SyncResult.ok("password_skip", username, "Password sync disabled")
        
        if not await self._acquire_lock(username):
            return SyncResult.fail("password", username, "Sync in progress")
        
        try:
            email = self._get_seafile_email(username)
            
            # Verify old password in Seafile
            token = await self.seafile.login(email, old_password)
            
            # Reset password in Seafile
            await self.seafile.reset_user_password(email, new_password)
            
            logger.info(f"Password for user {username} synced to Seafile")
            return SyncResult.ok("password", username, "Password synced to Seafile")
            
        except Exception as e:
            logger.error(f"Failed to sync password for user {username}: {e}")
            return SyncResult.fail("password", username, str(e))
        finally:
            self._release_lock(username)
    
    # ─── Group Sync ──────────────────────────────────────
    
    async def sync_to_group(
        self,
        username: str,
        group_id: int
    ) -> SyncResult:
        """Add user to Seafile group.
        
        Args:
            username: CoApis username
            group_id: Seafile group ID
            
        Returns:
            SyncResult
        """
        if not await self._acquire_lock(username):
            return SyncResult.fail("group", username, "Sync in progress")
        
        try:
            email = self._get_seafile_email(username)
            
            # Note: Seafile's group API is not exposed in the standard API
            # This is a placeholder for future implementation
            logger.warning(f"Group sync not implemented for user {username}")
            return SyncResult.fail("group", username, "Group sync not implemented")
            
        except Exception as e:
            logger.error(f"Failed to sync user {username} to group: {e}")
            return SyncResult.fail("group", username, str(e))
        finally:
            self._release_lock(username)
    
    # ─── Bulk Operations ─────────────────────────────────
    
    async def sync_all_users(
        self,
        direction: str = "coapis_to_seafile"
    ) -> List[SyncResult]:
        """Sync all users.
        
        Args:
            direction: "coapis_to_seafile" or "seafile_to_coapis"
            
        Returns:
            List of SyncResult
        """
        results = []
        
        if direction == "coapis_to_seafile":
            from ..user_store import list_users
            
            users = list_users()
            for user in users:
                username = user.get("username", "")
                result = await self.sync_on_update(username, user)
                results.append(result)
        else:
            # Seafile to CoApis
            seafile_users = await self.seafile.list_users()
            for seafile_user in seafile_users:
                username = self._get_coapis_username(seafile_user.email)
                result = await self._sync_seafile_to_coapis(username, seafile_user)
                results.append(result)
        
        return results
