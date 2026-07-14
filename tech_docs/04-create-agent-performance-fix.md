# 创建智能体性能优化方案

> 2026-07-07 | 蜜总裁

## 问题

创建一个智能体需要 **46-59 秒**，删除需要 **30 秒**。用户体验极差。

## 根因

`create_agent()` 调用 `workspace.start()`，后者是一个"全家桶"——启动**所有运行时服务**：

```
create_agent()
  → Workspace(agent_id, ...)
  → workspace.start()                          ← 问题在这
      → load_agent_config()                    ~1ms
      → _init_evolution_engine()               ~50ms
      → ServiceManager.start_all()             ~720ms
          → core / memory / tools / skills     ✅ 快
          → mcp_manager                        ❌ 30秒超时！
          → channel_manager                    ❌ 启动企微等
          → cron_manager
      → CronManager 注册
```

**MCP `mcp_server_time` 客户端**配置了 stdio 模式（`python -m mcp_server_time`），容器内没有这个模块，每次连接尝试 **30 秒超时后才放弃**。

### 关键洞察

MCP 是**聊天时用的工具**，Channel 是**消息收发**，Cron 是**定时任务**。这些全是**运行时服务**，创建智能体（管理操作）根本不需要它们。

当前架构把**管理操作**和**运行时初始化**混在了同一个 `workspace.start()` 里。

## 影响范围

| 场景 | 当前耗时 | 根因 |
|------|---------|------|
| API 创建智能体 | 46-59s | MCP 超时 30s + 其他服务 |
| API 删除智能体 | 30s | workspace.stop() 等待 MCP 关闭 |
| 服务器启动（N 个智能体） | N × 30s+ | load_default_agents 逐个 start() |
| 首次打开聊天 | 30s+ | get_agent lazy-load 也走 start() |

## 修改方案

### 核心思路：分离"注册"与"启动"

```
create_agent()     → 只做注册（建目录、写配置、入列表）    <1s
get_agent()        → 首次使用时才启动运行时服务            按需
workspace.start()  → MCP 加超时保护 + 可选跳过重型服务     <5s
```

### 子任务清单

#### 子任务 0：`create_agent` 不再调用 `workspace.start()`

**文件**：`server/coapis/app/multi_agent_manager.py` 第 171 行

**改动**：
- `create_agent()` 中删除 `await workspace.start()`
- 改为只做轻量初始化：创建 Workspace 对象、写入 `_workspaces` 和 `_user_agents`
- 添加注释说明：运行时服务由 `get_agent()` 首次使用时 lazy 启动

**影响**：
- API 创建智能体 <1s 完成
- 新创建的智能体在 `_workspaces` 中注册，但未启动运行时服务
- 首次聊天时 `get_agent()` → `workspace.start()` 才启动 MCP/Channel

#### 子任务 1：MCP 初始化加超时保护

**文件**：`server/coapis/app/mcp/manager.py` `init_from_config()` 方法

**改动**：
- 对每个 client 的 `_add_client()` 调用加 `asyncio.wait_for(timeout=5)` 超时
- 超时后 log warning 并跳过该 client，不阻塞整个 workspace 启动
- 默认超时 5 秒（可配置）

**效果**：即使 MCP 配置了不可用的 server，workspace 启动也只多等 5 秒而非 30 秒。

#### 子任务 2：`load_default_agents` 改为只注册不启动

**文件**：`server/coapis/app/multi_agent_manager.py` 第 424 行 `load_default_agents()`

**改动**：
- 方法重命名为 `discover_agents()` 或保持原名但行为变更
- 只扫描磁盘、创建 Workspace 对象、注册到 `_workspaces`
- 不调用 `workspace.start()`
- 由 `_app.py` 的 `_background_startup()` 调用

**效果**：服务器启动时只做磁盘扫描（<1s），各智能体在首次使用时才启动。

#### 子任务 3：`get_agent` 确保 lazy-start 正确

**文件**：`server/coapis/app/multi_agent_manager.py` 第 509 行 `get_agent()`

**改动**：
- 已有的 lazy-load 逻辑保持不变（首次调用时 `instance.start()`）
- 确保 `_started` 状态检查正确
- 首次聊天请求会触发 `workspace.start()`，此时才初始化 MCP/Channel

**验证**：创建智能体后立即发消息，确认 MCP/Channel 能正确启动。

#### 子任务 4：`delete_agent` 优化 stop 逻辑

**文件**：`server/coapis/app/multi_agent_manager.py` `destroy_agent()` 方法

**改动**：
- 如果 workspace 未启动（`_started=False`），直接跳过 `workspace.stop()`
- 只做目录清理和注册表移除

**效果**：删除未启动的智能体 <1s。

#### 子任务 5：验证

**测试矩阵**：

| 场景 | 预期 |
|------|------|
| API 创建智能体 | <1s |
| API 删除刚创建的智能体（未聊天） | <1s |
| 创建后立即发消息 | MCP 正确启动，消息正常 |
| 服务器启动 | <5s 完成所有智能体注册 |
| 首次打开已有智能体聊天 | MCP lazy 启动，首次稍慢，后续正常 |
| MCP 配置了不可用 server | 5s 超时后跳过，不阻塞 |

### 不改的部分

- `ServiceManager` 架构不变——只是不再在创建时调用它
- MCP 客户端逻辑不变——只是加超时保护
- Channel/Cron 等服务不变——只是延迟到首次使用时启动

### 风险评估

| 风险 | 概率 | 缓解 |
|------|------|------|
| 首次聊天体验稍慢（MCP 初始化） | 中 | 5s 超时 + loading 提示 |
| 某些功能依赖 start() 中的初始化 | 低 | get_agent 保证 start() 在使用前完成 |
| 并发首次访问同一智能体 | 低 | 已有 `_pending_starts` 去重机制 |
