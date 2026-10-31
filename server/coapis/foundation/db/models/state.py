# -*- coding: utf-8 -*-
"""migration_state — idempotency flags for one-shot data migrations.

``app_settings`` 挂在同一个模块里：它同样是 key/value 两列的 KV 表，只是
用途是运行期可改的全局设置项（判官设置等），不是迁移标记。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import REAL, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow


class MigrationState(BaseRow):
    __tablename__ = "migration_state"

    # NOTE: the Python attribute is ``key_`` because ``key`` is a reserved
    # Declarative attribute; the DB column stays ``key``.
    key_: Mapped[str] = mapped_column(
        "key", Text, primary_key=True, nullable=False
    )
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[float]] = mapped_column(REAL)


class AppSetting(BaseRow):
    """``app_settings`` — 全局设置项的 KV 表（value 存 JSON 文本）。

    与 :class:`MigrationState` 同形（``key`` 主键 + ``value`` + ``updated_at``），
    用途不同：这里放运行期可改的全局设置，例如判官设置项
    ``judgments/judge``（v14 §5.2）。库里没有现成的全局 KV 表，故新增本表；
    Alembic 迁移见 ``0021_app_settings``。
    """

    __tablename__ = "app_settings"

    key_: Mapped[str] = mapped_column(
        "key", Text, primary_key=True, nullable=False
    )
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[float]] = mapped_column(REAL)
