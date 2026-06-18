# CoApis 安全运维手册

> 面向运维人员的安全模块日常操作指南。涵盖环境配置、白名单维护、告警处理、故障排查等核心运维场景。

---

## 📋 目录

- [快速上手](#快速上手)
- [环境变量配置](#环境变量配置)
- [白名单维护](#白名单维护)
- [敏感文件列表更新](#敏感文件列表更新)
- [审批超时配置](#审批超时配置)
- [ToolCallMonitor 封禁处理](#toolcallmonitor-封禁处理)
- [Docker 资源限制调整](#docker-资源限制调整)
- [告警日志排查](#告警日志排查)

---

## 快速上手

服务启动后，按以下步骤验证安全模块是否正常加载：

```bash
# 1. 检查服务状态
docker compose -f docker/docker-compose.dev.yaml ps

# 2. 进入容器验证模块加载
docker compose -f docker/docker-compose.dev.yaml exec server python3 -c "
import sys; sys.path.insert(0, '/opt/coapis')
from coapis.security.command_risk_classifier import CommandRiskClassifier
from coapis.security.tool_monitor import get_tool_call_monitor
from coapis.security.import_sandbox import DEFAULT_BLOCKED_MODULES
from coapis.security.ast_sandbox import ASTSandbox
from coapis.security.sandboxed_executor import _RATE_LIMIT_MAX
print(f'CommandRiskClassifier: OK')
print(f'ToolCallMonitor: blocked={get_tool_call_monitor().should_block(\"test\")[0]}')
print(f'ImportSandbox: {len(DEFAULT_BLOCKED_MODULES)} blocked modules')
print(f'ASTSandbox: OK')
print(f'Rate limit: {_RATE_LIMIT_MAX}/min')
"

# 3. 验证审计日志表
docker compose -f docker/docker-compose.dev.yaml exec server python3 -c "
import sqlite3, os
db = os.environ.get('COAPIS_DATA_DIR', '/apps/ai/coapis') + '/system/user_system.db'
conn = sqlite3.connect(db)
count = conn.execute('SELECT COUNT(*) FROM audit_logs').fetchone()[0]
print(f'Audit logs: {count} records')
conn.close()
"
```

**预期输出：** 所有模块显示 OK，audit_logs 有记录。

---

## 环境变量配置

所有安全相关环境变量在 `docker/docker-compose.dev.yaml` 或 `.env` 文件中配置，修改后需重启服务。

### 核心安全配置

| 变量 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `COAPIS_ENABLE_NS` | int | `0` | 启用文件系统 namespace 隔离（需容器 SYS_ADMIN 权限） |
| `COAPIS_RATE_LIMIT_MAX` | int | `30` | Per-user 工具调用速率上限（次/窗口） |
| `COAPIS_RATE_LIMIT_WINDOW` | float | `60` | 速率限制窗口大小（秒） |
| `COAPIS_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS` | float | `300` | 审批确认超时时间（秒），超时自动拒绝 |
| `COAPIS_AUTH_ENABLED` | bool | `True` | 启用认证系统 |
| `COAPIS_USER_SYSTEM_ENABLED` | bool | `True` | 启用多租户用户体系 |

### 配置示例

```bash
# 在 .env 文件中添加
COAPIS_ENABLE_NS=1
COAPIS_RATE_LIMIT_MAX=50
COAPIS_RATE_LIMIT_WINDOW=60
COAPIS_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS=600

# 重启服务生效
docker compose -f docker/docker-compose.dev.yaml restart server
```

> ⚠️ `COAPIS_ENABLE_NS=1` 需要容器具备 SYS_ADMIN 能力，否则 namespace 操作会静默降级（不影响正常功能）。

---

## 白名单维护

### 查看当前白名单

白名单定义在 `server/coapis/agents/security/workspace_guard.py` 的 `FALLBACK_SHELL_WHITELIST` 中，按角色分级：

```python
FALLBACK_SHELL_WHITELIST = {
    "user":     ["ls", "cat", "head", "tail", "grep", "find", ...],
    "advanced": ["ls", "cat", "python3", "node", "git", "docker", ...],
    "admin":    ["ls", "cat", "python3", "node", "git", "docker", ...],  # 与 advanced 统一
    "owner":    ["*"],  # owner 不受白名单限制
}
```

### 添加新命令到白名单

**Good ✅ — 精确指定命令：**
```python
# 在对应角色的列表中添加
"user": ["ls", "cat", "head", "tail", "grep", "find", "wc", "sort", "uniq"],
```

**Bad ❌ — 使用通配符：**
```python
# 除 owner 外，不要使用通配符
"user": ["*"],  # 这会让所有命令绕过白名单检查
```

### 白名单条目语义

| 格式 | 示例 | 匹配行为 |
|------|------|---------|
| `base` | `"python3"` | 仅匹配 `python3` 本身 |
| `base *` | `"cat *"` | 匹配 `cat` + 任意参数 |
| `base *.ext` | `"python3 *.py"` | 匹配 `python3` + 至少一个 `.py` 文件，**拒绝** `-c/-e` 等内联标志 |

### 验证白名单修改

```bash
# 运行白名单测试
docker compose -f docker/docker-compose.dev.yaml exec server python3 /opt/coapis/tests/test_whitelist_standalone.py
```

---

## 敏感文件列表更新

敏感文件列表定义在 `server/coapis/security/tool_guard/guardians/file_guardian.py`：

### 添加新的敏感文件模式

**文件名匹配（精确）：** 编辑 `_SENSITIVE_FILE_NAMES` frozenset：
```python
_SENSITIVE_FILE_NAMES: frozenset[str] = frozenset({
    # ... 现有条目 ...
    "my_secret_config.json",    # 新增
    ".vault-key",               # 新增
})
```

**Glob 模式匹配（模糊）：** 编辑 `_SENSITIVE_FILE_GLOBS` list：
```python
_SENSITIVE_FILE_GLOBS: list[str] = [
    # ... 现有条目 ...
    "*.vault",     # 新增
    "*.key",       # 已有
]
```

### 验证敏感文件拦截

```bash
# 测试敏感文件访问是否被拦截
docker compose -f docker/docker-compose.dev.yaml exec server python3 -c "
from coapis.security.tool_guard.guardians.file_guardian import _SENSITIVE_FILE_NAMES
print(f'Total patterns: {len(_SENSITIVE_FILE_NAMES)}')
# 检查新增的模式是否存在
assert 'my_secret_config.json' in _SENSITIVE_FILE_NAMES
print('Verification passed')
"
```

---

## 审批超时配置

审批超时控制 ApprovalCard 的等待时间，超时后自动拒绝。

### 修改超时时间

```bash
# 在 .env 中设置（单位：秒）
COAPIS_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS=600   # 10 分钟
```

### 验证配置

```bash
docker compose -f docker/docker-compose.dev.yaml exec server python3 -c "
from coapis.constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
print(f'Approval timeout: {TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS}s')
"
```

---

## ToolCallMonitor 封禁处理

### 什么是 ToolCallMonitor？

ToolCallMonitor 持续监控每个用户的工具调用行为，当检测到异常模式时自动封禁用户。封禁期间，该用户的所有工具调用将被拒绝。

### 触发条件

| 条件 | 阈值 | 冷却期 |
|------|------|--------|
| 连续 critical 级告警 | 3 次 | 300 秒 |
| 累计异常事件 | 8 次 | 300 秒 |
| 解封后保护期 | — | 60 秒 |

### 症状 → 原因 → 解决方案

---

**症状：** 用户报告工具调用被拒绝，返回"安全告警过多"或"异常行为累积"。

**原因：** 该用户触发了 ToolCallMonitor 的自动封禁阈值。

**解决方案：**
1. 管理员手动解封：
```bash
POST /api/security/tool-monitor/unblock
Body: {"username": "被封禁的用户"}
```
2. 等待 5 分钟自动解封（冷却期过后）。
3. 排查该用户的异常行为日志：
```bash
GET /api/audit/logs?event_type=tool_monitor_blocked&username=被封禁的用户&limit=20
```

---

**症状：** 解封后立即又被封禁。

**原因：** 旧告警仍在滑动窗口内，解封后 60 秒冷却期内不因旧告警重新封禁，但新告警仍会触发。

**解决方案：** 等待 60 秒冷却期结束后再操作，或联系管理员检查是否存在持续的异常行为。

---

## Docker 资源限制调整

### 当前配置

```yaml
# docker/docker-compose.dev.yaml
server:
  deploy:
    resources:
      limits:
        memory: 2G
        cpus: "2.0"
      reservations:
        memory: 512M
        cpus: "0.5"

nginx:
  deploy:
    resources:
      limits:
        memory: 256M
        cpus: "0.5"
```

### 调整资源限制

```bash
# 编辑 docker/docker-compose.dev.yaml 中的 deploy.resources.limits
# 修改后重启
docker compose -f docker/docker-compose.dev.yaml up -d
```

> ⚠️ 降低内存限制可能导致 OOM。建议 server 容器至少保留 1G 内存。

### tmpfs 配置

当前 `/tmp` 挂载为 tmpfs（noexec + nosuid）：

| 容器 | 大小限制 | 挂载选项 |
|------|---------|---------|
| server | 256M | noexec, nosuid |
| nginx | 64M | noexec, nosuid |

---

## 告警日志排查

### 常见告警类型

| 告警类型 | 日志关键词 | 含义 |
|---------|-----------|------|
| 命令拦截 | `Tool Guard: BLOCK` | 高危命令被硬拒绝 |
| 命令审批 | `Tool Guard: CONFIRM` | 需审批确认的命令 |
| 模块拦截 | `Import blocked` | python3 -c 中导入了危险模块 |
| AST 拦截 | `AST violation` | 代码包含危险 AST 结构 |
| 封禁触发 | `Blocking user` | ToolCallMonitor 触发自动封禁 |
| 审批超时 | `approval timeout` | 审批确认超时，自动拒绝 |
| 速率限制 | `Rate limit exceeded` | 用户工具调用频率超限 |

### 查看实时日志

```bash
# 查看安全相关日志（过滤关键词）
docker compose -f docker/docker-compose.dev.yaml logs -f server 2>&1 | \
  grep -iE "block|denied|alert|violation|timeout|rate limit|monitor"
```

### 查看审计日志

```bash
# 查询最近的被拒绝操作
curl -s "http://localhost:4103/api/audit/logs?event_type=tool_guard_denied&limit=10" | python3 -m json.tool

# 查询最近的封禁事件
curl -s "http://localhost:4103/api/audit/logs?event_type=tool_monitor_blocked&limit=10" | python3 -m json.tool

# 查询特定用户的操作
curl -s "http://localhost:4103/api/audit/logs?username=目标用户&limit=20" | python3 -m json.tool
```

### 审计日志字段说明

每条审计记录包含以下关键字段：

| 字段 | 说明 |
|------|------|
| `event_type` | 事件类型（tool_guard_denied / tool_monitor_blocked / tool_guard_approval） |
| `risk_level` | 风险等级（critical / high / medium / low / block） |
| `command_category` | 命令类别（destruction / privilege / network / etc.） |
| `confirm_result` | 确认结果（denied / approved / timeout / monitor_blocked） |
| `tool_name` | 被操作的工具名称 |
| `command` | 原始命令内容 |

---

> 📌 **版本：** v0.8.0 | **最后更新：** 2026-06-13 | **维护团队：** CoApis Security
