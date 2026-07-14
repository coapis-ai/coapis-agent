# 沙箱安全验证方案

> 版本：v1.0  
> 日期：2026-06-29  
> 作者：蜜总裁 🐝💼  
> 状态：待实施

---

## 一、验证目标

验证沙箱安全实施方案的各层防护机制是否正常工作，确保：
1. 用户只能访问自己的工作空间
2. 系统目录不暴露给用户
3. 危险命令被拦截
4. 正常操作不受影响

---

## 二、验证环境

### 2.1 开发环境

- **前端**：http://localhost:4300
- **后端**：http://localhost:4308
- **容器**：coapis-server-dev

### 2.2 测试用户

- **admin** — 管理员用户
- **test1** — 普通用户

### 2.3 测试数据

```
/apps/ai/coapis/
├── workspaces/
│   ├── admin/
│   │   └── files/
│   │       └── test.txt          ← admin 的测试文件
│   └── test1/
│       └── files/
│           └── test.txt          ← test1 的测试文件
├── system/
│   └── config.json               ← 系统配置文件
└── agents/
    └── global_default/
        └── agent.json            ← 智能体配置文件
```

---

## 三、验证用例

### 3.1 路径穿越测试（P0）

**目标：** 验证路径穿越攻击被拦截

| 编号 | 测试用例 | 预期结果 | 优先级 |
|------|----------|----------|--------|
| TC-001 | `cat ../../../system/config.json` | 返回 "Path not allowed" | P0 |
| TC-002 | `cat /apps/ai/coapis/system/config.json` | 返回 "Path not allowed" | P0 |
| TC-003 | `cat ../../../../etc/passwd` | 返回 "Path not allowed" | P0 |
| TC-004 | `cat /etc/passwd` | 返回 "Path not allowed" | P0 |

**验证方法：**

```python
import requests

# 登录
r = requests.post('http://localhost:4308/api/auth/login', 
                  json={'username': 'test1', 'password': 'test123'})
token = r.json()['token']
h = {'Authorization': f'Bearer {token}'}

# TC-001: 路径穿越
r1 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'execute_shell_command',
    'params': {'command': 'cat ../../../system/config.json'}
})
print(f"TC-001: {r1.json()}")

# TC-002: 绝对路径访问系统目录
r2 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'execute_shell_command',
    'params': {'command': 'cat /apps/ai/coapis/system/config.json'}
})
print(f"TC-002: {r2.json()}")
```

### 3.2 跨用户访问测试（P0）

**目标：** 验证用户无法访问其他用户的工作空间

| 编号 | 测试用例 | 预期结果 | 优先级 |
|------|----------|----------|--------|
| TC-005 | `ls /apps/ai/coapis/workspaces/admin/` | 返回 "Path not allowed" | P0 |
| TC-006 | `cat /apps/ai/coapis/workspaces/admin/files/test.txt` | 返回 "Path not allowed" | P0 |
| TC-007 | `echo "hack" > /apps/ai/coapis/workspaces/admin/files/hack.txt` | 返回 "Path not allowed" | P0 |

**验证方法：**

```python
# TC-005: 列出其他用户目录
r5 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'execute_shell_command',
    'params': {'command': 'ls /apps/ai/coapis/workspaces/admin/'}
})
print(f"TC-005: {r5.json()}")

# TC-006: 读取其他用户文件
r6 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'execute_shell_command',
    'params': {'command': 'cat /apps/ai/coapis/workspaces/admin/files/test.txt'}
})
print(f"TC-006: {r6.json()}")
```

### 3.3 系统目录访问测试（P0）

**目标：** 验证系统目录不暴露给用户

| 编号 | 测试用例 | 预期结果 | 优先级 |
|------|----------|----------|--------|
| TC-008 | `ls /apps/ai/coapis/system/` | 返回 "Path not allowed" | P0 |
| TC-009 | `cat /apps/ai/coapis/system/config.json` | 返回 "Path not allowed" | P0 |
| TC-010 | `rm -rf /apps/ai/coapis/system/` | 返回 "Command blocked" | P0 |
| TC-011 | `ls /apps/ai/coapis/agents/` | 返回 "Path not allowed" | P0 |

**验证方法：**

```python
# TC-008: 列出系统目录
r8 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'execute_shell_command',
    'params': {'command': 'ls /apps/ai/coapis/system/'}
})
print(f"TC-008: {r8.json()}")

# TC-009: 读取系统配置
r9 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'execute_shell_command',
    'params': {'command': 'cat /apps/ai/coapis/system/config.json'}
})
print(f"TC-009: {r9.json()}")
```

### 3.4 危险命令测试（P0）

**目标：** 验证危险命令被拦截

| 编号 | 测试用例 | 预期结果 | 优先级 |
|------|----------|----------|--------|
| TC-012 | `rm -rf /` | 返回 "Command blocked" | P0 |
| TC-013 | `rm -rf /*` | 返回 "Command blocked" | P0 |
| TC-014 | `rm -rf /apps/ai/coapis/` | 返回 "Command blocked" | P0 |
| TC-015 | `dd if=/dev/zero of=/dev/sda` | 返回 "Command blocked" | P0 |
| TC-016 | `mkfs.ext4 /dev/sda` | 返回 "Command blocked" | P0 |
| TC-017 | `chmod 777 /` | 返回 "Command blocked" | P0 |

**验证方法：**

```python
# TC-012: 删除根目录
r12 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'execute_shell_command',
    'params': {'command': 'rm -rf /'}
})
print(f"TC-012: {r12.json()}")

# TC-013: 删除根目录（通配符）
r13 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'execute_shell_command',
    'params': {'command': 'rm -rf /*'}
})
print(f"TC-013: {r13.json()}")
```

### 3.5 文件工具路径检查测试（P0）

**目标：** 验证文件工具的路径检查

| 编号 | 测试用例 | 预期结果 | 优先级 |
|------|----------|----------|--------|
| TC-018 | `read_file(path='/apps/ai/coapis/system/config.json')` | 返回 "Path not allowed" | P0 |
| TC-019 | `read_file(path='../../../system/config.json')` | 返回 "Path not allowed" | P0 |
| TC-020 | `write_file(path='/apps/ai/coapis/system/hack.txt', content='hack')` | 返回 "Path not allowed" | P0 |
| TC-021 | `list_files(path='/apps/ai/coapis/system/')` | 返回 "Path not allowed" | P0 |

**验证方法：**

```python
# TC-018: 读取系统配置
r18 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'read_file',
    'params': {'path': '/apps/ai/coapis/system/config.json'}
})
print(f"TC-018: {r18.json()}")

# TC-019: 路径穿越读取
r19 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'read_file',
    'params': {'path': '../../../system/config.json'}
})
print(f"TC-019: {r19.json()}")
```

### 3.6 正常操作测试（P1）

**目标：** 验证正常操作不受影响

| 编号 | 测试用例 | 预期结果 | 优先级 |
|------|----------|----------|--------|
| TC-022 | `ls ~/files/` | 正常返回文件列表 | P1 |
| TC-023 | `cat ~/files/test.txt` | 正常返回文件内容 | P1 |
| TC-024 | `echo "test" > ~/files/new.txt` | 正常写入 | P1 |
| TC-025 | `mkdir ~/files/newdir` | 正常创建目录 | P1 |
| TC-026 | `grep "test" ~/files/test.txt` | 正常返回匹配结果 | P1 |
| TC-027 | `find ~/files/ -name "*.txt"` | 正常返回文件列表 | P1 |

**验证方法：**

```python
# TC-022: 列出用户文件
r22 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'execute_shell_command',
    'params': {'command': 'ls ~/files/'}
})
print(f"TC-022: {r22.json()}")

# TC-023: 读取用户文件
r23 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'execute_shell_command',
    'params': {'command': 'cat ~/files/test.txt'}
})
print(f"TC-023: {r23.json()}")
```

### 3.7 L0 命令直接放行测试（P1）

**目标：** 验证 L0 命令直接放行，不进入规则检测

| 编号 | 测试用例 | 预期结果 | 优先级 |
|------|----------|----------|--------|
| TC-028 | `ls -la` | 直接放行，无规则检测 | P1 |
| TC-029 | `cat ~/files/test.txt` | 直接放行，无规则检测 | P1 |
| TC-030 | `echo "hello"` | 直接放行，无规则检测 | P1 |
| TC-031 | `pwd` | 直接放行，无规则检测 | P1 |

**验证方法：**

```python
# TC-028: L0 命令直接放行
r28 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'execute_shell_command',
    'params': {'command': 'ls -la'}
})
print(f"TC-028: {r28.json()}")
```

### 3.8 审计日志测试（P1）

**目标：** 验证审计日志记录正确

| 编号 | 测试用例 | 预期结果 | 优先级 |
|------|----------|----------|--------|
| TC-032 | 执行被拦截的命令，检查日志 | 日志文件包含拦截记录 | P1 |
| TC-033 | 执行正常的 L1 命令，检查日志 | 日志文件包含审计记录 | P1 |
| TC-034 | 访问非授权路径，检查日志 | 日志文件包含路径检查失败记录 | P1 |

**验证方法：**

```python
# TC-032: 执行被拦截的命令，检查日志
r32 = requests.post('http://localhost:4308/api/tools/execute', headers=h, json={
    'tool': 'execute_shell_command',
    'params': {'command': 'rm -rf /'}
})
print(f"TC-032: {r32.json()}")

# 检查审计日志
import subprocess
log_content = subprocess.check_output(['tail', '-n', '1', '/apps/ai/coapis/system/security_audit.log']).decode()
print(f"审计日志: {log_content}")
```

---

## 四、验证脚本

### 4.1 自动化验证脚本

```python
#!/usr/bin/env python3
"""沙箱安全验证脚本"""

import requests
import json
import sys

# 配置
BASE_URL = "http://localhost:4308"
USERNAME = "test1"
PASSWORD = "test123"

def login():
    """登录获取 token"""
    r = requests.post(f"{BASE_URL}/api/auth/login", 
                      json={"username": USERNAME, "password": PASSWORD})
    if r.status_code != 200:
        print(f"登录失败: {r.status_code}")
        sys.exit(1)
    return r.json()["token"]

def execute_tool(token, tool, params):
    """执行工具"""
    h = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{BASE_URL}/api/tools/execute", headers=h, json={
        "tool": tool,
        "params": params
    })
    return r.json()

def test_case(tc_id, description, tool, params, expected_blocked=True):
    """执行测试用例"""
    result = execute_tool(token, tool, params)
    
    # 检查是否被拦截
    is_blocked = "error" in result or "not allowed" in str(result).lower() or "blocked" in str(result).lower()
    
    if expected_blocked and is_blocked:
        status = "✅ PASS"
    elif not expected_blocked and not is_blocked:
        status = "✅ PASS"
    else:
        status = "❌ FAIL"
    
    print(f"{tc_id}: {status} - {description}")
    if status == "❌ FAIL":
        print(f"  预期: {'拦截' if expected_blocked else '放行'}")
        print(f"  实际: {result}")
    
    return status == "✅ PASS"

# 登录
token = login()
print(f"登录成功: {USERNAME}")
print("=" * 60)

# 测试用例
test_cases = [
    # 路径穿越测试
    ("TC-001", "路径穿越 - cat ../../../system/config.json", 
     "execute_shell_command", {"command": "cat ../../../system/config.json"}, True),
    ("TC-002", "绝对路径 - cat /apps/ai/coapis/system/config.json", 
     "execute_shell_command", {"command": "cat /apps/ai/coapis/system/config.json"}, True),
    
    # 跨用户访问测试
    ("TC-005", "跨用户 - ls /apps/ai/coapis/workspaces/admin/", 
     "execute_shell_command", {"command": "ls /apps/ai/coapis/workspaces/admin/"}, True),
    
    # 系统目录访问测试
    ("TC-008", "系统目录 - ls /apps/ai/coapis/system/", 
     "execute_shell_command", {"command": "ls /apps/ai/coapis/system/"}, True),
    
    # 危险命令测试
    ("TC-012", "危险命令 - rm -rf /", 
     "execute_shell_command", {"command": "rm -rf /"}, True),
    
    # 文件工具路径检查测试
    ("TC-018", "文件工具 - read_file 系统配置", 
     "read_file", {"path": "/apps/ai/coapis/system/config.json"}, True),
    
    # 正常操作测试
    ("TC-022", "正常操作 - ls ~/files/", 
     "execute_shell_command", {"command": "ls ~/files/"}, False),
    ("TC-023", "正常操作 - cat ~/files/test.txt", 
     "execute_shell_command", {"command": "cat ~/files/test.txt"}, False),
]

# 执行测试
passed = 0
failed = 0
for tc in test_cases:
    if test_case(*tc):
        passed += 1
    else:
        failed += 1

# 统计结果
print("=" * 60)
print(f"测试完成: {passed} 通过, {failed} 失败")
if failed > 0:
    sys.exit(1)
```

### 4.2 运行验证脚本

```bash
# 在开发环境运行
cd /apps/ai/tool-dev/dev-coapis/coapis-agent
python3 docs/security/sandbox-security-verify.py
```

---

## 五、验证报告模板

### 5.1 验证结果

| 类别 | 总数 | 通过 | 失败 | 通过率 |
|------|------|------|------|--------|
| 路径穿越测试 | 4 | - | - | - |
| 跨用户访问测试 | 3 | - | - | - |
| 系统目录访问测试 | 4 | - | - | - |
| 危险命令测试 | 6 | - | - | - |
| 文件工具路径检查测试 | 4 | - | - | - |
| 正常操作测试 | 6 | - | - | - |
| L0 命令直接放行测试 | 4 | - | - | - |
| 审计日志测试 | 3 | - | - | - |
| **总计** | **34** | **-** | **-** | **-** |

### 5.2 问题记录

| 编号 | 问题描述 | 严重程度 | 状态 |
|------|----------|----------|------|
| - | - | - | - |

---

## 六、版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-06-29 | 初始方案 |

---

**文档结束** 🐝
