# -*- coding: utf-8 -*-
"""Scene-domain models: tags / scenes / user_scene_settings.

Mirrors ``community_schema.sql`` **exactly** (see ``models/user.py`` header
for the nullability / default conventions).

Nullability rule for the M1 domain: the legacy DDL marks *nearly every*
column ``NOT NULL`` — including those with server defaults (only a handful
are truly nullable: ``tags.parent_id``, ``scenes.category`` /
``scenes.primary_tag_id`` / ``scenes.created_by``). The models replicate
that precisely so Alembic autogenerate produces no spurious diffs against
legacy DBs and repository dict contracts stay byte-identical.

Timestamps are ISO-8601 text (M1 convention). JSON-ish columns are stored
as TEXT and converted at the repository layer.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow


class Tag(BaseRow):
    __tablename__ = "tags"

    id: Mapped[Optional[str]] = mapped_column(
        Text, primary_key=True, nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    type: Mapped[str] = mapped_column(
        Text, nullable=False, default="custom", server_default=text("'custom'")
    )
    parent_id: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    keywords: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    related_skills: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    show_in_menu: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    enabled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    category: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # 'metadata' is reserved by the Declarative API — attribute is
    # ``metadata_``, DB column stays ``metadata``.
    metadata_: Mapped[str] = mapped_column(
        "metadata", Text, nullable=False, default="{}", server_default=text("'{}'")
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )

    __table_args__ = (Index("idx_tags_type", "type"),)


class Scene(BaseRow):
    __tablename__ = "scenes"

    scene_id: Mapped[Optional[str]] = mapped_column(
        Text, primary_key=True, nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    short_description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    icon: Mapped[str] = mapped_column(
        Text, nullable=False, default="📝", server_default=text("'📝'")
    )
    category: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="active", server_default=text("'active'")
    )
    system_prompt: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    welcome_message: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    skills: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    tags: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    tag_ids: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    primary_tag_id: Mapped[Optional[str]] = mapped_column(Text)
    usage_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_by: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )

    __table_args__ = (
        Index("idx_scenes_status", "status"),
        Index("idx_scenes_primary_tag", "primary_tag_id"),
    )


class UserSceneSettings(BaseRow):
    __tablename__ = "user_scene_settings"

    user_id: Mapped[Optional[str]] = mapped_column(
        Text, primary_key=True, nullable=True
    )
    enabled_scenes: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    custom_scenes: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    preferences: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default=text("'{}'")
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
