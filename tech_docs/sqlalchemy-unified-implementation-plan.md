# CoApis 数据层统一 SQLAlchemy 实施方案 v1.0

> **决策背景（2026-09-17）**：用户明确推翻 K1（不引入 ORM）与 K2（不重写 14 仓储）
> 原约束。核心指令：
>
> 1. **统一使用 SQLAlchemy**，不允许裸 `sqlite3`
> 2. **一套模型、一套标准、一套迁移**，社区/企业共用
> 3. **代价再大也要改**
> 4. **遵守整体技术方案**（data-layer-unified-sqlite-plan v1.2 的 P1 范围 / D-6 / ABC 契约）
> 5. **不许胡乱发挥**

---

## 0. 设计原则

| # | 原则 | 说明 |
|---|------|------|
| P-1 | **单一事实来源** | 所有表结构由 SQLAlchemy Model 定义；Alembic 生成 DDL；不再有独立 SQL 文件 |
| P-2 | **方言无关** | 同一套 Model 跑 SQLite（社区）和 PostgreSQL（企业），用 SQLAlchemy 类型系统自动适配 |
| P-3 | **同步引擎** | 社区/企业均用同步 SQLAlchemy（`create_engine`），不引入 async |
| P-4 | **连接池** | 一个进程一个 Engine + 一个 Connection Pool（SQLite: StaticPool/NullPool; PG: QueuePool） |
| P-5 | **仓储模式不变** | 保留 ABC + Factory 注入，实现层从裸 sqlite3 换成 SQLAlchemy Session |
| P-6 | **Alembic 迁移** | 所有 schema 变更走 Alembic versioned migration；删除手写 `migrations.py` |
| P-7 | **Model 统一** | 一张表 = 一个 Model 类；社区/企业共享同一个 Model（企业扩展字段 nullable） |
| P-8 | **零方言分支** | 仓储实现中禁止出现 `if dialect == "postgresql"`；差异由 SQLAlchemy 类型系统吸收 |
| P-9 | **可测试性** | 每个仓储可注入 `session_factory`；测试用 `create_engine("sqlite:///:memory:")` |

---

## 1. 目录结构（目标态）

```
server/coapis/foundation/
├── __init__.py
├── db/                              # ★ 新增：统一 SQLAlchemy 层
│   ├── __init__.py
│   ├── engine.py                    # Engine + Session 工厂（社区/企业统一入口）
│   ├── base.py                      # DeclarativeBase（SQLAlchemy 2.0）
│   ├── models/                      # ★ 所有表 = Model 类
│   │   ├── __init__.py              # 导出全部 Model（供 Alembic 发现）
│   │   ├── user.py                  # users 表
│   │   ├── user_settings.py         # user_settings + user_preferences
│   │   ├── api_key.py               # api_keys
│   │   ├── audit_log.py             # audit_logs
│   │   ├── point_transaction.py     # point_transactions
│   │   ├── token_usage.py           # token_usage
│   │   ├── external_identity.py     # external_bindings
│   │   ├── external_system.py       # external_systems
│   │   ├── tag.py                   # tags
│   │   ├── scene.py                 # scenes
│   │   ├── user_scene_settings.py   # user_scene_settings
│   │   └── migration_state.py       # migration_state（过渡期用，Alembic 接管后废弃）
│   ├── repositories/                # ★ 仓储实现（用 SQLAlchemy）
│   │   ├── __init__.py
│   │   ├── user_repository.py       # ABC（从原 user_repository.py 移入）
│   │   ├── user_impl.py             # SQLAlchemyUserRepository
│   │   ├── tag_repository.py        # ABC + SqlaTagRepository
│   │   ├── scene_repository.py      # ABC + SqlaSceneRepository
│   │   ├── user_scene_repository.py # ABC + SqlaUserSceneRepository
│   │   └── external_identity_repo.py# ABC + SqlaExternalIdentityRepository
│   ├── migrations/                  # ★ Alembic
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       ├── 001_initial_schema.py
│   │       ├── 002_add_password_set_by_user.py
│   │       └── ...
│   └── seed.py                      # 初始数据（admin 用户、默认 tags、scenes）
├── repository_factory.py            # 改写：注入 SQLAlchemy 仓储
├── foundation_manager.py            # 适配新仓储接口
├── db_settings.py                   # 改写：返回 SQLAlchemy URL 而非 Path
└── sql/                             # ★ 删除（被 Alembic 取代）
    └── (community_schema.sql 等全部废弃)
```

> **企业版**（coapis-pro）对应改动：
> - 删除 `server/coapis/enterprise/database/models/`（改为 import 共享 Model）
> - 删除 `server/coapis/enterprise/database/repositories/`（改为使用共享仓储）
> - 保留 `server/coapis/enterprise/database/db_config.py` → 改指向共享 `db/engine.py`
> - 企业特有字段（tenant_id/org_id/dept_id 等）已在统一 Model 中 nullable 定义

---

## 2. 统一 Model 定义

### 2.1 Base

```python
# db/base.py
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

### 2.2 users 表（核心模型）

```python
# db/models/user.py
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class User(Base):
    __tablename__ = "users"

    # 主键（D-6: TEXT UUID hex string，社区/企业统一）
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # 基本身份
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    salt: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500))

    # 角色与状态
    role: Mapped[str] = mapped_column(String(50), default="user")
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    is_superuser: Mapped[int] = mapped_column(Integer, default=0)
    password_set_by_user: Mapped[int] = mapped_column(Integer, default=1)
    onboarding_completed: Mapped[int] = mapped_column(Integer, default=1)

    # Token 配额
    token_quota_monthly: Mapped[int] = mapped_column(Integer, default=1_000_000)
    token_used_monthly: Mapped[int] = mapped_column(Integer, default=0)

    # 企业扩展字段（社区版为 NULL）
    tenant_id: Mapped[Optional[str]] = mapped_column(String(64))
    org_id: Mapped[Optional[str]] = mapped_column(String(64))
    dept_id: Mapped[Optional[str]] = mapped_column(String(64))

    # 时间戳（统一用 DateTime；SQLite 自动映射为 REAL，PG 为 TIMESTAMP）
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # 杂项
    muga_key: Mapped[Optional[str]] = mapped_column(String(255))

    # 企业扩展：JSON 列（SQLite→TEXT, PG→JSON）
    settings: Mapped[Optional[str]] = mapped_column(Text)
    preferences: Mapped[Optional[str]] = mapped_column(Text)
    points: Mapped[Optional[int]] = mapped_column(Integer)
    quota: Mapped[Optional[str]] = mapped_column(Text)
```

**关键类型映射说明：**

| SQLAlchemy 类型 | SQLite 实际存储 | PostgreSQL 实际存储 |
|---|---|---|
| `String(n)` | VARCHAR | VARCHAR(n) |
| `Integer` | INTEGER | INTEGER |
| `Float` | REAL | DOUBLE PRECISION |
| `DateTime` | REAL (unix ts) 或 DATETIME | TIMESTAMP |
| `Text` | TEXT | TEXT |
| `Boolean` | INTEGER (0/1) | BOOLEAN |

> **JSON 列**：社区版统一用 `Text` 存 JSON 字符串（与现有 SQLite 一致，兼容迁移）；
> 企业版如需 native JSONB，在 Alembic migration 中针对 PG dialect 单独 ALTER。
> 仓储层用 `json.dumps/json.loads` 做序列化，对上层透明。

### 2.3 其余表（结构对照现有 schema）

| 表名 | Model 类 | 主键 | 核心列 |
|---|---|---|---|
| user_settings | UserSetting | (user_id, setting_key) | setting_value TEXT, updated_at DateTime |
| user_preferences | UserPreference | user_id (unique) | settings TEXT, username TEXT, updated_at |
| api_keys | ApiKey | id (auto) | user_id, name, key_prefix, key_hash, scopes, is_active |
| audit_logs | AuditLog | id (auto) | user_id, username, action, resource_type, resource_id, details, ip, ua, created_at |
| point_transactions | PointTransaction | id (auto) | user_id, amount, balance_after, type, description, ref_id, created_at |
| token_usage | TokenUsage | id (auto) | user_id, username, agent_id, model, input/out/total tokens, cost, created_at |
| external_bindings | ExternalBinding | id (auto) | user_id, external_system, external_user_id, display_name, email, extra_data, created_at; UNIQUE(external_system, external_user_id) |
| external_systems | ExternalSystem | provider_id | name, icon, login_type, sso, status, show_on_login, display_order, user_mapping, client_id, credential, auth_mode, base_urls, identity_token_ttl, extra_data |
| tags | Tag | id (String) | name, icon, type, parent_id, description, keywords, related_skills, sort_order, show_in_menu, enabled, category, metadata, created_at, updated_at |
| scenes | Scene | scene_id (String) | name, description, icon, category, status, system_prompt, welcome_message, skills, tags, tag_ids, primary_tag_id, usage_count, created_by, created_at, updated_at |
| user_scene_settings | UserSceneSettings | user_id | enabled_scenes, custom_scenes, preferences, created_at, updated_at |
| migration_state | MigrationState | key | value, updated_at |

> 每个 Model 的具体列与现有 `community_schema.sql` 一一对应，
> 仅做 SQLAlchemy 类型标注。企业扩展列（tenant_id, org_id, dept_id 等）
> 在统一 Model 中以 nullable 存在。

---

## 3. Engine 与 Session 管理

### 3.1 统一入口

```python
# db/engine.py
"""统一 SQLAlchemy Engine + Session 工厂。

社区版: SQLite (file-based, WAL mode, StaticPool 单连接)
企业版: PostgreSQL (QueuePool, 连接池)

唯一环境变量: COAPIS_DATABASE_URL
  - 社区: sqlite:////abs/path/coapis.db  或  system/coapis.db (相对 WORKING_DIR)
  - 企业: postgresql://user:pass@host:5432/dbname
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool, QueuePool

from ..constant import WORKING_DIR

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None
_lock = threading.Lock()


def _build_url() -> str:
    """从 COAPIS_DATABASE_URL 构造 SQLAlchemy URL。"""
    raw = os.environ.get("COAPIS_DATABASE_URL", "").strip()
    if not raw:
        # 默认: <WORKING_DIR>/system/coapis.db
        return f"sqlite:///{WORKING_DIR / 'system' / 'coapis.db'}"

    if raw.startswith("sqlite"):
        # 已是 SQLAlchemy 格式
        if raw.startswith("sqlite://"):
            rest = raw[len("sqlite://"):]
            if not rest.startswith("//"):
                # 相对路径 → 绝对
                p = (WORKING_DIR / rest.lstrip("/")).resolve()
                return f"sqlite:///{p}"
            return raw  # 已是绝对路径
        return raw
    if raw.startswith("postgresql") or raw.startswith("postgres"):
        # 企业版
        if raw.startswith("postgresql://"):
            return "postgresql+psycopg2://" + raw[len("postgresql://"):]
        if raw.startswith("postgres://"):
            return "postgresql+psycopg2://" + raw[len("postgres://"):]
        return raw
    raise ValueError(f"Unsupported COAPIS_DATABASE_URL scheme: {raw[:20]}...")


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def get_engine() -> Engine:
    """获取全局 Engine（lazy init, thread-safe）。"""
    global _engine, _session_factory
    if _engine is not None:
        return _engine

    with _lock:
        if _engine is not None:
            return _engine

        url = _build_url()
        if _is_sqlite(url):
            # SQLite: 单连接 + WAL（与现有行为一致）
            _engine = create_engine(
                url,
                poolclass=StaticPool,       # 单连接，避免锁竞争
                connect_args={
                    "check_same_thread": False,
                    "timeout": 30,
                },
                echo=False,
            )
            # 启用 WAL + 外键
            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, _):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()
        else:
            # PostgreSQL: 连接池
            _engine = create_engine(
                url,
                poolclass=QueuePool,
                pool_size=20,
                max_overflow=10,
                pool_recycle=3600,
                pool_pre_ping=True,
                echo=False,
            )

        _session_factory = sessionmaker(
            bind=_engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        return _engine


def get_session_factory() -> sessionmaker:
    """获取全局 Session 工厂。"""
    get_engine()  # 确保已初始化
    assert _session_factory is not None
    return _session_factory


@contextmanager
def get_session() -> Session:
    """Context manager: 自动 commit / rollback / close。"""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """测试用：销毁全局 Engine 并重置。"""
    global _engine, _session_factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _session_factory = None
```

### 3.2 与原 `db_settings.py` 的关系

- `db_settings.py` 保留为**兼容性层**（导出 `resolve_db_path()` 供旧代码引用）
- 新增 `db/engine.py` 为唯一真实入口
- 所有仓储通过 `get_session()` 获取 Session，不再各自 `sqlite3.connect()`

---

## 4. 仓储层（SQLAlchemy 实现）

### 4.1 设计约定

| 约定 | 说明 |
|------|------|
| Session 管理 | 每个方法内 `with get_session() as session:` 获取会话 |
| 返回值 | 保持与现有 ABC 一致（`Dict[str, Any]` / `List[Dict]` / `bool` / `int`） |
| 类型转换 | Model ↔ Dict 映射用 Model 类上的 `to_dict()` / `from_dict()` 方法 |
| 并发安全 | 由 SQLAlchemy 连接池 + SQLite WAL 保证，不再需要手动 RLock |
| 错误处理 | 捕获 `sqlalchemy.exc.SQLAlchemyError`，向上抛 `DataAccessError` |
| 时间戳 | 写入时用 `datetime.now(timezone.utc)`；读取时统一转 ISO string |

### 4.2 UserRepository 实现示例

```python
# db/repositories/user_impl.py
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select, update, delete, func

from ..base import Base
from ..engine import get_session
from ..models.user import User
from .user_repository import UserRepository  # ABC


class SqlaUserRepository(UserRepository):
    """统一 SQLAlchemy 用户仓储（社区/企业共用）。"""

    # ── User CRUD ──────────────────────────────────────────────────

    def create_user(self, user_data: Dict[str, Any]) -> str:
        user_id = user_data.get("id") or _generate_uuid()
        with get_session() as session:
            user = User(
                id=user_id,
                username=user_data["username"],
                password_hash=user_data.get("password_hash", ""),
                salt=user_data.get("salt", ""),
                display_name=user_data.get("display_name"),
                email=user_data.get("email"),
                avatar_url=user_data.get("avatar_url"),
                role=user_data.get("role", "user"),
                is_active=user_data.get("is_active", 1),
                password_set_by_user=user_data.get("password_set_by_user", 1),
                onboarding_completed=user_data.get("onboarding_completed", 1),
                tenant_id=user_data.get("tenant_id"),
                org_id=user_data.get("org_id"),
                dept_id=user_data.get("dept_id"),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                last_login_at=user_data.get("last_login_at"),
            )
            session.add(user)
        return user_id

    def get_user_by_id(self, user_id: Any) -> Optional[Dict[str, Any]]:
        with get_session() as session:
            user = session.execute(
                select(User).where(User.id == str(user_id))
            ).scalar_one_or_none()
            return user.to_dict() if user else None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        with get_session() as session:
            user = session.execute(
                select(User).where(User.username == username)
            ).scalar_one_or_none()
            return user.to_dict() if user else None

    # ... (其余 21 个方法同理：select/update/delete + to_dict)

    def list_users_page(
        self, page: int = 1, page_size: int = 20, search: Optional[str] = None
    ) -> tuple:
        with get_session() as session:
            q = select(User).order_by(User.created_at.desc())
            if search:
                like = f"%{search}%"
                q = q.where(
                    (User.username.like(like)) | (User.display_name.like(like))
                )
            total = session.execute(
                select(func.count()).select_from(q.subquery())
            ).scalar()
            users = session.execute(
                q.offset((page - 1) * page_size).limit(page_size)
            ).scalars().all()
            return [u.to_dict() for u in users], total

    # ... 其余方法
```

### 4.3 其余仓储

TagRepository / SceneRepository / UserSceneRepository / ExternalIdentityRepository
实现模式与上述完全一致：
- 使用对应 Model
- `with get_session() as session:` 获取会话
- CRUD 用 `session.execute(select(...))` / `session.add()` / `session.execute(update(...))`
- 返回 `Dict[str, Any]`（Model.to_dict()）

---

## 5. Alembic 迁移

### 5.1 配置

```ini
# alembic.ini (位于 server/coapis/foundation/db/migrations/alembic.ini)
[alembic]
script_location = .
sqlalchemy.url =  # 运行时从 COAPIS_DATABASE_URL 注入
```

```python
# db/migrations/env.py
from alembic import context
from sqlalchemy import engine_from_config, pool
import os, sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from coapis.foundation.db.base import Base
from coapis.foundation.db.models import *  # noqa: F401,F403 — 让 Alembic 发现所有 Model

target_metadata = Base.metadata


def run_migrations_online():
    raw_url = os.environ.get("COAPIS_DATABASE_URL", "").strip()
    # 与 db/engine.py 相同的 URL 解析逻辑
    config = context.config
    config.set_main_option("sqlalchemy.url", _build_url())

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()
```

### 5.2 首个迁移（001_initial_schema.py）

由 `alembic revision --autogenerate -m "initial schema"` 自动生成，
内容等价于现有 `community_schema.sql` 的全部 13 张表 + 索引。

### 5.3 迁移策略

| 阶段 | 动作 |
|------|------|
| 首次部署 | `alembic upgrade head` 建表 |
| 升级 | `alembic revision --autogenerate` + 人工审查 + `alembic upgrade head` |
| 回滚 | `alembic downgrade -1` |
| 数据迁移（JSON→DB） | 保留在 `db/seed.py` 中（一次性脚本，不走 Alembic），用 Model 操作数据 |

### 5.4 数据迁移脚本（JSON → DB）

```python
# db/seed.py
"""一次性数据迁移：从旧 JSON 文件导入数据到 SQLAlchemy 管理的 DB。

幂等：检查 migration_state 表中的标记。
"""

def migrate_users_from_json(json_path: Path) -> int:
    """users.json → users 表（UPSERT by username）。"""
    ...

def migrate_tags_from_json(json_path: Path) -> int:
    """tags.json → tags 表（UPSERT by id）。"""
    ...

def migrate_scenes_from_json(json_path: Path) -> int:
    """scenes.json → scenes 表（UPSERT by scene_id）。"""
    ...

def migrate_external_bindings_from_json(json_path: Path) -> int:
    """external_identity_mappings.json → external_bindings 表。"""
    ...

def run_all_migrations() -> None:
    """按顺序执行所有数据迁移（幂等）。"""
    ...
```

> 注意：数据迁移不走 Alembic（Alembic 只管 schema），
> 数据迁移是应用层的一次性脚本，用 `get_session()` 操作 Model。

---

## 6. RepositoryFactory 改写

```python
# repository_factory.py (改写)
from __future__ import annotations

import logging
from typing import Any, Optional

from .db.engine import get_session_factory
from .db.repositories.user_impl import SqlaUserRepository
from .db.repositories.tag_repository import SqlaTagRepository
from .db.repositories.scene_repository import SqlaSceneRepository
from .db.repositories.user_scene_repository import SqlaUserSceneRepository
from .db.repositories.external_identity_repo import SqlaExternalIdentityRepository

logger = logging.getLogger(__name__)


class RepositoryFactory:
    """统一仓储工厂（社区/企业共用，底层均为 SQLAlchemy）。"""

    _user_repo: Optional[Any] = None
    _tag_repo: Optional[Any] = None
    _scene_repo: Optional[Any] = None
    _user_scene_repo: Optional[Any] = None
    _external_repo: Optional[Any] = None
    _initialized: bool = False

    @classmethod
    def initialize(cls, edition: str = "community", **kwargs) -> None:
        """初始化所有仓储。

        社区版：自动创建 Engine（SQLite）+ 执行 Alembic upgrade + seed。
        企业版：自动创建 Engine（PG）+ 执行 Alembic upgrade。
        """
        if cls._initialized:
            logger.warning("RepositoryFactory already initialized, re-initializing...")
            cls._shutdown()

        from .db.engine import get_engine
        from alembic.config import Config
        from alembic import command

        # 1. 创建 Engine
        engine = get_engine()
        logger.info("Engine created: %s", engine.url)

        # 2. Alembic upgrade head
        alembic_cfg = Config(
            str(Path(__file__).parent / "db" / "migrations" / "alembic.ini")
        )
        command.upgrade(alembic_cfg, "head")
        logger.info("Alembic migration: upgrade head complete")

        # 3. 数据迁移（仅社区版首次启动时需要）
        if edition == "community":
            from .db.seed import run_all_migrations
            run_all_migrations()

        # 4. 创建仓储实例（无参构造，内部用 get_session()）
        cls._user_repo = SqlaUserRepository()
        cls._tag_repo = SqlaTagRepository()
        cls._scene_repo = SqlaSceneRepository()
        cls._user_scene_repo = SqlaUserSceneRepository()
        cls._external_repo = SqlaExternalIdentityRepository()
        cls._initialized = True
        logger.info("RepositoryFactory initialized (%s)", edition)

    @classmethod
    def get_user_repository(cls):
        return cls._user_repo

    # ... 其余 getter 同理

    @classmethod
    def _shutdown(cls) -> None:
        from .db.engine import reset_engine
        reset_engine()
        cls._user_repo = None
        # ... 全部置 None
        cls._initialized = False
```

---

## 7. 删除清单

| 文件/代码 | 动作 | 原因 |
|---|---|---|
| `foundation/sql/community_schema.sql` | **删除** | 由 Alembic Model 取代 |
| `foundation/sql/community_seed.sql` | **删除** | 由 `db/seed.py` 取代 |
| `foundation/sql/__init__.py` | **删除** | 同上 |
| `foundation/migrations.py` (783行) | **删除** | 由 Alembic 取代 |
| `foundation/user_repository_sqlite.py` (464行) | **删除** | 由 `db/repositories/user_impl.py` 取代 |
| `foundation/tag_repository_sqlite.py` (188行) | **删除** | 由 `db/repositories/tag_repository.py` 取代 |
| `foundation/scene_repository_sqlite.py` (235行) | **删除** | 由 `db/repositories/scene_repository.py` 取代 |
| `foundation/user_scene_repository_sqlite.py` (166行) | **删除** | 由 `db/repositories/user_scene_repository.py` 取代 |
| `foundation/external_identity_store_sqlite.py` (346行) | **删除** | 由 `db/repositories/external_identity_repo.py` 取代 |
| `foundation/user_repository.py` (ABC 308行) | **移动** 到 `db/repositories/user_repository.py` | 接口不变 |
| `foundation/repository_json.py` | **保留**（KnowledgeBase 仍用 JSON） | KB 不在本次范围 |
| `agents/tools/data_store.py` 中的 sqlite3 | **改为** SQLAlchemy | 统一 |
| `app/cleanup.py` 中的 sqlite3 | **改为** SQLAlchemy | 统一 |
| `app/channels/imessage/channel.py` 中的 sqlite3 | **保留**（外部 IME 数据库，只读） | 非业务数据 |
| `cli/doctor_checks.py` 中的 sqlite3 | **保留**（仅检查 sqlite 版本） | 诊断工具 |
| 企业版 `enterprise/database/models/*.py` | **删除** | 改为 import 共享 Model |
| 企业版 `enterprise/database/repositories/*.py` | **删除** | 改为使用共享仓储 |
| 企业版 `enterprise/database/db_config.py` | **删除** | 改为 import `db/engine.py` |

---

## 8. 实施阶段

### Phase 1: 地基（Day 1）

| 步骤 | 产出 | 验收 |
|------