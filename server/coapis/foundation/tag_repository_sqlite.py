# -*- coding: utf-8 -*-
"""M1 域C：tags.json → ``tags`` 表 — ORM implementation (T4).

Dialect-neutral rewrite of the legacy raw-sqlite3 repository. Persistence goes
through per-call SQLAlchemy sessions on the shared global engine, so this repo
is no longer tied to a concrete SQLite file: community resolves its URL from
COAPIS_DATABASE_URL / db_settings; enterprise PG uses exactly the same code path.

Public surface and row contract are unchanged (dict-in/dict-out), call-sites keep working::

    {"id","name","icon","type","parent_id"(nullable),"description",
     "keywords"(list),"related_skills"(list)","sort_order"(int),
     "show_in_menu"(int),"enabled"(int),"category","metadata"(dict),
     "created_at","updated_at"}

Semantics preserved from the legacy implementation:
* ``save_tag`` is a full-row upsert — every column is written (missing keys are
  filled with their defaults, exactly like the legacy ``_dict_to_row``). Unknown
  input keys (e.g. historical ``color``) are ignored without erroring.
* ``seed_many`` skips empty ids and never overwrites existing rows; returns the
  number of newly inserted tags. Idempotent.
* ``save_many(list)`` is a full reconcile inside ONE transaction: everything not
  in the list is deleted, then every provided row upserts. An EMPTY list (or one
  without any id) is a no-op — clearing must go through an explicit API call.

No raw sqlite3 calls and no shared-connection locking here: each method opens a
short-lived session from the pool via ``get_session()`` (one repo method == one
session == one transaction), same pattern as T2's user repository. The legacy
constructor signature is kept so existing factories/tests keep working;
``db_path`` is ignored — the URL comes from the global engine.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _loads_list(text: Optional[str]) -> list:
    if text is None or text == "" or text in ("null",):
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        logger.warning("tag json column parse failed, fallback default: %r", str(text)[:100])
        return []
    if not isinstance(parsed, list):  # defensive (legacy data drift)
        return [parsed]
    return parsed


def _loads_obj(raw: Optional[str]) -> dict:
    if raw is None or raw == "" or raw in ("null",):
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("tag metadata parse failed, fallback {}: %r", str(raw)[:100])
        return {}
    if not isinstance(parsed, dict):  # defensive (legacy data drift)
        return {"value": parsed}
    return parsed


def _dumps(value: Any, is_list: bool) -> str:
    """Serialize a JSON-bearing TEXT column; empty/None → ``[]`` / ``{}``."""
    if value in ("", None):
        value = [] if is_list else {}
    try:
        return json.dumps(list(value), ensure_ascii=False) \
            if is_list else json.dumps(dict(value), ensure_ascii=False)
    except (TypeError, ValueError):  # non-iterable scalar / bad dict — legacy tolerated ints etc.
        logger.warning("tag_repository._dumps fallback for %r (%s)", str(value)[:80], type(value).__name__)
        return "[]" if is_list else "{}"


def _text(value: Any) -> str:
    """把任意值归一为可入库文本：datetime → ISO 字符串，None → 空串。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else str(value)


def _int0(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


from .db.engine import get_session  # noqa: E402

from sqlalchemy import delete as sa_delete, select  # noqa: E402

from .db.models.scene import Tag  # noqa: E402


class SqliteTagRepository:
    """Dialect-neutral tag storage (community SQLite / enterprise PG).

    Legacy constructor signature kept so the factory keeps working unchanged;
    ``db_path`` is ignored — sessions come from the global engine.
    """

    def __init__(self, db_path=None) -> None:  # legacy signature kept for compatibility
        self._db_path = str(db_path or "") if not isinstance(db_path, type(None)) else ""

    @staticmethod
    def _row_to_dict(row: Tag) -> Dict[str, Any]:
        """ORM row → service-layer dict with JSON columns parsed."""
        d: Dict[str, Any] = {}
        for col in row.__table__.columns:  # type: ignore[attr-defined]
            attr_key = "metadata_" if col.name == "metadata" else col.key
            try:
                value = getattr(row, attr_key)
            except AttributeError:
                value = ""
            d[col.name] = value

        for col in ("keywords", "related_skills"):
            d[col] = _loads_list(d.get(col))
        meta_raw = d.pop("metadata")
        if isinstance(meta_raw, dict):  # already parsed (defensive)
            d["metadata"] = meta_raw
        else:
            d["metadata"] = _loads_obj(meta_raw)

        for col in ("sort_order", "show_in_menu"):
            raw = d.get(col)
            try:
                d[col] = int(raw) if raw is not None else 0
            except (TypeError, ValueError):
                d[col] = 0
        # 0/1 整数列：用 .get(col, default) 语义而非 `value or default`，
        # 否则 disabled(enabled=0) 会被误判成启用。
        raw_en = d.get("enabled")
        try:
            d["enabled"] = int(raw_en) if raw_en is not None else 1
        except (TypeError, ValueError):
            d["enabled"] = 1

        # 时间列：空串/None → None（TagConfig 字段 Optional[datetime] 不接受 ""）。
        for col in ("created_at", "updated_at"):
            raw = d.get(col)
            if isinstance(raw, str) and not raw.strip():
                d[col] = None

        return d

    @staticmethod
    def _dict_to_row(tag: Dict[str, Any]) -> Dict[str, Any]:
        """Service-layer dict → ORM values. Unknown keys ignored; missing filled with defaults."""
        raw_parent = tag.get("parent_id")
        row: Dict[str, Any] = {
            "id": str(tag["id"]),  # caller guarantees presence (save_tag/seed_many/save_many guard it)
            "name": _text(tag.get("name")),
            "icon": _text(tag.get("icon")),
            "type": _text(tag.get("type")) or "custom",
            "parent_id": None if raw_parent in ("", None) else str(raw_parent),
            "description": _text(tag.get("description")),
            "keywords": _dumps(tag.get("keywords"), True),
            "related_skills": _dumps(tag.get("related_skills"), True),
            "sort_order": int(tag.get("sort_order") or 0),
            "show_in_menu": int(bool(tag.get("show_in_menu"))),
            "enabled": int(tag.get("enabled", 1)),
            "category": _text(tag.get("category")),
            # 'metadata' is reserved by the Declarative API — attribute ``metadata_``.
            "metadata_": _dumps(tag.get("metadata"), False),
            "created_at": _text(tag.get("created_at")),
            "updated_at": _text(tag.get("updated_at")),
        }
        return row

    @staticmethod
    def _upsert(session, tag_id: str, values: Dict[str, Any]) -> None:
        """Full-row upsert by id (INSERT if absent else UPDATE every column)."""
        existing = session.execute(select(Tag.id).where(Tag.id == tag_id)).scalar_one_or_none()
        if existing is None:
            session.add(Tag(**values))
        else:  # type: ignore[union-attr]
            row_obj = session.get(Tag, tag_id)
            for key, value in values.items():
                setattr(row_obj, key, value)

    # ------------------------------------------------------------------- CRUD

    def get_tag(self, tag_id: str) -> Optional[Dict[str, Any]]:
        with get_session() as s:
            row = s.execute(select(Tag).where(Tag.id == tag_id)).scalar_one_or_none()
        return self._row_to_dict(row) if row else None

    def list_tags(
        self,
        type: Optional[str] = None,  # noqa: A002 — legacy signature kept for call-sites
        enabled_only: bool = False,
        keyword: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = select(Tag)
        if type:
            query = query.where(Tag.type == type)  # noqa: A003 — column named `type` in legacy schema
        if enabled_only:
            query = query.where(Tag.enabled == 1)
        if keyword:
            like = f"%{keyword}%"
            from sqlalchemy import or_

            query = query.where(or_(Tag.name.like(like), Tag.description.like(like)))
        with get_session() as s:
            rows = [r for r in s.execute(query.order_by(Tag.sort_order.asc(), Tag.created_at.desc())).scalars()]
        return [self._row_to_dict(r) for r in rows]

    def get_all(self) -> List[Dict[str, Any]]:
        return self.list_tags()

    def save_tag(self, tag: Dict[str, Any]) -> None:
        """按 id upsert（全行覆盖，缺失键填默认值）。"""
        if not tag.get("id"):
            raise ValueError("tag must have id")
        values = self._dict_to_row(tag)
        with get_session() as s:
            self._upsert(s, str(values["id"]), values)

    def seed_many(self, tags: List[Dict[str, Any]]) -> int:
        """迁移种子：仅插入不存在的（等价 INSERT OR IGNORE），绝不删除/覆盖已有行。

        幂等：重复执行不产生副作用；DB 里比 JSON 新出的行不受影响。
        返回实际插入条数。
        """
        candidates = [t for t in tags if t.get("id")]
        inserted = 0
        with get_session() as s:
            existing_ids = set(
                s.execute(select(Tag.id).where(Tag.id.in_([str(t["id"]) for t in candidates]))).scalars().all()
            )
            for t in tags:
                if not t.get("id"):
                    continue
                tag_id = str(t["id"])
                if tag_id in existing_ids:
                    continue  # never overwrite seeded/existing rows
                s.add(Tag(**self._dict_to_row(t)))
                inserted += 1
        return inserted

    def save_many(self, tags: List[Dict[str, Any]]) -> None:
        """批量 upsert + reconcile（服务层 load-all → modify → save-all 模式）。

        - 空列表/无有效 id → no-op（避免误清空整表），清库须走显式 API。
        - 否则在单个事务内：删除不在列表内的行，再全量 upsert 列表内容。
          这样删除标签才真正生效；重复 id 按出现顺序后者覆盖前者（同 legacy）。
        """
        ids = [str(t["id"]) for t in tags if t.get("id")]
        if not ids:
            return
        with get_session() as s:  # one transaction: delete-then-upsert, same order as legacy
            s.execute(sa_delete(Tag).where(Tag.id.not_in(set(ids))))
            for t in tags:
                if not t.get("id"):
                    continue
                self._upsert(s, str(t["id"]), self._dict_to_row(t))  # duplicate ids: later wins (legacy order)

    def delete_tag(self, tag_id: str) -> bool:
        with get_session() as s:
            result = s.execute(sa_delete(Tag).where(Tag.id == tag_id))
        return (result.rowcount or 0) > 0

    def close(self) -> None:
        """Legacy no-op — pooled connections are managed by the global engine."""
