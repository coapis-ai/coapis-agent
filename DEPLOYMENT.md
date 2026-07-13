# CoApis 部署文档

## 🚀 一键安装（推荐）

### 使用安装脚本

**最简单的部署方式**：

```bash
# 默认版本（v0.9.11）
curl -fsSL https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/install.sh | bash

# 指定版本
COAPIS_VERSION=v0.9.12 curl -fsSL https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/install.sh | bash

# 访问服务
# 地址：http://localhost:4208
# 账号：admin / admin123
```

### 安装脚本功能

- ✅ 自动检测并安装 Docker
- ✅ 自动下载配置文件（docker-compose.yml、.env）
- ✅ 自动拉取镜像并启动服务
- ✅ 支持多种安装模式：
  - `bash -s -- --source` - 源码构建
  - `bash -s -- --with-playwright` - 包含浏览器服务
  - `bash -s -- --update` - 更新到新版本
  - `bash -s -- --uninstall` - 卸载

### 安装脚本选项

```bash
bash install.sh [选项]

选项:
  (无参数)          标准安装（默认版本: v0.9.11）
  COAPIS_VERSION=v1.0.0 bash install.sh  指定版本
  --source          源码构建模式
  --with-playwright 包含浏览器自动化服务
  --update          更新到新版本
  --uninstall       卸载
```

---

## 📦 手动部署

### 查看可用版本

访问：https://github.com/coapis-ai/coapis-agent/pkgs/container/server

### 部署步骤

```bash
# 1. 设置镜像版本（必填，与 GitHub tag 同步）
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.12

# 2. 下载 docker-compose.yml
wget https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/docker-compose.yml

# 3. 启动服务
docker compose up -d

# 4. 访问服务
# 地址：http://localhost:4208
# 账号：admin / admin123
```

---

## 📦 部署方式对比

### 方式一：一键安装（最简单 ⭐）

```bash
curl -fsSL https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/install.sh | bash
```

**优点**：
- ✅ 全自动安装，无需手动配置
- ✅ 自动检测并安装 Docker
- ✅ 支持指定版本
- ✅ 支持多种安装模式

**适用场景**：快速体验、测试环境、生产环境

---

### 方式二：手动部署（推荐生产 ⭐）

```bash
# 1. 下载配置文件
wget https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/.env.example -O .env

# 2. 指定版本（必填）
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.12

# 3. 编辑配置（可选）
nano .env

# 4. 启动
docker compose up -d
```

**优点**：
- ✅ 版本可控（与 GitHub tag 同步）
- ✅ 支持自定义配置
- ✅ 生产环境推荐

**适用场景**：生产环境、企业部署

---

### 方式三：源码构建（开发者）

```bash
git clone https://github.com/coapis-ai/coapis-agent.git
cd coapis-agent/docker
cp .env.example .env
nano .env  # 填写 API Key
docker compose -f docker-compose.build.yml up -d --build
```

**适用场景**：开发测试、自定义修改

---

## 环境变量配置

### 核心配置

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `COAPIS_IMAGE` | Docker 镜像版本 | **必填** |
| `COAPIS_SERVER_PORT` | API 服务端口 | `4208` |
| `COAPIS_WORKING_DIR` | 数据目录 | `/apps/ai/coapis` |

### 完整配置

参考 `.env.example` 文件：

```bash
# 镜像配置（必填）
# 查看可用版本: https://github.com/coapis-ai/coapis-agent/pkgs/container/server
COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11

# 端口配置
COAPIS_SERVER_PORT=4208

# 数据目录
COAPIS_WORKING_DIR=/apps/ai/coapis
COAPIS_WORKSPACES_DIR=${COAPIS_WORKING_DIR}/workspaces

# 其他配置
LOG_LEVEL=INFO
TZ=Asia/Shanghai
```

---

## 访问服务

- **地址**：`http://<server-ip>:4208`
- **默认管理员**：`admin` / `admin123`
- ⚠️ **首次登录后请立即修改默认密码**

---

## 升级

### 升级到新版本

```bash
# 1. 设置新版本
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.12

# 2. 拉取并重启
docker compose pull
docker compose up -d
```

---

## 数据备份

所有数据存储在 `COAPIS_WORKING_DIR` 目录中。

```bash
# 备份
tar czf coapis-backup-$(date +%Y%m%d).tar.gz ${COAPIS_WORKING_DIR:-/apps/ai/coapis}

# 恢复
tar xzf coapis-backup-YYYYMMDD.tar.gz -C /
```

---

## 常见问题

### 1. 未设置镜像版本

**错误信息**：
```
ERROR: required variable COAPIS_IMAGE is missing a value
```

**解决方法**：
```bash
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11
docker compose up -d
```

### 2. 端口被占用

修改 `COAPIS_SERVER_PORT`：

```bash
export COAPIS_SERVER_PORT=8080
docker compose up -d
```

### 3. 容器无法启动

查看日志：

```bash
docker compose logs -f server
```

### 4. 镜像拉取失败

检查网络连接，或使用国内镜像源：

```bash
# 使用阿里云镜像加速
export COAPIS_IMAGE=registry.cn-hangzhou.aliyuncs.com/coapis/server:v0.9.11
```

### 5. 权限问题

确保数据目录权限正确：

```bash
mkdir -p ${COAPIS_WORKING_DIR:-/apps/ai/coapis}
chmod 755 ${COAPIS_WORKING_DIR:-/apps/ai/coapis}
```

---

## 版本发布说明

### 自动构建规则

**开发版本**（每次推送到 main）：
- ✅ 格式：`dev-YYYYMMDD-{commit_sha}`
- ✅ 示例：`dev-20260713-abc1234`
- ✅ 包含最新功能
- ⚠️ 可能不稳定，仅供测试

**正式版本**（打 tag）：
- ✅ 格式：`v主版本.次版本.补丁版本`
- ✅ 示例：`v0.9.11`、`v1.0.0`
- ✅ 与 GitHub tag 完全同步
- ✅ 推荐生产使用

### 版本号规范

- 使用语义化版本：`MAJOR.MINOR.PATCH`
- 例如：`v0.9.11`、`v1.0.0`
- 与 GitHub tag 完全同步

### 查看可用版本

访问：https://github.com/coapis-ai/coapis-agent/pkgs/container/server
