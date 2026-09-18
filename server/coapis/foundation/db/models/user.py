# -*- coding: utf-8 -*-
"""User-domain models: users / user_settings / user_preferences / api_keys / audit_logs.

Every column mirrors ``community_schema.sql`` **exactly** (name, type,
nullability, server default, index) so that:

* existing dev/prod databases need zero data migration;
* Alembic autogenerate produces no spurious diffs against legacy DBs;
* repository dict contracts stay byte-identical to the sqlite3 code.

Nullability rule: the legacy schema marks only a few columns NOT NULL
(username / password_hash / salt / …); every other column — including
those with server defaults — is nullable in SQLite. The models replicate
that precisely.

Timestamps are epoch floats (REAL) — the API contract is
``new Date(ts * 1000)``.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Index, Integer, REAL, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow


class User(BaseRow):
    __tablename__ = "users"

    id: Mapped[Optional[str]] = mapped_column(
        Text, primary_key=True, nullable=True
    )
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    salt: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(Text)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text)
    token_quota_monthly: Mapped[Optional[int]] = mapped_column(
        Integer, default=1_000_000, server_default=text("1000000")
    )
    token_used_monthly: Mapped[Optional[int]] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    role: Mapped[Optional[str]] = mapped_column(
        Text, default="user", server_default=text("'user'")
    )
    is_active: Mapped[Optional[int]] = mapped_column(
        Integer, default=1, server_default=text("1")
    )
    created_at: Mapped[Optional[float]] = mapped_column(REAL)
    updated_at: Mapped[Optional[float]] = mapped_column(REAL)
    last_login_at: Mapped[Optional[float]] = mapped_column(REAL)
    muga_key: Mapped[Optional[str]] = mapped_column(Text)
    password_set_by_user: Mapped[Optional[int]] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    onboarding_completed: Mapped[Optional[int]] = mapped_column(
        Integer, default=1, server_default=text("1")
    )

    __table_args__ = (
        Index("idx_users_username", "username"),
        Index("idx_users_email", "email"),
        Index("idx_users_created", "created_at"),
    )


class UserSetting(BaseRow):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    setting_key: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    setting_value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[float]] = mapped_column(REAL)


class UserPreference(BaseRow):
    __tablename__ = "user_preferences"

    id: Mapped[Optional[int]] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=True
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    username: Mapped[Optional[str]] = mapped_column(Text)
    settings: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[float]] = mapped_column(REAL)


class ApiKey(BaseRow):
    __tablename__ = "api_keys"

    id: Mapped[Optional[int]] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=True
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[Optional[str]] = mapped_column(
        Text, default="[]", server_default=text("'[]'")
    )
    is_active: Mapped[Optional[int]] = mapped_column(
        Integer, default=1, server_default=text("1")
    )
    created_at: Mapped[Optional[float]] = mapped_column(REAL)
    last_used_at: Mapped[Optional[float]] = mapped_column(REAL)

    __table_args__ = (Index("idx_api_keys_user", "user_id"),)


class AuditLog(BaseRow):
    __tablename__ = "audit_logs"

    id: Mapped[Optional[int]] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(Text)
    username: Mapped[Optional[str]] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(Text)
    resource_id: Mapped[Optional[str]] = mapped_column(Text)
    details: Mapped[Optional[str]] = mapped_column(Text)
    ip_address: Mapped[Optional[str]] = mapped_column(Text)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[float]] = mapped_column(REAL)

    __table_args__ = (
        Index("idx_audit_logs_user", "user_id"),
        Index("idx_audit_logs_action", "action"),
        Index("idx_audit_logs_created", "created_at"),
    )
