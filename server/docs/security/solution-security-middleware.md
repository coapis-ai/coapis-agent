# 安全中间件解决方案

**日期**: 2026-06-29  
**目标**: 修复 v0.8.48 安全审计发现的架构断层，将4个死代码模块激活回执行路径  
**核心发现**: agentscope Toolkit 提供 `register_middleware()` 洋葱模型中间件，可在 `call_tool_function` 前后注入安全检查

---

## 一、问题根因

### 1.1 架构断层图

```
当前架构（断层）:

WebSocket → CoApisAgent._acting
  → ToolGuardMixin._acting          ← 旧安全系统（独立运行）
    → ToolCallMonitor               ✅ 行为监控
    → CommandRiskClassifier          ✅ 命令分级（51条）
    → ToolGuardEngine                ❌ 规则=0，完全失效
  → ReActAgent._acting
    → agentscope Toolkit.call_tool_function()  ← 直接调用，绕过一切
      → builtin.py: execute_shell_command()
        → ToolSandbox.check_command            ✅ 但只有14条简陋规则
        → ProcessIsolator                      ✅ 但root运行
        
断层: UnifiedToolGuardEngine(108命令+29规则)、InputGuardEngine(14规则)、
      SandboxedExecutor、ToolRegistry.call()白名单 → 全部是死代码
```

### 1.2 根因

工具调用走 agentscope 的 `Toolkit.call_tool_function()` 直接调用工具函数，**不经过** 我们的 `ToolRegistry.call()`。所以：
- `SandboxedExecutor` 永远不会被触发
- `UnifiedToolGuardEngine` 和 `InputGuardEngine` 只在 `SandboxedExecutor` 中被引用
- `ToolRegistry.call()` 中的白名单检查永远不会被执行

### 1.3 旧系统的问题

- ToolGuardMixin 的 `_decide_guard_action()` 在工具调用**之前**运行，但它只做决策（allow/deny/confirm），**不拦截工具函数本身的执行**
- ToolGuardEngine 规则数=0（3条规则因 `GuardThreatCategory` 枚举缺失被跳过）
- 旧审计日志 `coapis_audit.jsonl` 文件不存在，所有日志丢失
- 两套安全系统互不连通，各自独立运行

---

## 二、解决方案：Security Middleware

### 2.1 核心思路

利用 agentscope Toolkit 的 `register_middleware()` 方法，注册一个安全中间件，**在 `call_tool_function` 执行前** 拦截所有工具调用，运行完整的安全检查链。

```
目标架构:

WebSocket → CoApisAgent._acting
  → ReActAgent._acting
    → agentscope Toolkit.call_tool_function()
      → SecurityMiddleware (洋葱中间件)          ← 新增！
        → [1] InputGuardEngine.check()           ← 激活死代码
        → [2] UnifiedToolGuardEngine.process()    ← 激活死代码
        → [3] ToolSandbox.check_path()            ← 保留
        → [4] ToolSandbox.check_command()          ← 保留
        → [5] SecurityAuditLogger.log()            ← 统一审计
        → [6] 审批流（confirm → 等待用户确认）
        → next_handler(**kwargs)                   ← 继续执行工具函数
      → builtin.py: execute_shell_command()
        → ProcessIsolator                          ← 保留（移除重复检查）
```

### 2.2 关键优势

1. **单一拦截点**：所有安全检查在中间件中统一完成，不在每个工具函数中重复
2. **激活死代码**：UnifiedToolGuardEngine、InputGuardEngine 直接在中间件中调用
3. **不修改工具函数**：builtin.py 中的工具函数保持简洁，只负责执行
4. **统一审计**：所有安全事件在中间件中统一记录
5. **向后兼容**：中间件可以开关，不影响现有功能

### 2.3 实现架构

```
coapis/security/
├── middleware.py              ← 新增：SecurityMiddleware 类
├── tool_guard/
│   ├── unified_engine.py      ← 已有：UnifiedToolGuardEngine（激活）
│   └── engine.py              ← 已有：ToolGuardEngine（修复规则）
├── input_guard/
│   └── engine.py              ← 已有：InputGuardEngine（激活）
├── tool_sandbox.py            ← 已有：ToolSandbox（保留）
├── audit_logger.py            ← 已有：SecurityAuditLogger（统一）
└── process_isolator.py        ← 已有：ProcessIsolator（保留）

coapis/agents/
├── react_agent.py             ← 修改：注册中间件
├── tool_guard_mixin.py        ← 修改：简化，移除重复逻辑
└── tools/
    └── builtin.py             ← 修改：移除重复安全检查
```

---

## 三、详细设计

### 3.1 SecurityMiddleware 类

```python
# coapis/security/middleware.py

class SecurityMiddleware:
    """洋葱模型安全中间件，拦截所有工具调用。
    
    注册到 agentscope Toolkit 的 register_middleware()，
    在 call_tool_function 执行前运行完整安全检查链。
    """
    
    def __init__(self, agent_instance):
        """
        Args:
            agent_instance: CoApisAgent 实例，用于获取上下文
        """
        self._agent = agent_instance
        self._unified_engine = None      # 懒加载
        self._input_guard = None         # 懒加载
        self._sandbox = None             # 懒加载
        self._audit_logger = None        # 懒加载
    
    async def __call__(self, kwargs, next_handler):
        """中间件入口，符合 agentscope 中间件签名。"""
        tool_call = kwargs["tool_call"]
        tool_name = tool_call["name"]
        tool_input = tool_call.get("input", {})
        
        # 获取上下文
        username = self._get_username()
        role = self._get_role()
        agent_id = self._get_agent_id()
        workspace_dir = self._get_workspace_dir()
        
        # ── 检查点 1: InputGuardEngine ──
        # 对 shell 命令做输入内容检测（Prompt注入/数据窃取）
        if tool_name == "execute_shell_command":
            command = tool_input.get("command", "")
            input_result = self._check_input_guard(command, username, agent_id)
            if input_result.blocked:
                yield self._make_blocked_response(input_result.reason)
                return
        
        # ── 检查点 2: UnifiedToolGuardEngine ──
        # 命令分级 + 模式规则 + 逃逸检测
        if tool_name == "execute_shell_command":
            command = tool_input.get("command", "")
            guard_result = self._check_unified_guard(command, username, role, agent_id)
            if guard_result.action == "block":
                yield self._make_blocked_response(guard_result.reason)
                return
            if guard_result.action == "confirm":
                # 审批流：等待用户确认
                approved = await self._wait_approval(tool_call, guard_result)
                if not approved:
                    yield self._make_blocked_response("User denied execution")
                    return
        
        # ── 检查点 3: ToolSandbox 路径检查 ──
        if tool_name in ("file_read", "file_write", "list_files"):
            path = tool_input.get("path", "")
            path_result = self._check_path(path, tool_name, username, workspace_dir)
            if not path_result.allowed:
                yield self._make_blocked_response(path_result.reason)
                return
        
        # ── 检查点 4: 统一审计日志 ──
        self._log_tool_execute(tool_name, tool_input, username, agent_id)
        
        # ── 继续执行工具函数 ──
        async for response in await next_handler(**kwargs):
            yield response
```

### 3.2 注册点（react_agent.py）

在 `CoApisAgent.__init__` 中，`self.toolkit = toolkit` 之后注册中间件：

```python
# react_agent.py L200 之后
self.toolkit = toolkit

# 注册安全中间件
from ..security.middleware import SecurityMiddleware
self._security_middleware = SecurityMiddleware(self)
self.toolkit.register_middleware(self._security_middleware)
```

### 3.3 builtin.py 简化

移除 `builtin.py` 中的重复安全检查，只保留 `ProcessIsolator` 执行：

```python
# builtin.py: shell_execute 简化后
async def shell_execute(command: str) -> str:
    """Execute a shell command. Security checks are handled by SecurityMiddleware."""
    # 安全检查已由 SecurityMiddleware 统一处理
    # 这里只负责隔离执行
    from ..security.process_isolator import ProcessIsolator
    isolator = ProcessIsolator(base_workspace=str(workspace_dir))
    result = await isolator.execute(command)
    return result.stdout
```

### 3.4 ToolGuardMixin 简化

`ToolGuardMixin._decide_guard_action()` 中的 `CommandRiskClassifier` 和 `ToolGuardEngine` 逻辑可以保留（作为第二道防线），但需要：

1. 修复 `ToolGuardEngine` 的规则（修复 `GuardThreatCategory` 枚举）
2. 统一审计日志（旧 `AuditLogger` → 新 `SecurityAuditLogger`）

或者，如果确认中间件覆盖了所有检查，可以简化 `ToolGuardMixin` 只保留 `ToolCallMonitor`（行为监控）。

---

## 四、执行时序与分层职责

### 4.1 四层安全架构

```
第1层 ToolGuardMixin._acting (工具调用前)
  ├── ToolCallMonitor        ← 行为频率监控（保留）
  └── (简化: 移除 CommandRiskClassifier + ToolGuardEngine + 审批流)

第2层 ReActAgent._acting (不修改)
  └── toolkit.call_tool_function()

第3层 SecurityMiddleware (工具调用时，核心新增)
  ├── InputGuardEngine       ← 输入内容检测（激活死代码）
  ├── UnifiedToolGuardEngine ← 命令分级+模式规则+逃逸检测（激活死代码）
  ├── ToolSandbox            ← 路径检查+命令模式检查（保留）
  ├── SecurityAuditLogger    ← 统一审计日志（激活死代码）
  └── ApprovalService        ← 审批流（复用现有）

第4层 builtin.py (工具函数内，简化)
  └── ProcessIsolator        ← 隔离执行（保留）
```

### 4.2 为什么中间件必须自己处理审批

中间件在 ToolGuardMixin 之后执行（第3层 vs 第1层），无法"委托回"。
但中间件可以复用现有的 `ApprovalService`：
- `ApprovalService.create_pending()` → 创建 Future
- `agent._emit_waiting_for_approval_blocking()` → 发送 ApprovalCard
- `agent._wait_for_approval_with_heartbeat()` → await Future

中间件通过闭包捕获 agent 实例，可以调用这些方法。

### 4.3 审批流在中间件中的实现

```python
# middleware.py 中的审批流
if guard_result.action == "confirm":
    # 复用现有 ApprovalService
    svc = self._agent._tool_guard_approval_service
    pending = await svc.create_pending(
        session_id=session_id,
        tool_name=tool_name,
        result=guard_result,
        timeout_seconds=TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
    )
    # 发送审批卡片给用户
    await self._agent._emit_waiting_for_approval_blocking(pending, guard_result)
    # 等待用户审批（带心跳）
    decision = await self._agent._wait_for_approval_with_heartbeat(
        pending.request_id, pending.future,
        timeout_seconds=TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
    )
    if decision != ApprovalDecision.APPROVED:
        yield make_blocked_response("User denied execution")
        return
```

---

## 五、执行计划

### Phase 1: 创建 SecurityMiddleware（核心，预计2h）

1. 创建 `coapis/security/middleware.py`
2. 实现 `SecurityMiddleware.__call__()` 洋葱中间件
3. 集成 `UnifiedToolGuardEngine`（命令分级+29规则+逃逸检测）
4. 集成 `InputGuardEngine`（14条输入检测规则）
5. 集成 `ToolSandbox`（路径检查+命令模式检查）
6. 集成 `SecurityAuditLogger`（7种事件类型全覆盖）
7. 集成 `ApprovalService`（复用现有审批流）

### Phase 2: 注册中间件（预计30min）

1. 修改 `react_agent.py`：在 `self.toolkit = toolkit` (L200) 后注册中间件
2. 闭包捕获 `self`（CoApisAgent 实例），获取 username/role/workspace_dir

### Phase 3: 简化 builtin.py（预计30min）

1. 移除 `_check_command_access()` 和 `_check_path_access()`
2. 移除 `ToolSandbox` 的重复调用
3. 保留 `ProcessIsolator` 作为唯一执行引擎
4. 添加注释说明安全检查已由中间件统一处理

### Phase 4: 简化 ToolGuardMixin（预计30min）

1. `_decide_guard_action()` 中移除 `CommandRiskClassifier` 和 `ToolGuardEngine` 调用
2. 只保留 `ToolCallMonitor.should_block()`（行为监控）
3. 移除 `_acting_with_approval()`（审批流移至中间件）
4. 统一旧 `AuditLogger` 到新 `SecurityAuditLogger`

### Phase 5: 修复旧引擎（预计30min）

1. 修复 `GuardThreatCategory` 枚举（添加 `container_management`、`package_management`、`version_control`）
2. 或直接移除 ToolGuardEngine（已被 UnifiedToolGuardEngine 完全覆盖）

### Phase 6: 验证（预计1h）

1. 语法检查（9个修改文件）
2. 编译验证（前端 build）
3. dev 环境部署（docker compose up -d --force-recreate）
4. 执行 19 个攻击向量测试
5. 验证审计日志覆盖度（7种事件类型）
6. 验证审批流（confirm → 用户审批 → 执行/拒绝）

---

## 六、风险评估与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 中间件异常导致工具调用失败 | 工具不可用 | 中 | try-except 包裹，异常时放行+记录审计日志 |
| 中间件性能开销过大 | 响应变慢 | 低 | L0 命令直接跳过（0.01ms），非 shell 工具只做白名单检查 |
| 审批流阻塞 WebSocket | 用户体验差 | 中 | 复用现有超时机制（TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS） |
| 与 ToolGuardMixin 重复检查 | 性能下降 | 高 | Phase 4 简化 ToolGuardMixin，只保留 ToolCallMonitor |
| 中间件顺序问题 | 检测遗漏 | 低 | InputGuard → UnifiedGuard → ToolSandbox → 审计，顺序固定 |

---

## 七、预期效果

| 指标 | 当前 | 修复后 | 改善 |
|------|------|--------|------|
| 实际生效的安全模块 | 6个 | 10个 | +4个激活 |
| 死代码模块 | 4个 | 0个 | 全部激活 |
| 命令拦截率 | 48% | 95%+ | +47% |
| 审计日志覆盖率 | 14% | 100% | +86% |
| 输入防护规则 | 0条 | 14条 | +14条 |
| 逃逸检测 | 0个 | 7个 | +7个 |
| 安全检查代码重复 | 3处 | 1处 | -2处 |
| 安全检查延迟 | ~5ms | ~10ms | +5ms（可接受） |

---

## 八、关键设计决策

### 8.1 为什么用中间件而不是修改 builtin.py？

| 方案 | 优点 | 缺点 |
|------|------|------|
| 修改 builtin.py | 简单直接 | 每个工具函数都要改，代码重复，新工具容易遗漏 |
| 中间件（推荐） | 单一拦截点，自动覆盖所有工具，新工具无需改动 | 需要理解 agentscope 中间件机制 |

### 8.2 为什么中间件自己处理审批而不是委托 ToolGuardMixin？

中间件在 ToolGuardMixin 之后执行（第3层 vs 第1层），时序上无法委托。
但可以复用现有的 `ApprovalService` 和 agent 的消息发送方法。

### 8.3 为什么保留 ToolGuardMixin 的 ToolCallMonitor？

ToolCallMonitor 做的是行为频率监控（同一工具连续调用N次），属于不同的安全维度。
它在工具调用前运行（第1层），中间件在工具调用时运行（第3层），两者互补。

### 8.4 L0 命令性能优化

L0 命令（21个只读命令：ls/cat/grep/find 等）直接跳过所有规则检测，只做路径检查。
预计 90%+ 的工具调用是 L0，中间件平均延迟 < 1ms。

