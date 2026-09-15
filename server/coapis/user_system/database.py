# -*- coding: utf-8 -*-
"""User system database — thin shell over UserRepository (P1 refactor).

All 25 ``if self._use_database:`` branches removed.
Each method is a one-line delegate to ``RepositoryFactory.get_user_repository()``.
``int`` user_id is transparently converted to UUID string by the repository layer.

Public API is unchanged: callers can still use ``get_db().get_user_by_username(...)``,
``get_db().insert_audit_log(...)`` etc. with zero changes.

Storage backend:
  - Community: single-file SQLite at ``SYSTEM_DIR/coapis.db``
  - Enterprise: PostgreSQL (injected via RepositoryFactory)
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from ..foundation.repository_factory import RepositoryFactory
from ..foundation.user_repository import UserRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_db_instance: Optional["UserSystemDB"] = None
_db_lock = threading.Lock()


class UserSystemDB:
    """Thin facade over the active UserRepository.

    This class is a singleton. Use :func:`get_db` to obtain the instance.
    Every public method delegates to the repository selected by
    :class:`RepositoryFactory` (SQLite by default, JSON as escape hatch).

    D-6: ``user_id`` parameters accept both ``int`` (legacy) and ``str``
    (UUID hex). The repository layer handles the conversion transparently.
    """

    _instance: Optional["UserSystemDB"] = None
    _instance_lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Singleton accessor
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "UserSystemDB":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Repository accessor
    # ------------------------------------------------------------------

    @property
    def _repo(self) -> UserRepository:
        return RepositoryFactory.get_user_repository()

    # ------------------------------------------------------------------
    # User CRUD (1-14)
    # ------------------------------------------------------------------

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        return self._repo.get_user_by_username(username)

    def insert_user(self, user_data: Dict[str, Any]) -> str:
        """Create a new user. Returns the user ID (UUID hex string)."""
        return self._repo.create_user(user_data)

    def update_user(self, username: str, update_data: Dict[str, Any]) -> bool:
        return self._repo.update_user(username, update_data)

    def count_users(self) -> int:
        return self._repo.count_users()

    def count_active_users(self) -> int:
        return self._repo.count_active_users()

    def list_users(self) -> List[Dict[str, Any]]:
        return self._repo.list_users()

    def user_exists(self, username: str) -> bool:
        return self._repo.user_exists(username)

    def email_exists(self, email: str) -> bool:
        return self._repo.email_exists(email)

    def get_user_by_id(self, user_id: Any) -> Optional[Dict[str, Any]]:
        """Get user by ID. Accepts int (legacy) or str (UUID)."""
        return self._repo.get_user_by_id(user_id)

    def update_user_by_id(self, user_id: Any, update_data: Dict[str, Any]) -> bool:
        return self._repo.update_user_by_id(user_id, update_data)

    def delete_user_by_id(self, user_id: Any) -> bool:
        return self._repo.delete_user_by_id(user_id)

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return self._repo.get_user_by_email(email)

    def delete_user(self, username: str) -> bool:
        return self._repo.delete_user(username)

    def list_users_page(
        self, page: int = 1, page_size: int = 20, search: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        return self._repo.list_users_page(page, page_size, search)

    # ------------------------------------------------------------------
    # Audit / Points / Token (15-19)
    # ------------------------------------------------------------------

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
        self._repo.insert_audit_log(
            user_id, username, action, resource_type, resource_id,
            details, ip_address, user_agent,
        )

    def insert_point_transaction(
        self,
        user_id: Any,
        amount: int,
        balance_after: int,
        transaction_type: str,
        description: str = "",
        reference_id: str = "",
    ) -> None:
        self._repo.insert_point_transaction(
            user_id, amount, balance_after, transaction_type,
            description, reference_id,
        )

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
        self._repo.insert_token_usage(
            user_id, username, agent_id, model,
            input_tokens, output_tokens, total_tokens, cost_cents,
        )

    def get_user_token_usage(
        self,
        username: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._repo.get_user_token_usage(username, start_date, end_date)

    def get_agent_token_usage(
        self,
        agent_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._repo.get_agent_token_usage(agent_id, start_date, end_date)

    # ------------------------------------------------------------------
    # Preferences (20-23)
    # ------------------------------------------------------------------

    def get_user_preferences(self, username: str) -> Optional[Dict[str, Any]]:
        return self._repo.get_user_preferences(username)

    def save_user_preferences(self, username: str, prefs_data: Dict[str, Any]) -> None:
        self._repo.save_user_preferences(username, prefs_data)

    def get_user_preference(self, user_id: Any, key: str) -> Optional[str]:
        return self._repo.get_user_preference(user_id, key)

    def set_user_preference(self, user_id: Any, key: str, value: str) -> bool:
        return self._repo.set_user_preference(user_id, key, value)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying repository (release connections / file handles)."""
        RepositoryFactory.reset_user_repo()
        logger.info("UserSystemDB closed (repository reset)")


# ---------------------------------------------------------------------------
# Public accessor
# ---------------------------------------------------------------------------

def get_db() -> UserSystemDB:
    """Get the UserSystemDB singleton instance."""
    return UserSystemDB.get_instance()
