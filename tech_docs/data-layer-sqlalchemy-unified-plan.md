# 数据层 SQLAlchemy 统一实施方案

> 版本: 1.0 | 日期: 2026-09-17 | 状态: 待拍板
> 决策背景: 用户明确否决"不引入 ORM"的旧约束（原 K1），要求统一使用 SQLAlchemy，代价再大也要改。
> 本方案取代 `data-layer-unified-sqlite-plan.md` 中的 K1 约束，其余决策（D-6/D-7/D-8/D-9）仍有效。

---

## 0. 设计原则（不可违反）

| # | 原则 | 说明 |
|---|---|---|
| P-1 | **单一 ORM** | 全系统（社区+企业）只使用 SQLAlchemy 2.0（ORM 模式），禁止裸 sqlite3 / 手写 SQL 出现在数据访问层 |
| P-2 | **单一模型源** | 所有表结构只定义一次（SQLAlchemy `DeclarativeBase`），社区和企业共用同一套 Model 类，通过 nullable 字段区分版本差异 |
| P-3 | **单一引擎** | 一个进程只有一个 Engine + 一个 SessionFactory。社区用 SQLite，企业用 PostgreSQL，但引擎创建逻辑统一 |
| P-4 | **Alembic 迁移** | 所有 schema 变更走 Alembic revision，禁止 `CREATE TABLE IF NOT EXISTS` 散落各处 |
| P-5 | **Repository 接口不变** | 现有 ABC（UserRepository 23 方法 / TagRepository / SceneRepository / ExternalIdentityStore）签名保持不变，只改内部实现 |
| P-6 | **同步模式** | 社区+企业都用同步 SQLAlchemy（`create_engine`，非 async），与现有 FastAPI 同步路由兼容 |
| P-7 | **dialect 中立** | Model 定义不引用 `sqlalchemy.dialects.postgresql.*`（除企业独有列），保证 SQLite / PG 均可跑 |
| P-8 | **fail-fast** | 启动时如果 DB 不可达/迁移未通过，直接报错，不降级 |

---

## 1. 当前状态（调研结论）

### 1.1 社区版（coapis-agent）

| 文件 | 行数 | 问题 |
|---|---|---|
| `user_repository_sqlite.py` | 464 | 裸 sqlite3，每连接 RLock，手写 JSON 序列化 |
| `tag_repository_sqlite.py` | 188 | 同上 |
| `scene_repository_sqlite.py` | 235 | 同上 |
| `user_scene_repository_sqlite.py` | 166 | 同上 |
| `external_identity_store_sqlite.py` | 346 | 同上 |
| `migrations.py` | 783 | 手写 executescript，无版本管理 |
| `db_settings.py` | 97 | 仅做路径解析 |
| `sql/community_schema.sql` | ~150 | 13 张表的 DDL（唯一事实来源） |

### 1.2 企业版（coapis-pro）

| 文件 | 问题 |
|---|---|
| `enterprise/database/models/*.py` | 旧式 `declarative_base + Column`，绑定 PG 特有类型（UUID, JSONB） |
| `enterprise/database/repositories/*.py` | 同步 SQLAlchemy Session，但模型与社区不可共用 |
| `enterprise/database/db_config.py` | 引擎配置合理但独立于社区 |

### 1.3 其他 sqlite3 使用点（不在本次范围）

- `agents/tools/data_store.py` — 工具数据缓存，非业务数据
- `app/channels/imessage/channel.py` — 读 iMessage 本地 DB（只读）
- `app/cleanup.py` — 清理会话数据（只读）
- `cli/doctor_checks.py` — 版本检测

> **范围界定**：本次只改 `foundation/` 下的 5 个仓储 + 迁移系统 + 引擎配置。上述非业务数据点保持不动。

---

## 2. 目标架构

```
coapis-agent/server/coapis/foundation/
├── db/                              ← 新增：统一数据层
│   ├── __init__.py
│   ├── engine.py                   ← 引擎+Session 工厂（统一入口）
│   ├── base.py                     ← DeclarativeBase
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py                 ← users
│   │   ├── user_settings.py        ← user_settings + user_preferences
│   │   ├── api_key.py              ← api_keys
│   │   ├── audit_log.py            ← audit_logs
│   │   ├── point.py                ← point_transactions
│   │   ├── token_usage.py          ← token_usage
│   │   ├── external_identity.py    ← external_bindings + external_systems
│   │   ├── tag.py                  ← tags
│   │   ├── scene.py                ← scenes + user_scene_settings
│   │   └── migration_state.py      ← migration_state
│   ├── session.py                  ← Session 上下文管理器
│   └── seed.py                     ← 初始化种子数据
├── migrations/                      ← 新增：Alembic
│   ├── alembic.ini
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial.py          ← 初始 schema（13 张表）
├── user_repository.py              ← ABC（不变）
├── user_repository_impl.py         ← 替代 user_repository_sqlite.py
├── tag_repository_impl.py          ← 替代 tag_repository_sqlite.py
├── scene_repository_impl.py        ← 替代 scene_repository_sqlite.py
├── user_scene_repository_impl.py   ← 替代 user_scene_repository_sqlite.py
├── external_identity_impl.py       ← 替代 external_identity_store_sqlite.py
├── repository_factory.py           ← 改造：注入 SQLAlchemy Session
├── db_settings.py                  ← 保留（路径解析逻辑复用）
└── foundation_manager.py           ← 保留（对外接口不变）
```

**删除的文件**（实现完成后）：
- `user_repository_sqlite.py`
- `tag_repository_sqlite.py`
- `scene_repository_sqlite.py`
- `user_scene_repository_sqlite.py`
- `external_identity_store_sqlite.py`
- `migrations.py`（由 Alembic 替代）
- `sql/` 目录（DDL 移入 Alembic migration）

---

## 3. 数据模型（SQLAlchemy 2.0）

### 3.1 类型映射（SQLite ↔ PG 兼容）

| 业务类型 | SQLAlchemy 类型 | SQLite 存储 | PG 存储 |
|---|---|---|---|
| UUID 主键 | `String(64)` | TEXT | VARCHAR(64) |
| 普通文本 | `String(N)` | TEXT | VARCHAR(N) |
| 长文本 | `Text` | TEXT | TEXT |
| 整数 | `Integer` | INTEGER | INTEGER |
| 浮点 | `Float` | REAL | DOUBLE PRECISION |
| JSON | `JSON` | TEXT（SQLite 方言自动处理） | JSONB（PG 方言自动处理） |
| 时间戳 | `DateTime` | REAL（SQLite 方言） | TIMESTAMP（PG 方言） |
| 布尔 | `Boolean` | INTEGER（0/1） | BOOLEAN |

> **关键点**：SQLAlchemy 的 `JSON` 和 `DateTime` 类型在 SQLite 方言下自动降级为 TEXT/REAL，在 PG 方言下自动升级为 JSONB/TIMESTAMPTZ。**模型定义一次，两边都能跑。**

### 3.2 统一 Model 定义（示例：users）

```python
# db/models/user.py
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    token_quota_monthly: Mapped[int] = mapped_column(Integer, default=1_000_000)
    token_used_monthly: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String(50), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    muga_key: Mapped[str | None] = mapped_column(String(255))
    password_set_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=True)

    # ---- 企业版扩展字段（社区版留 NULL）----
    tenant_id: Mapped[str | None] = mapped_column(String(64))
    org_id: Mapped[int | None] = mapped_column(Integer)
    dept_id: Mapped[int | None] = mapped_column(Integer)
    additional_roles: Mapped[list | None] = mapped_column(JSON, default=list)
    permissions: Mapped[list | None] = mapped_column(JSON, default=list)
    permissions_overrides: Mapped[dict | None] = mapped_column(JSON, default=dict)
    status: Mapped[str | None] = mapped_column(String(50))
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    points: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict | None] = mapped_column(JSON, default=dict)
    preferences: Mapped[dict | None] = mapped_column(JSON, default=dict)
    memo: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
```

> 社区版只使用前 17 列；企业版全用。同一 Model，两边兼容。

### 3.3 全部 13 张表的 Model 清单

| # | 表名 | Model 文件 | 主键 | 说明 |
|---|---|---|---|---|
| 1 | users | `user.py` | String(64) UUID | 用户主表 |
| 2 | user_settings | `user_settings.py` | (user_id, key) 复合 | key-value 设置 |
| 3 | user_preferences | `user_settings.py` | user_id | 整包 JSON 偏好 |
| 4 | api_keys | `api_key.py` | Integer 自增 | API 密钥 |
| 5 | audit_logs | `audit_log.py` | Integer 自增 | 审计日志（append-only） |
| 6 | point_transactions | `point.py` | Integer 自增 | 积分流水 |
| 7 | token_usage | `token_usage.py` | Integer 自增 | Token 用量 |
| 8 | migration_state | `migration_state.py` | key | 迁移标记 |
| 9 | external_bindings | `external_identity.py` | Integer 自增 | SSO 绑定 |
| 10 | external_systems | `external_identity.py` | provider_id | SSO 系统配置 |
| 11 | tags | `tag.py` | String(64) | 标签 |
| 12 | scenes | `scene.py` | String(64) | 场景 |
| 13 | user_scene_settings | `scene.py` | user_id | 用户场景定制 |

---

## 4. 引擎与会话管理

### 4.1 `db/engine.py`

```python
"""统一引擎工厂：一个进程一个 Engine。"""
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session
from ..db_settings import resolve_db_path
from ...constant import WORKING_DIR

_engine: Engine | None = None
_session_factory: sessionmaker | None = None

def get_engine() -> Engine:
    """惰性创建 Engine（单例）。"""
    global _engine, _session_factory
    if _engine is None:
        db_url = _build_url()
        _engine = create_engine(
            db_url,
            # SQLite 优化
            connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
            # 通用
            pool_pre_ping=True,
            echo=False,
        )
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine

def get_session() -> Session:
    """获取 Session（由 get_session_context 管理生命周期）。"""
    return get_engine()  # 确保 engine 已创建
    return _session_factory()

def _build_url() -> str:
    """根据 edition 构建 SQLAlchemy URL。"""
    import os
    raw = os.environ.get("COAPIS_DATABASE_URL", "").strip()
    if raw and raw.startswith("postgresql"):
        # 企业版
        return raw.replace("postgresql://", "postgresql+psycopg2://", 1)
    # 社区版：SQLite
    db_path = resolve_db_path()
    return f"sqlite:///{db_path}"
```

### 4.2 `db/session.py` — 上下文管理器

```python
from contextlib import contextmanager
from sqlalchemy.orm import Session

@contextmanager
def session_scope():
    """事务性会话：自动 commit / rollback / close。"""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

### 4.3 线程安全

- SQLAlchemy `Engine` 内部自带连接池（QueuePool），**不需要**手动 RLock
- SQLite WAL 模式下多读单写，连接池 `pool_size=5, max_overflow=3` 足够
- 每个 `session_scope()` 是短生命周期的（一个请求/一次操作），不存在长连接

---

## 5. Alembic 迁移

### 5.1 目录结构

```
foundation/migrations/
├── alembic.ini
├── env.py
├── script.py.mako
└── versions/
    └── 001_initial.py    ← 初始 schema（13 张表）
```

### 5.2 启动时行为

```python
# 在 RepositoryFactory.initialize() 中调用
from alembic.config import Config
from alembic import command

def run_migrations():
    cfg = Config("foundation/migrations/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", get_engine().url)
    command.upgrade(cfg, "head")
```

- **幂等**：Alembic 自动管理 `alembic_version` 表，已执行的 revision 不会重跑
- **替代**：替换现有 `migrations.py`（783行）+ `sql/community_schema.sql`
- **JSON 数据迁移**：初始 revision 之后加 `002_import_legacy_data.py`，从 JSON 文件导入历史数据（一次性的）

### 5.3 版本控制

- 每次 schema 变更 = 一个新 revision
- 禁止直接改旧 revision
- `alembic revision --autogenerate -m "description"` 自动生成

---

## 6. Repository 实现（SQLAlchemy 版）

### 6.1 设计模式

```python
class SQLAlchemyUserRepository(UserRepository):
    """UserRepository ABC 的 SQLAlchemy 实现。"""

    def _session(self) -> Generator[Session, None, None]:
        return session_scope()

    async def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with session_scope() as s:
            user = s.execute(
                select(User).where(User.username == username)
            ).scalar_one_or_none()
            return self._to_dict(user) if user else None

    def _to_dict(self, user: User) -> dict[str, Any]:
        """Model → dict（与现有 ABC 契约对齐）。"""
        return {
            "id": user.id,
            "username": user.username,
            "password_hash": user.password_hash,
            "salt": user.salt,
            "display_name": user.display_name,
            "email": user.email,
            "avatar_url": user.avatar_url,
            "token_quota_monthly": user.token_quota_monthly,
            "token_used_monthly": user.token_used_monthly,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at.timestamp() if user.created_at else None,
            "updated_at": user.updated_at.timestamp() if user.updated_at else None,
            "last_login_at": user.last_login_at.timestamp() if user.last_login_at else None,
            "muga_key": user.muga_key,
            "password_set_by_user": user.password_set_by_user,
            "onboarding_completed": user.onboarding_completed,
        }
```

### 6.2 5 个实现类对照

| 旧文件（删除） | 新文件 | 行数预估 |
|---|---|---|
| `user_repository_sqlite.py` (464) | `user_repository_impl.py` | ~380 |
| `tag_repository_sqlite.py` (188) | `tag_repository_impl.py` | ~140 |
| `scene_repository_sqlite.py` (235) | `scene_repository_impl.py` | ~170 |
| `user_scene_repository_sqlite.py` (166) | `user_scene_repository_impl.py` | ~120 |
| `external_identity_store_sqlite.py` (346) | `external_identity_impl.py` | ~250 |

**总计**：~1060 行新实现，替代现有 1399 行裸 sqlite3 代码。

### 6.3 关键改进

| 改进点 | 旧（裸 sqlite3） | 新（SQLAlchemy） |
|---|---|---|
| JSON 字段序列化 | 手动 `json.dumps/loads` | `JSON` 类型自动处理 |
| 时间戳 | 手动 `time.time()` / `.isoformat()` | `DateTime` 类型 + `datetime` 对象 |
| 连接管理 | 手动 `connect/close` + `RLock` | Engine 连接池自动管理 |
| 事务 | 手动 `commit/rollback` | `session_scope()` 上下文 |
| 查询 | 手写 SQL 字符串 | `select()` 表达式（类型安全） |
| 迁移 | 手写 executescript | Alembic revision |
| 新增列 | 手写 ALTER TABLE | `alembic revision --autogenerate` |

---

## 7. 企业版对齐

### 7.1 企业版改造

企业版现有 `coapis-pro/server/coapis/enterprise/database/` 下的模型：
- **删除**：`models/base.py`（旧 declarative_base）
- **替换**：所有 Model 文件改为使用社区版统一的 `db/models/*.py`
- **保留**：`repositories/*.py`（已用 SQLAlchemy Session，只需改 import 路径）
- **删除**：`db_config.py`（由统一 `db/engine.py` 替代）

### 7.2 字段差异处理

| 字段 | 社区 | 企业 | 处理方式 |
|---|---|---|---|
| `tenant_id` | NULL | 必填 | `Mapped[str | None]`，企业层校验 non-null |
| `org_id` / `dept_id` | NULL | 有值 | 同上 |
| `additional_roles` (JSON) | NULL | 数组 | 同上 |
| `is_superuser` | False | 视情况 | 统一字段，社区默认 False |
| `points` | 0 | 积分系统 | 统一字段，社区不用即 0 |

> **原则**：模型不感知版本差异，字段全部 nullable（除了主键和基本必填项），版本差异由**服务层**决定哪些字段必填。

---

## 8. 实施阶段

### Phase 0：基础设施搭建（预估 1-2 天）

| 步骤 | 内容 | 产出 |
|---|---|---|
| 0.1 | `db/__init__.py` + `db/base.py`（DeclarativeBase） | 基础类 |
| 0.2 | `db/engine.py` + `db/session.py`（引擎+Session） | 可连接 DB |
| 0.3 | `db/models/` 全部 13 个 Model 文件 | 完整 schema 定义 |
| 0.4 | `migrations/` Alembic 初始化 + `001_initial.py` | 可跑 migration |
| 0.5 | 验证：`alembic upgrade head` 在空目录创建出 13 张表 | 通过 |
| 0.6 | 验证：`alembic upgrade head` 在 PG 上同样通过 | 通过 |

**验收标准**：
- `python -c "from coapis.foundation.db.models import *; from coapis.foundation.db.engine import get_engine; get_engine()"` 不报错
- 空目录上 `alembic upgrade head` 成功
- 现有测试 13/13 仍然通过（此阶段不动仓储实现）

### Phase 1：用户域仓储重写（预估 2-3 天）

| 步骤 | 内容 | 产出 |
|---|---|---|
| 1.1 | `user_repository_impl.py`（23 个方法） | 新实现 |
| 1.2 | `external_identity_impl.py`（SSO 绑定+系统） | 新实现 |
| 1.3 | 改造 `repository_factory.py`：注入 SQLAlchemy 版 | 接线 |
| 1.4 | `002_import_legacy_data.py`：从 JSON 导入历史用户数据 | 数据迁移 |
| 1.5 | 删除 `user_repository_sqlite.py` + `external_identity_store_sqlite.py` | 清理 |
| 1.6 | 全量测试：T1（12）+ T2（1）+ T3（5）+ T4（4）+ T5（1）+ T6（7）= 30 个 | 全绿 |

**验收标准**：
- 所有 30 个测试通过
- 无 `import sqlite3` 在 foundation/ 下
- 启动日志显示 "SQLAlchemy engine initialized"
- 注册→登录→CRUD 全链路手动验证通过

### Phase 2：标签/场景域仓储重写（预估 1-2 天）

| 步骤 | 内容 | 产出 |
|---|---|---|
| 2.1 | `tag_repository_impl.py` | 新实现 |
| 2.2 | `scene_repository_impl.py` + `user_scene_repository_impl.py` | 新实现 |
| 2.3 | 改造 `repository_factory.py` 接线 | 接线 |
| 2.4 | 删除 3 个旧 SQLite 文件 | 清理 |
| 2.5 | 标签/场景 CRUD 验证（浏览器端点 + API） | 全绿 |

### Phase 3：迁移系统替换（预估 0.5 天）

| 步骤 | 内容 | 产出 |
|---|---|---|
| 3.1 | 删除 `migrations.py`（783行） | 清理 |
| 3.2 | 删除 `sql/` 目录（DDL 已在 Alembic） | 清理 |
| 3.3 | `repository_factory.py` 中 `ensure_migrated()` → `run_migrations()` | 接线 |
| 3.4 | 全量回归测试 | 全绿 |

### Phase 4：企业版对齐（预估 1-2 天）

| 步骤 | 内容 | 产出 |
|---|---|---|
| 4.1 | 企业版 Model 替换为统一 Model | 统一 |
| 4.2 | `db_config.py` 删除，改用 `db/engine.py` | 统一 |
| 4.3 | 企业版 Repository import 路径更新 | 接线 |
| 4.4 | PG 上 `alembic upgrade head` 验证 | 通过 |
| 4.5 | 企业版全量测试 | 全绿 |

### Phase 5：收尾（预估 0.5 天）

| 步骤 | 内容 | 产出 |
|---|---|---|
| 5.1 | `db_settings.py` 简化（仅保留路径解析） | 清理 |
| 5.2 | 更新 `pyproject.toml`：确认 `sqlalchemy>=2.0` + `alembic>=1.13` 依赖 | 依赖 |
| 5.3 | 更新 `docker-compose` 确认 SQLAlchemy 依赖在镜像中 | 部署 |
| 5.4 | 全量测试（社区 30 + 企业套件） | 全绿 |
| 5.5 | 文档更新 | 完成 |

### 时间估算

| Phase | 天数 | 说明 |
|---|---|---|
| 0 | 1-2 | 基建 |
| 1 | 2-3 | 用户域（最复杂，23 方法） |
| 2 | 1-2 | 标签/场景 |
| 3 | 0.5 | 迁移替换 |
| 4 | 1-2 | 企业对齐 |
| 5 | 0.5 | 收尾 |
| **合计** | **6-11 天** | 含测试 |

---

## 9. 数据迁移策略

### 9.1 现有 SQLite 数据库 → 新 schema

**关键发现**：新 schema 的 13 张表结构与现有 SQLite 完全一致（我们就是根据现有 SQL 定义的 Model）。所以：

- **社区版**：现有 `coapis.db` 直接可用！Alembic 的 `001_initial.py` 用 `CREATE TABLE IF NOT EXISTS`，已存在的表不会重建。Alembic 只记录版本号，数据原封不动。
- **企业版**：PG 的表结构需要对比（可能有多余列或缺少列），用 Alembic autogenerate 生成差异 migration。

### 9.2 JSON → DB（历史遗留）

- `users.json` 已在 v1.0.3 迁移，不需要再处理
- `tags.json` / `scenes.json` / `user_scenes.json` 已在 M1 迁移，不需要再处理
- `external_identity_mappings.json` 已迁移到 `external_bindings` 表
- **唯一需要确认的**：`external_systems_config.json` 是否已完整迁移到 `external_systems` 表

### 9.3 回滚策略

- 每个 Phase 完成后打 git tag
- `alembic downgrade` 支持回滚 schema（但数据不可回滚，需要 DB 备份）
- 数据备份：`cp coapis.db coapis.db.bak` 在每个 Phase 开始前执行

---

## 10. 测试策略

### 10.1 单元测试

- 每个 Repository 方法：正常路径 + 异常路径（用户不存在、重复创建等）
- 使用 `tmp_path` fixture 创建临时 SQLite 文件
- Alembic `upgrade head` + `downgrade base` 循环测试

### 10.2 集成测试

- 现有 T1-T6 测试套件（30 个）全部通过
- 新增：Alembic 迁移幂等性测试
- 新增：并发写入测试（多线程同时创建用户）

### 10.3 端到端测试

- 启动 dev 环境 → 登录 → 设置页 CRUD 全链路
- 标签管理：创建/编辑/删除
- 场景管理：创建/编辑/启用/禁用
- 外部系统：绑定/解绑
- API Keys：生成/列表/删除

### 10.4 回归矩阵

| 环境 | 测试内容 | 通过标准 |
|---|---|---|
| dev (SQLite) | 全量 30 单测 + E2E | 全绿 |
| ent-dev (PG) | 企业版测试套件 | 全绿 |
| mycom (PG 生产) | 只验证启动 + 登录 + 设置页可访问 | 无 500 |

---

## 11. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| SQLAlchemy `JSON` 类型在 SQLite 的 round-trip 不一致 | 中 | 中 | Phase 0 写专项测试验证 |
| `DateTime` 在 SQLite 存 REAL 但 Model 期望 datetime 对象 | 低 | 中 | SQLAlchemy SQLite 方言自动处理，但需验证 |
| 现有测试依赖 sqlite3.Row 的行为 | 低 | 高 | Phase 1 前跑全量测试，确认接口无变化 |
| Alembic 在已有表上执行 upgrade 的兼容问题 | 中 | 中 | `IF NOT EXISTS` + 版本号初始化 |
| 企业版 PG 列类型与 SQLite 不完全一致 | 中 | 中 | Phase 4 用 autogenerate 生成差异 migration |
| 性能退化（SQLAlchemy 比裸 sqlite3 慢） | 低 | 低 | 连接池 + 短会话，实际几乎无差异 |

---

## 12. 依赖变更

```toml
# pyproject.toml [project.dependencies] 新增
"sqlalchemy>=2.0,<3.0",
"alembic>=1.13",
# 已有（确认）
# "psycopg2-binary>=2.9"  ← 企业版需要
```

**移除**：无（`sqlite3` 是 stdlib，不需要移除依赖，只是代码不再 import 它）

---

## 13. 决策点

| # | 决策 | 选项 | 推荐 |
|---|---|---|---|
| D-10 | SQLAlchemy 版本 | 2.0（新 API）vs 1.4（旧 API） | **2.0**（用户要求统一标准，用最新） |
| D-11 | 企业版 Model 是否合并到社区代码 | A: 完全合并（一套 Model） / B: 企业单独维护 | **A**（用户要求统一） |
| D-12 | 社区版是否也支持 PG | A: 仅 SQLite / B: 可选 PG | **A**（保持 D-8 决策） |
| D-13 | `migration_state` 表是否保留 | A: 保留（Alembic 不替代业务迁移标记）/ B: 删除 | **A**（Alembic 管 schema 版本，migration_state 管数据迁移标记，职责不同） |
| D-14 | 时间字段类型 | A: `DateTime`（SQLAlchemy 类型）/ B: 保留 `Float`（unix timestamp） | **A**（标准做法，SQLite 自动降级） |
| D-15 | 实施节奏 | A: 全部一次性 / B: 按 Phase 逐步交付（每 Phase 可独立部署） | **B**（降低风险，每步可回滚） |

---

## 14. 明确不做的事

1. **不改 ABC 接口**：`UserRepository` 23 个方法的签名一字不改
2. **不改服务层**：`foundation_manager.py` 对外方法签名不变
3. **不改前端**：API 响应格式完全不变
4. **不改 agents/tools/data_store.py**：工具层独立，不在本次范围
5. **不引入 async SQLAlchemy**：保持同步
6. **不引入 ORM relationship**：只用 `select()` 查询 + 手动 join（简单可控）

---

## 15. 成功标准

完成后，以下所有条件必须同时满足：

1. ✅ `coapis-agent/server/coapis/foundation/` 下**零** `import sqlite3`
2. ✅ 全系统只有一个 `create_engine` 调用点（`db/engine.py`）
3. ✅ 所有 schema 变更走 Alembic revision
4. ✅ 社区版（SQLite）全量测试通过
5. ✅ 企业版（PG）全量测试通过
6. ✅ 现有 30 个差分测试 100% 通过
7. ✅ 设置页所有功能（用户/标签/场景/外部系统/权限）正常
8. ✅ `grep -r "sqlite3" foundation/` 返回空

---

<!-- ⟦ SQLAlchemy统一方案v1.0交付:13表/5仓储/6阶段/15决策点待拍板,未动码 ⟧ -->
