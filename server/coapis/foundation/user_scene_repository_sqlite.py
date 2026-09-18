"""用户场景偏好仓储（社区版）— SQLite。

域 D3：`user_scenes.json`（按 user_id 存 enabled_scenes / custom_scenes /
preferences）落到 `user_scene_settings` 表，与 `user_scenes.json` 并存（双写，
读以 DB 为准），消除"标签/场景改名后用户侧引用断裂、无 DB 持久化"的问题。

设计同 tag/scene 仓储：
- 线程安全（RLock），单连接，commit 后释放
- ``seed_many``：迁移种子，INSERT OR IGNORE，绝不删除/覆盖已有行（幂等）
- ``save_many``：upsert + reconcile（服务层 load-all/modify/save-all 模式）
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

_JSON_LIST_COLS = ("enabled_scenes", "custom_scenes")
_JSON_DICT_COLS = ("preferences",)
_TEXT_COLS = ("created_at", "updated_at")


def _loads(text: Optional[str], is_list: bool) -> Any:
    if text is None or text == "":
        return [] if is_list else {}
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return [] if is_list else {}


def _dumps(value: Any, is_list: bool) -> str:
    if value is None:
        value = [] if is_list else {}
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps([] if is_list else {}, ensure_ascii=False)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else str(value)


class SqliteUserSceneSettingsRepo:
    """用户场景偏好仓储（SQLite 后端）。"""

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._lock = threading.RLock()
        self._conn = self._connect()

    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        d["enabled_scenes"] = _loads(d.get("enabled_scenes"), True)
        d["custom_scenes"] = _loads(d.get("custom_scenes"), True)
        d["preferences"] = _loads(d.get("preferences"), False)
        return d

    @staticmethod
    def _dict_to_row(s: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "user_id": s.get("user_id"),
            "enabled_scenes": _dumps(s.get("enabled_scenes"), True),
            "custom_scenes": _dumps(s.get("custom_scenes"), True),
            "preferences": _dumps(s.get("preferences"), False),
            "created_at": _text(s.get("created_at")),
            "updated_at": _text(s.get("updated_at")),
        }

    def _upsert_sql(self) -> str:
        cols = ["user_id", *_JSON_LIST_COLS, *_JSON_DICT_COLS, *_TEXT_COLS]
        col_sql = ", ".join(cols)
        ph_sql = ", ".join(f":{c}" for c in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "user_id")
        return (
            f"INSERT INTO user_scene_settings ({col_sql}) VALUES ({ph_sql}) "
            f"ON CONFLICT(user_id) DO UPDATE SET {updates}"
        )

    def _seed_sql(self) -> str:
        cols = ["user_id", *_JSON_LIST_COLS, *_JSON_DICT_COLS, *_TEXT_COLS]
        col_sql = ", ".join(cols)
        ph_sql = ", ".join(f":{c}" for c in cols)
        return f"INSERT OR IGNORE INTO user_scene_settings ({col_sql}) VALUES ({ph_sql})"

    # ------------------------------------------------------------------
    def seed_many(self, settings_list: List[Dict[str, Any]]) -> int:
        """迁移种子：仅插入不存在的，绝不删除/覆盖。返回插入条数。"""
        inserted = 0
        with self._lock, self._conn:
            for s in settings_list:
                if not s.get("user_id"):
                    continue
                cur = self._conn.execute(self._seed_sql(), self._dict_to_row(s))
                inserted += cur.rowcount
        return inserted

    def save_many(self, settings_list: List[Dict[str, Any]]) -> None:
        """批量 upsert + reconcile。空列表 → no-op。"""
        with self._lock, self._conn:
            ids = [s["user_id"] for s in settings_list if s.get("user_id")]
            if not ids:
                return
            ph = ",".join("?" * len(ids))
            self._conn.execute(f"DELETE FROM user_scene_settings WHERE user_id NOT IN ({ph})", ids)
            for s in settings_list:
                self._conn.execute(self._upsert_sql(), self._dict_to_row(s))

    def save(self, s: Dict[str, Any]) -> None:
        """单条 upsert。"""
        if not s.get("user_id"):
            return
        with self._lock, self._conn:
            self._conn.execute(self._upsert_sql(), self._dict_to_row(s))

    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        """取某用户偏好，未设置返回 None。"""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM user_scene_settings WHERE user_id = ?", (user_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_all(self) -> List[Dict[str, Any]]:
        """全量偏好。"""
        with self._lock, self._conn:
            rows = self._conn.execute("SELECT * FROM user_scene_settings ORDER BY user_id").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete(self, user_id: str) -> bool:
        """删除某用户偏好。"""
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM user_scene_settings WHERE user_id = ?", (user_id,))
            return cur.rowcount > 0

    def count(self) -> int:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM user_scene_settings").fetchone()
            return int(row["c"]) if row else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
