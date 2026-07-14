# 沙箱安全实施方案

> 版本：v1.0  
> 日期：2026-06-29  
> 作者：蜜总裁 🐝💼  
> 状态：待确认

---

## 一、问题分析

### 1.1 当前安全状况

**核心问题：安全基础设施全部是死代码**

| 模块 | 文件路径 | 功能 | 是否被调用 |
|------|----------|------|-----------|
| ToolSandbox | `security/tool_sandbox.py` | 路径白名单 + 命令验证 | ❌ 零调用 |
| SandboxedExecutor | `security/sandboxed_executor.py` | 工具白名单 + 路径验证 | ❌ 零调用 |
| ProcessIsolator | `security/process_isolator.py` | 隔离子进程 + 环境变量过滤 | ❌ 零调用 |
| InputGuardEngine | `security/input_guard/` | 输入内容安全检测 | ❌ 零调用 |
| UnifiedToolGuardEngine | `security/tool_guard/unified_engine.py` | 命令分级 + 规则检测 + 逃逸检测 | ❌ 零调用 |

**实际执行路径（零防护）：**

```
用户消息 → websocket.py → Agent → 调用工具 → builtin.py 直接执行
                                                     ↑
                                              无任何沙箱/路径/命令检查
```

### 1.2 风险分析

**当前无防护的操作：**

| 工具 | 风险 | 示例 |
|------|------|------|
| `shell_execute` | 直接以 root 执行任意命令 | `rm -rf /apps/ai/coapis/system/` |
| `file_read` | 可读取任意文件 | 读取其他用户工作空间、系统配置 |
| `file_write` | 可写入任意文件 | 覆盖系统配置、植入后门 |
| `list_files` | 可列出任意目录 | 探测系统目录结构 |

**攻击场景：**

1. **路径穿越** — `cat ../../../system/config.json` 读取系统配置
2. **跨用户访问** — `cat /apps/ai/coapis/workspaces/admin/...` 读取其他用户文件
3. **系统破坏** — `rm -rf /apps/ai/coapis/system/` 删除系统配置
4. **权限提升** — `chmod 777 /apps/ai/coapis/` 修改系统权限

---

## 二、方案设计

### 2.1 设计原则

1. **最小权限** — 用户只能访问自己的工作空间
2. **纵深防御** — 多层安全检查，任何一层被绕过都有下一层防护
3. **激活已有** — 优先激活已有的安全基础设施，减少重复开发
4. **性能优先** — L0 命令直接放行，避免不必要的检查

### 2.2 安全架构

**三层纵深防御：**

```
┌─────────────────────────────────────────────────────────────┐
│                    工具调用请求                               │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  L1: SandboxedExecutor (工具白名单 + 路径验证)                │
│  ├─ 工具白名单检查                                           │
│  ├─ 路径白名单检查 (ToolSandbox)                              │
│  └─ 命令验证 (ToolSandbox)                                   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  L2: UnifiedToolGuardEngine (命令分级 + 规则检测)             │
│  ├─ 命令分级 (L0-L4)                                         │
│  ├─ 模式规则匹配                                             │
│  └─ 逃逸检测                                                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  L3: InputGuardEngine (输入内容安全检测)                      │
│  ├─ 命令注入检测                                             │
│  ├─ Prompt 注入检测                                          │
│  └─ 数据窃取检测                                             │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  隔离执行 (ProcessIsolator)                                  │
│  ├─ 临时工作目录                                             │
│  ├─ 环境变量过滤                                             │
│  └─ 输出截断 + 超时控制                                      │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 路径访问规则

| 操作 | 用户工作空间 | 系统目录 | 其他用户空间 |
|------|-------------|----------|-------------|
| 读取 | ✅ 允许 | ❌ 禁止 | ❌ 禁止 |
| 写入 | ✅ 允许 | ❌ 禁止 | ❌ 禁止 |
| 执行 | ✅ 允许 | ❌ 禁止 | ❌ 禁止 |
| 列出 | ✅ 允许 | ❌ 禁止 | ❌ 禁止 |

**工作空间结构：**

```
/apps/ai/coapis/
├── workspaces/
│   ├── {username}/          ← 用户数据（隔离）
│   │   ├── files/           ← 用户文件
│   │   ├── chats/           ← 聊天记录
│   │   ├── memory/          ← 记忆文件
│   │   └── skills/          ← 用户技能
│   └── ...
├── agents/                  ← 智能体配置（系统内部）
├── system/                  ← 系统配置（系统内部）
└── coapis.log               ← 系统日志
```

### 2.4 安全检查流程

**工具调用流程：**

```python
async def execute_tool(tool_name, tool_func, **kwargs):
    # 1. 工具白名单检查
    if tool_name not in ALLOWED_TOOLS:
        raise PermissionError(f"Tool not allowed: {tool_name}")
    
    # 2. 路径白名单检查（文件类工具）
    if tool_name in PATH_TOOLS:
        path = kwargs.get("path")
        result = sandbox.check_path(path, operation)
        if not result.allowed:
            raise PermissionError(f"Path not allowed: {result.reason}")
    
    # 3. 命令验证（shell 类工具）
    if tool_name in COMMAND_TOOLS:
        command = kwargs.get("command")
        result = sandbox.check_command(command)
        if not result.allowed:
            raise PermissionError(f"Command not allowed: {result.reason}")
        
        # 4. 命令分级检查
        guard_result = unified_engine.process_command(tool_name, kwargs)
        if guard_result["action"] == "block":
            raise PermissionError(f"Command blocked: {guard_result['reason']}")
    
    # 5. 输入内容检查
    input_result = input_guard.check(str(kwargs))
    if input_result.blocked:
        raise PermissionError(f"Input blocked: {input_result.reason}")
    
    # 6. 隔离执行
    return await process_isolator.execute(command, cwd=user_workspace)
```

---

## 三、文件改动清单

### 3.1 核心改动文件

| 文件 | 改动内容 | 原因 |
|------|----------|------|
| `tools/builtin.py` | shell_execute 增加 cwd + 路径拦截 | 当前直接 subprocess.run 无限制 |
| `tools/builtin.py` | file_read/file_write/list_files 增加路径检查 | 当前直接读写无限制 |
| `tools/registry.py` | call_tool 接入 SandboxedExecutor | 工具执行的统一入口 |
| `security/tool_sandbox.py` | 调整 allowed_dirs（系统目录不暴露） | 系统目录只允许系统内部访问 |
| `security/sandboxed_executor.py` | 接入 UnifiedToolGuardEngine + InputGuardEngine | 统一安全检查链 |
| `security/process_isolator.py` | 修复 Path 导入问题 | 当前代码有 bug |
| `security/audit_logger.py` | 新增安全审计日志模块 | 记录所有安全检查结果 |

### 3.2 配置文件

| 文件 | 改动内容 |
|------|----------|
| `docker-compose.dev.yaml` | 添加安全相关环境变量 |
| `docker-compose.yml` | 添加安全相关环境变量 |
| `.env` | 添加安全配置说明 |

### 3.3 技术文档

| 文件 | 内容 |
|------|------|
| `docs/security/sandbox-security-plan.md` | 本文档 |
| `docs/security/sandbox-security-verify.md` | 验证方案 |

---

## 四、实施步骤

### 4.1 阶段一：激活路径沙箱 + 审计日志（P0）

**目标：** 限制文件操作只能在用户工作空间内，并记录审计日志

**改动：**

1. **新增 `security/audit_logger.py`**
   - 实现 SecurityAuditLogger 类
   - 支持 JSON Lines 格式
   - 支持按日期轮转日志文件

2. **修改 `tools/builtin.py`**
   - `file_read` 增加路径白名单检查 + 审计日志
   - `file_write` 增加路径白名单检查 + 审计日志
   - `list_files` 增加路径白名单检查 + 审计日志
   - `shell_execute` 增加 `cwd=user_workspace` + 审计日志

3. **修改 `security/tool_sandbox.py`**
   - 移除系统目录到 allowed_dirs
   - 只保留用户工作空间
   - 集成审计日志

4. **修改 `tools/registry.py`**
   - `call_tool` 方法接入 SandboxedExecutor

### 4.2 阶段二：激活命令防护（P1）

**目标：** 限制 shell 命令执行

**改动：**

1. **修改 `security/sandboxed_executor.py`**
   - 接入 UnifiedToolGuardEngine
   - 接入 InputGuardEngine
   - 移除速率限制
   - 集成审计日志

2. **修改 `security/tool_guard/unified_engine.py`**
   - 确保 `process_command` 正常工作
   - 验证 L0 命令直接放行优化
   - 集成审计日志

3. **修改 `security/input_guard/engine.py`**
   - 增加路径穿越检测规则
   - 验证规则匹配
   - 集成审计日志

### 4.3 阶段三：隔离执行（P2）

**目标：** 隔离子进程执行环境

**改动：**

1. **修改 `security/process_isolator.py`**
   - 修复 Path 导入问题
   - 验证临时目录创建
   - 验证环境变量过滤
   - 集成审计日志

2. **修改 `security/sandboxed_executor.py`**
   - 接入 ProcessIsolator
   - 验证超时控制

### 4.4 阶段四：验证与测试（P3）

**目标：** 验证安全防护生效

**测试用例：**

1. **路径穿越测试**
   - `cat ../../../system/config.json` → 应返回 "Path not allowed"
   - `cat /apps/ai/coapis/workspaces/admin/...` → 应返回 "Path not allowed"

2. **跨用户访问测试**
   - `ls /apps/ai/coapis/workspaces/admin/` → 应返回 "Path not allowed"
   - `echo "test" > /apps/ai/coapis/workspaces/admin/test.txt` → 应返回 "Path not allowed"

3. **系统目录访问测试**
   - `cat /apps/ai/coapis/system/config.json` → 应返回 "Path not allowed"
   - `rm -rf /apps/ai/coapis/system/` → 应返回 "Command blocked"

4. **正常操作测试**
   - `ls ~/files/` → 应正常返回
   - `cat ~/files/test.txt` → 应正常返回
   - `echo "test" > ~/files/test.txt` → 应正常返回

---

## 五、风险评估

### 5.1 已有安全机制

| 风险 | 防护机制 | 状态 |
|------|----------|------|
| 符号链接攻击 | `ToolSandbox.check_path` 使用 `Path.resolve()` | ✅ 已有 |
| 相对路径穿越 | `ToolSandbox.check_path` 使用 `Path.resolve()` | ✅ 已有 |
| 环境变量注入 | `ProcessIsolator._build_env` 过滤环境变量 | ✅ 已有 |
| 命令注入 | `UnifiedToolGuardEngine.process_command` | ✅ 已有 |
| Prompt 注入 | `InputGuardEngine` | ✅ 已有 |

### 5.2 潜在风险

| 风险 | 缓解措施 |
|------|----------|
| 性能影响 | L0 命令直接放行，避免不必要的检查 |
| 误报 | 提供白名单机制，允许特定路径/命令 |
| 兼容性 | 保持旧 API 兼容，渐进式迁移 |

---

## 六、配置说明

### 6.1 环境变量

```bash
# 工具沙箱配置
COAPIS_TOOL_SANDBOX_ENABLED=true          # 是否启用工具沙箱

# 路径配置
COAPIS_WORKING_DIR=/apps/ai/coapis        # 工作目录
COAPIS_WORKSPACES_DIR=/apps/ai/coapis/workspaces  # 工作空间目录

# 审计日志配置
COAPIS_SECURITY_AUDIT_LOG_DIR=/apps/ai/coapis/system  # 审计日志目录
COAPIS_SECURITY_AUDIT_LOG_RETENTION_DAYS=30           # 日志保留天数
```

### 6.2 白名单配置

**工具白名单（`sandboxed_executor.py`）：**

```python
ALLOWED_TOOLS = frozenset({
    "read_file", "write_file", "edit_file",
    "grep_search", "glob_search",
    "execute_shell_command",
    "get_current_time", "set_user_timezone",
    "get_token_usage",
    "view_image",
    "send_file_to_user",
    "desktop_screenshot",
    "memory_search",
})
```

**路径白名单（`tool_sandbox.py`）：**

```python
def _build_allowed_dirs(self) -> Set[Path]:
    """Build set of allowed directories."""
    dirs = {
        self.workspace_dir,
        self.workspace_dir / "files",
        self.workspace_dir / "chats",
    }
    # Temp directory — per-user, under workspace/files/tmp
    dirs.add(self.workspace_dir / "files" / "tmp")
    return dirs
```

---

## 七、验证方案

详见：`docs/security/sandbox-security-verify.md`

---

## 八、版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-06-29 | 初始方案 |

---

## 九、审计日志

### 9.1 审计日志设计

**日志文件路径：** `system/security_audit.log`

**日志格式：** JSON Lines (每行一个 JSON 对象)

**日志字段：**

```json
{
  "timestamp": "2026-06-29T12:00:00+08:00",
  "user": "test1",
  "agent_id": "global_default",
  "tool": "execute_shell_command",
  "action": "block",
  "level": "L3",
  "command": "rm -rf /",
  "reason": "Command blocked: dangerous pattern detected",
  "workspace": "/apps/ai/coapis/workspaces/test1",
  "source_ip": "172.18.0.1",
  "session_id": "ws-xxx"
}
```

### 9.2 审计日志触发条件

| 触发条件 | 日志级别 | 说明 |
|----------|----------|------|
| 路径检查失败 | WARNING | 用户尝试访问非授权路径 |
| 命令被拦截 | WARNING | L3/L4 命令被 block |
| 命令被审计 | INFO | L1/L2/L3 命令被 audit |
| 工具被拒绝 | WARNING | 用户尝试调用非白名单工具 |
| 输入被拦截 | WARNING | InputGuard 检测到恶意输入 |

### 9.3 审计日志实现

**新增文件：** `security/audit_logger.py`

```python
import json
import logging
from datetime import datetime
from pathlib import Path

class SecurityAuditLogger:
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = self._setup_logger()
    
    def _setup_logger(self):
        logger = logging.getLogger("security_audit")
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(self.log_dir / "security_audit.log")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        return logger
    
    def log(self, user, agent_id, tool, action, level, command, reason, workspace, source_ip, session_id):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user": user,
            "agent_id": agent_id,
            "tool": tool,
            "action": action,
            "level": level,
            "command": command,
            "reason": reason,
            "workspace": str(workspace),
            "source_ip": source_ip,
            "session_id": session_id
        }
        self.logger.info(json.dumps(entry, ensure_ascii=False))
```

---

## 十、待确认问题

1. ✅ 系统目录只允许系统内部读取，不暴露给用户
2. ✅ 速率限制已移除
3. ✅ 白名单机制：暂不启用（已有功能保留）
4. ✅ 审计日志：需要，记录所有安全检查结果

---

**文档结束** 🐝
