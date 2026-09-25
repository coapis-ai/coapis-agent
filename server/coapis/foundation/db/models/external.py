# -*- coding: utf-8 -*-
"""External-identity models: external_bindings / external_systems.

Mirrors ``community_schema.sql`` **exactly** (see ``models/user.py`` header
for the nullability / default conventions).

Nullability rule for the M1 domain: the legacy DDL marks *nearly every*
column ``NOT NULL`` — including those with server defaults. The only truly
nullable columns are ``external_systems.identity_token_ttl`` (and the
surrogate / natural primary keys). The models replicate that precisely so
Alembic autogenerate produces no spurious diffs against legacy DBs and
repository dict contracts stay byte-identical.

``external_bindings.created_at`` is ``NOT NULL`` with **no** server default
(matches the legacy DDL exactly).

Timestamps are ISO-8601 text (M1 convention). JSON-ish columns are stored
as TEXT and converted at the repository layer.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow


class ExternalBinding(BaseRow):
    __tablename__ = "external_bindings"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_system: Mapped[str] = mapped_column(Text, nullable=False)
    external_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    email: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    extra_data: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default=text("'{}'")
    )
    # ── 外部系统 token（B 方案：从 extra_data 提升为一等公民列）────────
    # 登录成功后落库，token 刷新时更新；出站透传优先读这里的列。
    external_access_token: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    external_refresh_token: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    token_expires_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    token_updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("external_system", "external_user_id"),
        Index("idx_bindings_user", "user_id"),
    )


class ExternalSystem(BaseRow):
    __tablename__ = "external_systems"

    provider_id: Mapped[str] = mapped_column(
        Text, primary_key=True, nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    login_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="password", server_default=text("'password'")
    )
    sso: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default=text("'{}'")
    )
    status: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    show_on_login: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    user_mapping: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default=text("'{}'")
    )
    client_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    credential: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default=text("'{}'")
    )
    auth_mode: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    base_urls: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    identity_token_ttl: Mapped[Optional[int]] = mapped_column(Integer)
    extra_data: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default=text("'{}'")
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
