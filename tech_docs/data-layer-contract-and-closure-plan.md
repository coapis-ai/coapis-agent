# 数据层契约抽象与残缺补齐方案

> 版本 v1.0（2026-09-17）
> 触发：M1 四域落库后复盘，发现「到处都是残缺」+ 用户要求「数据库处理要抽象，不要每加一个库写一套」
> 性质：**方案文档，未动代码**。含 4 个决策点（D-1~D-4），待拍板后执行。

---

## 1. 根因诊断（为什么"到处都是残缺"）

残缺不是「少写几个测试」，而是**四层里三层没建全**。M1 做的是「JSON → SQLite 落库搬运」，
没做「抽象契约 + 完整契约测试」。证据如下：

### 1.1 契约层（最大残缺）
| 域 | 抽象基类 | 现状 |
|----|---------|------|
| user | `UserRepository`（foundation） | 存在，但**假契约**：社区版同步 / 企业版 async；`create_user` 社区返回 `str`、企业返回 `Dict` —— 同步性 + 返回类型两处不一致 |
| tag | **无** | 只有 `SqliteTagRepository`，直接一个类，没有 ABC |
| scene | **无** | 只有 `SqliteSceneRepository`，没有 ABC |
| user_scene | **无** | 只有 `SqliteUserSceneSettingsRepo`，没有 ABC |
| （知识库） | `KnowledgeBaseRepository` | **孤儿**：知识库已删，接口还在 `repository.py`，零引用 |

### 1.2 实现层（社区 vs 企业，接口全不一致）
| 方法 | 社区版（裸 sqlite3） | 企业版（SQLAlchemy ORM） |
|------|--------------------|------------------------|
| Tag 列表 | `get_all()` / `list_tags(type, enabled_only, keyword)` | `list_tags(tag_type, parent_id, enabled, show_in_menu)` |
| Tag 保存 | `save_tag(dict)→None`、`save_many`(reconcile)、`seed_many` | `save_tag(Tag对象)→Tag`（**无 save_many/seed_many**） |
| Scene 读 | `get_scene` | `get_scene_by_id` |
| Scene 写 | `save_scene`(upsert) | `create_scene` + `update_scene`（**无 save_scene**） |
| Scene 删 | 硬删除 | **软删除**（设 deleted_at） |
| Scene 计数 | `increment_usage/count_by_primary_tag/count_referencing` | **无** |
| 返回类型 | 全是 `Dict` | 全是 **ORM 对象** |

**方法名、参数、返回类型、删除语义——全对不上。**

### 1.3 服务层（被迫 if/else 硬分叉）
`app/services/tag_service.py`（社区/企业**同一份代码**）：
- `__init__` 里 `if is_enterprise_installed() → _enterprise_repo else → _community_repo`
- `_load_tags_from_repository()`（企业）：`list_tags()` 拿 ORM 对象，逐字段 `getattr` 转 `TagConfig`
- `_load_tags_from_db()`（社区）：`get_all()` 拿 dict，`TagConfig(**row)` 直接展开
- 每个操作维护两套逻辑 → 加第三套数据库 = 再加第三个 if 分支

### 1.4 测试层
- 现有测试只覆盖 **SQLite 单实现**，没测契约、没测企业版实现
- 上一轮盘点的 M1 四域 CRUD 缺口（update 路径、save_many reconcile、边界、并发、迁移）未补齐

---

## 2. 「抽象」的两个层次（先澄清认知，避免方案跑偏）

用户诉求「不要每加一个库写一套」，必须拆开看，否则要么过度设计，要么没解决问题：

- **层次 1 · 契约抽象（Repository 接口）**
  定义 ABC，社区/企业/未来任何库都实现它。服务层、测试层、上层业务**只依赖契约**。
  → **能消除**：换库时服务层/测试/业务零改动；行为一致性可用同一份契约测试保证。
  → 这是 Repository/DAO 模式的核心，**必做**。

- **层次 2 · SQL 方言抽象（一套 SQL 代码跨库）**
  用 ORM（SQLAlchemy）让同一段查询代码既跑 SQLite 又跑 PG。
  → **能消除**：连 SQL 实现层也只写一套。
  → **代价**：社区版目前**没有 SQLAlchemy 依赖**（纯 sqlite3），引入要加依赖 + 重写 4 个仓储 + D-8 的 SQL 脚本改为 alembic/`create_all`。
  → **结论**：只有当「社区版未来也要跑 PG/MySQL」时才值得。若社区版**只跑 SQLite**（既定方向），
    层次 1 已解决 90% 痛点，层次 2 的边际收益小、代价大。

> 关键澄清：**「每库一套 SQL 实现」在分层架构里是正常的**（就像每个数据源一个 DAO），不是缺陷。
> 真正要消除的是**契约层残缺 + 服务层硬分叉**。看到 sqlite 关键字 ≠ 架构有问题，
> 问题在于 tag/scene 连 ABC 都没有、两套实现对不齐、服务层被迫分叉。

---

## 3. 目标架构（三层）

```
┌─────────────────────────────────────────────┐
│ 服务层  TagService / SceneService / UserService │  只依赖 ABC，无 if/else 分叉
├─────────────────────────────────────────────┤
│ 契约层  TagRepository / SceneRepository / ...  │  ABC，方法名+参数+返回类型严格统一
├─────────────────────────────────────────────┤
│ 实现层                                          │  每个库一套（正常分层）
│   ├─ SqliteTagRepository（社区，裸 sqlite3）      │
│   └─ PostgresTagRepository（企业，SQLAlchemy）    │
└─────────────────────────────────────────────┘
```

- 契约放社区版 `foundation`（企业版继承，与现有 `UserRepository` 一致）
- **统一返回 `Dict`**（不是 ORM 对象）——企业版用 `_normalize` 转 dict，服务层不感知 ORM
- 服务层删掉 `_load_tags_from_repository` / `_load_tags_from_db` 分叉，合并成单一路径
- 契约测试：一份用例参数化跑遍 SQLite + PG 两个实现

---

## 4. 契约设计（方法集 = 社区 ∪ 企业 并集，统一返回 dict）

### TagRepository
```python
class TagRepository(ABC):
    def get_tag(self, tag_id) -> Optional[Dict]
    def list_tags(self, tag_type=None, parent_id=None, enabled=None, keyword=None) -> List[Dict]
    def get_all(self) -> List[Dict]                 # = list_tags()
    def save_tag(self, tag: Dict) -> None           # upsert by id
    def save_many(self, tags: List[Dict]) -> None   # reconcile：DELETE NOT IN + upsert（企业版需补实现）
    def seed_many(self, tags: List[Dict]) -> int    # INSERT OR IGNORE（迁移种子；企业版可返回 0）
    def delete_tag(self, tag_id) -> bool
```
- 参数取并集：`tag_type`(=type) / `parent_id` / `enabled` / `keyword`
- 企业版 `save_many` 需补：`DELETE WHERE id NOT IN (…) + 逐条 upsert`

### SceneRepository
```python
class SceneRepository(ABC):
    def get_scene(self, scene_id) -> Optional[Dict]
    def list_scenes(self, status=None, category=None, limit=100, offset=0) -> List[Dict]
    def save_scene(self, scene: Dict) -> None       # upsert（企业版需补，替代 create+update）
    def delete_scene(self, scene_id) -> bool
    def seed_many(self, scenes) -> int
    def save_many(self, scenes) -> None
    def increment_usage(self, scene_id) -> None
    def count_by_primary_tag(self) -> Dict[str, int]
    def count_referencing(self, scene_id) -> int
    def list_referencing(self, scene_id) -> List[Dict]
```

### UserSceneSettingsRepository
```python
class UserSceneSettingsRepository(ABC):
    def get_settings(self, user_id) -> Dict
    def update_settings(self, user_id, settings: Dict) -> Dict
    def delete_settings(self, user_id) -> bool
```

### UserRepository（修复现有假契约）
- 统一**同步**（社区不动；企业 `async def` → `def`，SQLAlchemy sync engine）
- 统一**返回类型**：`create_user` 统一返回 `str`（user id），与 docstring 一致
- 方法签名在 ABC 上强制（当前 ABC 方法非 abstract，社区同步覆写/企业 async 覆写都没被约束）

---

## 5. 决策点（需拍板）

- **D-1 契约返回类型**：统一 `Dict`（推荐，服务层不感知 ORM） vs 统一 ORM 对象
- **D-2 SQL 实现策略**：
  - **方案 X（推荐）**：社区保持 sqlite3、企业保持 ORM，各自实现 ABC。
    零新增依赖，改动集中在「对齐方法名/返回类型」+「服务层去分叉」+「契约测试」。
    加新库 = 加一个实现类 + 跑同一份契约测试，服务层零改动。
  - **方案 Y（激进）**：社区引入 SQLAlchemy，统一 ORM，一套 model + repo 跨库。
    代价：新增依赖 + 4 仓储重写 + D-8 脚本改 alembic。仅当社区版确定要跑多库才值得。
- **D-3 同步 vs async 契约**：统一**同步**（推荐：社区现状、企业 tag/scene 本就同步、SQLAlchemy 可同步、规避 R1 await 缺陷） vs 全 async（服务层全改 async，连锁大）
- **D-4 删除语义**：scene 统一**软删除**（推荐，可恢复、保 usage_count，社区加 deleted_at 列）；tag 保持**硬删除** vs 全硬删除

> 推荐组合：**D-1=Dict、D-2=方案X、D-3=同步、D-4=scene软删/tag硬删**。
> 这套 = 标准 Repository/DAO 模式，不强行 ORM，最大化复用现有代码，一次性补齐四层残缺。

---

## 6. 分阶段执行清单（拍板后执行）

| 阶段 | 内容 | 验证标准 |
|------|------|---------|
| **P0** | 建 3 个 ABC（tag/scene/user_scene）+ 修复 UserRepository（同步/返回类型）+ 删孤儿 `KnowledgeBaseRepository` | `pytest` 收集通过；ABC 方法集与 §4 一致 |
| **P1** | 社区版实现对齐：tag/scene 方法名改到契约（`get_all`→保留为契约方法、`save_scene` 等）；统一返回 dict | 现有 SQLite 测试全绿（行为不变，只改接口名） |
| **P2** | 服务层去 if/else 分叉：tag/scene/user service 只依赖 ABC，合并双路径 | 服务层单测全绿；无 `is_enterprise_installed` 分叉残留（或仅保留注入处） |
| **P3** | 企业版实现对齐：PostgresTag/Scene 补 `get_all/save_many/count_*`、返回 dict、软删对齐；user 改同步 | 企业版契约测试（PG）全绿 |
| **P4** | 契约测试：一份参数化用例跑 SQLite + PG | 两实现行为一致（CRUD 全矩阵通过） |
| **P5** | CRUD 缺口补齐（上一轮盘点）：update 路径、save_many reconcile、边界、并发、迁移幂等 | 全绿 + 差分测试 |

每阶段独立可验证、可回滚；P0–P2 是社区版闭环，P3 依赖企业版 PG 环境。

---

## 7. 测试补齐矩阵（P4/P5 覆盖）

| 域 | Create | Read | Update | Delete | 边界/并发/迁移 |
|----|:---:|:---:|:---:|:---:|:---|
| user | ✅ | ✅ | ⬜ 部分 | ✅ | ⬜ 并发锁/迁移幂等 |
| tag | ✅(save) | ✅ | ⬜ save_many reconcile | ✅(硬) | ⬜ 幂等/边界 |
| scene | ✅ | ✅ | ⬜ save_many | ⬜(软删未测) | ⬜ usage 计数/引用 |
| user_scene | ⬜ | ✅ | ⬜ | ⬜ | ⬜ |

（✅ 已覆盖 / ⬜ 缺口）

---

## 8. 范围与影响

- **不改**：数据库表结构（§community_schema.sql 已定）、D-8 SQL 脚本、迁移逻辑（P0–P2 方案 X 下）
- **影响面**：foundation 3 新文件 + user_repository 修复 + 3 个 service 去分叉 + 企业版 3 仓储对齐 + 契约测试
- **风险**：P2 服务层去分叉是最大风险点（双路径合并易漏），需逐方法对照测试兜底
- **回滚**：每阶段 git 独立提交；契约 ABC 是纯新增，删除即回滚
