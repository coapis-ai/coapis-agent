"""社区版场景仓储（SQLite）。

M1 域D：scenes.json → ``scenes`` 表。JSON 文件迁移后为只读备份，
本仓储是场景数据的唯一读写入口（每场景 agent.json 仍落文件，不变）。

设计说明
--------
- 列结构与 ``models/scene.py::SceneConfig`` 字段一一对应
  （scalar 直接存，list 存 JSON 文本），读写无损。
  注意模型主键字段名为 ``id``，表主键列名为 ``scene_id``，
  由 ``to_scene_dict()`` / ``from_scene_dict()`` 负责映射。
- 时间字段沿用模型的 ISO-8601 字符串。
- 同步实现（与 SqliteUserRepository 一致），WAL + 每连接 RLock
  保证进程内并发安全（R4 同款策略）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_JSON_LIST_COLS = ("skills", "tags", "tag_ids")
_TEXT_COLS = (
    "name",
    "description",
    "short_description",
    "icon",
    "category",
    "status",
    "system_prompt",
    "welcome_message",
    "primary_tag_id",
    "created_by",
    "created_at",
    "updated_at",
)
_ALL_COLS = ["scene_id", *_TEXT_COLS, *_JSON_LIST_COLS, "usage_count"]


def _dumps_list(value: Any) -> str:
    if value is None:
        value = []
    return json.dumps(value, ensure_ascii=False)


def _loads_list(text: Optional[str]) -> list:
    if text is None or text == "":
        return []
    try:
        v = json.loads(text)
        return v if isinstance(v, list) else []
    except (TypeError, ValueError):
        logger.warning("scene list column parse failed, fallback []: %r", text[:100])
        return []


class SqliteSceneRepository:
    """SQLite 场景仓储（社区版，非 enterprise）。"""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

    # ---------------------------------------------------------------- mapping

    @staticmethod
    def row_to_scene_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """DB 行 → SceneConfig 形状的 dict（id 即 scene_id）。"""
        d: Dict[str, Any] = dict(row)
        d["id"] = d.pop("scene_id")
        for col in _JSON_LIST_COLS:
            d[col] = _loads_list(d.get(col))
        d["usage_count"] = int(d.get("usage_count") or 0)
        return d

    @staticmethod
    def scene_dict_to_row(scene: Dict[str, Any]) -> Dict[str, Any]:
        """SceneConfig 形状的 dict → DB 行。

        接受任意多余字段（忽略），与 ``SceneConfig(**scene)`` 的
        ``extra="forbid"`` 不冲突——调用方先经模型校验再入仓储。
        """
        row: Dict[str, Any] = {}
        row["scene_id"] = scene.get("id") or scene.get("scene_id")
        for col in _TEXT_COLS:
            v = scene.get(col)
            if v is None:
                v = "" if col in ("name", "icon", "status", "system_prompt",
                                  "welcome_message", "description", "short_description") else None
            row[col] = v
        for col in _JSON_LIST_COLS:
            row[col] = _dumps_list(scene.get(col))
        row["usage_count"] = int(scene.get("usage_count") or 0)
        return row

    def _upsert_sql(self) -> str:
        col_sql = ", ".join(_ALL_COLS)
        ph_sql = ", ".join(f":{c}" for c in _ALL_COLS)
        updates = [f"{c} = excluded.{c}" for c in _ALL_COLS if c != "scene_id"]
        return (
            f"INSERT INTO scenes ({col_sql}) VALUES ({ph_sql}) "
            f"ON CONFLICT(scene_id) DO UPDATE SET {', '.join(updates)}"
        )

    # ------------------------------------------------------------------- CRUD

    def get_scene(self, scene_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM scenes WHERE scene_id = ?", (scene_id,)
            ).fetchone()
        return self.row_to_scene_dict(row) if row else None

    def list_scenes(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM scenes"
        conds, params = [], []
        if status:
            conds.append("status = ?")
            params.append(status)
        if category:
            conds.append("category = ?")
            params.append(category)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY usage_count DESC, created_at DESC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self.row_to_scene_dict(r) for r in rows]

    def get_all(self) -> List[Dict[str, Any]]:
        return self.list_scenes()

    def save_scene(self, scene: Dict[str, Any]) -> None:
        """按 id upsert。"""
        if not (scene.get("id") or scene.get("scene_id")):
            raise ValueError("scene must have id")
        with self._lock, self._conn:
            self._conn.execute(self._upsert_sql(), self.scene_dict_to_row(scene))

    def _seed_sql(self) -> str:
        col_sql = ", ".join(_ALL_COLS)
        ph_sql = ", ".join(f":{c}" for c in _ALL_COLS)
        return f"INSERT OR IGNORE INTO scenes ({col_sql}) VALUES ({ph_sql})"

    def seed_many(self, scenes: List[Dict[str, Any]]) -> int:
        """迁移种子：仅插入不存在的（INSERT OR IGNORE），绝不删除/覆盖已有行。

        幂等：重复执行无副作用；DB 里比 JSON 新出的行不受影响。返回插入条数。
        """
        inserted = 0
        with self._lock, self._conn:
            for s in scenes:
                if not (s.get("id") or s.get("scene_id")):
                    continue
                cur = self._conn.execute(self._seed_sql(), self.scene_dict_to_row(s))
                inserted += cur.rowcount
        return inserted

    def save_many(self, scenes: List[Dict[str, Any]]) -> None:
        """批量 upsert + reconcile（服务层 load-all → modify → save-all 模式）。

        - 空列表 → no-op（避免误清空整表）。
        - 否则：删除不在列表内的 scene_id，再 upsert 列表内全部（硬删除才真正生效）。
        """
        with self._lock, self._conn:
            ids = [s.get("id") or s.get("scene_id") for s in scenes
                   if (s.get("id") or s.get("scene_id"))]
            if not ids:
                return
            ph = ",".join("?" * len(ids))
            self._conn.execute(f"DELETE FROM scenes WHERE scene_id NOT IN ({ph})", ids)
            for s in scenes:
                self._conn.execute(self._upsert_sql(), self.scene_dict_to_row(s))

    def delete_scene(self, scene_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM scenes WHERE scene_id = ?", (scene_id,))
        return cur.rowcount > 0

    # --------------------------------------------------------------- helpers

    def increment_usage(self, scene_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE scenes SET usage_count = usage_count + 1 WHERE scene_id = ?",
                (scene_id,),
            )

    def count_by_primary_tag(self, tag_id: str, status: str = "active") -> int:
        """primary_tag_id 命中的场景数（与 JSON 版 _count_scenes_by_tag 语义一致）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM scenes WHERE primary_tag_id = ? AND status = ?",
                (tag_id, status),
            ).fetchone()
        return int(row[0]) if row else 0

    def count_referencing(self, tag_id: str) -> int:
        """D6：引用该标签的场景数（primary_tag_id 或 tag_ids 含该标签）。"""
        n = 0
        for s in self.list_scenes():
            if s.get("primary_tag_id") == tag_id or tag_id in (s.get("tag_ids") or []):
                n += 1
        return n

    def list_referencing(self, tag_id: str) -> List[Dict[str, Any]]:
        """D6：列出引用该标签的场景（供删除拦截提示）。"""
        return [
            s
            for s in self.list_scenes()
            if s.get("primary_tag_id") == tag_id or tag_id in (s.get("tag_ids") or [])
        ]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
