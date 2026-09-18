"""社区版标签仓储（SQLite）。

M1 域C：tags.json → ``tags`` 表。JSON 文件迁移后为只读备份，
本仓储是标签数据的唯一读写入口。

字段与 ``models/tag.py::TagConfig`` 一一对应（list/dict 存 JSON 文本）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_JSON_LIST_COLS = ("keywords", "related_skills")
_JSON_DICT_COLS = ("metadata",)
_INT_COLS = ("sort_order", "show_in_menu", "enabled")
_TEXT_COLS = ("name", "icon", "type", "parent_id", "description", "category", "created_at", "updated_at")


def _dumps(value: Any, is_list: bool) -> str:
    if value is None:
        value = [] if is_list else {}
    return json.dumps(value, ensure_ascii=False)


def _loads(text: Optional[str], is_list: bool, default: Any) -> Any:
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        logger.warning("tag json column parse failed, fallback default: %r", text[:100])
        return default


def _text(value: Any) -> str:
    """把任意值归一为可入库文本：datetime → ISO 字符串，None → 空串。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else str(value)


class SqliteTagRepository:
    """SQLite 标签仓储（社区版，非 enterprise）。"""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d: Dict[str, Any] = dict(row)
        for col in _JSON_LIST_COLS:
            d[col] = _loads(d.get(col), True, [])
        for col in _JSON_DICT_COLS:
            d[col] = _loads(d.get(col), False, {})
        d["sort_order"] = int(d.get("sort_order") or 0)
        # 0/1 整数列：用 .get(col, default) 而非 (col or default)，
        # 否则 disabled(enabled=0) 会被 `0 or 1` 误判成启用。
        d["show_in_menu"] = int(d.get("show_in_menu", 0))
        d["enabled"] = int(d.get("enabled", 1))
        return d

    @staticmethod
    def _dict_to_row(tag: Dict[str, Any]) -> Dict[str, Any]:
        row: Dict[str, Any] = {"id": tag.get("id")}
        for col in _TEXT_COLS:
            raw = tag.get(col)
            row[col] = (raw if raw else None) if col == "parent_id" else _text(raw)
        for col in _JSON_LIST_COLS:
            row[col] = _dumps(tag.get(col), True)
        for col in _JSON_DICT_COLS:
            row[col] = _dumps(tag.get(col), False)
        row["sort_order"] = int(tag.get("sort_order") or 0)
        row["show_in_menu"] = int(bool(tag.get("show_in_menu")))
        row["enabled"] = int(tag.get("enabled", 1))
        return row

    def _upsert_sql(self) -> str:
        cols = ["id", *_TEXT_COLS, *_JSON_LIST_COLS, *_JSON_DICT_COLS, *_INT_COLS]
        col_sql = ", ".join(cols)
        ph_sql = ", ".join(f":{c}" for c in cols)
        updates = [f"{c} = excluded.{c}" for c in cols if c != "id"]
        return (
            f"INSERT INTO tags ({col_sql}) VALUES ({ph_sql}) "
            f"ON CONFLICT(id) DO UPDATE SET {', '.join(updates)}"
        )

    # ------------------------------------------------------------------- CRUD

    def get_tag(self, tag_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_tags(
        self,
        type: Optional[str] = None,
        enabled_only: bool = False,
        keyword: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM tags"
        conds, params = [], []
        if type:
            conds.append("type = ?")
            params.append(type)
        if enabled_only:
            conds.append("enabled = 1")
        if keyword:
            conds.append("(name LIKE ? OR description LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY sort_order ASC, created_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_all(self) -> List[Dict[str, Any]]:
        return self.list_tags()

    def save_tag(self, tag: Dict[str, Any]) -> None:
        """按 id upsert。"""
        if not tag.get("id"):
            raise ValueError("tag must have id")
        row = self._dict_to_row(tag)
        with self._lock, self._conn:
            self._conn.execute(self._upsert_sql(), row)

    def _seed_sql(self) -> str:
        cols = ["id", *_TEXT_COLS, *_JSON_LIST_COLS, *_JSON_DICT_COLS, *_INT_COLS]
        col_sql = ", ".join(cols)
        ph_sql = ", ".join(f":{c}" for c in cols)
        return f"INSERT OR IGNORE INTO tags ({col_sql}) VALUES ({ph_sql})"

    def seed_many(self, tags: List[Dict[str, Any]]) -> int:
        """迁移种子：仅插入不存在的（INSERT OR IGNORE），绝不删除/覆盖已有行。

        幂等：重复执行不产生副作用；DB 里比 JSON 新出的行不受影响。
        返回实际插入条数。
        """
        inserted = 0
        with self._lock, self._conn:
            for t in tags:
                if not t.get("id"):
                    continue
                cur = self._conn.execute(self._seed_sql(), self._dict_to_row(t))
                inserted += cur.rowcount
        return inserted

    def save_many(self, tags: List[Dict[str, Any]]) -> None:
        """批量 upsert + reconcile（服务层 load-all → modify → save-all 模式）。

        - 空列表 → no-op（避免误清空整表）。
        - 否则：删除不在列表内的 id，再 upsert 列表内全部。这样删除标签才真正生效。
        """
        with self._lock, self._conn:
            ids = [t["id"] for t in tags if t.get("id")]
            if not ids:
                return
            ph = ",".join("?" * len(ids))
            self._conn.execute(f"DELETE FROM tags WHERE id NOT IN ({ph})", ids)
            for t in tags:
                self._conn.execute(self._upsert_sql(), self._dict_to_row(t))

    def delete_tag(self, tag_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        return cur.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
