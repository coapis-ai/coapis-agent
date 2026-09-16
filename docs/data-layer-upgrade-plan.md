# 社区版数据层优化方案（可执行版）

> 版本：v1.0　日期：2026-09-15　状态：**待社区版审计收口后启动**
> 前置条件：社区版 SQLite 迁移稳定、最后审计完成、接口基线冻结
> 本文档是给社区版自己的改造施工图，与"企业版不改社区版"原则并行：社区版把数据层做扎实，企业版只需换连接串，两边互不颠覆。

---

## 一、背景：要解的四个病

| # | 问题 | 现状证据 |
|---|------|---------|
| 1 | **存储三套并存** | 用户域、外部身份绑定在 SQLite（`foundation/user_repository_sqlite.py`、`foundation/external_identity_store_sqlite.py`）；标签在 JSON（`app/services/tag_service.py` 读写 `data/tags.json`）；场景在 JSON（`services/scene_agent_service.py` 读写 `data/scenes.json`）；知识库在 JSON（`foundation/repository_json.py`）；记忆/聊天归档在文本文件 |
| 2 | **换数据库 = 重写** | 用户域 SQLite 实现是裸 `sqlite3` 手写 SQL（`user_repository_sqlite.py`，464 行），方言硬编码在代码里。企业版上 PostgreSQL 时 23 个方法必须全部重写一遍 |
| 3 | **同步异步混用** | 用户域仓储接口是同步签名（`foundation/user_repository.py`，23 个方法，无 `async`）；知识库抽象基类是异步（`foundation/repository.py` 的 `KnowledgeBaseRepository`，全部 `async def`）。企业版实现全是异步 → 用户域调用拿到协程对象直接炸（已实锤的 P0） |
| 4 | **收尾不干净** | 启动处初始化调用与 `RepositoryFactory.initialize()` 新签名存在对不上的 bug（v1.0.3 遗留）；老 JSON 用户路径（`user_system/database.py` 的 `UserSystemDB`）尚未删除，新旧两套并存 |

**核心结论**：问题根在社区版数据层本身——没做成"一套接口 + 一套通用实现"。企业版的痛苦（重写、失配）是社区版结构问题的下游症状。修社区版，企业版问题自然消解。

---

## 二、目标与原则

**目标**

1. **单一数据源**：用户、标签、场景、知识库、外部身份绑定全部进同一个库。社区版默认仍用 SQLite（零外部依赖、单文件、简单）。
2. **方言可换**：仓储实现只写数据库无关的 SQL 表达，SQLite / PostgreSQL 差异全部由方言层吸收。企业版理论上只给连接串 + 自己的建表脚本。
3. **接口即契约**：仓储接口冻结后不再动，配一套合规测试集。任何实现（社区默认、企业版）跑过同一套测试即合格，不再人肉对齐。

**原则（强制）**

- **P1 全异步统一**：所有仓储接口统一 `async def`，这是最大的不稳定源，最先定死。FastAPI 本身异步，企业版实现本来就是异步——统一后企业版用户域 P0 直接消失。
- **P2 一套实现多库复用**：SQL 只写一次，不引入重型 ORM，只用 SQLAlchemy 核心（Core）的 SQL 表达 + 方言能力。
- **P3 可移植类型**：禁用 `postgresql.UUID`、`postgresql.JSONB` 等方言专用类型；主键统一 36 位字符串（兼容 UUID 形态），JSON 用通用 `JSON` 类型。
- **P4 JSON 退场**：JSON 文件只保留两个身份——初始种子、迁移来源。迁完库后只读不写，保留 30 天作回退备份。
- **P5 每阶段独立可交付**：每阶段结束后系统完整可运行，不出现"改一半不能用"的窗口。
- **P6 不改业务行为**：只动数据层，路由、接口、前端一律不动；对外 API 的响应结构保持不变。

---

## 三、目标架构：两层结构

```
业务/服务层（tag_service、scene_agent_service、knowledge_base_service、user 相关服务）
        │  只依赖域接口，不感知数据库
┌───────▼───────────────────────────────────────┐
│  上层：域接口层（foundation/repository_*.py）    │  ← 契约，冻结后不动
│   UserRepository(23方法) / TagRepository /       │
│   SceneRepository / KBRepository /               │
│   ExternalIdentityStore　全部 async              │
├───────────────────────────────────────────────┤
│  下层：通用 SQL 实现（foundation/sql_impl/）     │  ← SQLAlchemy Core，一次实现
│   方言无关 SQL；SQLite/PostgreSQL 差异由          │
│   方言机制自动处理（自增、布尔、JSON、分页）        │
├───────────────────────────────────────────────┤
│  连接层：COAPIS_DATABASE_URL 标准连接串            │
│   社区默认 sqlite:///system/coapis.db            │
│   企业版 postgresql+asyncpg://...                │
└───────────────────────────────────────────────┘
```

**关键组件**

| 组件 | 位置 | 职责 |
|------|------|------|
| 域接口基类 | `foundation/repository*.py` | 每域一个 ABC，方法=业务动作，不含任何 SQL |
| 通用 SQL 实现 | `foundation/sql_impl/`（新增目录） | 各域的 SQLAlchemy Core 实现，两版共用 |
| 仓储工厂 | `foundation/repository_factory.py` | 按 `COAPIS_EDITION` 选择实现；社区=通用 SQL 实现，企业=可注入 |
| 迁移机制 | `foundation/migrations.py`（扩展） | 建表 + 版本管理 + JSON→DB 数据迁移，统一入口，全部幂等 |
| 合规测试集 | `tests/foundation/contract/`（新增） | 对每个域接口一组用例，社区/企业实现同跑 |

**注入口子（保持现状，企业版零改动兼容）**：服务层通过 `RepositoryFactory.is_initialized()` + `get_*_repository()` 取仓储，取不到就回退。现有 `tag_service.py`、`scene_agent_service.py` 里"企业版注入、社区版 JSON 回退"的分支结构原样保留，只是社区版的"回退目标"从 JSON 变成 SQLite 通用实现。

---

## 四、接口契约（冻结基线）

### 4.1 统一异步签名标准

所有仓储方法：`async def`，入参/出参用 `dict` / 实体 dataclass / 分页对象，**禁止**返回 ORM 行对象或裸 DB 游标。

```python
class TagRepository(ABC):
    async def list_tags(self, scene_id: str | None = None,
                        include_disabled: bool = False) -> list[dict]: ...
    async def get_tag(self, tag_id: str) -> dict | None: ...
    async def create_tag(self, tag: dict) -> str: ...          # 返回 tag_id
    async def update_tag(self, tag_id: str, data: dict) -> bool: ...
    async def delete_tag(self, tag_id: str) -> bool: ...       # 软删，置 disabled
    async def count_tags(self) -> int: ...
```

### 4.2 用户域 23 方法清单（现有 `foundation/user_repository.py`，全部转 async）

| # | 方法 | # | 方法 |
|---|------|---|------|
| 1 | `create_user(user_data) -> str` | 13 | `count_users() -> int` |
| 2 | `get_user_by_id(user_id) -> dict` | 14 | `count_active_users() -> int` |
| 3 | `get_user_by_username(username) -> dict` | 15 | `insert_audit_log(...) -> None` |
| 4 | `get_user_by_email(email) -> dict` | 16 | `insert_point_transaction(...) -> None` |
| 5 | `update_user(username, data) -> bool` | 17 | `insert_token_usage(...) -> None` |
| 6 | `update_user_by_id(user_id, data) -> bool` | 18 | `get_user_token_usage(user_id) -> dict` |
| 7 | `delete_user(username) -> bool` | 19 | `get_agent_token_usage(agent_id) -> dict` |
| 8 | `delete_user_by_id(user_id) -> bool` | 20 | `get_user_preferences(username) -> dict` |
| 9 | `list_users() -> list[dict]` | 21 | `save_user_preferences(username, prefs) -> None` |
| 10 | `list_users_page(...) -> (list, total)` | 22 | `get_user_preference(user_id, key) -> str` |
| 11 | `user_exists(username) -> bool` | 23 | `set_user_preference(user_id, key, value) -> bool` |
| 12 | `email_exists(email) -> bool` | | |

> 冻结规则：审计收口时以该清单 + 各方法完整签名为基线，写入 `docs/user-repository-contract.md` 并加版本号。此后任何签名变更必须走"接口变更评审 + 合规测试集全跑"。

### 4.3 新增三个域接口（第二阶段新增）

- **TagRepository**：见 4.1 示例，方法集 = 现 `tag_service.py` 实际用到的读写动作（列表/按 id 查/增/改/删/计数/按场景过滤）。
- **SceneRepository**：`list_scenes(status, category, tag)`、`get_scene(scene_id)`、`create/update/delete_scene`、`get_scene_tags()`、`count_scenes()`（对齐 `scene_agent_service.py` 现有 JSON 读写动作）。
- **ExternalIdentityStore**：现有 `foundation/external_identity_store_sqlite.py` 的接口转 async，方法不变（按用户名查 / 按外部身份查 / 写入 / 删除）。

---

## 五、分阶段执行计划

> 阶段顺序不可颠倒。每阶段有明确的"完成定义"，完成前不进入下一阶段。

### 第一阶段：统一异步 + 修 bug（约 1 天）

| 任务 | 内容 | 涉及文件 |
|------|------|---------|
| 1.1 | 用户仓储接口 23 方法全部改 `async def` | `foundation/user_repository.py` |
| 1.2 | SQLite 实现同步改异步（`sqlite3` → `aiosqlite`，或 `asyncio.to_thread` 包同步实现，二选一，**推荐 aiosqlite**，为第三阶段做铺垫） | `foundation/user_repository_sqlite.py` |
| 1.3 | 外部身份绑定仓储转 async | `foundation/external_identity_store_sqlite.py` |
| 1.4 | 全部消费方补 `await`：用户系统服务、认证中间件、积分/用量/审计/偏好相关路由 | `user_system/`、`app/auth*.py`、`app/routers/` 下消费用户仓储的文件 |
| 1.5 | 修启动初始化 bug：`app/_app.py` 启动处的调用与 `RepositoryFactory.initialize()` 签名对齐 | `app/_app.py`、`foundation/repository_factory.py` |
| 1.6 | 删除老 JSON 用户路径，单一数据源 | `user_system/database.py`（`UserSystemDB` 相关）及其调用点 |
| 1.7 | 接口基线冻结文档 | 新增 `docs/user-repository-contract.md` |

**完成定义**
- 社区版全功能回归通过（登录、用户管理、审计、积分、用量、偏好、外部绑定）。
- 老 JSON 用户文件不再被写入；首启迁移（users.json → DB）仍幂等可用。
- 全部仓储方法 `async def` 化完成，无同步/异步混用（可用 grep 检查 `def ` 中无 `async` 的仓储方法）。

### 第二阶段：标签、场景、知识库、外部绑定入库（约 2~3 天）

| 任务 | 内容 | 涉及文件 |
|------|------|---------|
| 2.1 | 定义三个新域接口基类（Tag / Scene / 外部绑定转 async 版） | `foundation/tag_repository.py`、`foundation/scene_repository.py`（新增） |
| 2.2 | 建表：`tags`、`scenes`、（知识库沿用现有 KB 表或按现有 JSON 结构落表） | `foundation/sql/community_schema.sql` 扩展 |
| 2.3 | SQLite 默认实现（本阶段仍可用 aiosqlite 裸写，SQL 按"可移植写法"约束：不用方言函数、主键字符串、JSON 用 TEXT 存 JSON 串或通用 JSON 类型） | `foundation/tag_repository_sqlite.py`、`foundation/scene_repository_sqlite.py`（新增） |
| 2.4 | 服务层切换：`tag_service.py`、`scene_agent_service.py` 的 JSON 读写分支改为"仓储工厂取实现 → 没有则报错"（JSON 回退逻辑删除，改为迁移保证数据在库） | `app/services/tag_service.py`、`services/scene_agent_service.py` |
| 2.5 | 知识库：`repository_json.py` 的 JSON 实现换成 SQLite 实现（接口 `KnowledgeBaseRepository` 已是 async，只换下层） | `foundation/repository_factory.py`、新增 `foundation/kb_repository_sqlite.py` |
| 2.6 | 迁移脚本扩展：`tags.json`、`scenes.json`、`knowledge_bases.json` 首启自动迁入 DB；逐条校验条数与内容；幂等（`migration_state` 表记录） | `foundation/migrations.py` |
| 2.7 | 迁完 JSON 转只读：代码中所有 `json.dump` 写入路径移除/禁用，文件保留 30 天 | 各服务层 |

**完成定义**
- 一个 SQLite 文件里能查到用户、标签、场景、知识库、外部绑定全部数据。
- 存量 JSON 数据迁移后逐条比对一致（迁移脚本自带校验输出）。
- 标签管理、场景管理、知识库管理界面全功能回归通过。
- 重启两次，迁移脚本幂等（第二次跳过，无报错、无重复数据）。

### 第三阶段：方言层改造（约 3~5 天，最大的一块）

| 任务 | 内容 | 涉及文件 |
|------|------|---------|
| 3.1 | 引入 `sqlalchemy[asyncio]` 依赖（仅 Core，不引 ORM）；`pyproject`/`requirements` 加依赖，明确驱动：社区 `aiosqlite`，企业 `asyncpg` | 依赖清单 |
| 3.2 | 新建 `foundation/sql_impl/`：用 SQLAlchemy Core 重写全部五个域的仓储实现（用户 23 方法 + 标签 + 场景 + KB + 外部绑定），一套代码 | 新增目录 |
| 3.3 | 类型可移植化：`postgresql.UUID`/`JSONB` 全部换成通用类型；主键统一 36 位字符串；JSON 字段用 `sqlalchemy.JSON` | 新实现内 |
| 3.4 | 连接层统一：`db_settings.py` 扩展为解析标准连接串（`sqlite:///...` 与 `postgresql+asyncpg://...`），社区默认本地文件 | `foundation/db_settings.py` |
| 3.5 | 建表/版本管理统一走 SQLAlchemy 迁移（`schema_version` 表 + 迁移脚本序列），替代手写 `CREATE TABLE IF NOT EXISTS` 散落的写法 | `foundation/sql/`、`migrations.py` |
| 3.6 | 工厂切换：`RepositoryFactory` 社区版从"SQLite 裸实现"切到"sql_impl 通用实现"；企业版注入口子不变 | `foundation/repository_factory.py` |
| 3.7 | 双库验证：同一套 `sql_impl` 代码在 SQLite 和 PostgreSQL（临时起一个）上各跑一遍全量测试 | 测试环境 |

**完成定义**
- 同一套仓储代码在 SQLite、PostgreSQL 上测试全绿（"换库 = 换连接串"成立）。
- 依赖增量只有 `sqlalchemy` + `aiosqlite`（社区）两个，无 ORM、无重型框架。
- 社区版全功能回归通过（同第二阶段口径 + 用户域）。
- 数据无损：从第二阶段产物（aiosqlite 数据）迁到 SQLAlchemy 管理下，逐表逐行比对一致。

### 第四阶段：契约固化（约 1~2 天，收尾）

| 任务 | 内容 |
|------|------|
| 4.1 | 接口契约文档定稿：五域接口完整签名 + 语义说明 + 版本号（`docs/foundation-contract.md`） |
| 4.2 | 合规测试集 `tests/foundation/contract/`：每域一组用例，必须覆盖——基本 CRUD、边界（空值、重复键、不存在 id、分页越界）、事务语义（软删可查/不可见、幂等重跑）。用 pytest-asyncio，针对接口基类写，实现无关 |
| 4.3 | CI 接入：合规测试集进常规测试流程；社区实现默认全绿 |
| 4.4 | 版本锁定：`COAPIS_EDITION` 基线版本写入发布说明；企业版挂载时校验社区版本 ≥ 契约版本 |

**完成定义**
- 合规测试集在社区默认实现上全绿。
- 企业版拿到契约文档 + 测试集后，按其实现跑同一套测试即可验收，双方不再人肉对齐。
- 数据层结构稳定：接口、表结构、迁移机制有版本记录，后续变更有流程。

---

## 六、数据迁移规范（全阶段通用）

1. **幂等**：所有迁移脚本可重复执行，靠 `migration_state` 表（表名 + 版本 + 完成时间戳）防重。
2. **先校验后切换**：迁移脚本先跑"校验模式"（读 JSON、比对 DB，输出差异报告），确认 0 差异再真正切换服务层读写路径。
3. **保留备份**：原 JSON 文件迁移后只读保留 30 天，命名加 `.migrated` 后缀；30 天后由清理脚本删除。
4. **失败回退**：迁移中途失败 → 事务回滚 + `migration_state` 不标记完成 → 下次启动自动重跑；JSON 文件未动，可安全回退到旧路径。
5. **日志**：每域迁移输出 `条数 / 成功 / 跳过（已存在）/ 失败` 四计数，失败逐条打印。

---

## 七、测试与验收清单

**每阶段通用回归（必跑）**

- [ ] 登录 / 注册 / 用户 CRUD / 分页
- [ ] 审计日志、积分流水、用量明细、偏好读写
- [ ] 外部身份绑定：按用户名查 / 按外部身份查 / 写入 / 删除
- [ ] 标签管理：CRUD + 按场景筛选
- [ ] 场景管理：CRUD + 分类 + 标签 + 工作台菜单
- [ ] 知识库：CRUD + 文档上传 + 检索
- [ ] 冷启动：空数据目录首启自动建表 + 迁移
- [ ] 重启幂等：重启两次无报错、无重复数据

**第三阶段额外**

- [ ] PostgreSQL 环境跑同一套合规测试集全绿
- [ ] 连接串切换演练：仅改 `COAPIS_DATABASE_URL`，不改代码，数据层切换成功
- [ ] 类型可移植检查：grep 无 `postgresql.` 方言类型残留

**第四阶段额外**

- [ ] 合规测试集全绿（社区实现）
- [ ] 契约文档与代码签名一致性核对（可用脚本比对 ABC 方法清单）

---

## 八、风险与对策

| 风险 | 对策 |
|------|------|
| 全异步改造波及消费方广 | 第一阶段单独做完、单独回归；消费方清单在执行前用 grep 全量拉出（`RepositoryFactory.get_user_repository()` 的所有调用点），逐个改、逐个测 |
| JSON 迁库丢数据 | 第六节迁移规范：校验模式先行 + 逐条比对 + 只读备份 30 天 |
| SQLAlchemy 引入带来依赖/性能顾虑 | 只用 Core 不用 ORM；连接池参数按社区单用户场景调小；性能回归对比改造前后主要接口响应 |
| 社区版审计还在进行，接口还会微调 | 本方案启动时机就定在审计收口后；第一阶段先定死"全异步"这一个标准（最大不稳定源），其余签名随审计冻结一次性定稿 |
| 执行中企业版需要紧急上线 | 每阶段独立可交付；第二阶段完成后企业版即可开始按新契约适配（标签/场景接口先冻结先行），不阻塞主线 |
| 阶段间出现半成品状态 | P5 原则 + 每阶段完成定义把关，未完成不发布 |

---

## 九、启动检查清单（审计收口后、动手前）

- [ ] 社区版最后审计完成，用户域接口无未决变更
- [ ] `docs/user-repository-contract.md` 基于 4.2 清单定稿并打版本号
- [ ] 消费方全量清单拉出（用户仓储 / 标签 / 场景 / KB / 外部绑定的全部调用点）
- [ ] 备份当前数据目录与代码基线（打 tag，如 `pre-dl-upgrade`）
- [ ] 确认 PostgreSQL 测试实例可用（第三阶段需要）
- [ ] 逐阶段排期确认，每阶段完成后人工验收再进下一阶段

---

## 十、附：企业版侧联动（不在本方案范围内，仅说明边界）

社区版本方案完成后，企业版的工作收敛为三件：

1. 用户域 PostgreSQL 仓储按冻结契约补齐 23 个方法（异步，与本方案统一）——从"重写"变成"按契约适配"；
2. 企业独有表（机构、租户、部门、配额、外部系统）保持企业版自持；
3. 标签/场景/KB/外部绑定：注入方式不变，实现改为复用 `sql_impl` 通用代码 + 企业连接串，**零重写**。

验收方式：跑社区版第四阶段产出的同一套合规测试集。
