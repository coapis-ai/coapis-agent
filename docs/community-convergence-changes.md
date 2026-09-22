# 社区版数据层优化改动清单

> 生成日期：2026-09-21（2026-09-21 三次校对：去掉全部知识库相关内容 —— 社区版没有知识库产品能力，知识库数据全走 Weaviate，不建数据库表）
> 背景：社区版统一数据层尚不完整 —— Alembic 与 raw SQL 双真相源、多张表没有 ORM model、部分仓储写死 sqlite、插件扩展点（model / 仓储 / 生命周期）未补齐。这些缺口会让上层版本被迫自建第二套 DB 层。本文只列 **社区版需要优化/改动的部分**，每项标注现状、风险、改法。

---

## 一、数据库层（P0，第一批）

### 1. 清理社区版知识库遗留存储层

**背景**
知识库是企业版新增能力，数据全在 Weaviate，不建数据库表；社区版没有知识库产品功能。但社区版代码里仍带着一整套**无任何调用方**的 KB 存储层（早期引入），会持续误导后续维护（比如反复出现"社区版为什么有知识库表"的问题），必须整体清除。

**现状**（已逐一核实）
- `foundation/repository.py`：KnowledgeBase dataclass + KnowledgeBaseRepository 抽象类（整文件 KB 专属）；
- `foundation/repository_json.py`：JsonKnowledgeBaseRepository（读写 data/knowledge_bases.json）；
- `foundation/knowledge_base_impl.py`：SqlaKnowledgeBaseRepository（knowledge_bases 表）；
- `foundation/knowledge_base_service.py`：KnowledgeBaseService，社区版内无任何调用方；
- `foundation/repository_factory.py`：KB import 与 `_kb_repo` 工厂入口；
- `foundation/__init__.py`：导出 KnowledgeBase / KnowledgeBaseRepository；
- `foundation/sql/community_schema.sql`：knowledge_bases 表 DDL（还带着 department_id / visibility / tenant_id 等企业字段）；
- `foundation/migrations.py`：`_migrate_knowledge_bases` 及迁移注册项；
- `tests/test_foundation.py`：KB 相关测试；
- 数据文件 `data/knowledge_bases.json`。

**改法**
1. 删 4 个文件：repository.py / repository_json.py / knowledge_base_impl.py / knowledge_base_service.py，及对应测试用例；
2. `repository_factory.py` 去掉 KB import 与 `_kb_repo` 工厂入口；`__init__.py` 去掉 KB 导出；
3. `community_schema.sql` 删 knowledge_bases 表 DDL；`migrations.py` 删 `_migrate_knowledge_bases` 及注册项；
4. `data/knowledge_bases.json` 挪到备份目录归档，不直接删；
5. `models/scene.py` 的 `knowledge_bases` 字段（场景挂载的 KB ID 列表）：是"知识库嵌入聊天"方案的预留挂载点，**默认保留**（纯配置字段、不依赖任何表），注释标注"企业版扩展用"。

**验收**
- 全社区代码 grep `knowledge_base` 仅剩 scene 配置字段及注释，无 KB 类/仓储/服务/表；
- 全新库（sqlite / PG）建库后不存在 knowledge_bases 表。

### 2. Alembic 迁移链补 3 张表 —— 让 Base.metadata 成为唯一 schema 真相源

**现状**
- Alembic `0001_initial` 从 `Base.metadata`（13 张表，已核实：api_keys、audit_logs、external_bindings、external_systems、migration_state、point_transactions、scenes、tags、token_usage、user_preferences、user_scene_settings、user_settings、users）生成；
- 但实际建表事实源是 `foundation/sql/community_schema.sql` + `foundation/migrations.py` 里的 raw SQL（`_create_schema`）；
- B 档 3 张表 `token_usage_daily` / `permissions_config` / `token_usage_details` **没有 ORM model**，不在 Alembic 链里，靠 `ensure_runtime_domain_migrated` 的裸 SQL 补建。

**风险**
- 纯 Alembic 路径的全新安装（尤其是 PostgreSQL 等非 sqlite 方言）这 3 张表不会建出来 → 用量统计、权限配置功能直接没表可用。

**改法**
1. 给这 3 张表补 ORM model（`models/usage.py` 并入 `token_usage_daily`/`token_usage_details`、`models/state.py` 加 `permissions_config`）；
2. `alembic upgrade head` 对全新库可一次建全（含插件模型，见第 3 条），保留 `0001` 现幂等"补缺表/索引"逻辑；
3. `community_schema.sql` / `_create_schema` 降级为 legacy 兜底或直接删除，杜绝双真相源。

### 3. 插件模型扩展点（register_models 钩子）

**现状**
- `migrations/env.py` 与 `0001_initial._tables()` 都硬编码 `coapis.foundation.db.models`；
- 插件无法把自己的 ORM model 并入社区迁移链，只能自建脚本建表。

**改法**
1. 插件系统加 `register_models()` 钩子：插件在启动早期把自己的 model import 注册到社区 `Base` 上（只 import，不建 engine、不连库）；
2. `0001_initial._tables()` 和 `env.py` 改为动态收集 `Base.metadata`（去掉硬编码导入清单）；
3. 约定：插件 model 不得占用社区表名，新表命名带业务前缀。

### 4. RepositoryFactory 改纯注入，去掉反向 import 与死分支

**现状**（`foundation/repository_factory.py`，已核实 L137/149/175）
- 工厂里有两处直接 import 上层版本的仓储实现，**社区代码 import 上层包，方向反了**；
- 还有一条死分支指向不存在的模块；
- `_app.py` lifespan 中非社区模式**整个跳过** `RepositoryFactory.initialize()` → 社区自己的 13 张表 schema 在该模式下无人管理；
- 存在靠私改 `RepositoryFactory._initialized = True` 的 hack 绕过初始化检查。

**改法**
1. 删掉上层 import 和死分支；非社区模式只接受仓储注入，缺失直接报清晰错误；
2. `_app.py` lifespan 改为：**所有模式都先跑社区自己的 Alembic 迁移**（只管社区表），然后调插件 `startup()` 注入仓储；
3. 提供显式初始化语义（如 `initialize(edition=..., **injected)` 内部自行处理，或 `mark_initialized()`），外部不再私改私有属性。

---

## 二、连接池与启动生命周期（P1，第二批）

### 5. 连接池参数可配置

**现状**：`foundation/db/engine.py` L94 硬编码 `pool_size=5, max_overflow=10`。

**改法**：支持 `COAPIS_DB_POOL_SIZE` / `COAPIS_DB_MAX_OVERFLOW` 环境变量（sqlite 方言忽略），社区默认值不变。

### 6. 插件生命周期两段化

**现状**：`register_plugin()` 在 `_app.py` 模块导入期执行，`RepositoryFactory` 初始化在 lifespan；插件在 import 期就自行初始化 DB，顺序不明确、不可控。

**改法**：插件 API 分两阶段——
- `register`（导入期）：只注册路由、中间件、**model**，不建 engine、不连库；
- `startup`（lifespan，在 RepositoryFactory 就绪前由社区统一调用）：建 engine、跑校验、注入仓储。

启动顺序固定为：**社区迁移 → 插件 startup → 业务使用**。

---

## 三、仓储可复用（P1，第三批）

### 7. tag / scene / user_scene 三仓储方言中立化

**现状**
- `SqliteTagRepository` / `SqliteSceneRepository` / `SqliteUserSceneSettingsRepo` 全部基于 `sqlite3` 直连、构造参数是 `db_path`；
- 只能跑 sqlite，任何上层要换 PG 就必须自维护一套同功能仓储（分叉根源）。

**改法**：参照已验证的模式（`external_identity_impl.py`），三仓储改为走统一 engine 的 `get_session()`，sqlite / PG 同一份代码。

---

## 四、迁移脚本方言清理（P1/P2）

### 8. migrations.py 清掉 sqlite 专用路径

**现状**（已核实 `foundation/migrations.py` 全文 1002 行）
- `ensure_runtime_domain_migrated` 及多处直接 `sqlite3.connect`（L136/177/247/277/384/417 等）；
- `external_bindings` 等数据迁移用 `?` 占位符 + `INSERT OR REPLACE`（L843 起），在 PG 上必炸。

**改法**：B 档表并入 Alembic 链（第 2 条）后，raw SQL 建表路径删除；剩余 JSON→DB 数据迁移路径要么显式标注"仅社区 sqlite"（非 sqlite 库不走），要么改成方言中立 `text()`。

---

## 执行顺序与验收

| 批次 | 条目 | 完成后的效果 |
|---|---|---|
| 第一批（P0） | 1, 2, 3, 4 | 社区版 KB 遗留存储层清零；单一 schema 真相源（Alembic）；插件 model/仓储扩展点齐备；社区代码零反向依赖、零死分支 |
| 第二批（P1） | 5, 6, 7 | 连接池可配；插件生命周期可控；三仓储 sqlite/PG 同码复用 |
| 第三批（P1/P2） | 8 | 迁移路径方言干净 |

**验收标准（全部满足才算完成）**
1. 全新库（sqlite 与 PostgreSQL 两种方言）一次 `alembic upgrade head` 建齐社区 13 表 + B 档 3 表，不执行任何 raw SQL 建表；
2. 社区代码里不存在任何指向上层版本的 import，死分支清零；
3. tag / scene / user_scene 三仓储在 sqlite 与 PG 上同一份代码回归全绿；
4. 社区版单独跑（`COAPIS_EDITION=community`）行为与现在完全一致（回归测试不变）。
