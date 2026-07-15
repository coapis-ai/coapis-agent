# 权限机制全面分析报告

**日期**：2026-07-15  
**范围**：write_file、shell 命令权限检查机制  
**目的**：分析权限拒绝的根本原因，提供解决方案

---

## 1. 权限检查机制概览

### 1.1 核心组件

| 组件 | 文件 | 用途 |
|------|------|------|
| WorkspaceGuard | workspace_guard.py | 权限检查核心类 |
| check_path | workspace_guard.py | 路径权限检查 |
| check_command | workspace_guard.py | 命令权限检查 |

### 1.2 检查流程

```
工具调用
  ↓
路径/命令检查
  ↓
白名单/黑名单/危险模式
  ↓
允许/拒绝
```

---

## 2. write_file 工具权限检查

### 2.1 路径解析逻辑

**函数**：`_resolve_write_path(file_path)`

**规则**：
1. **绝对路径** → 直接使用
2. **相对路径** → 解析到 `workspace/files/`
3. 自动创建 `files/` 目录

**示例**：
```python
# 输入：report.pdf
# 输出：/home/user/.coapis/workspaces/admin/files/report.pdf

# 输入：/tmp/report.pdf
# 输出：/tmp/report.pdf（绝对路径，直接使用）
```

### 2.2 权限检查逻辑

**函数**：`check_path(file_path, operation="write")`

**检查步骤**：
1. 解析路径（跟随符号链接）
2. 检查是否在 workspace 内
3. 检查是否在全局共享目录（skill_pool）
4. 不满足条件 → 拒绝

**代码片段**：
```python
# Check 1: Resolved path (follows symlinks) within workspace
target_resolved.relative_to(ws)

# Check 2: Non-resolved path (before following symlinks) within workspace
target_unresolved.relative_to(ws)

# Check 3: Global shared directories (skill_pool)
target_resolved.relative_to(skill_pool_dir.resolve())
```

### 2.3 常见错误场景

| 场景 | 原因 | 解决方案 |
|------|------|---------|
| 相对路径被拒绝 | workspace 未配置 | 确保配置 `COAPIS_WORKING_DIR` |
| 绝对路径被拒绝 | 路径不在 workspace 内 | 使用相对路径或添加到白名单 |
| 文件不存在被拒绝 | 父目录不存在 | 检查路径，确保父目录存在 |

---

## 3. Shell 命令权限检查

### 3.1 白名单配置

**位置**：`workspace_guard.py` 第49-119行

**user 角色白名单**：
```python
"user": [
    "ls *",
    "cat *", "head *", "tail *", "wc *", "grep *", "find *",
    "pwd", "date", "whoami",
    "echo *", "printf *",
    "mkdir *", "touch *", "rm *", "cp *", "mv *", "tree",
    "sort *", "uniq *", "cut *", "tr *", "sed *", "awk *",
    "python3 *", "python *",
    "node *", "npm *", "npx *", "pip3 *", "pip *",
    "git *",
    "curl *", "wget *",
    "tar *", "zip *", "unzip *",
],
```

### 3.2 黑名单配置

**位置**：`workspace_guard.py` 第141-155行

**黑名单命令**：
```python
FALLBACK_SHELL_BLACKLIST: List[str] = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "mkfs.*",
    "dd if=",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "fdisk",
    "parted",
    "iptables",
    "nft",
]
```

### 3.3 危险模式配置

**位置**：`workspace_guard.py` 第157-188行

**危险模式（正则表达式）**：
```python
FALLBACK_DANGEROUS_PATTERNS: List[str] = [
    r"rm\s+-[a-zA-Z]*f[a-zA-Z]*\s+(/|\~|/home|/root|/etc|/usr|/bin|/sbin)",
    r">\s*(/dev/|/etc/|/usr/|/bin/|/sbin/)",
    r"chmod\s+[0-7]*[7][0-7]*\s+(/|/etc/|/usr/|/bin/|/sbin/)",
    # 禁止解释器内联执行
    r"(python3?|node|ruby|perl|php)\s+(-c|--eval|-e)\s",
    # 禁止通过解释器模块执行命令
    r"python3?\s+-m\s+(subprocess|os|pty|shutil)",
    # 禁止反弹 shell
    r"socket\.socket\s*\(",
    r"subprocess\.(call|run|Popen)\s*\(",
    r"os\.system\s*\(",
    # 禁止将文件内容发送到外部
    r"curl\s+.*-d\s+@",
    r"curl\s+.*--data\s+@",
    r"wget\s+.*--post-file",
]
```

### 3.4 命令检查流程

**函数**：`is_command_allowed(command, role)`

**流程**：
```
1. 黑名单检查 → 匹配则拒绝
2. 危险模式检查 → 匹配则拒绝
3. 白名单检查 → 不匹配则拒绝
4. 参数检查（对于 python3 *.py 等）
   - 检查是否有 -c、-e 等内联执行标志
   - 检查文件路径是否在 workspace 内
```

---

## 4. 问题分析

### 4.1 cat 命令被拒绝

**场景**：`cat /etc/passwd` 或 `cat ~/.ssh/id_rsa`

**原因**：
- ✅ `cat *` 在白名单中（允许）
- ❌ 参数是绝对路径，且不在 workspace 内
- ❌ `_args_are_files_only()` 函数检查失败

**代码片段**：
```python
# Non-flag argument: validate it's within workspace
arg_path = Path(arg).expanduser()
if arg_path.is_absolute():
    if workspace:
        try:
            resolved = arg_path.resolve()
            resolved.relative_to(Path(workspace).resolve())
        except ValueError:
            # 路径不在 workspace 内 → 拒绝
            return False
```

**解决方案**：
1. **方案1**：使用相对路径
   ```bash
   # 不要用：cat /etc/passwd
   # 使用：cat files/passwd（先复制文件到 workspace）
   ```

2. **方案2**：添加到全局共享目录
   ```python
   # 修改 workspace_guard.py
   # Check 3: Global shared directories
   shared_dirs = [
       WORKING_DIR / "skill_pool",
       WORKING_DIR / "shared_files",  # 新增
   ]
   ```

3. **方案3**：使用 read_file 工具（也有权限检查）
   - 问题：read_file 也有权限检查，不能访问 workspace 外的文件

### 4.2 write_file 参数格式不对

**场景1**：相对路径解析错误

**原因**：
```python
# 输入：report.pdf
# 解析后：/home/user/.coapis/workspaces/admin/files/report.pdf
# 如果 workspace 未配置，会使用 WORKING_DIR
```

**解决方案**：确保配置 `COAPIS_WORKING_DIR`

**场景2**：绝对路径被拒绝

**原因**：
```python
# 输入：/tmp/report.pdf
# 解析后：/tmp/report.pdf（绝对路径，直接使用）
# 权限检查：不在 workspace 内 → 拒绝
```

**解决方案**：
1. 使用相对路径
2. 或添加路径到白名单

**场景3**：文件不存在

**原因**：父目录不存在

**解决方案**：确保父目录存在，或使用相对路径（会自动创建）

---

## 5. 权限架构设计原则

### 5.1 核心原则

1. **最小权限原则**：只允许必要的操作
2. **零信任架构**：所有操作都需要验证
3. **白名单优先**：默认拒绝，白名单明确允许
4. **路径隔离**：每个用户只能访问自己的 workspace

### 5.2 三层检查

| 层级 | 检查内容 | 目的 |
|------|---------|------|
| 黑名单 | 直接拒绝危险命令 | 防止系统破坏 |
| 危险模式 | 检测绕过尝试 | 防止权限提升 |
| 白名单 | 只允许明确授权的命令 | 最小权限原则 |

### 5.3 全局共享目录

**当前配置**：
- ✅ `skill_pool`：全局技能池

**设计目的**：
- 允许用户访问共享资源
- 无需复制文件到每个 workspace

---

## 6. 解决方案建议

### 6.1 cat 命令问题

**问题**：`cat /etc/passwd` 被拒绝（绝对路径不在 workspace 内）

**解决方案**：

**方案1：允许特定目录**（推荐）
```python
# 修改 workspace_guard.py
# 在 is_within_workspace() 函数中添加
SHARED_READ_DIRS = [
    "/etc/passwd",  # 允许读取
    "/etc/hosts",
    "/usr/share/doc",
]

def is_within_workspace(self, target_path: str | Path, username: str | None = None) -> bool:
    # ... existing checks ...
    
    # Check 4: Shared read directories
    for shared_dir in SHARED_READ_DIRS:
        try:
            target_resolved.relative_to(Path(shared_dir).resolve())
            return True
        except ValueError:
            pass
    
    return False
```

**方案2：使用工具包装**
```python
# 新建工具：safe_read_file
@register_tool(name="safe_read_file", ...)
async def safe_read_file(file_path: str) -> dict:
    """安全的文件读取工具，允许读取特定白名单路径"""
    ALLOWED_PATHS = [
        "/etc/passwd",
        "/etc/hosts",
        "/usr/share/doc/*",
    ]
    
    # 检查是否在白名单中
    for pattern in ALLOWED_PATHS:
        if fnmatch.fnmatch(file_path, pattern):
            with open(file_path, 'r') as f:
                return {"content": f.read()}
    
    return {"error": "路径不在白名单中"}
```

### 6.2 write_file 问题

**问题1**：参数格式不对

**解决方案**：明确文档说明
```python
# 文档示例
write_file(file_path="report.pdf", content="...")
# 解析为：/home/user/.coapis/workspaces/admin/files/report.pdf

write_file(file_path="/tmp/report.pdf", content="...")
# 解析为：/tmp/report.pdf（绝对路径，可能被拒绝）
```

**问题2**：绝对路径被拒绝

**解决方案**：
1. 使用相对路径
2. 或添加到白名单

---

## 7. 最佳实践

### 7.1 用户指南

**推荐做法**：
1. ✅ 使用相对路径（自动解析到 workspace/files/）
2. ✅ 在 workspace 内操作
3. ✅ 使用 doc_reader 等无权限检查的工具

**不推荐做法**：
1. ❌ 使用绝对路径（可能被拒绝）
2. ❌ 访问 workspace 外的文件（需要权限）
3. ❌ 使用危险的 shell 命令（rm -rf / 等）

### 7.2 开发者指南

**新增工具时**：
1. 考虑是否需要权限检查
2. 使用 `check_path()` 检查路径权限
3. 使用 `check_command()` 检查命令权限
4. 添加到白名单或黑名单

**新增全局共享目录时**：
1. 修改 `is_within_workspace()` 函数
2. 添加到白名单检查
3. 更新文档

---

## 8. 总结

### 8.1 核心机制

| 工具 | 权限检查 | 解决方案 |
|------|---------|---------|
| write_file | ✅ 路径检查 | 使用相对路径 |
| read_file | ✅ 路径检查 | 使用相对路径 |
| doc_reader | ❌ 无检查 | 推荐用于 PDF/DOCX |
| shell (cat) | ✅ 命令+路径检查 | 在 workspace 内使用 |
| shell (python) | ✅ 命令+参数检查 | 仅脚本文件模式 |

### 8.2 关键要点

1. **路径隔离**：每个用户只能访问自己的 workspace
2. **白名单机制**：默认拒绝，明确允许
3. **危险模式检测**：防止权限提升和绕过
4. **全局共享**：skill_pool 对所有用户开放

### 8.3 下一步

1. **添加更多全局共享目录**（如需要）
2. **完善文档**：明确说明权限规则
3. **优化用户体验**：提供更友好的错误提示
4. **监控审计**：记录权限拒绝事件

---

**文档版本**：v1.0  
**最后更新**：2026-07-15
