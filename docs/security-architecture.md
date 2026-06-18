# CoApis 安全面架构开发者指南

> 面向开发者的安全模块架构文档。涵盖七层安全架构、工具执行链路、核心模块接口、权限矩阵、扩展指南与测试说明。

---

## 📋 目录

- [架构总览](#架构总览)
- [工具执行安全检查链路](#工具执行安全检查链路)
- [核心模块说明](#核心模块说明)
- [权限矩阵](#权限矩阵)
- [扩展指南](#扩展指南)
- [测试说明](#测试说明)

---

## 架构总览

CoApis 采用 **七层纵深防御** 架构。每一层独立运作、互不依赖，即使某层被绕过，后续层仍可拦截：

```
用户消息 / API 请求
        │
        ▼
┌─ Layer 1 ─────────────────────────────────────────────────────────┐
│  WorkspaceGuard（工作区守卫）                                       │
│  · 文件路径校验：防止路径穿越（../）                                  │
│  · 工作区边界检查：确保操作在用户 workspace 内                        │
│  位置: agents/security/workspace_guard.py                          │
└───────────────────────────────────────────────────────────────────┘
        │ pass
        ▼
┌─ Layer 2 ─────────────────────────────────────────────────────────┐
│  角色权限校验（RBAC）                                                │
│  · 四级角色: user → advanced → admin → owner                       │
│  · 白名单语义匹配: base-only / wildcard / file-pattern              │
│  位置: agents/security/workspace_guard.py::check_command()         │
└───────────────────────────────────────────────────────────────────┘
        │ pass
        ▼
┌─ Layer 3 ─────────────────────────────────────────────────────────┐
│  沙箱与隔离                                                          │
│  · ProcessIsolator: 环境变量最小化（4 个必要变量）                    │
│  · ResourceLimiter: CPU 10s / 内存 256MB / 进程数 50                │
│  · Namespace Isolation: unshare(CLONE_NEWNS) 可选启用               │
│  · ImportSandbox / ASTSandbox: Python 代码静态检查                  │
│  位置: security/process_isolator.py                                │
│          security/resource_limiter.py                               │
│          agent/tools/shell.py::_make_ns_preexec()                  │
└───────────────────────────────────────────────────────────────────┘
        │ pass
        ▼
┌─ Layer 4 ─────────────────────────────────────────────────────────┐
│  工具防护引擎（Tool Guard）                                          │
│  · YAML 规则匹配: 29 条危险命令规则                                  │
│  · FileGuard: 65 个敏感文件模式                                     │
│  · 支持 block / confirm / log 三种动作                              │
│  位置: security/tool_guard/engine.py                               │
│          security/tool_guard/guardians/file_guardian.py             │
│          security/tool_guard/rules/dangerous_shell_commands.yaml   │
└───────────────────────────────────────────────────────────────────┘
        │ pass
        ▼
┌─ Layer 5 ─────────────────────────────────────────────────────────┐
│  命令风险分类器（CommandRiskClassifier）                              │
│  · 三级分类: AUTO / CONFIRM / BLOCK                                 │
│  · 17 种命令类别 × 4 级角色权限矩阵                                 │
│  · 60+ 条正则匹配规则                                               │
│  位置: security/command_risk_classifier.py                          │
└───────────────────────────────────────────────────────────────────┘
        │ pass
        ▼
┌─ Layer 6 ─────────────────────────────────────────────────────────┐
│  行为监控与阻断（ToolCallMonitor）                                   │
│  · 滑动窗口异常检测                                                  │
│  · 自动封禁: 3 次 critical 或 8 次异常 → 封禁 5 分钟               │
│  · Per-User 速率限制: 30 次/分钟（SandboxedExecutor）               │
│  位置: security/tool_monitor.py                                    │
│          security/sandboxed_executor.py                             │
└───────────────────────────────────────────────────────────────────┘
        │ pass
        ▼
┌─ Layer 7 ─────────────────────────────────────────────────────────┐
│  审计与合规                                                          │
│  · 所有操作写入 SQLite audit_logs 表                                │
│  · 含 risk_level / command_category / confirm_result               │
│  · 链式文件 (chain.jsonl) 用于完整性校验                            │
│  位置: agent/security/audit_logger.py                              │
│          app/routers/audit.py                                      │
└───────────────────────────────────────────────────────────────────┘
        │
        ▼
    执行 Shell 命令
```

---

## 工具执行安全检查链路

以 `execute_shell_command` 为例，一条 Shell 命令从输入到执行经过以下完整检查链路：

```
用户发送消息: "python3 -c 'import os; os.system(\"rm -rf /\")'"
        │
        ▼
① ToolGuardMixin._acting()
   │
   ├─ ② ToolCallMonitor.should_block(username)
   │   · 检查是否被封禁
   │   · 被封禁 → 直接返回错误 + 写审计日志
   │
   ├─ ③ CommandRiskClassifier.classify(command, role)
   │   · 匹配 60+ 条正则 → 返回 risk_level
   │   · BLOCK → 自动拒绝
   │   · CONFIRM → 弹出 ApprovalCard → 等待用户确认
   │   · AUTO → 放行
   │
   └─ ④ WorkspaceGuard.check_command(command)
       · 白名单语义匹配
       · python3 -c → 检测到内联标志 -c → 拒绝
       │
       ▼
⑤ Shell 执行前检查
   │
   ├─ ImportSandbox 静态检查
   │   · 正则匹配 python3 -c 中的 import 语句
   │   · 检测到 import os → 拦截（os 在 DEFAULT_BLOCKED_MODULES 中）
   │
   ├─ ASTSandbox 代码检查
   │   · 解析 Python 代码 AST
   │   · 检测到 __subclasses__() / getattr() → 拦截
   │
   ├─ ProcessIsolator 环境过滤
   │   · 仅保留 PATH / LANG / LC_ALL / TERM
   │   · 移除 HOME / USER / SHELL 等身份变量
   │
   ├─ ResourceLimiter 资源限制
   │   · preexec_fn: CPU 10s / 内存 256MB / 进程数 50
   │
   └─ 可选: Namespace Isolation
       · COAPIS_ENABLE_NS=1 时启用
       · unshare(CLONE_NEWNS) + / 只读 + 工作目录可写
        │
        ▼
⑥ 执行完毕 → AuditLogger 记录结果
```

### 关键决策点总结

| 检查点 | 位置 | 失败行为 | 恢复方式 |
|--------|------|---------|---------|
| ToolCallMonitor 封禁 | tool_guard_mixin.py:202 | 返回错误 | 等待自动解封或管理员手动解封 |
| CommandRiskClassifier BLOCK | command_risk_classifier.py | 自动拒绝 | 不可恢复 |
| CommandRiskClassifier CONFIRM | command_risk_classifier.py | 弹审批卡片 | 用户确认/拒绝/超时 |
| WorkspaceGuard 白名单 | workspace_guard.py | 返回 PermissionError | 需管理员修改白名单 |
| ImportSandbox 模块拦截 | shell.py:443 | 返回 ToolResponse 错误 | 去除危险 import |
| ASTSandbox 代码拦截 | shell.py:463 | 返回 ToolResponse 错误 | 修改代码 |
| ResourceLimiter 超限 | shell.py (preexec_fn) | 进程被 SIGKILL | — |

---

## 核心模块说明

### CommandRiskClassifier

**定位：** 命令级风险分类引擎，将 Shell 命令分为 AUTO / CONFIRM / BLOCK 三级。

**文件：** `server/coapis/security/command_risk_classifier.py`

**接口：**
```python
from coapis.security.command_risk_classifier import (
    CommandRiskClassifier,
    CommandRiskLevel,   # AUTO / CONFIRM / BLOCK / DENIED
)

classifier = CommandRiskClassifier()
result = classifier.classify(command="rm -rf /", role="user")

# result.risk_level  -> CommandRiskLevel.BLOCK
# result.category    -> "destruction"
# result.matched_rule -> "TOOL_CMD_RF_FORCE"
```

**权限矩阵（角色 × 类别）：**

| 类别 | user | advanced | admin |
|------|------|---------|-------|
| file_destruction | BLOCK | CONFIRM | CONFIRM |
| privilege_escalation | BLOCK | BLOCK | BLOCK |
| network_outbound | CONFIRM | AUTO | AUTO |
| package_install | BLOCK | CONFIRM | CONFIRM |
| git_destructive | BLOCK | CONFIRM | CONFIRM |
| docker_operations | BLOCK | CONFIRM | CONFIRM |
| ... | ... | ... | ... |

**配置：** 无需额外配置，规则内置在代码中。

---

### ToolCallMonitor（阻断能力）

**定位：** 用户级行为监控与自动封禁引擎。

**文件：** `server/coapis/security/tool_monitor.py`

**接口：**
```python
from coapis.security.tool_monitor import get_tool_call_monitor

monitor = get_tool_call_monitor()  # 单例

# 检查是否应封禁
blocked, reason = monitor.should_block("user_id")

# 手动解封
monitor.unblock_user("user_id")

# 检查是否被封禁
is_banned = monitor.is_blocked("user_id")
```

**封禁阈值：**

| 触发条件 | 阈值 | 封禁时长 | 冷却期 |
|---------|------|---------|--------|
| critical 级告警 | 3 次 | 300s | 60s |
| 异常事件累计 | 8 次 | 300s | 60s |

**配置：** 通过修改 `TOOL_CALL_MONITOR` 类中的 `_CRITICAL_THRESHOLD` 和 `_ANOMALY_THRESHOLD` 常量调整。

---

### ImportSandbox 静态检查

**定位：** Python 内联代码的模块导入静态检查（不 monkey-patch，仅正则扫描）。

**集成点：** `server/coapis/agent/tools/shell.py:443`

**拦截范围：** 18 个危险模块（os, subprocess, socket, ctypes, shutil, sys, importlib, ...）

**配置：** 编辑 `server/coapis/security/import_sandbox.py` 的 `DEFAULT_BLOCKED_MODULES` 集合。

---

### ASTSandbox 代码检查

**定位：** Python 代码的 AST 结构安全检查。

**集成点：** `server/coapis/agent/tools/shell.py:463`

**检测项：**
- 危险函数调用：`exec`, `eval`, `compile`, `__import__`, `getattr`, `setattr`
- 危险 dunder 属性：`__subclasses__`, `__bases__`, `__mro__`, `__globals__`, `__code__`
- 危险 import 语句

**配置：** 编辑 `server/coapis/security/ast_sandbox.py` 的 `DANGEROUS_BUILTINS` 和 `DANGEROUS_DUNDERS` 集合。

---

### SandboxedExecutor 速率限制

**定位：** Per-user 工具调用速率限制器（滑动窗口）。

**文件：** `server/coapis/security/sandboxed_executor.py`

**接口：**
```python
from coapis.security.sandboxed_executor import SandboxedExecutor

executor = SandboxedExecutor(username="alice", workspace_dir="/workspace/alice")
# 内部自动检查速率限制
```

**配置：**

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `COAPIS_RATE_LIMIT_MAX` | 30 | 窗口内最大调用次数 |
| `COAPIS_RATE_LIMIT_WINDOW` | 60 | 窗口大小（秒） |

---

## 权限矩阵

### Shell 命令白名单（角色 × 命令）

| 命令 | user | advanced | admin |
|------|:----:|:--------:|:-----:|
| `ls` | ✅ | ✅ | ✅ |
| `cat` | ✅ | ✅ | ✅ |
| `grep` | ✅ | ✅ | ✅ |
| `find` | ✅ | ✅ | ✅ |
| `python3 *.py` | ✅ | ✅ | ✅ |
| `python3 -c` | ❌ | ❌ | ❌ |
| `git` | ❌ | ✅ | ✅ |
| `docker` | ❌ | ✅ | ✅ |
| `node` | ❌ | ✅ | ✅ |
| `rm` | ❌ | ❌ | ❌ |
| `sudo` | ❌ | ❌ | ❌ |
| `curl \| bash` | ❌ | ❌ | ❌ |

### 命令风险级别（CommandRiskClassifier）

| 级别 | 含义 | user | advanced | admin |
|------|------|:----:|:--------:|:-----:|
| AUTO | 安全命令，自动放行 | ✅ | ✅ | ✅ |
| CONFIRM | 需审批确认 | ⚠️ | ⚠️ | ⚠️ |
| BLOCK | 高危命令，硬拒绝 | ❌ | ❌ | ❌ |
| DENIED | 禁止执行（仅 owner 外所有角色） | ❌ | ❌ | ❌ |

---

## 扩展指南

### 如何新增命令分类规则

**Good ✅ — 在 CommandRiskClassifier 中添加：**
```python
# server/coapis/security/command_risk_classifier.py
# 在 _RULES 列表中添加新规则
_CMD_RULES: list[tuple[str, str, str, CommandRiskLevel]] = [
    # ... 现有规则 ...
    ("TOOL_CMD_CUSTOM_RULE", r"your_regex_pattern", "custom_category", CommandRiskLevel.CONFIRM),
]
```

**Good ✅ — 在 YAML 规则中添加：**
```yaml
# server/coapis/security/tool_guard/rules/dangerous_shell_commands.yaml
- id: TOOL_CMD_CUSTOM_RULE
  pattern: "your_regex_pattern_here"
  severity: high
  description: "描述该规则拦截的命令"
  action: block
```

**Bad ❌ — 直接修改白名单绕过检查：**
```python
# 不要这样做！
"user": ["ls", "cat", "rm", "sudo"],  # rm 和 sudo 不应在 user 白名单中
```

---

### 如何新增敏感文件模式

**Good ✅ — 在 file_guardian.py 中添加：**
```python
# server/coapis/security/tool_guard/guardians/file_guardian.py

# 精确文件名匹配
_SENSITIVE_FILE_NAMES: frozenset[str] = frozenset({
    # ... 现有条目 ...
    "new_secret.json",     # 新增
})

# Glob 模式匹配
_SENSITIVE_FILE_GLOBS: list[str] = [
    # ... 现有条目 ...
    "*.vault",             # 新增
]
```

**Bad ❌ — 只加精确匹配不加 glob：**
```python
# 如果新文件有变体（如 secret.json, secret.local），只加精确匹配会遗漏
_SENSITIVE_FILE_NAMES = frozenset({"secret.json"})  # 遗漏 secret.local
# 应同时添加 glob
_SENSITIVE_FILE_GLOBS = ["secret*"]
```

---

### 如何新增 Python 代码拦截模式

**在 ASTSandbox 中添加：**
```python
# server/coapis/security/ast_sandbox.py

# 新增危险函数
DANGEROUS_BUILTINS = frozenset({
    # ... 现有项 ...
    "exec", "eval", "compile", "__import__",
    "getattr", "setattr", "delattr", "hasattr",
    "globals", "locals", "vars",
    "breakpoint", "exit", "quit",
    "open",
})

# 新增危险 dunder
DANGEROUS_DUNDERS = frozenset({
    "__subclasses__", "__bases__", "__mro__",
    "__globals__", "__code__", "__dict__",
    "__class__", "__init_subclass__",
    "__loader__", "__spec__",
})
```

**在 ImportSandbox 中添加：**
```python
# server/coapis/security/import_sandbox.py

DEFAULT_BLOCKED_MODULES: Set[str] = {
    # ... 现有项 ...
    "os", "subprocess", "shutil", "sys", "importlib",
    "socket", "http", "urllib", "requests", "aiohttp",
    "ctypes", "struct", "mmap",
    "code", "codeop", "compileall",
    "multiprocessing", "threading",
}
```

---

## 测试说明

### 运行所有安全模块测试

```bash
# 在容器内运行
docker compose -f docker/docker-compose.dev.yaml exec server python3 -m pytest tests/test_whitelist_standalone.py tests/test_tool_monitor_blocking.py -v
```

### 独立测试脚本

| 测试文件 | 覆盖模块 | 用例数 |
|---------|---------|--------|
| `tests/test_whitelist_standalone.py` | 白名单语义匹配 | 33 |
| `tests/test_tool_monitor_blocking.py` | ToolCallMonitor 阻断 | 7 |
| `tests/test_ns_isolation.py` | Namespace 隔离 | 3 |

### 运行单个测试

```bash
# 白名单测试
docker compose -f docker/docker-compose.dev.yaml exec server python3 tests/test_whitelist_standalone.py

# ToolCallMonitor 测试
docker compose -f docker/docker-compose.dev.yaml exec server python3 tests/test_tool_monitor_blocking.py
```

### 手动验证安全检查

```bash
# 验证 CommandRiskClassifier
docker compose -f docker/docker-compose.dev.yaml exec server python3 -c "
import sys; sys.path.insert(0, '/opt/coapis')
from coapis.security.command_risk_classifier import CommandRiskClassifier
cr = CommandRiskClassifier()
tests = [
    ('ls -la', 'user', 'AUTO'),
    ('rm -rf /', 'user', 'BLOCK'),
    ('python3 script.py', 'advanced', 'AUTO'),
    ('python3 -c \"import os\"', 'user', 'BLOCK'),
    ('git push origin main', 'advanced', 'CONFIRM'),
    ('docker rm -f container', 'advanced', 'CONFIRM'),
]
for cmd, role, expected in tests:
    r = cr.classify(cmd, role)
    status = '✅' if r.risk_level.name == expected else '❌'
    print(f'{status} {cmd:40s} role={role:10s} → {r.risk_level.name} (expect {expected})')
"
```

---

> 📌 **版本：** v0.8.0 | **最后更新：** 2026-06-13 | **维护团队：** CoApis Security
