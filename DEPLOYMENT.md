# CoApis 部署文档

## 🚀 一键部署（推荐）

### 最新版本

```bash
# 下载 docker-compose.yml
wget https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/docker-compose.yml

# 启动服务（自动拉取 latest 镜像）
docker compose up -d

# 访问服务
# 地址：http://localhost:4208
# 账号：admin / admin123
```

### 指定版本

```bash
# 设置镜像版本（与 GitHub tag 同步）
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11

# 启动服务
docker compose up -d
```

### 镜像版本说明

| 镜像标签 | 说明 | 用途 |
|---------|------|------|
| `latest` | 最新正式版本 | 推荐生产使用 |
| `v0.9.11` | 指定版本 | 生产环境固定版本 |
| `dev` | 开发版本 | 每次推送到 main 自动构建 |

**查看所有版本**：[GitHub Packages](https://github.com/coapis-ai/coapis-agent/pkgs/container/server)

---

## 📦 部署方式

### 方式一：一键部署（最简单 ⭐）

```bash
# 下载并启动
wget https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/docker-compose.yml
docker compose up -d
```

**优点**：
- ✅ 一行命令完成部署
- ✅ 自动拉取最新镜像
- ✅ 无需配置文件

**适用场景**：快速体验、测试环境

---

### 方式二：指定版本部署（推荐生产 ⭐）

```bash
# 1. 下载配置文件
wget https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/docker-compose.yml
wget https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/.env.example -O .env

# 2. 指定版本
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11

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
| `COAPIS_IMAGE` | Docker 镜像版本 | `ghcr.io/coapis-ai/coapis-agent/server:latest` |
| `COAPIS_SERVER_PORT` | API 服务端口 | `4208` |
| `COAPIS_WORKING_DIR` | 数据目录 | `/apps/ai/coapis` |

### 完整配置

参考 `.env.example` 文件：

```bash
# 镜像配置
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

### 升级到最新版本

```bash
# 拉取最新镜像
docker compose pull

# 重启服务
docker compose up -d
```

### 升级到指定版本

```bash
# 设置新版本
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.12

# 拉取并重启
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

### 1. 端口被占用

修改 `.env` 中的 `COAPIS_SERVER_PORT`：

```bash
export COAPIS_SERVER_PORT=8080
docker compose up -d
```

### 2. 容器无法启动

查看日志：

```bash
docker compose logs -f server
```

### 3. 镜像拉取失败

检查网络连接，或使用国内镜像源：

```bash
# 使用阿里云镜像加速
export COAPIS_IMAGE=registry.cn-hangzhou.aliyuncs.com/coapis/server:latest
```

### 4. 权限问题

确保数据目录权限正确：

```bash
mkdir -p ${COAPIS_WORKING_DIR:-/apps/ai/coapis}
chmod 755 ${COAPIS_WORKING_DIR:-/apps/ai/coapis}
```

---

## 版本发布说明

**自动构建规则**：

- ✅ **推送代码到 main** → 自动构建 `:dev` 镜像
- ✅ **打 tag（如 v0.9.11）** → 自动构建 `:v0.9.11` 和 `:latest` 镜像
- ✅ **镜像地址**：`ghcr.io/coapis-ai/coapis-agent/server`

**版本号规范**：

- 使用语义化版本：`MAJOR.MINOR.PATCH`
- 例如：`v0.9.11`、`v1.0.0`
- 与 GitHub tag 完全同步
