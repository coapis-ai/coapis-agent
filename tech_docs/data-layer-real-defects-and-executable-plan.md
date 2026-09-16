# 数据层：真实缺陷诊断 + 可执行实施计划

> 状态：诊断 + 方案（未改任何代码）
> 日期：2026-09-15
> 方法：逐文件读源码核对 `media/wecom_*_data-layer-upgrade-plan.md` 的四宗罪与 14 张清单，用 file:line 证据说话。
> 结论先行：**那份方案方向对，但 P0 被夸大、两宗罪已过时、漏掉了 3 个真问题；它开出的"统一 14 仓储异步+方言中立"大重写药方，对社区版是过度设计，会重蹈"折腾很久没解决真问题"的覆辙。**

---

## 一、先给结论（Bottom line）

真正卡住社区的**不是架构，是 2 个坏掉的调用点 + 1 个失效的配置 + 2 个并发/事务缺口**。

| # | 真问题 | 位置 | 影响 | 是否活跃 |
|---|--------|------|------|---------|
| R1 | `await` 打在**同步**仓储上 | `admin_users.py:346` | admin 建用户 500 | ✅ 活跃 |
| R2 | `db.create_user(…)` 方法不存在 | `auth.py:342` | 注册多一层静默 AttributeError（已被吞） | ✅ 活跃 |
| R3 | `COAPIS_DATABASE_URL` 是死代码 | `lifespan` 走 `DATA_DIR`，从不调 `resolve_db_path()` | 配置项不生效，D-7/D-8/D-9 名不副实 | ✅ 活跃 |
| R4 | 外部身份库：独立连接、无 `busy_timeout`、`save_bindings` 全删全插 | `external_identity_store_sqlite.py` | SSO 风暴下锁竞争 + 绑定表空窗 | ⚠️ 隐患 |
| R5 | 迁移非原子：`executescript` 中途隐式 commit、标志与数据分两次 commit | `migrations.py` | 崩溃中途 → 部分表迁移、users.json 没改名 | ⚠️ 隐患 |

那 14 张清单（14 个仓储）里，**真正需要动的只有 3 个文件**（user_repo 消费边界、external_identity、migrations）。其余 11 个（KB/文档/会话/runner/cron/场景标签等）在社区版是各自闭环、能跑的，不该为"统一"而重写。

---

## 二、逐条核对那份方案（对 / 错 / 过时 / 漏）

### 对的部分（四宗罪方向都成立）
- **一 同步/异步分裂**：属实。`foundation/user_repository.py` 23 个方法全 `def`（同步）；`foundation/repository.py` `KnowledgeBaseRepository` 全 `async def`。两套基类并存确实存在。
- **二 两套 SQLite**：属实。`user_repository_sqlite.py` 与 `external_identity_store_sqlite.py` 各自 `sqlite3.connect` 同一文件、各自一把锁、各自 pragma。
- **三 迁移重复**：方向对，但**表述已过时**（见下）。
- **四 绕道**：方向对，但**具体症状已过时**（见下）。
- **五 场景/标签不在库里**：属实。社区版 `tag_service.py:136` 用 `tags.json`，`scene_agent_service.py` 用 `scenes.json`，无 SQLite 路径。

### 错 / 夸大的部分
- **"P0 已实锤：用户域调用拿到协程对象直接炸"** —— **夸大**。用户域消费端其实大多是**同步→同步**（`UserSystemDB` 全同步、`user_store` 全同步），能正常跑。真正"await 同步"只有一处：`admin_users.py:346`。KB/cron/runner 仓储本身是全异步，消费端 `await` 也对，**不是 bug**。所以爆炸半径是**一个 admin 端点**，不是"整个用户域"。
- **清单 P0-1 "用户域 23 个方法"** —— 把范围说大了，实际只需要**消费边界**那一处对齐。

### 过时的部分
- **三 "迁移没有幂等标志，重跑翻倍（已实锤）"** —— **已过时**。`migrations.py` 现在**已有 F6 表级幂等标志**：`migration_state` 表按表打 marker + `json_migration` 完成标志 + `INSERT OR REPLACE`（users/preferences/settings/bindings）。"重跑翻倍"的原始 bug 已被修复。
  - **但**方案没提到的真问题还在：**非原子**。`_create_schema` 用 `executescript`（会隐式 `COMMIT`），把建表和迁移劈开；append-only 表的"插数据"和"打标志"是**两次独立 commit**，崩溃落在中间 → 部分表已迁移、users.json 未改名、标志半套。重跑虽不会整表翻倍，但状态是"半迁移"，不是干净幂等。
- **四 "users.json 被 30 处当数据源"** —— **已过时**。`app/user_store.py` 文档明确"SQLite-backed…旧 users.json 不再被业务逻辑读写"，`authenticate()` 走的是 `user_store.authenticate_user`（SQLite）+ `user_system`（同一个 SQLite）双读。**JSON 用户主存储已下线**。真正的残留不是"30 处读 JSON"，而是 **2 个坏调用点**（R1/R2）+ 一堆冗余的"双存储"代码。

### 漏掉的部分（方案完全没提）
- **R3 `COAPIS_DATABASE_URL` 失效**：`app/_app.py:323` `RepositoryFactory.initialize(data_dir=DATA_DIR)` → `initialize_community(DATA_DIR)` → `SqliteUserRepository(data_dir=DATA_DIR)` → 路径恒为 `DATA_DIR/coapis.db`（=`SYSTEM_DIR/coapis.db`，`constant.py:147` 写死 `DATA_DIR=SYSTEM_DIR`）。而 `resolve_db_path()`（唯一认 `COAPIS_DATABASE_URL` 的地方）**只在 `get_user_repository()` 的兜底分支**被调，正常启动下 `_user_repo` 已被 lifespan 预先建好，**永远走不到**。→ 文档吹的"单一环境变量"根本不控制真实落盘路径。
- **R4 外部身份库并发细节**：`external_identity_store_sqlite.py` 只设了 `journal_mode=WAL`，**没设 `busy_timeout`**（用户库那边有 `busy_timeout=3000`）；且 `save_bindings` 是**整表 `DELETE` 再逐行 `INSERT`**，读改写非定向 upsert，SSO 并发下有绑定表空窗 + 锁竞争。
- **R5 迁移原子性**（见上）。

---

## 三、为什么那份方案的药方对社区版是错的

方案主张：**"统一 14 个仓储为异步 + 方言中立 + 单一入口 + 社区版 SQLite 单库"**，并把 **T1（统一异步）** 排第一步。

问题：
1. **社区版只跑 SQLite 单库**（方案自己也承认），却要把 14 个仓储全部重写为"方言中立异步"——这是**企业版需求驱动的过度设计**。
2. **T1 排第一 = 又一次"折腾很久"**。真正活跃的 P0（R1/R2）是**小时级、孤立、低风险**的改动；先去做 14 仓储异步大重写，回归面 = 14 仓储 × 所有调用方，而它**并不能更快修好 R1/R2**。
3. **大重写不解决 R3/R4/R5**。配置失效、并发缺口、迁移原子性，重写 14 仓储一个都治不了，得单独修。
4. **社区 vs 企业边界被搅浑**。异步/方言中立是企业版（coapis-pro）的事，塞进社区仓会让社区版背上企业复杂度。

**判断**：方案的"病"诊断大半对，"药"对社区版开重了。正确的顺序是**先止血（R1/R2）→ 再修一致性（R3/R4/R5）→ 最后才谈结构化收敛（且分社区/企业两线）**。

---

## 四、可执行实施计划（分阶段、可验证、小步）

> 原则：每阶段独立可验证、可回滚；社区版不做企业复杂度；大重写不进社区仓。

### 阶段 0 —— 止血（P0，小时级，立即解锁用户）
目标：让 admin 建用户、注册这两条链路在**社区版**真正可用。

- **F0.1 修 `admin_users.py:346` 的 await-同步**
  - 最小改法（两版通吃，不重写）：
    ```python
    result = user_repo.create_user(user_data)
    if inspect.isawaitable(result):      # 企业版异步仓储
        result = await result
    user = result
    ```
  - 同步社区版直接拿 `str`；异步企业版才 await。**一行判断，零重写。**
- **F0.2 删/修 `auth.py:342` 的坏调用**
  - `db = UserSystemDB(); db.create_user(username, pw_hash, salt, role="user")` → `UserSystemDB` 没有 `create_user`（只有 `insert_user`）且签名不对，**AttributeError 被 `except Exception` 吞掉**，是静默死代码。
  - 因为上一行 `user_store.create_user(username, password)` **已经写入 SQLite**，这行是冗余且坏的 → **直接删除**（连同多余的 `db=`/哈希块），注册链路即干净。
- **F0.3 全仓扫一遍同类错配**（已扫完，结果锁定）：
  - 坏点共 2 个：`admin_users.py:346`、`auth.py:342`。
  - KB/cron/runner 的 `await` 都是真异步仓储，**不用动**。
  - `user_store.py:91/171`、`database.py:77` 都是同步正确调用，**不用动**。
- **验证**：dev 环境起 admin 建用户（201）、用户自注册（200）各一次，查 SQLite 有记录、无 500、日志无 AttributeError。

### 阶段 1 —— 一致性与并发（P1，中风险，1-2 天）
目标：让"配置、连接、事务"三件事各归其位。

- **F1.1 让 `COAPIS_DATABASE_URL` 真正生效（或删掉）**（R3）
  - 选 A（推荐）：`lifespan` 改为 `RepositoryFactory.initialize(data_dir=resolve_db_path().parent)`，让环境变量成为**唯一**路径来源；`get_user_repository()` 兜底分支的 `resolve_db_path()` 保留作安全网。
  - 选 B：删掉 `COAPIS_DATABASE_URL` 文档与 `db_settings.resolve_db_path`，明确"路径恒为 `DATA_DIR/coapis.db`（挂载卷内）"，少一个坑。
- **F1.2 合并两条 SQLite 连接 + 并发加固**（R4）
  - `SqliteExternalIdentityStore` 不再自建连接，改为**接收用户库的连接/连接管理器**（单一连接、单一锁、单一 pragma 组）。
  - 两个仓储都补 `PRAGMA busy_timeout`（外部库当前缺失）。
  - `save_bindings` 从"整表 DELETE+INSERT"改为**按 `external_id` 定向 upsert**（消除空窗 + 提速）。
- **F1.3 迁移原子化**（R5）
  - 去掉 `executescript` 的中途隐式 commit：建表与迁移放**同一连接同一事务**。
  - append-only 表的"插数据 + 打标志"**同一事务一次 commit**。
  - 目标：任意时刻崩溃，重跑都能收敛到一致态（要么全没迁移、要么全迁移完）。
- **验证**：① 设 `COAPIS_DATABASE_URL=custom/coapis.db` 启动，确认落盘路径真的变了（选 A）；② 并发 SSO 登录压测，绑定表无空窗、无 `database is locked`；③ 迁移中途 kill 进程，重启后状态一致、无半迁移。

### 阶段 2 —— 结构化收敛（P2，社区线，分两块）
目标：单一数据通路，但**只收敛社区需要的**，不碰 14 仓储大重写。

- **F2.1 用户域单一写通路**（清 R2 遗留的冗余）
  - 指定**唯一**用户写入口 = `user_store`/`repo`（已是 SQLite 单库）。
  - 删掉 `authenticate()` 里冗余的"SQLite 双读兜底"（现在读的是同一个库）、删掉 auth.py 里所有 `UserSystemDB` 二次同步。
  - 补一个"单一写通路"测试：任意创建路径，最终只落一张 `users` 表、只一处代码路径。
- **F2.2 异步/同步方向一次定死（社区版）**
  - **推荐**：社区版**保持同步**（现状能跑、低风险），消费边界用 F0.1 的 `isawaitable` 兜底即可；**不**把 14 仓储重写为异步。
  - 企业版异步统一 → 放 **coapis-pro**（独立仓、独立排期），不进社区仓。
- **F2.3 场景/标签入库**（disease #5，独立收尾）
  - `tag_service`/`scene_service` 社区版补 SQLite 路径，**复用阶段 1 的单一连接**，JSON 仅留作一次性历史导入。
  - 这两块自包含、可最后做，不在 P0/P1 关键路径上。

### 阶段 3 —— 企业版（独立仓 coapis-pro，单独排期）
- 14 仓储"异步 + 方言中立 + 单一入口 + 连接池"的完整统一，**只在 coapis-pro 做**。
- 社区仓不背企业复杂度。社区/企业共享的，只有 `user_repository.py` 抽象基类（签名对齐即可）。

---

## 五、改动面汇总（对比方案）

| 范围 | 方案主张 | 本计划 |
|------|---------|--------|
| 改文件数 | 14 仓储 + 全调用方 + 基类 | **阶段 0：2 个文件**；阶段 1：3 个文件；阶段 2：2-3 个文件 |
| 异步重写 | 14 仓储全部 | **0**（社区保持同步，边界用 `isawaitable` 兜底） |
| 方言中立 | 全做 | **不做**（社区只 SQLite；方言中立归 coapis-pro） |
| 回归面 | 巨大 | 小且可逐阶段回滚 |
| 修好 R1-R5 | 否（只治架构） | **是** |

---

## 六、待拍板（Decision points）

- **D-A｜先止血？** 是否按阶段 0 先修 `admin_users.py:346` + 删 `auth.py:342`（2 文件，小时级）？——**强烈建议先做这个**。
- **D-B｜`COAPIS_DATABASE_URL`** 选 A（让它生效，`lifespan` 走 `resolve_db_path`）还是选 B（删掉该变量与文档，路径恒为 `DATA_DIR/coapis.db`）？
- **D-C｜同步/异步** 社区版**保持同步 + 边界兜底**（推荐），还是按方案做全异步统一（不推荐进社区仓）？
- **D-D｜14 仓储大重写** 是否**明确划到 coapis-pro 企业仓**、社区仓不动？（推荐：是）
- **D-E｜验证强度** 阶段 1 的并发压测 / 迁移 kill 测试，是否要写进 CI？

> 拍板后我再动代码。现在**一行代码未改**。
