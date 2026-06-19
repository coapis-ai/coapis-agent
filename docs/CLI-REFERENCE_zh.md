# CoApis CLI 命令参考

本文档提供 CoApis 命令行工具的完整参考。

## 目录

- [系统初始化](#系统初始化)
- [管理命令](#管理命令)
- [开发命令](#开发命令)
- [故障排除](#故障排除)

---

## 系统初始化

### coapis init

初始化工作区和配置文件。

```bash
coapis init [OPTIONS]
```

**选项**：

| 参数 | 说明 |
|------|------|
| `--force` | 覆盖已存在的配置文件和 HEARTBEAT.md |
| `--defaults` | 使用默认值，不进行交互式提示（适用于脚本） |
| `--accept-security` | 跳过安全确认（与 `--defaults` 配合用于 Docker） |
| `-h, --help` | 显示帮助信息 |

**使用示例**：

```bash
# 交互式初始化（推荐首次使用）
coapis init

# 非交互式初始化（适用于自动化脚本）
coapis init --defaults --accept-security

# 强制重新初始化
coapis init --force

# 组合使用
coapis init --defaults --accept-security --force
```

### 在生产容器中运行

```bash
# 进入容器
docker exec -it coapis-server-prod bash

# 运行初始化
coapis init --defaults --accept-security

# 或者直接在宿主机执行
docker exec coapis-server-prod coapis init --defaults --accept-security
```

### Python 初始化器

```bash
# 通过 Python 直接调用（在容器内）
python3 -c "
from coapis.system import initialize_system
result = initialize_system()
print(result)
"

# 检查初始化状态
python3 -c "
from coapis.system import check_system_status
import json
print(json.dumps(check_system_status(), indent=2))
"
```

---

## 管理命令

### coapis auth

管理 Web 认证。

```bash
coapis auth [OPTIONS] COMMAND [ARGS]...
```

**子命令**：

| 命令 | 说明 |
|------|------|
| `coapis auth status` | 查看认证状态 |
| `coapis auth enable` | 启用认证 |
| `coapis auth disable` | 禁用认证 |

### coapis admin

管理员系统工具（低频操作）。

```bash
coapis admin [OPTIONS] COMMAND [ARGS]...
```

### coapis models

管理 LLM 模型和提供商配置。

```bash
coapis models [OPTIONS] COMMAND [ARGS]...
```

**子命令**：

| 命令 | 说明 |
|------|------|
| `coapis models list` | 列出所有模型 |
| `coapis models add` | 添加模型配置 |
| `coapis models remove` | 移除模型配置 |

### coapis channels

管理频道配置。

```bash
coapis channels [OPTIONS] COMMAND [ARGS]...
```

**子命令**：

| 命令 | 说明 |
|------|------|
| `coapis channels list` | 列出所有频道 |
| `coapis channels add` | 添加频道配置 |
| `coapis channels remove` | 移除频道配置 |

### coapis cron

管理定时任务。

```bash
coapis cron [OPTIONS] COMMAND [ARGS]...
```

**子命令**：

| 命令 | 说明 |
|------|------|
| `coapis cron list` | 列出所有定时任务 |
| `coapis cron add` | 添加定时任务 |
| `coapis cron remove` | 移除定时任务 |
| `coapis cron enable` | 启用定时任务 |
| `coapis cron disable` | 禁用定时任务 |

### coapis agent

管理智能体和智能体间通信。

```bash
coapis agent [OPTIONS] COMMAND [ARGS]...
```

### coapis agents

管理智能体和智能体间通信（别名）。

```bash
coapis agents [OPTIONS] COMMAND [ARGS]...
```

---

## 开发命令

### coapis app

运行 CoApis FastAPI 应用。

```bash
coapis app [OPTIONS]
```

**选项**：

| 参数 | 说明 |
|------|------|
| `--host TEXT` | API 主机地址 |
| `--port INTEGER` | API 端口号 |
| `-h, --help` | 显示帮助信息 |

### coapis daemon

守护进程命令。

```bash
coapis daemon [OPTIONS] COMMAND [ARGS]...
```

**子命令**：

| 命令 | 说明 |
|------|------|
| `coapis daemon status` | 查看守护进程状态 |
| `coapis daemon restart` | 重启守护进程 |
| `coapis daemon reload-config` | 重新加载配置 |
| `coapis daemon version` | 查看版本信息 |
| `coapis daemon logs` | 查看日志 |

### coapis doctor

本地健康检查。

```bash
coapis doctor [OPTIONS]
```

### coapis clean

清理 CoApis WORKING_DIR（默认为 ~/.coapis）。

```bash
coapis clean [OPTIONS]
```

### coapis env

管理环境变量。

```bash
coapis env [OPTIONS] COMMAND [ARGS]...
```

### coapis plugin

插件管理命令。

```bash
coapis plugin [OPTIONS] COMMAND [ARGS]...
```

---

## 故障排除

### 常见问题

**Q: coapis 命令未找到**

A: 确保已正确安装 CoApis 并将可执行文件路径添加到 PATH。

**Q: 初始化失败**

A: 检查目录权限，确保 CoApis 有写入权限。

**Q: 无法连接到 LLM 服务**

A: 检查 `COAPIS_LLM_BASE_URL` 配置是否正确，确保 CoApis 可以访问 LLM 服务。

### 查看日志

```bash
# 查看所有容器日志
docker compose logs -f

# 查看后端日志
docker compose logs -f server

# 查看 Nginx 日志
docker compose logs -f nginx
```

---

**相关文档**：
- [安装指南](./installation.md)
- [配置指南](./help/03-配置指南_zh.md)
- [API 参考](./API-REFERENCE_zh.md)
