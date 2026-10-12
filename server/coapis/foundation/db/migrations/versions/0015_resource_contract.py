# -*- coding: utf-8 -*-
"""Resource contract: create ``resources`` + ``resource_refs`` (R1).

Two new tables, deliberately kept **separate** from ``file_records``:
``file_records`` is an append-only event stream (never DELETE, read paths
dedupe by ``file_path``); ``resources`` is a state table and ``resource_refs``
is the only source of reference counts. Merging them would break the
"never DELETE" contract and every existing read path.

``resource_key`` includes the owner component. The P0 fixed in migration 0014
was exactly a global UNIQUE on an owner-less key (``memories.dedup_key``): two
agents producing the same result collided on INSERT and the second writer's
row collapsed into the first writer's. Same defect must not be recreated here.

Reference counts are derived from ``resource_refs`` — no redundant count
column (a denormalised counter drifts from the relation table and the drift
is undetectable).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _existing_indexes(table: str) -> set:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _existing_tables()

    if "resources" not in tables:
        op.create_table(
            "resources",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("resource_key", sa.Text(), nullable=False),
            sa.Column("owner_scope", sa.Text(), nullable=False),
            sa.Column("owner_id", sa.Text(), nullable=False),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("path", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("fs_present", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("first_seen_at", sa.Float(), nullable=True),
            sa.Column("last_seen_at", sa.Float(), nullable=True),
            sa.Column("updated_at", sa.Float(), nullable=True),
            sa.Column("deleted_at", sa.Float(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("resource_key"),
        )

    if "resource_refs" not in tables:
        op.create_table(
            "resource_refs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("resource_key", sa.Text(), nullable=False),
            sa.Column("referrer_kind", sa.Text(), nullable=False),
            sa.Column("referrer_id", sa.Text(), nullable=False),
            sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'reference'")),
            sa.Column("created_at", sa.Float(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("resource_key", "referrer_kind", "referrer_id"),
        )

    idxs = _existing_indexes("resources")
    for name, cols in (
        ("idx_resources_owner", ["owner_scope", "owner_id"]),
        ("idx_resources_kind", ["kind"]),
        ("idx_resources_status", ["status"]),
        ("idx_resources_fs", ["fs_present"]),
    ):
        if name not in idxs:
            op.create_index(name, "resources", cols)

    idxs = _existing_indexes("resource_refs")
    for name, cols in (
        ("idx_resource_refs_key", ["resource_key"]),
        ("idx_resource_refs_referrer", ["referrer_kind", "referrer_id"]),
    ):
        if name not in idxs:
            op.create_index(name, "resource_refs", cols)


def downgrade() -> None:
    tables = _existing_tables()
    if "resource_refs" in tables:
        for name in ("idx_resource_refs_referrer", "idx_resource_refs_key"):
            if name in _existing_indexes("resource_refs"):
                op.drop_index(name, table_name="resource_refs")
        op.drop_table("resource_refs")
    if "resources" in tables:
        for name in (
            "idx_resources_fs",
            "idx_resources_status",
            "idx_resources_kind",
            "idx_resources_owner",
        ):
            if name in _existing_indexes("resources"):
                op.drop_index(name, table_name="resources")
        op.drop_table("resources")
