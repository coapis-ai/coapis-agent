# -*- coding: utf-8 -*-
"""File-ledger model: file_records.

Append-only ledger of files materialized in user workspaces
(``workspaces/{username}/files/...``).  Rows are written by the file-write
hooks (``upload`` / ``write_file`` / ``edit_file`` / ``append_file``) and by
the reconcile sweep (``source='reconcile'``).  **No DELETE is ever issued**;
read paths deduplicate by ``file_path`` keeping the newest row.

``user_id`` stores the username string (same convention as
``token_usage.user_id``); timestamps are Unix epoch floats (REAL), the
user-domain convention inherited from the legacy schema.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Index, Integer, REAL, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow


class FileRecord(BaseRow):
    __tablename__ = "file_records"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(Text)
    agent_id: Mapped[Optional[str]] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[Optional[int]] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[Optional[float]] = mapped_column(REAL)

    __table_args__ = (
        Index("idx_file_records_user", "user_id"),
        Index("idx_file_records_session", "session_id"),
        Index("idx_file_records_created", "created_at"),
    )
