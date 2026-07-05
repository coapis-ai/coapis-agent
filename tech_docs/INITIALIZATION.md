# CoApis 系统初始化 — 深度分析与优化方案

> **版本**: v0.8.59 | **更新**: 2026-07-02
> **状态**: 分析完成，待确认实施

---

## 一、当前初始化流程全景

### 1.1 版本号机制（现状）

```
COAPIS_VERSION 环境变量
        ↓
coapis/__version__.py  →  __version__ = os.environ.get("COAPIS_VERSION", "0.0.0-dev")
        ↓
entrypoint.sh  →  覆写 __version__.py（Docker 启动时）
        ↓
pyproject.toml  →  version = {attr = "coapis.__version__.__version__"}
```

**问题**：`defaults.py` 中 `SYSTEM_VERSION = "0.8.12"` 是硬编码的，与实际版本脱节。

### 1.2 启动链路（4层 × 2种安装方式）

#### Docker 安装

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: entrypoint.sh                                      │
│   ├─ 检查核心配置文件是否存在                                  │
│   ├─ 不存在 → 运行 init_workspace.sh                         │
│   │   └─ init_workspace.sh → coapis init --defaults          │
│   │       └─ init_cmd.py → 创建 config.json + HEARTBEAT.md   │
│   ├─ 生成 __version__.py（从 COAPIS_VERSION 环境变量）         │
│   ├─ 运行 Python migration（静默失败）                         │
│   ├─ 恢复 MCP 包                                             │
│   └─ exec uvicorn                                            │
├─────────────────────────────────────────────────────────────┤
│ Layer 2: _app.py lifespan Phase 1（同步）                     │
│   ├─ auto_register_from_env()                                │
│   ├─ 7 个 migration 函数（每次启动都执行）                      │
│   ├─ 创建 Manager 实例                                       │
│   └─ 初始化 PermissionManager / AuditLogger / ...            │
├─────────────────────────────────────────────────────────────┤
│ Layer 3: _app.py lifespan Phase 2（后台异步）                 │
│   ├─ UserSystemDB / Plugin / ApprovalService                 │
│   └─ 打印 Ready Banner                                       │
└─────────────────────────────────────────────────────────────┘
```

#### 非 Docker 安装（pip / 源码）

```
┌─────────────────────────────────────────────────────────────┐
│ 用户手动执行: coapis init [--defaults] [--accept-security]   │
│   └─ init_cmd.py                                            │
│       ├─ 安全警告确认                                        │
│       ├─ 遥测收集（可选）                                     │
│       ├─ 创建 config.json                                    │
│       ├─ 配置 providers                                      │
│       ├─ 配置 channels                                       │
│       ├─ 配置 skills                                         │
│       ├─ 配置 env                                            │
│       └─ 创建 HEARTBEAT.md                                   │
├─────────────────────────────────────────────────────────────┤
│ 用户执行: coapis app 或 coapis desktop                       │
│   └─ _app.py lifespan（同 Docker Layer 2-3）                 │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 三个初始化入口的关系

| 入口 | 文件 | 触发条件 | 实际作用 |
|------|------|----------|----------|
| `coapis init` | `cli/init_cmd.py` | 用户手动执行 / init_workspace.sh | 创建 config.json + 配置 providers/channels/skills |
| `init_workspace.sh` | `server/deploy/init_workspace.sh` | Docker 首次启动（config.json不存在） | 回退方案：mkdir + 写默认配置 + 调用 coapis init |
| `_app.py lifespan` | `app/_app.py` | 每次启动 | 7个 migration 函数 + Manager 初始化 |
| `SystemInitializer` | `system/initializer.py` | **从未被调用** | 死代码 |

### 1.4 `coapis init` 实际做了什么

```python
# cli/init_cmd.py
def init_cmd(force, use_defaults, accept_security):
    # 1. 安全警告确认
    # 2. 遥测收集（可选）
    # 3. 创建 working_dir 目录
    # 4. 创建 config.json（交互式或默认值）
    # 5. 配置 providers（交互式）
    # 6. 配置 channels（交互式）
    # 7. 配置 skills（交互式）
    # 8. 配置 env（交互式）
    # 9. 创建 HEARTBEAT.md
    # 10. 调用 migration 函数：
    #     - migrate_legacy_skills_to_skill_pool()
    #     - ensure_default_agent_exists()
    #     - ensure_qa_agent_exists()
```

**注意**：`coapis init` **不创建目录结构**（只创建 working_dir），**不创建权限文件**，**不创建默认用户**。

---

## 二、发现的问题（按严重程度排序）

### 🔴 P0: `SystemInitializer.initialize()` 从未被调用

**现状**：
- `initializer.py` 定义了完整的初始化逻辑（目录、配置、权限、用户、Token统计、审计日志、版本迁移）
- 但 **没有任何地方调用它**
- `init_workspace.sh` 尝试调用 `coapis.system.initialize_system()`，但实际 `coapis init` 是独立的 CLI 命令，不走 `SystemInitializer`
- `_app.py` lifespan 直接调用 migration 函数，也不走 `SystemInitializer`

**影响**：
- `SystemInitializer` 成了死代码
- `_init_token_usage()`、`_init_audit_logs()` 等方法从未执行
- 目录创建依赖 `mkdir -p`（Shell）或运行时 `os.makedirs()`（Python），不统一

### 🔴 P0: SYSTEM_VERSION 硬编码且严重滞后

**现状**：
```python
# defaults.py
SYSTEM_VERSION = "0.8.12"  # 硬编码，实际版本已是 0.8.59
INIT_SCHEMA_VERSION = 1    # 从未递增
```

**影响**：
- `_check_version_migration()` 基于 SYSTEM_VERSION 做迁移判断，但版本号永远是 0.8.12
- 任何需要版本感知的迁移逻辑都无法正确触发

**正确做法**：
```python
# 应该从 __version__ 读取（已从 COAPIS_VERSION 环境变量获取）
from ..__version__ import __version__
SYSTEM_VERSION = __version__

# 或者直接从环境变量读取
import os
SYSTEM_VERSION = os.environ.get("COAPIS_VERSION", "0.0.0-dev")
```

### 🟡 P1: entrypoint.sh 重复执行 migration

**现状**：
```
entrypoint.sh → Python: migrate_legacy_workspace_to_default_agent()  ← 第1次
_app.py lifespan → migrate_legacy_workspace_to_default_agent()        ← 第2次
```

**影响**：
- 双重执行浪费启动时间

### 🟡 P1: entrypoint.sh 静默吞掉错误

**现状**：
```bash
python3 -c "...migrate_legacy_workspace_to_default_agent()..." 2>/dev/null || echo "⚠ Migration skipped"
```

**影响**：
- 如果 migration 失败，只打印 "Migration skipped"，无任何错误详情

### 🟡 P1: 目录创建不完整

**现状**：`DEFAULT_DIRECTORIES` 缺少以下目录：

| 缺失目录 | 使用方 |
|----------|--------|
| `audit_log` | AuditLogger（Phase 1 初始化时需要） |
| `tmp` | 多处临时文件操作 |
| `system/reviews` | 进化系统审核 |
| `system/skill_evolution` | 技能进化数据 |

### 🟢 P2: 初始化状态不可观测

- 没有 `.initialized` 标记文件
- 无法区分"首次启动"和"正常重启"
- 每次启动都执行全部 migration 检查

---

## 三、优化方案

### 3.1 设计原则

1. **两种安装方式，统一初始化逻辑**：Docker 和非 Docker 都调用同一个 `SystemInitializer`
2. **版本号动态化**：`SYSTEM_VERSION` 从 `COAPIS_VERSION` 环境变量获取
3. **首次 vs 日常分离**：首次初始化做全量，日常重启只做增量检查
4. **幂等安全**：任意次执行结果一致
5. **失败可见**：错误绝不静默吞掉

### 3.2 统一初始化架构

```
┌─────────────────────────────────────────────────────────────┐
│ 场景 A: Docker 首次启动（config.json 不存在）                  │
│                                                             │
│ entrypoint.sh                                               │
│   ├─ 生成 __version__.py（从 COAPIS_VERSION）                │
│   ├─ 检测 config.json 不存在 → 调用 coapis init --defaults   │
│   │   └─ init_cmd.py → SystemInitializer().initialize()     │
│   │       ├─ _ensure_directories()                          │
│   │       ├─ _ensure_config_files()                         │
│   │       ├─ _ensure_permissions()                          │
│   │       ├─ _ensure_default_user()                         │
│   │       └─ _write_init_marker()                           │
│   ├─ 恢复 MCP 包                                            │
│   └─ exec uvicorn                                           │
├─────────────────────────────────────────────────────────────┤
│ 场景 B: Docker 日常重启（config.json 已存在）                  │
│                                                             │
│ entrypoint.sh                                               │
│   ├─ 生成 __version__.py                                    │
│   ├─ 检测 config.json 存在 → 跳过初始化                       │
│   ├─ 恢复 MCP 包                                            │
│   └─ exec uvicorn                                           │
├─────────────────────────────────────────────────────────────┤
│ 场景 C: 非 Docker 安装                                       │
│                                                             │
│ 用户执行: coapis init [--defaults]                           │
│   └─ init_cmd.py                                            │
│       ├─ 安全警告确认                                        │
│       ├─ SystemInitializer().initialize()                   │
│       └─ 交互式配置（providers/channels/skills）              │
│                                                             │
│ 用户执行: coapis app / coapis desktop                        │
│   └─ _app.py lifespan                                       │
│       ├─ SystemInitializer().ensure_ready()  ← 增量检查      │
│       └─ Manager 初始化                                     │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 具体改造项

#### 改造 1: `defaults.py` — SYSTEM_VERSION 动态化

```python
# defaults.py
import os
from ..__version__ import __version__

# 版本号从环境变量获取（Docker 由 entrypoint.sh 注入，非 Docker 由 pip 安装时生成）
SYSTEM_VERSION = __version__

# Schema 版本用于数据格式迁移（独立于发布版本）
INIT_SCHEMA_VERSION = 2  # 递增以触发 schema 迁移
```

#### 改造 2: 重写 `SystemInitializer.initialize()`

```python
class SystemInitializer:
    """系统初始化器 — 单例模式."""

    def initialize(self, force: bool = False) -> Dict[str, Any]:
        """执行完整的系统初始化（幂等）.

        调用场景：
        - Docker 首次启动：entrypoint.sh → coapis init --defaults → 此方法
        - 非 Docker 安装：coapis init → 此方法

        Args:
            force: 是否强制重新初始化（覆盖现有配置）

        Returns:
            初始化结果摘要
        """
        result = {
            "success": True,
            "version": SYSTEM_VERSION,
            "schema_version": INIT_SCHEMA_VERSION,
            "actions": [],
            "warnings": [],
        }

        try:
            # 1. 确保所有目录存在（幂等）
            self._ensure_directories(result)

            # 2. 确保配置文件存在（不覆盖已有）
            self._ensure_config_files(force, result)

            # 3. 确保权限矩阵完整（合并新增权限）
            self._ensure_permissions(force, result)

            # 4. 确保默认用户存在
            self._ensure_default_user(force, result)

            # 5. 初始化 Token 统计文件
            self._ensure_token_usage(result)

            # 6. 初始化审计日志目录
            self._ensure_audit_logs(result)

            # 7. 版本迁移（带版本感知）
            self._run_migrations(result)

            # 8. 写入初始化完成标记
            self._write_init_marker(result)

            logger.info(
                "System initialization completed: %d actions, %d warnings",
                len(result["actions"]),
                len(result["warnings"]),
            )

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            logger.error("System initialization failed: %s", e, exc_info=True)

        return result

    def ensure_ready(self) -> bool:
        """增量检查：确保系统已初始化（用于日常重启）.

        调用场景：
        - _app.py lifespan 启动时调用

        Returns:
            True 如果系统已就绪，False 如果需要重新初始化
        """
        marker_file = self.working_dir / ".initialized"

        if not marker_file.exists():
            logger.warning("No .initialized marker found, running full initialization...")
            result = self.initialize()
            return result["success"]

        # 检查核心文件是否存在
        core_files = [
            self.system_dir / "config.json",
            self.system_dir / "permissions.json",
            self.system_dir / "users.json",
        ]
        for f in core_files:
            if not f.exists():
                logger.warning(f"Core file missing: {f}, running re-initialization...")
                result = self.initialize()
                return result["success"]

        # 检查版本是否需要迁移
        try:
            with open(marker_file, "r", encoding="utf-8") as f:
                marker = json.load(f)
            marker_version = marker.get("version", "0.0.0")
            if marker_version != SYSTEM_VERSION:
                logger.info(f"Version changed ({marker_version} → {SYSTEM_VERSION}), running migrations...")
                result = {"success": True, "actions": [], "warnings": []}
                self._run_migrations(result)
                self._write_init_marker(result)
        except Exception as e:
            logger.warning(f"Error reading init marker: {e}")

        return True
```

#### 改造 3: 统一目录列表

```python
DEFAULT_DIRECTORIES: List[str] = [
    # 系统核心
    "system",
    "system/.secret",
    "system/templates",
    "system/evolution",
    "system/reviews",
    "system/skill_evolution",
    # 全局数据
    "agents",
    "skills",
    "skill_pool",
    "logs",
    "audit_log",
    "media",
    "local_models",
    "memory",
    "models",
    "plugins",
    "custom_channels",
    ".backups",
    "tmp",
    "files",
    # 用户工作区根目录
    "workspaces",
]
```

#### 改造 4: 版本感知迁移

```python
def _run_migrations(self, result: Dict[str, Any]) -> None:
    """运行版本迁移（仅在版本升级时执行）."""
    config_file = self.system_dir / "config.json"
    if not config_file.exists():
        return

    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    current_version = config.get("version", "0.0.0")

    if current_version == SYSTEM_VERSION:
        return  # 版本一致，无需迁移

    logger.info(f"Migrating from {current_version} to {SYSTEM_VERSION}")

    # 按版本递增执行迁移脚本
    migrations = [
        ("0.8.50", self._migrate_to_0_8_50),
        ("0.8.55", self._migrate_to_0_8_55),
        # 新版本在此追加
    ]

    for version, migrate_fn in migrations:
        if _version_lt(current_version, version):
            try:
                migrate_fn(result)
                result["actions"].append(f"migration:{version}")
            except Exception as e:
                result["warnings"].append(f"migration:{version} failed: {e}")
                logger.warning(f"Migration to {version} failed: {e}")

    # 更新 config.json 中的版本号
    config["version"] = SYSTEM_VERSION
    _save_config(config_file, config)
```

#### 改造 5: 初始化完成标记

```python
def _write_init_marker(self, result: Dict[str, Any]) -> None:
    """写入初始化完成标记文件."""
    marker_file = self.working_dir / ".initialized"
    marker = {
        "initialized_at": time.time(),
        "version": SYSTEM_VERSION,
        "schema_version": INIT_SCHEMA_VERSION,
        "actions_count": len(result["actions"]),
    }
    with open(marker_file, "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2)
    logger.debug(f"Wrote init marker: {marker_file}")
```

#### 改造 6: 精简 entrypoint.sh

```bash
#!/bin/sh
set -e

WORKING_DIR="${COAPIS_WORKING_DIR:-/apps/ai/coapis}"
SYSTEM_DIR="${WORKING_DIR}/system"

echo "CoApis Server Starting (WORKING_DIR: ${WORKING_DIR})"

# 1. 生成版本文件（从 COAPIS_VERSION 环境变量）
COAPIS_VER="${COAPIS_VERSION:-0.0.0-dev}"
cat > /app/coapis/__version__.py << VEOF
# Auto-generated by entrypoint.sh
__version__ = "${COAPIS_VER}"
VEOF
echo "✓ Version: ${COAPIS_VER}"

# 2. 首次启动初始化（config.json 不存在时）
if [ ! -f "${SYSTEM_DIR}/config.json" ]; then
    echo "📦 First startup detected, running initialization..."
    coapis init --defaults --accept-security
    echo "✅ Initialization complete!"
else
    echo "✓ System already initialized."
fi

# 3. 设置环境
export PLAYWRIGHT_BROWSERS_PATH=/app/volume/playwright

# 4. 恢复 MCP 包
...

# 5. 启动服务器（不再重复执行 migration）
exec uvicorn coapis.app._app:app --host 0.0.0.0 --port "${COAPIS_PORT:-8000}"
```

#### 改造 7: 精简 `_app.py` lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_start_time = time.time()

    # ═══════════════════════════════════════════════
    # Phase 1: 系统就绪检查（同步，< 100ms）
    # ═══════════════════════════════════════════════
    from coapis.system.initializer import SystemInitializer
    initializer = SystemInitializer()

    # 增量检查：确保已初始化、核心文件存在、版本无需迁移
    if not initializer.ensure_ready():
        logger.error("System initialization check failed!")

    # auto_register_from_env() 保留（从环境变量注册管理员）
    from .auth import auto_register_from_env
    auto_register_from_env()

    # ═══════════════════════════════════════════════
    # Phase 2: 创建 Manager 实例（轻量，无 I/O）
    # ═══════════════════════════════════════════════
    multi_agent_manager = MultiAgentManager(base_dir=WORKSPACES_DIR)
    provider_manager = ProviderManager.get_instance()
    ...

    # ═══════════════════════════════════════════════
    # Phase 3: 后台异步初始化（不阻塞端口监听）
    # ═══════════════════════════════════════════════
    async def _background_startup():
        # 确保默认智能体存在（需要异步 I/O）
        ensure_default_agent_exists()
        ensure_qa_agent_exists()
        ensure_global_templates_exist()
        ensure_global_agent_roles()
        ensure_layered_templates()
        ...

    _bg_task = asyncio.create_task(_background_startup())
    yield
    ...
```

#### 改造 8: `coapis init` 集成 SystemInitializer

```python
# cli/init_cmd.py
@click.command("init")
@click.option("--force", is_flag=True)
@click.option("--defaults", "use_defaults", is_flag=True)
@click.option("--accept-security", "accept_security", is_flag=True)
def init_cmd(force, use_defaults, accept_security):
    """Create working dir with config.json and HEARTBEAT.md (interactive)."""
    from ..system.initializer import SystemInitializer

    # 1. 安全警告确认
    _echo_security_warning_box()
    if use_defaults and accept_security:
        click.echo("Security acceptance assumed.")
    else:
        accepted = prompt_confirm("Have you read and accepted the security notice?")
        if not accepted:
            raise click.Abort()

    # 2. 调用统一初始化器
    click.echo("Running system initialization...")
    result = SystemInitializer().initialize(force=force)

    if result["success"]:
        click.echo(f"✅ System initialized ({len(result['actions'])} actions)")
    else:
        click.echo(f"❌ Initialization failed: {result.get('error')}")
        raise click.Abort()

    # 3. 交互式配置（仅非 --defaults 模式）
    if not use_defaults:
        configure_providers_interactive()
        configure_channels_interactive()
        configure_skills_interactive()
        configure_env_interactive()

    # 4. 创建 HEARTBEAT.md
    ...
```

---

## 四、迁移策略（确保平滑升级）

### 4.1 现有系统兼容

| 场景 | 处理方式 |
|------|----------|
| 已有 config.json | `SystemInitializer` 检测到存在，只做合并更新（不覆盖） |
| 已有 users.json | 读取现有用户，只补充缺失字段 |
| 已有 permissions.json | 合并新增权限，不删除已有权限 |
| 已有 workspaces/ | 不动 |
| 无 .initialized 标记 | `ensure_ready()` 检测到缺失，自动运行初始化并创建标记 |

### 4.2 版本升级兼容

```
启动 → ensure_ready() → 读取 .initialized
  ├─ 不存在 → 运行 initialize() → 创建标记
  ├─ 存在但版本不一致 → 运行 _run_migrations() → 更新标记
  └─ 存在且版本一致 → 跳过（< 100ms）
```

### 4.3 回退方案

如果 `SystemInitializer` 出问题：
1. 删除 `.initialized` 标记文件
2. 重启容器 → 自动重新初始化
3. 或手动执行 `coapis init --defaults --accept-security`

---

## 五、预期效果

| 指标 | 当前 | 优化后 |
|------|------|--------|
| 初始化入口 | 3个（entrypoint.sh + init_cmd + migration.py） | 1个（SystemInitializer） |
| SYSTEM_VERSION | 硬编码 0.8.12 | 从 COAPIS_VERSION 环境变量动态获取 |
| 启动耗时（首次） | ~5s（多次 migration + MCP 安装） | ~2s（单次初始化） |
| 启动耗时（日常重启） | ~3s（每次跑7个migration检查） | < 100ms（检查 .initialized 跳过） |
| 错误可见性 | 部分静默吞掉 | 全部记录到日志 + init_marker |
| 目录完整性 | 部分缺失靠运行时 mkdir | 启动时100%确保 |

---

## 六、待确认问题

1. **entrypoint.sh 中的 `init_workspace.sh` 是否保留？** 建议保留作为 fallback，但默认路径改为 `coapis init --defaults`
2. **`_app.py` 中的 7 个 migration 函数是否移入 `SystemInitializer`？** 建议将目录/配置相关的移入，智能体/模板相关的保留在 `_app.py` 后台任务中（需要异步 I/O）
3. **`.initialized` 标记文件格式**：建议 JSON 格式，包含 version/schema_version/timestamp
4. **`coapis init` 的交互式配置是否保留？** 建议保留，但 `--defaults` 模式下跳过
