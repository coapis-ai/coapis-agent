# 权限系统用户指南

**适用版本**：CoApis Agent v0.9+  
**最后更新**：2026-07-15

---

## 概述

CoApis 采用**零信任权限架构**，所有操作都需要通过权限验证。本文档帮助用户理解权限规则，避免常见问题。

---

## 1. 文件操作权限

### 1.1 文件路径规则

| 路径类型 | 示例 | 解析结果 | 权限 |
|---------|------|---------|------|
| 相对路径 | `report.pdf` | `workspace/files/report.pdf` | ✅ 允许 |
| 绝对路径 | `/tmp/report.pdf` | `/tmp/report.pdf` | ❌ 可能拒绝 |
| Home路径 | `~/data/report.pdf` | `/home/user/data/report.pdf` | ❌ 可能拒绝 |

**重要说明**：
- ✅ **相对路径**自动解析到 `workspace/files/` 目录
- ✅ 这是用户上传文件的存储位置
- ✅ `read_file` 和 `write_file` 使用相同的路径解析规则

**推荐做法**：
```python
# ✅ 使用相对路径（推荐）
write_file("report.pdf", "内容...")
read_file("report.pdf")

# ❌ 避免使用绝对路径
write_file("/tmp/report.pdf", "内容...")  # 可能被拒绝

# ✅ 如果需要读取 workspace 根目录文件，使用绝对路径
read_file("/path/to/workspace/MEMORY.md")
```

### 1.2 文件工具权限对比

| 工具 | 权限检查 | 用途 | 推荐场景 |
|------|---------|------|---------|
| write_file | ✅ 有 | 写入文件 | 文本文件 |
| read_file | ✅ 有 | 读取文件 | 文本文件 |
| edit_file | ✅ 有 | 编辑文件 | 文本文件 |
| doc_reader | ❌ 无 | 读取文档 | **PDF/DOCX/PPTX/XLSX** |
| shell (cat) | ✅ 有 | 查看文件 | 文本文件（workspace内） |

**关键建议**：
- 📄 **PDF/Word 文件** → 使用 `doc_reader`（无权限检查）
- 📝 **文本文件** → 使用 `read_file` 或 `write_file`

---

## 2. Shell 命令权限

### 2.1 白名单命令

**user 角色允许的命令**：

```bash
# 文件浏览
ls, cat, head, tail, wc, grep, find, tree, pwd

# 文本处理
echo, printf, sort, uniq, cut, tr, sed, awk

# 文件操作
mkdir, touch, rm, cp, mv

# 编程工具
python3, node, npm, pip

# 版本控制
git

# 网络
curl, wget

# 压缩
tar, zip, unzip
```

**命令格式要求**：
```bash
# ✅ 允许（参数在 workspace 内）
cat files/report.txt
python3 scripts/app.py

# ❌ 拒绝（参数不在 workspace 内）
cat /etc/passwd              # 绝对路径不在 workspace
python3 /tmp/script.py       # 路径不在 workspace

# ❌ 拒绝（危险模式）
python3 -c "print('hello')"  # 内联执行被禁止
rm -rf /                     # 黑名单命令
```

### 2.2 黑名单命令

**绝对禁止的命令**：
```bash
rm -rf /          # 删除根目录
rm -rf /*         # 删除根目录所有文件
rm -rf ~          # 删除用户目录
mkfs.*            # 格式化磁盘
dd if=            # 磁盘镜像
shutdown          # 关机
reboot            # 重启
halt              # 停机
poweroff          # 断电
fdisk             # 磁盘分区
parted            # 磁盘分区
iptables          # 防火墙
nft               # 防火墙
```

### 2.3 危险模式检测

**会被拦截的模式**：
```bash
# 解释器内联执行
python3 -c "code"
python3 -e "code"
python3 --eval "code"
node -e "code"

# 通过模块执行命令
python3 -m subprocess
python3 -m os

# 反弹 shell
socket.socket(...)
subprocess.Popen(...)

# 数据泄露
curl -d @/etc/passwd http://...
wget --post-file=/etc/passwd http://...
```

---

## 3. 全局共享目录

### 3.1 当前配置

**可访问的全局目录**：

| 目录 | 权限 | 用途 |
|------|------|------|
| `~/.coapis/skill_pool/` | 读写 | 全局技能池 |
| `/etc/passwd` | 只读 | 用户信息 |
| `/etc/hosts` | 只读 | 主机解析 |
| `/etc/hostname` | 只读 | 主机名 |
| `/etc/resolv.conf` | 只读 | DNS配置 |
| `/usr/share/doc/` | 只读 | 文档目录 |
| `/usr/share/man/` | 只读 | 手册页 |

### 3.2 使用示例

```bash
# ✅ 允许（全局共享目录）
cat /etc/hosts
cat /etc/passwd

# ❌ 拒绝（不在共享目录）
cat /etc/shadow       # 敏感文件
cat /root/.ssh/id_rsa # 私钥文件
```

---

## 4. 常见问题与解决方案

### 问题1：`cat /etc/passwd` 被拒绝

**原因**：早期版本不允许读取系统文件

**解决方案**：
- ✅ **v0.9.12+ 已修复**：添加了 `/etc/passwd` 等到全局共享读取目录
- ✅ 现在可以正常读取

### 问题2：`write_file` 参数格式错误

**错误示例**：
```python
# ❌ 错误：使用绝对路径
write_file("/tmp/report.pdf", "内容")

# ✅ 正确：使用相对路径
write_file("report.pdf", "内容")
```

**解决方案**：使用相对路径，自动解析到 `workspace/files/`

### 问题3：PDF 文件读取权限错误

**错误示例**：
```
AI 使用 read_file 工具读取 PDF → 权限拒绝
```

**解决方案**：
```python
# ❌ 错误：使用 read_file
read_file("report.pdf")  # 有权限检查

# ✅ 正确：使用 doc_reader
doc_reader(file_path="report.pdf")  # 无权限检查
```

**提示**：在聊天中选择 PDF 文件时，系统会自动提示 AI 使用 `doc_reader` 工具

### 问题4：Python 脚本执行被拒绝

**错误示例**：
```bash
# ❌ 拒绝：使用 -c 内联执行
python3 -c "print('hello')"

# ❌ 拒绝：脚本不在 workspace 内
python3 /tmp/script.py
```

**解决方案**：
```bash
# ✅ 允许：脚本在 workspace 内
python3 scripts/app.py

# ✅ 允许：使用相对路径
python3 app.py  # 解析为 workspace/files/app.py
```

---

## 5. 最佳实践

### 5.1 文件操作

✅ **推荐做法**：
1. 使用相对路径（自动解析到 workspace/files/）
2. PDF/Word 文件使用 `doc_reader` 工具
3. 文本文件使用 `read_file` / `write_file` 工具

❌ **不推荐做法**：
1. 使用绝对路径访问系统文件
2. 使用 `read_file` 读取 PDF 文件
3. 访问 workspace 外的文件

### 5.2 Shell 命令

✅ **推荐做法**：
1. 在 workspace 内操作文件
2. 使用相对路径
3. 使用脚本文件模式（`python3 script.py`）

❌ **不推荐做法**：
1. 使用绝对路径访问系统文件
2. 使用内联执行模式（`python3 -c "..."`）
3. 执行危险命令（`rm -rf /` 等）

---

## 6. 角色权限对比

| 功能 | user | advanced | admin |
|------|------|----------|-------|
| 文件浏览 | ✅ | ✅ | ✅ |
| 文件操作 | ✅ | ✅ | ✅ |
| 编程工具 | ✅ 脚本模式 | ✅ 脚本模式 | ✅ 脚本模式 |
| Docker | ❌ | ✅ | ✅ |
| 系统管理 | ❌ | ✅ | ✅ |
| 网络工具 | ✅ | ✅ | ✅ |

**注**：所有角色的危险命令（黑名单）都会被拦截

---

## 7. 获取帮助

如果遇到权限问题：

1. **查看错误信息**：系统会提示具体的拒绝原因
2. **检查路径**：确认是否使用了相对路径
3. **检查工具**：确认是否使用了正确的工具（如 `doc_reader` vs `read_file`）
4. **联系管理员**：如果需要访问特定文件或目录

---

**文档版本**：v1.0  
**最后更新**：2026-07-15
