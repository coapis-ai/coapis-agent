# CoApis 数据层统一技术方案：消灭双重实现，社区版引入 SQLite

> 状态：**P1 改动清单已出**（D-5、D-6 已拍板；D-1/D-2/D-3/D-4 未定，D-2/D-3 决定 P1 能否开工）
> 日期：2026-09-14（v1.2：D-6 拍板 = A（ID 体系统一 TEXT(uuid)）；企业版对比盘点 §5.3F；P1 文件级改动清单 §11）
> 关联：v1.0.1（59ba286）之后的架构治理专项

---

## 1. 背景与问题

### 1.1 用户提出的两个问题

1. 基于文件的数据管理到一定程度瓶颈很大（性能、并发、完整性）。
2. 原计划数据库只在企业版支持，但因为"多重实现"已经遇到很多问题——为了维护生态，是否应该让社区版也支持数据库？开源对企业版生态的影响如何？

### 1.2 先纠正一个框定

**真正的病灶不是"文件 vs 数据库"，而是"两套持久化框架并存 = 每件事写两遍"。**
就算数据库只留企业版，JSON 和 SQLite 两条路照样要同时维护，双重实现债一分不少。
所以本方案的核心是**收敛成一个 repository 接口**，社区/企业只是接口下面的不同后端。

### 1.3 硬证据（2026-09-13/14 调研）

**（a）存储现状不是"纯文件"，是文件 + 多套库混用：**

| 数据 | 形态 | 位置 | 问题 |
|---|---|---|---|
| 用户/审计/偏好/API Key/积分 | JSON | `system/users.json`、`audit_logs.json`、`user_settings.json`、`user_preferences.json`、`api_keys.json`、`point_transactions.json` | 读改写竞态、无事务 |
| 场景/标签/分类 | JSON | `scenes.json`(46KB)、`tags.json`、`categories.json`、`user_tags.json`、`domain_contexts.json` | 同上 |
| 会话历史 | JSON + SQLite | `workspaces/*/sessions/*.json`（单文件最大 150KB）+ `history.db`（test88 已 3.7MB） | 两种历史并存，口径不一 |
| 会话列表 | JSON | `workspaces/*/chat/chats.json` | 整文件读改写 |
| Agent 配置 | JSON | `agent.json`、`skill.json`、`config.json` | 同上 |
| LLM 记忆/人设 | Markdown | `MEMORY.md`、`PROFILE.md`、`SOUL.md`、`HEARTBEAT.md`、`AGENTS.md` | **无**——给 LLM 读的，就该是文件 |

生产 mycom 数据目录共 **2323 个文件**（test88 单用户 1774 个）。
`scenes.json.bak`、`tags.json.backup_*` 一堆备份文件 = 文件读改写竞态/损坏的疤痕。

**（b）"多重实现"的真实形态 = 两套持久化框架并存：**

- `server/coapis/foundation/repository_factory.py`（+ `repository.py` / `user_repository.py` / `*_json.py`）
  干净的依赖注入：社区 = JSON 实现，企业 = 动态 import 私有包 `coapis.enterprise` 的 Postgres 实现。
  另有 tag / scene / external_identity store 注入点。
  调用方：`scene_agent_service`、`tag_service`、`_app.py`、`external_identity`、`external_auth`、`admin_users`、`external_systems_admin`。
- `server/coapis/user_system/database.py`（`UserSystemDB` 单例）
  单类双模式：**25 个 `if self._use_database:` 分支**，每个 CRUD 写两遍；
  `_is_database_enabled()` 社区恒返回 False，即社区版恒走 JSON。
  调用方：`service.py`、`tokens.py`、`app/auth.py`、`backup/restore`、`audit_log`、`security_ops`、各 workspace router、`permissions`。

两套各自维护 → CRUD 写两遍、测试跑两遍、两条路径互相漂移。
这就是"多重实现遇到很多问题"的根源。

**（c）授权自相矛盾（开源门票，法律地雷）：**

- 根 `LICENSE` + `README` badge + 包元数据：**Apache 2.0**
- **523 个 py 文件头**：**AGPL 3.0**
- 622 个 py 文件头：只有版权声明、无明确 license

**（d）企业版边界目前干净：**
`coapis.enterprise`（Postgres 仓库/集群/监控）不在开源仓，走 `enterprise_stubs.py` + 动态 import。
守住这条边界即可，本方案不动它。

**（e）与迁移相关的一个澄清（v1.2 更新，D-6 已拍板）：**
"用户ID统一字符串"（7f6d1e8）**只改了 API 层**（admin_users 端点按 username 解析，
`_resolve_user` 已兼容 username/整数/UUID 三种形态）。
内部 `users.id` 此前仍是 `INTEGER PRIMARY KEY AUTOINCREMENT`。
**D-6 拍板 = A**：P1 中社区版 `users.id` 一并改为 `TEXT(uuid)`（对齐企业版 PG），
存量 int 用确定性公式 `uuid.UUID(int=old_id)` 映射（幂等、可逆、无需映射表）；
JSON→SQLite 迁移与 ID 改造在同一事务内完成（见 §6 阶段 1）。

---

## 2. 核心结论

### 2.1 社区版要不要数据库？

**要——用 SQLite，且必须走同一个 repository 接口。**

1. **这是消灭双重实现债的唯一办法。** 统一接口后：社区 = SQLite 后端、企业 = Postgres 后端，
   CRUD **只写一遍**。JSON 后端从"长期维护的第二条路"降级成"迁移完就删的东西"。
2. **SQLite 零运维。** 就是一个文件，无服务器、无配置、无端口。
   社区白拿事务/索引/并发控制，零负担——这正是它适合做社区后端的原因。
3. **修掉一整类真 bug。** 文件读改写的竞态/损坏是文件模式的固有缺陷，SQLite 在存储层就解决了。
4. **社区/企业数据层一致。** 一个 bug 两边都能复现，不再"dev 好使、prod 崩"。

### 2.2 开源对企业版生态的影响

**关键判断：数据层不是护城河。**

- 护城河是企业版独有的：多节点集群/HA、监控看板、SSO、多租户、高级安全、**Postgres 水平扩展**、企业 SLA。
  本方案一个没动。
- **SQLite → Postgres 是"基础设施升级"，不是"功能下放"。**
  给社区 SQLite 不侵蚀企业价值，反而强化"要规模/高可用就得上企业版"的定位。
- 这是标准 open-core 打法：把"给了不心疼、又卡着 adoption"的给出去，把"需要真金白银 infra"的收费。
- 开源收益：① 开源产品真能上生产 → 信任 + 销售漏斗；② 外部贡献者基于稳定数据层做生态。

**真正的风险只有两个：**

1. **授权必须先理清**——523 个文件头 AGPL vs 根 LICENSE Apache 是法律地雷。
   对外发数据层（别人会 vendor）之前必须统一口径。
2. **别把企业代码漏出去**——Postgres 仓库/集群/监控保持私有（现状边界干净，守住即可）。

---

## 3. 目标与非目标

### 目标

- G1：全系统收敛为**一个** repository 抽象（以 `foundation/repository_factory` 为基准）。
- G2：社区版默认 **SQLite** 后端，CRUD 只写一遍，JSON 双路代码删除。
- G3：存量 JSON 数据**非破坏性**一次性迁移（自动 + 留备份）。
- G4：授权口径统一（开源门票）。
- G5：企业版 Postgres 后端接口不变，`coapis.enterprise` 继续私有。

### 非目标（本方案不做）

- 不改 LLM 记忆类文件（`MEMORY.md`/`PROFILE.md`/`SOUL.md`/`HEARTBEAT.md`/`AGENTS.md`）——它们是给模型读的，天然是文件。
- 不动 `workspaces/*/history.db`——它已经是 SQLite，保持现状（会话历史查询走它）。
- 不动企业版私有包内部实现。
- 不引入 ORM（保持裸 sqlite3 / 轻量 SQL，与现有 `db_ops` 风格一致；是否上 SQLAlchemy 留作后续决策）。

---

## 4. 总体架构

```
                    ┌────────────────────────────────────────┐
                    │  业务层 (routers / services / tools)    │
                    │  只依赖 repository 接口，不碰存储细节    │
                    └───────────────────┬────────────────────┘
                                        │ RepositoryFactory
                    ┌───────────────────▼────────────────────┐
                    │  统一 Repository 接口 (foundation/)     │
                    │  UserRepository / KBRepository /        │
                    │  TagRepository / SceneRepository /      │
                    │  ExternalIdentityStore / AuditRepo /    │
                    │  UsageRepo / PreferenceRepo / PointRepo │
                    └───────┬───────────────────────┬────────┘
              社区默认       │                       │  企业版
                    ┌───────▼───────┐         ┌─────▼──────────────┐
                    │  SqliteBackend │         │  PostgresBackend   │
                    │ (stdlib sqlite3)│        │ (coapis.enterprise, │
                    │ system/coapis.db│        │  私有包, 动态import) │
                    └───────────────┘         └────────────────────┘
   迁移期: JsonBackend 作为临时实现并存，迁移完成后删除
```

要点：

- **一个接口，N 个后端。** 后端是可插拔的，社区/企业只差一个 DSN/驱动。
- 社区版单文件 `system/coapis.db`（与 `user_system.db` 同目录），WAL 模式。
- 企业版沿用现有 Postgres 注入路径，接口签名不变。
- `UserSystemDB`（25 个 if 的那个）在阶段 1 被拆散并入统一接口，最终删除。

---

## 5. 数据域划分与建表规划

### 5.1 数据域（按迁移优先级）

| 域 | 现有文件 | 目标表（SQLite，单库 `system/coapis.db`） | 阶段 |
|---|---|---|---|
| **D1 用户域** | `users.json` | `users`（字段以 `_create_tables()` 为准；**`id` 改 `TEXT(uuid)` PK**，D-6=a 对齐企业版；其余各表 `user_id` 外键同步 TEXT） | **P1 打穿验证** |
| D1 审计 | `audit_logs.json` | `audit_logs` | P1 |
| D1 偏好 | `user_settings.json` / `user_preferences.json` | `user_settings` / `user_preferences` | P1 |
| D1 密钥 | `api_keys.json` | `api_keys` | P1 |
| D1 积分/用量 | `point_transactions.json` / token_usage | `point_transactions` / `token_usage` | P1 |
| D2 场景域 | `scenes.json` / `user_scenes.json` | `scenes` / `user_scenes` | P2 |
| D2 标签域 | `tags.json` / `user_tags.json` | `tags` / `user_tags` | P2 |
| D2 分类/上下文 | `categories.json` / `domain_contexts.json` | `categories` / `domain_contexts` | P2 |
| D3 会话列表 | `workspaces/*/chat/chats.json` | `chats`（workspace 维度分库或加列，P3 再定） | P3（可选） |
| D3 会话快照 | `workspaces/*/sessions/*.json` | 保留 JSON（单会话文件，写频率低）或并入 history.db，**P3 再评估** | P3（可选） |
| D2.5 外部系统域（v1.1 新增） | `system/external_systems_config.json` / `system/external_identity_mappings.json` | `external_systems` / `external_bindings`（对齐企业版 migration 005，见 §5.3B5） | P2 |
| 不动 | `agent.json`/`skill.json`/`config.json`/Markdown | 保持文件（低频、单写者、LLM 可读） | — |

> D3 的会话数据已经是"每 workspace 一个 history.db"的格局，强行并库收益低、风险高，
> 放到最后评估，**P1/P2 不碰**。

### 5.2 表结构原则

- 直接沿用 `UserSystemDB._create_tables()` 里已有的 SQLite schema（users / audit_logs / 各 usage 表）——
  那套 schema 已经写过、验证过，不重新发明。
- JSON 文件里 schema 外的脏字段：迁移时原样存进 `extra JSON` 兜底列，不丢数据。
- 所有表带 `updated_at REAL`（沿用 `time.time()` 风格），便于增量备份。
- **v1.1 增补（对齐企业版规范）**：新表采用企业版 `table-structure-standard.md` v1.2 的标准 5 字段（`id`/`created_at`/`updated_at`/`deleted_at`/`memo`）；SQLite 适配——`updated_at` 应用层维护、`deleted_at` 逻辑删、`memo` 备注。新表主键用 TEXT（对齐企业版 `scenes` 表 VARCHAR(64) PK 先例，与社区版字符串 ID 体系一致）。
- **v1.2 更新（D-6 已拍板）**：`users` 表不再是"INTEGER 主键例外"——`id` 改 **`TEXT(uuid)`**（对齐企业版 PG UUID 主键；存量 int 用 `uuid.UUID(int=old_id)` 确定性映射，幂等可逆、无需映射表），各表 `user_id` 外键同步 TEXT。**所有表主键与 ID 字段统一 TEXT(uuid)**。时间戳差距（社区 REAL unix 秒 vs 企业 `timestamptz`）P1 不动，P4 对齐时按字段映射表处理（§5.3F）。

### 5.3 企业版 coapis-pro 现有盘点（v1.1 新增，本方案优化依据）

> 源码树：`/apps/ai/tool-dev/dev-coapis/coapis-pro`（⚠️ 非 git 仓库，纯源码树，基线需确认）。
> **结论先行：企业版已经在做同一件事**（repository 抽象 + 注入式替换数据层），且外部系统域 P0 已落地。
> 社区版方案不是从零发明，而是**对齐企业版既有接口、吸收 pro 树里已写好的地基代码**。

**A. 可参考的文档**（`coapis-pro/docs/`）：

| 文档 | 价值 |
|---|---|
| `REPOSITORY_USAGE_GUIDE.md` | 仓储工厂使用指南（注意：其中 `EnterpriseRepositoryFactory` 是文档"规划态"，代码里仍是 `foundation.RepositoryFactory`，以代码为准） |
| `外部系统接入与用户绑定-数据库化方案.md` | 外部系统/绑定数据库化方案，**P0 已实施（2026-09-06）**；其 P1 计划（foundation 抽象 + JSON + PG 双实现）与本方案 P1–P2 高度重叠 |
| `database/table-structure-standard.md` v1.2 | 表结构规范：标准 5 字段、四类表（普通/分区/缓存/复合主键）、21 表盘点清单 |
| `database/postgres-tables-design(-v2).md`、`postgres-migration(-plan).md` | PG 表设计与迁移方案 |

**B. 已落地的代码（pro 树）**：

1. **`foundation/repositories/`**（社区树缺失，pro 树独有）：
   - `base.py` — `UserRepository` 等 ABC 接口，注释明写"**未来可合并到社区版**"。
   - `json/` — user / scene / memory 的 **JSON 实现**（正是 P1 要写的 JSON 后端，已有人写过一版）。
2. **`enterprise/database/repositories/`** — Postgres 实现全家桶：`PostgresUserRepository`、`PostgresTagRepository`、`PostgresSceneRepository`、`PostgresExternalIdentityStore`（外部系统+绑定）、`PostgresChatRepository`、`PostgresMessageRepository`、`PostgresAuditLogRepository`。
3. **`enterprise/plugin_scenes_tags.py`** — 注入接线，文件头写明架构原则：**"复用社区版路由，经 RepositoryFactory 注入替换数据层，不做 monkey-patch"**——与 K3 完全同路，已被企业版验证。
4. **`enterprise/__init__.py` `register_plugin`** — 启动时注入 user / scenes / tags / external_identity / KB 五类仓储；企业模式对用户域是**硬要求**（无 session 直接 raise，不静默回退 JSON）——比社区版现状（静默 fallback）更严，值得借鉴。
5. **`database/migrations/`** — 002 KB(3 表) / 003 audit(1) / 004 企业管理(3) / **005 外部系统(2：`external_systems` + `external_bindings`)** / 006–007 字段对齐 / `scenes_table.sql`。
6. **`sql/`** — config(6) / rate_limit(5) / sso(3) / task_queue(4) 共 18 张表。
7. **`database/migrate_external_json_to_pg.py`** — JSON→PG 迁移参考实现（幂等 + 备份 + 对账），K4 迁移模式的现成范本。

**C. 社区版已存在的注入点（本次核实，P2 无需新增机制）**：

| 注入点 | 使用方 | 现状 |
|---|---|---|
| `RepositoryFactory.inject/get_external_identity_store` | `app/external_identity.py`、`routers/external_auth.py`、`routers/external_systems_admin.py` | 社区模式无注入 → 走 `system/external_systems_config.json` + `system/external_identity_mappings.json` |
| `inject/get_tag_repository` | `app/services/tag_service.py` | try/except → JSON 文件 fallback |
| `inject/get_scene_repository` | `services/scene_agent_service.py` | 同上 |

**D. 对方案的具体优化（v1.1 变更点）**：

1. **（v1.2 修订）P1 不吸收 pro 树 `foundation/repositories/`**（经 v1.2 盘点确认为**零引用孤儿设计**：企业 PG 实现并不引用它，启动注入也没用它，见 §5.3F3）。改为：**以社区版 `foundation/user_repository.py` ABC 为唯一基线**扩充方法集，**参照企业版 `PostgresUserRepository`（8 方法、UUID 参数）**补齐签名，保证 P4 兼容。factory diff（session 保留、企业版 DB 硬要求）仍吸收。
2. **P2 增加外部系统域**：`external_systems` / `external_bindings` 两张表（对齐企业版 migration 005），迁移 `system/external_systems_config.json` + `external_identity_mappings.json`；接口用现成的 `ExternalIdentityStore` 注入点。
3. **P4 方向反转、工作量减半**：不是"企业版去实现社区版的接口"，而是"验证社区版 SQLite 实现与企业版既有 PG 实现的签名兼容"；企业版只需换 `initialize()` 传参，**企业侧代码改动 ≈ 0**。
4. **表结构对齐企业版规范 v1.2**（见 5.2 增补）。
5. **迁移模式参照 `migrate_external_json_to_pg.py`**（幂等/留底/对账三件套直接移植）。
6. **借鉴企业版"DB 硬要求"**：SQLite 初始化失败时不再静默回退 JSON，改为明确报错 + 日志。~~（`COAPIS_STORE=json` 逃生开关除外）~~ **[已执行：JSON 后端已彻底删除，`COAPIS_STORE` 环境变量不再存在]**

**E. 盘点中发现的坑**：
- pro 树非 git 仓库，无法确认其相对社区版 main 的漂移程度 → 见决策点 D-5（v1.2 已拍板：`server/` 树为基线）。
- `REPOSITORY_USAGE_GUIDE.md` 与代码不同步（工厂名不一致）→ 引用文档时以代码为准。
- pro 树 `user_repository_json.py` 与社区版有细微 diff（email 字段、返回值清理）→ 若后续参照使用，以社区版为基、合并 pro 侧增强。

**F. 企业版对比盘点（v1.2 新增，2026-09-14 聚焦排查）**：

> 问题：聚焦数据库支持，社区做完后企业版能否无缝衔接？
> **结论：注入层已无缝；用户域有 3 条缝（D-6 拍板后剩 2 条）；pro 的 `foundation/repositories/` 是零引用孤儿，不吸收。**

1. **注入层（已无缝）**：社区/企业都走同一个 `foundation.RepositoryFactory`（kb/user/tag/scene/external_identity 五注入点），企业版 `register_plugin` 启动注入，机制与社区完全一致。P1 落地后企业版**只需换 `initialize()` 传参，代码改动 ≈ 0**。
2. **用户域 3 条缝（真正的差异）**：
   - **ID 类型**：社区 `int` vs 企业 `UUID` → **D-6 拍板 = A 已解决**（社区改 TEXT(uuid)，§5.2 v1.2）。
   - **字段宽度**：社区 REAL（unix 秒）/ INTEGER vs 企业 `timestamptz` / `VARCHAR` → P1 不动，P4 对齐时出**字段映射表**（id: str(uuid) ↔ UUID；时间: REAL ↔ timestamptz；is_active: INTEGER(0/1) ↔ BOOLEAN）。
   - **签名集合**：社区 ABC 6 方法、企业 PG 8 方法（多 `get_user_by_username_sync`，参数 UUID）、`UserSystemDB` 27 个公开方法 → P1 把 ABC 扩到覆盖 27 方法（§11.4），P4 验证 ⊇ PG 8 方法。
3. **`foundation/repositories/` 是孤儿（v1.1 D1 因此反转）**：该目录（base.py ABC + json/）在 pro 树中**零引用**——企业 PG 实现引用的是自己的 `enterprise/database/repositories/`，启动注入也不走它。"注释写未来可合并"只是规划态。→ P1 不吸收，参照 PG 实现签名即可。
4. **pro 树有两套树**：`server/`（在用主树）与 `coapis/`（旧树）。**D-5 拍板：以 `server/` 树为 pro 基线**，旧树仅交叉参考。
5. **死代码**：`repository_factory.py` 的 `try: from coapis.enterprise … except: fallback` 分支在社区版是死分支（无 enterprise 包）→ P1 顺手清理（可选，不影响机制）。

---

## 6. 分阶段实施计划

### 阶段 0：授权统一（前置必做，开源门票）

- 定口径（决策点 D-1，见 §8）。
- 批量替换 523 个 py 文件头 + 622 个无 license 头，统一为选定口径（脚本 + 全量 diff 复核）。
- 根 LICENSE / README badge / `pyproject.toml` license 字段三处对齐。
- **验收**：`grep -rl "AGPL" server/ client/` 与口径一致；CI 加 license-header 检查。
- 风险：低（纯文本）；法律口径需小蜜蜂最终确认。

### 阶段 1：收敛用户域（P1 打穿，验证模式）⭐ 建议先做

目标：把 `UserSystemDB` 的 25 个 `if self._use_database:` 拆掉，用户域走统一接口 + SQLite。

**步骤：**

1. 在 `foundation/` 补全用户域接口（**以社区版 ABC 为基线**，v1.2 修订：不吸收 pro 孤儿目录，见 §5.3F3）：
   把 `UserRepository` 从现有 6 方法扩到覆盖 `UserSystemDB` 全部 27 个公开方法的方法集
   （`get_user_by_username` / `insert_user` / `update_user` / `list_users_page` / `insert_audit_log` /
   `get_user_token_usage` / `save_user_preferences` / …，完整清单见 §11.4），
   签名**参照企业版 `PostgresUserRepository`**（8 方法、UUID 参数），JSON/SQLite 行为等价。
2. **D-6=a ID 体系改造（v1.2 新增）**：`users.id INTEGER → TEXT(uuid)`，各表 `user_id` 外键同步 TEXT。
   存量 int 用确定性映射 `uuid.UUID(int=old_id)`（幂等、可逆、无映射表）；新用户 `uuid4()`。
   全代码 `user_id: int` 注解改 `str`（19 个调用方文件，清单见 §11.3）。
3. 实现 `SqliteUserRepository`（单文件 `system/coapis.db`，WAL）。
   SQL 直接搬 `_create_tables()`（users.id 改 TEXT PK、去 AUTOINCREMENT）+ 各分支里的现有 SQL，**不是重写**。
4. `UserSystemDB` 降级为一个薄壳：内部持有 `RepositoryFactory.get_user_repository()`，
   25 个 `if` 全删，方法一行转发（调用方 19 个文件逻辑零改动，止血最快）。
5. 首启迁移钩子（**ID 改造与 JSON→SQLite 迁移同一事务**）：
   检测到 `system/users.json` 存在且 `coapis.db` 无 users 表数据 →
   自动 import（事务内，int→uuid 映射）→ 成功后把原文件 rename 为 `users.json.migrated-<ts>` 留底。
6. 双跑对账：迁移后跑一次 JSON 与 SQLite 全量 diff（按 username 比对，不依赖 id）+ int→uuid 映射双射校验，不一致报警。
7. 测试矩阵：同一批 27 方法用例跑 JSON backend 和 SQLite backend，结果 diff 为零
   + 新增 ID 映射双射测试 / 迁移幂等测试（详见 §11.5）。
8. 灰度：dev 环境全量跑一周 → mycom 生产迁移（迁移脚本幂等，可重跑）。
9. ~~JSON 后端代码保留一个版本（配置开关 `COAPIS_STORE=json|sqlite`，默认 sqlite），下个版本删除。~~
   **[已执行：`user_repository_json.py` 已删除，`COAPIS_STORE` 环境变量已移除，社区版仅 SQLite，无回退]**

**验收：**
- `user_system/database.py` 中 `if self._use_database:` 归零（文件可整体删除或只剩薄壳）。
- `users.id` 全为 uuid 字符串；存量 int 数据 100% 映射（对账：迁移前后用户数一致 + 映射双射）。
- 生产迁移后登录/改密/重置/API Key/积分/审计全链路 E2E 通过。
- 回滚预案：恢复 `.migrated-<ts>` 备份文件 + 删除 `coapis.db` 重启（10 分钟内完成）。

### 阶段 2：铺开场景/标签/分类域（D2）+ 外部系统域（D2.5，v1.1 新增）

- 同样模式：接口补全 → `SqliteTagRepository` / `SqliteSceneRepository` / `SqliteCategoryRepository` →
  薄壳转发 → 迁移钩子（`scenes.json` 46KB 量级，秒级）→ 双跑对账。
- `tag_service` / `scene_agent_service` 已经走 `RepositoryFactory`，改动面小。
- **外部系统域**：`external_systems` / `external_bindings` 两张表（对齐企业版 migration 005 的表结构）；
  接口走现成的 `RepositoryFactory.inject/get_external_identity_store` 注入点
  （`external_identity.py` / `routers/external_auth.py` / `routers/external_systems_admin.py` 三个使用方已就绪），
  只需补 SQLite 实现 + 迁移 `system/external_systems_config.json` + `system/external_identity_mappings.json`。
  注意：2026-09-14 刚落地的"前缀+外部 ID"统一命名规则落在 `external_bindings` 表上，入库后该一致性由唯一约束兜底。
- 清理生产里的 `scenes.json.bak` / `tags.json.backup_*` 疤痕（归档后删除）。

### 阶段 3：会话域评估（D3，可延后）

- 先评估 `chats.json` 整读整写在生产实测下的实际耗时；不达标才动。
- 会话快照 JSON 是否并入 `history.db`：以"同一会话数据在两个存储里口径不一"的真实 bug 数为决策依据。
- 本阶段**可能只做评估不做改动**，结论写回本文档。

### 阶段 4：企业版 Postgres 对齐（v1.1 方向反转，工作量减半）

- 企业版**已有一整套 Postgres 实现**（User/Tag/Scene/ExternalIdentity/Chat/Message/Audit，
  均通过同一个 `RepositoryFactory` 注入，见 §5.3B2–B4），所以 P4 不再是"企业版去实现社区版接口"，而是：
  1. **签名兼容验证（v1.2 具体化）**：社区版 `UserRepository` 方法集 **⊇ `UserSystemDB` 27 方法 ∪ 企业版 `PostgresUserRepository` 8 方法**（含 `get_user_by_username_sync`），逐方法比对参数/返回值出差异表；字段宽度按映射表对齐（id: `str(uuid)` ↔ `UUID`；时间: REAL ↔ `timestamptz`；is_active: INTEGER(0/1) ↔ BOOLEAN，见 §5.3F2）；
  2. 企业版只需换 `initialize()` 传参（PG session 替代 SQLite 连接），**企业侧代码改动 ≈ 0**；
  3. `enterprise_stubs.py` 动态导入机制不变，K8 边界保持。
- 验证：同一套测试矩阵在 SQLite 和 Postgres 上各跑一遍，结果等价。
- 这一步把"CRUD 只写一遍"从社区版扩展到全生态——两版共享同一套 `foundation/repositories/` 地基。

### 里程碑与工作量估计

| 阶段 | 内容 | 估计 | 依赖 |
|---|---|---|---|
| P0 | 授权统一 | 0.5 天 | 决策点 D-1 |
| P1 | 用户域收敛 + 迁移 | 3–5 天 | 无（可与 P0 并行） |
| P2 | 场景/标签/分类收敛 + 迁移 | 2–3 天 | P1 模式验证 |
| P3 | 会话域评估 | 0.5–1 天 | P2 |
| P4 | 企业版对齐（签名兼容验证 + initialize 传参，企业侧改动 ≈ 0，v1.1） | 1–2 天 | P1/P2（需私有包仓库权限） |

---

## 7. 关键设计决策（已在方案内定，可推翻）

| # | 决策 | 理由 |
|---|---|---|
| K1 | 社区后端用 SQLite（stdlib sqlite3），不引入 ORM | 零依赖、零运维；与现有 db_ops 风格一致；避免 SQLAlchemy 的引入面 |
| K2 | 单文件 `system/coapis.db`（D1/D2 同库），WAL | 简单；单实例部署够用；WAL 解决读写并发 |
| K3 | `UserSystemDB` 保留为薄壳转发层，调用方零改动 | 止血最快、风险最低；验证后再考虑彻底扁平化 |
| K4 | 迁移 = 首启自动 + 幂等 + 留备份 + 双跑对账 | 非破坏性；生产迁移可重跑、可回滚 |
| K5（已执行） | ~~JSON 后端保留一个版本作为逃生开关（`COAPIS_STORE`）~~ | **已删除**：`user_repository_json.py` 移除，`COAPIS_STORE` 环境变量不存在，社区版仅 SQLite |
| K6 | LLM 记忆类 Markdown 不动 | 给模型读的，必须是文件 |
| K7 | 会话域（D3）最后评估，不强行并库 | 已是 per-workspace SQLite 格局，强行统一收益低风险高 |
| K8 | 企业边界不动：`coapis.enterprise` 继续私有 + 动态 import | 现状干净，守住即可 |
| K9（v1.2 修订） | 地基代码**只参照**企业版既有实现（`foundation/repositories/` 经盘点为零引用孤儿，**不吸收**；表结构规范 v1.2、迁移脚本模式、PG 实现签名仍参照） | 社区版 ABC 为唯一基线扩充到 27 方法（§11.4），签名对齐企业 PG 即可达成"接口天然一致"，无需引入孤儿代码 |
| K10（v1.2） | 社区版 `users.id` 改 `TEXT(uuid)`，各表 `user_id` 外键同步 TEXT（D-6=a） | 与企业版 PG UUID 主键对齐，消除用户域最硬的 ID 类型缝；存量 int 确定性映射 `uuid.UUID(int=id)`，幂等可逆 |

---

## 8. 待拍板决策点

- **D-1 授权口径**（最优先，P0 的前置）：
  a) 全部 Apache 2.0（含文件头批量替换）；
  b) 核心 Apache 2.0 + 企业私有包商业授权（文件头按目录区分）。
  **我的建议：a**——开源生态里 Apache 单一口径最省心，企业代码靠私有包边界保护，不靠 license 条款。
- **D-2 社区后端确认 SQLite**：是否同意 K1/K2（SQLite 单文件，不引 ORM）？
- **D-3 迁移策略**：是否同意 K4（首启自动迁移 + 留备份 + 双跑对账），还是要求生产手动执行迁移脚本？
- **D-4 范围与节奏**：
  a) 先只打穿用户域（P1）验证模式，绿了再铺 P2——**我的建议**；
  b) 一口气 P1+P2 做完再部署。
- **D-5 pro 树基线与吸收方式（v1.1 新增，v1.2 已拍板）**：**pro 基线 = `coapis-pro/server/` 树**（旧 `coapis/` 树仅交叉参考）；吸收方式因 v1.2 盘点（§5.3F3：`foundation/repositories/` 为零引用孤儿）修订为**只参照不吸收**——签名参照 `PostgresUserRepository`，规范参照表结构 v1.2 与迁移脚本模式。
- **D-6 ID 体系统一（v1.2 新增，已拍板 = A）**：社区版 `users.id` 改 `TEXT(uuid)`，对齐企业版 PG（K10）。影响面：`user_id: int` 注解全改 `str`（19 个调用方文件）、users.json/SQLite 双端 ID 改造与 JSON→SQLite 迁移同一事务（§6 阶段 1、§11）。备选留档：b) 仅 API 层字符串化（已做完，但用户域 ID 缝保留到 P4）；c) 不做（不推荐）。

> D-5、D-6 已拍板，P1 文件级改动清单已出（§11）。**剩 D-1（阻塞 P0）、D-2（确认 SQLite）、D-3（迁移策略）、D-4（节奏，建议 a）未拍板——D-2/D-3 定了即可开工 P1**（P1 与 P0 可并行，不依赖 D-1）。

---

## 9. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 迁移丢数据 | 高 | 事务内 import + 双跑对账 + 原文件 rename 留底（回滚：恢复备份 + 删 db 重启） |
| SQLite 并发写入锁（生产多 worker） | 中 | WAL + busy_timeout；单实例部署下写 QPS 极低；P1 灰度期压测观察 |
| 薄壳转发层引入性能开销 | 低 | 转发是纯函数调用，纳秒级；测试矩阵里带基准对比 |
| 授权批量替换改坏文件 | 低 | 脚本只动文件头 block，CI license 检查 + 全量 diff 复核 + 单独 commit 便于回滚 |
| 企业版接口对齐延迟 | 中 | P4 独立排期；社区版不阻塞 |
| `history.db` 与新库口径漂移（会话域） | 中 | P3 先评估不动手；口径问题以真实 bug 数决策 |

---

## 10. 与现有工作的关系

- 本方案**不改变**任何用户可见功能行为——纯存储层收敛，API/前端零变化（P1 期间调用方甚至零改动）。
- 与"用户ID字符串化"（7f6d1e8）兼容且互补：API 层已按 username/整数/UUID 解析（`_resolve_user`），**D-6=a 让内部 `users.id` 也变为 TEXT(uuid)**，内外口径彻底统一。
- 与 v1.0.1 生产（mycom）兼容：迁移脚本幂等，可在下次发版时随镜像一起执行，或提前手动跑。
- `enterprise_stubs.py` 的升级提示端点不受影响。
- **与 coapis-pro 的关系（v1.2 更新）**：企业版已在同一条统一路线上实现（repository 抽象 + 注入式替换数据层，外部系统域 P0 已落地）。v1.2 盘点结论（§5.3F）：注入层已无缝、用户域 3 缝中 ID 缝由 D-6=a 解决；其 `foundation/repositories/` 为零引用孤儿，**只参照不吸收**——P1 起两版共享同一套接口地基（社区 ABC 扩到 27 方法、签名对齐 PG），杜绝两套抽象漂移（详见 §5.3F）。

---

## 11. P1 文件级改动清单（v1.2 定稿，D-6=A；**未动代码**）

### 11.0 前提与范围
- **未决前置**：D-2（确认 SQLite 后端）、D-3（迁移策略）——D-2/D-3 拍板即可开工；P1 与 P0 并行，不依赖 D-1。
- **范围**：仅 P1（用户域收敛 + ID 体系统一 + JSON→SQLite 迁移 + 测试）。P2–P4 不含。
- **总原则**：API 层零改动（7f6d1e8 已字符串化，`_resolve_user` 天然兼容 uuid，前端零改动）；调用方逻辑零改动（薄壳转发）；改动集中在 foundation/ + user_system/ + 类型注解。

### 11.1 新增文件（2）
| # | 文件 | 内容 |
|---|---|---|
| N1 | `server/coapis/foundation/user_repository_sqlite.py` | `SqliteUserRepository`：21 个业务方法（§11.4）；单文件 `system/coapis.db`（WAL + busy_timeout）；schema 搬 `_create_tables()`，**`users.id` TEXT PK（去 AUTOINCREMENT）、各表 `user_id` 外键 TEXT**；SQL 直接搬现有分支，不重写 |
| N2 | `server/coapis/foundation/migrations.py` | 首启迁移：`users.json`→`coapis.db` 事务 import + int→uuid 确定性映射（`uuid.UUID(int=old_id)`，幂等可逆无映射表）+ 原文件 rename `users.json.migrated-<ts>` 留底；可重跑（无开关，SQLite 唯一） |

### 11.2 核心改动文件（7）
| # | 文件 | 改动点 |
|---|---|---|
| C1 | `foundation/user_repository.py`（239 行） | `User` dataclass `id: int → str(uuid)`；ABC **6 → 21 业务方法**（§11.4），`user_id: int → str`；`create_user` 返回含 `id` 的 dict；签名参照企业版 `PostgresUserRepository`（UUID 参数） |
| C2（已执行） | ~~`foundation/user_repository_json.py`（229 行）~~ | **已删除**：`user_repository_json.py` 整体移除，JSON 后端不再存在 |
| C3 | `foundation/repository_factory.py` | `get_user_repository()` 社区版固定 SQLite（无开关）；企业版必须注入 session/user_repo（否则报错）；`initialize()` 签名不变 |
| C4 | `user_system/database.py`（815 行）→ 薄壳 | 保留 `UserSystemDB()` 单例入口与 21 个业务方法签名（`user_id: int → str`，**int 入参兼容**：uuid 映射后转发）；**25 个 `if self._use_database:` 分支全删**，方法一行转发 `RepositoryFactory.get_user_repository()`；`_create_tables`/`_load_json`/`_save_json`/`_find_*` 移除（归 C2/N1）；`close()` 保留转发 |
| C5 | `user_system/models.py` | `TokenUsageRecord.user_id` / `AuditLog.user_id` / `AuditLogCreate.user_id`：`int → str` |
| C6 | `user_system/service.py` | `get_user_by_id(user_id: int → str)`；`register()` 新 id 为 uuid 字符串（逻辑不变） |
| C7 | `app/routers/user/user_scene_preferences.py` | `_get_preference` / `_set_preference`：`user_id: int → str` |

### 11.3 调用方适配（19 个文件，逻辑零改动）
- 其余 14 个调用方（`app/auth.py`、`app/routers/auth.py`、`workspace_*`、`permissions.py`、`admin_system.py`、`admin_audit.py`、`user_system/audit_log.py`、`user_system/security_ops.py`、`user_scene_preferences` 路由、`user_feedback.py`、`user_model_prefs.py`、`backup/*`、`external_systems` 相关）：**薄壳转发，逻辑零改动**。
- 唯一例外 `app/routers/admin/admin_users.py`（2 处）：
  - `_resolve_user` int 分支：`int(user_id)` → `str(uuid.UUID(int=int(user_id)))` 映射（兼容旧整数链接）；
  - `_create_user_fallback`：返回的 `id` 为 uuid 字符串（API 已字符串化，前端零改动）。
- 核对清单：全库 grep `user_id: int` 归零（C1/C2/C4/C5/C6/C7 覆盖全部 19 处注解）。

### 11.4 ABC 方法集（21 业务方法，由 6 扩）
- **用户 CRUD（14）**：`create_user`(=insert_user)、`get_user_by_id`、`get_user_by_username`、`get_user_by_email`、`update_user`(by username)、`update_user_by_id`、`delete_user`(by username)、`delete_user_by_id`、`list_users`、`list_users_page`、`user_exists`、`email_exists`、`count_users`、`count_active_users`
- **审计/积分/用量（5）**：`insert_audit_log`、`insert_point_transaction`、`insert_token_usage`、`get_user_token_usage`、`get_agent_token_usage`
- **偏好（2）**：`get_user_preferences`、`save_user_preferences`
- 说明：`UserSystemDB` 27 个公开方法中，`__new__/__init__/execute/executemany/commit/fetch_one/fetch_all` 属连接层职责，不进 ABC（由 N1/C4 内部持有）；`close` 由薄壳转发。最终方法表以 P1 实现 diff 为准，**JSON/SQLite（+P4 PG）三方等价**。

### 11.5 测试与脚本（新增 2）
| # | 文件 | 内容 |
|---|---|---|
| T1 | `tests/test_user_repository.py`（新） | 参数化：21 方法用例在 JsonBackend / SqliteBackend 跑，diff 为零；int→uuid 映射**双射**测试（`uuid.UUID(int=id)` 往返）；迁移**幂等**测试（二次运行 no-op）；薄壳转发等价测试（`UserSystemDB()` 直调 vs repository 直调） |
| T2 | `scripts/reconcile_users.py`（新） | 双跑对账：`users.json` ↔ `coapis.db` 按 username 全字段 diff + int→uuid 双射校验；不一致报警 |

### 11.6 连带小项（P1 窗口内顺手）
- `backup/_ops/create_helpers.py`（L161 备份文件列表）：新增 `coapis.db`——迁移后用户数据主身在 `coapis.db`，备份必须覆盖。
- `backup/_ops/restore_helpers.py`（L327 `users.json` 特判）：验证 restore 流程兼容（恢复 `coapis.db`，`users.json` 缺失时跳过）。

### 11.7 执行顺序与验收
1. C1 ABC 扩充 → C2/N1 双实现 → C3 factory 接线 → C4 薄壳（止血，调用方零改动）。
2. C5–C7 类型注解 → 11.3 调用方适配 → T1 测试矩阵全绿。
3. N2 迁移钩子 + T2 对账脚本 → dev 灰度一周 → mycom 生产迁移（幂等可重跑）。
4. **验收**：`if self._use_database:` 归零；`users.id` 100% uuid 且映射双射；登录/改密/重置/API Key/积分/审计 E2E 全绿；回滚演练（恢复 `.migrated-<ts>` 备份 + 删 `coapis.db` 重启）10 分钟内。
