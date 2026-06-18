# CoApis 工具触发调用机制深度分析

## 一、工具触发调用全链路

### 1.1 注册阶段（静态）

```
@register_tool decorators on each tool .py file
        ↓
    _registry (global dict)
        ↓
    _auto_register.py → register_all_builtin_tools()
        ↓
    __init__.py → explicit imports
```

每个工具通过 `@register_tool(name=..., description=..., tags=[...], category=...)` 装饰器注册到全局 `_registry` 字典。这是一个**纯静态注册表**——模块加载时一次性写入，运行时不变。

### 1.2 实例化阶段（每个 Agent 实例）

```
CoApisAgent.__init__()
        ↓
    _create_toolkit(namesake_strategy)
        ↓
    get_registered_tools()           ← 读 registry
        ↓
    对比 agent_config.tools.builtin_tools  ← 过滤 disabled
        ↓
    toolkit.register_tool_function()  ← 注入 LLM 可见的工具列表
```

**关键逻辑**：
- 配置中**没有的工具默认启用**（向后兼容）
- 只有 `execute_shell_command` 支持 `async_execution`
- 异步工具会自动注册 `view_task_status` 和 `cancel_task` 辅助工具

### 1.3 调用阶段（运行时，每次 LLM 响应）

```
LLM 输出 tool_call JSON
        ↓
    ToolGuardMixin._acting()          ← 拦截点
        ↓
    ┌─────────────────────────────────┐
    │ 1. 规则引擎 RuleBasedGuardian   │ ← YAML 正则规则
    │ 2. 文件路径 Guardian             │ ← 敏感路径拦截
    │ 3. Shell 混淆 Guardian           │ ← 逃逸检测
    └─────────────────────────────────┘
        ↓
    如果需要审批 → approval_queue → WebSocket 推送前端
        ↓
    用户在前端 approve/reject
        ↓
    tool_stats.record_tool_call()     ← 记录指标
        ↓
    实际执行工具函数
        ↓
    结果返回 LLM
```

---

## 二、多用户多智能体机制分析

### 2.1 架构模型

```
┌─────────────────────────────────────────────────────┐
│                    CoApis Server                   │
├──────────┬──────────┬──────────┬─────────────────────┤
│ Agent A  │ Agent B  │ Agent C  │  Shared Services    │
│ (workspace_a/) │ (workspace_b/) │ (workspace_c/) │                     │
├──────────┴──────────┴──────────┤  ├─────────────────────┤
│  ContextVar per-request         │  │ ProviderManager     │
│  current_workspace_dir          │  │ ToolGuardEngine     │
│  → 文件隔离、工作区隔离          │  │ EvolutionSystem     │
└─────────────────────────────────┘  └─────────────────────┘
```

### 2.2 工作区隔离

- 每个 Agent 有独立的 `workspace/{user}/files` 目录
- `ContextVar[Path]` 在请求级别设置，确保文件操作不越界
- `FilePathToolGuardian` 拦截访问 `.secret/`、`.coapis.secret/` 等敏感目录

### 2.3 工具状态共享问题

**⚠️ 严重设计问题**：

| 状态 | 存储位置 | 隔离性 |
|------|----------|--------|
| `_registry`（全局注册表） | 进程内存 | ❌ **全局共享** |
| `TOOL_STATE`（启禁状态） | `system/tool_state.json` | ❌ **全局共享** |
| `tool_stats` | `workspace/{user}/files/tool_stats.json` | ✅ 用户级隔离 |
| `audit_log` | `system/tool_audit.json` | ❌ **全局共享** |
| `context_manager` | `workspace/{user}/files/context.json` | ✅ 用户级隔离 |
| `resource_guard` | 通过 context_manager | ✅ 用户级隔离 |

**这意味着**：用户 A 禁用一个工具，**所有用户**的该工具都被禁用。这是当前架构的最大缺陷。

---

## 三、工具对能力效用的影响分析

### 3.1 工具能力矩阵

| 类别 | 工具数 | 核心能力 | 效用评分 |
|------|--------|----------|----------|
| 文件操作 | 9 | read/write/edit/glob/grep/diff/send/batch/notes | ⭐⭐⭐⭐⭐ |
| 代码操作 | 6 | shell/code_runner/formatter/docgen/review/ast_search | ⭐⭐⭐⭐⭐ |
| 网络/API | 3 | web_search/http_client/api_mock | ⭐⭐⭐⭐ |
| AI/LLM | 4 | llm_ops/prompt_builder/embedding_ops/image_gen | ⭐⭐⭐⭐ |
| 知识/RAG | 3 | knowledge_base/rag_search/doc_reader | ⭐⭐⭐⭐ |
| 安全 | 3 | secret_scan/dependency_audit/audit_log | ⭐⭐⭐ |
| 数据 | 4 | data_processor/db_ops/cache_ops/queue_ops | ⭐⭐⭐ |
| 运维 | 5 | deploy_helper/test_runner/cron_scheduler/auto_heal/perf_monitor | ⭐⭐⭐ |
| 系统 | 8 | archive/crypto/env/clipboard/git/todo/checkpoint/notes | ⭐⭐⭐ |
| 协作 | 3 | notify_ops/shared_state/task_delegation | ⭐⭐⭐ |
| 监控 | 3 | structured_logger/trace_ops/health_check | ⭐⭐⭐ |
| AI增强 | 3 | skill_manager/workflow_engine/agent_optimizer | ⭐⭐⭐⭐ |
| 上下文 | 4 | memory_manager/context_manager/session_search/tool_stats | ⭐⭐⭐⭐⭐ |

### 3.2 工具冗余度分析

| 工具组 | 高频工具 | 低频/冗余工具 | 冗余率 |
|--------|----------|---------------|--------|
| 文件操作 | read_file, write_file, edit_file | append_file（write_file 可替代） | 11% |
| 搜索 | grep_search, glob_search | ast_search（代码场景重叠） | 33% |
| 网络 | web_search, http_client | api_mock（开发场景） | 33% |
| AI | llm_ops, prompt_builder | embedding_ops（需要向量库） | 33% |
| 数据 | data_processor | db_ops, cache_ops, queue_ops（场景较窄） | 67% |
| 安全 | secret_scan | dependency_audit, audit_log（低频） | 67% |

**总计**：75 个工具中约 **15-20 个为低频/冗余工具**，实际高频使用约 50-55 个。

### 3.3 工具过载对 LLM 的影响

每个工具在 LLM 上下文中占用约 **200-400 tokens**（name + description + parameters）。

| 工具数 | 占用 tokens | 占 128K 上下文 | 影响 |
|--------|-------------|----------------|------|
| 55 个（实际高频） | ~15,000 | 11.7% | ✅ 健康 |
| 75 个（全部注册） | ~22,000 | 17.2% | ⚠️ 轻微影响 |
| 100 个（假设扩展） | ~30,000 | 23.4% | 🔴 严重影响推理质量 |

**结论**：工具数量与 LLM 推理质量成反比。75 个工具已接近合理上限。

---

## 四、性能影响分析

### 4.1 工具调用延迟分析

| 阶段 | 延迟 | 优化建议 |
|------|------|----------|
| LLM 生成 tool_call | N/A（模型侧） | - |
| ToolGuard 规则匹配 | 1-5ms | 已优化（预编译正则） |
| 审批等待（需审批时） | 3-30s | 仅敏感操作 |
| 工具函数执行 | 10ms-30s | 按工具差异大 |
| 结果序列化 | <1ms | - |
| record_tool_call | 5-20ms | 异步写磁盘 |

### 4.2 磁盘 I/O 热点

每次工具调用涉及的磁盘操作：

1. `tool_stats.json` 读写 → **高频**（每次调用）
2. `tool_state.json` 读 → 初始化时
3. `tool_audit.json` 读写 → 启禁操作时
4. `context.json` 读写 → context_manager 调用时
5. `memory.json` 读写 → memory_manager 调用时

**问题**：`tool_stats.json` 在高并发下是单点写入瓶颈。JSON 文件无锁，多请求并发写入可能导致数据丢失。

### 4.3 内存影响

- `_registry` 全局字典：~500KB（75 工具 × ~7KB/条目）
- 每个 Agent 实例的 Toolkit：~2MB
- 10 个并发 Agent：~20MB toolkit + 5MB registry

**评估**：内存影响可控，不是瓶颈。

---

## 五、安全影响分析

### 5.1 安全防护架构（三层）

```
┌──────────────────────────────────────────┐
│  Layer 1: RuleBasedToolGuardian          │
│  - 50+ YAML 规则（shell 注入、数据外泄）  │
│  - 正则匹配 tool 参数                     │
├──────────────────────────────────────────┤
│  Layer 2: FilePathToolGuardian           │
│  - 敏感路径黑名单（.secret, .env）         │
│  - 工作区边界检查                          │
├──────────────────────────────────────────┤
│  Layer 3: ShellEvasionGuardian           │
│  - 命令替换检测 ($(), ``)                │
│  - 混淆检测（ANSI-C quoting, 转义）       │
│  - 注释-引号去同步攻击                    │
└──────────────────────────────────────────┘
        ↓
  需要审批 → ApprovalQueue → WebSocket → 前端
```

### 5.2 安全风险评估

| 风险等级 | 风险点 | 现有防护 | 差距 |
|----------|--------|----------|------|
| 🔴 高 | `execute_shell_command` RCE | 三层 Guardian + 审批 | ✅ 防护完善 |
| 🔴 高 | `write_file` 覆盖系统文件 | FilePathToolGuardian | ⚠️ 仅拦截 .secret 目录 |
| 🟡 中 | `http_client` 内网扫描 | URL 黑名单 | ⚠️ 黑名单不完整 |
| 🟡 中 | `code_runner` 沙箱逃逸 | 隔离执行 | ⚠️ 共享 Python 进程 |
| 🟡 中 | `llm_ops` Token 滥用 | resource_guard | ⚠️ 软限制可绕过 |
| 🟢 低 | `tool_stats` 数据篡改 | JSON 无锁写入 | ⚠️ 并发写入不安全 |
| 🟢 低 | `audit_log` 防篡改 | 无（JSON 可直接编辑） | 🔴 缺少哈希链 |

### 5.3 多用户安全隔离

| 维度 | 现状 | 风险 |
|------|------|------|
| 文件隔离 | ContextVar + workspace 路径 | ⚠️ 工具函数可被直接调用越界 |
| 工具启禁 | **全局共享** | 🔴 用户 A 可禁用所有用户的工具 |
| 审计日志 | **全局共享** | 🔴 用户 A 可看到用户 B 的操作 |
| 资源限制 | 用户级隔离 | ✅ 正确 |
| 工具统计 | 用户级隔离 | ✅ 正确 |

---

## 六、关键发现与改进建议

### 6.1 架构级问题

| 问题 | 严重性 | 建议 |
|------|--------|------|
| 工具启禁状态全局共享 | 🔴 | 改为 per-user 存储 `{workspace}/tool_state.json` |
| 审计日志全局共享 | 🔴 | 改为 per-user + 全局双写 |
| `tool_stats` JSON 无锁写入 | 🟡 | 引入文件锁或 SQLite |
| 工具注册表运行时不可变 | 🟡 | 支持热加载/卸载（skill_manager 已有雏形） |
| 75 个工具全部注入 LLM | 🟡 | 按场景动态裁剪工具列表（参考 agent_optimizer） |

### 6.2 工具效用优化

| 建议 | 预期效果 |
|------|----------|
| 工具按场景分组（coding / ops / data / security） | 减少 LLM 上下文占用 30% |
| 低频工具默认禁用（audit_log, dependency_audit 等） | 减少 token 消耗 |
| 工具调用结果缓存（cache_ops 联动） | 重复调用延迟降低 80% |
| 基于 tool_stats 的智能推荐（agent_optimizer） | 提升工具选择准确率 |

### 6.3 安全加固建议

| 建议 | 优先级 |
|------|--------|
| `audit_log` 引入 SHA-256 链式哈希（防篡改） | 高 |
| `code_runner` 隔离为独立进程（非共享 Python） | 高 |
| `http_client` 内网 IP 黑名单完善 | 中 |
| 工具调用 per-user 频率限制 | 中 |

---

## 七、总结

**工具触发调用机制**：设计合理，`register_tool` → `get_registered_tools` → `ToolGuardMixin` 三层架构清晰。安全防护（三层 Guardian + 审批流）在业界属于较高水平。

**多用户多智能体**：文件级隔离通过 ContextVar 实现，但**工具启禁状态和审计日志仍为全局共享**，这是当前最大的架构缺陷，需要优先修复。

**能力效用**：75 个工具覆盖全面，但存在 15-20 个低频冗余工具。工具过载已接近 LLM 上下文的合理上限（17.2%），建议引入按场景动态裁剪。

**性能**：主要瓶颈在 `tool_stats.json` 的并发写入。内存和 CPU 影响可控。

**安全**：三层防护体系完善，但 `audit_log` 缺乏防篡改机制、`code_runner` 共享进程、多用户状态隔离不足是需要优先解决的安全短板。
