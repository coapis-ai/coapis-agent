# CoApis 快速部署指南

## 🚀 一键部署

### 查看可用版本

访问：https://github.com/coapis-ai/coapis-agent/pkgs/container/server

### 部署步骤

```bash
# 1. 设置镜像版本（必填，与 GitHub tag 同步）
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11

# 2. 下载 docker-compose.yml
wget https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/docker-compose.yml

# 3. 启动服务
docker compose up -d

# 4. 访问服务
# 地址：http://localhost:4208
# 账号：admin / admin123
```

---

## 📌 版本说明

### 正式版本（推荐生产）

```bash
# 格式: v主版本.次版本.补丁版本
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11
```

- ✅ 与 GitHub tag 完全同步
- ✅ 经过测试的稳定版本
- ✅ 生产环境推荐使用

### 开发版本

```bash
# 格式: dev-YYYYMMDD-{commit_sha}
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:dev-20260713-abc1234
```

- ✅ 每次推送到 main 自动构建
- ✅ 包含最新功能
- ⚠️ 可能不稳定，仅供测试

---

## 🔄 升级版本

### 升级到新版本

```bash
# 1. 设置新版本
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.12

# 2. 拉取并重启
docker compose pull
docker compose up -d
```

---

## 🔗 自动构建规则

**触发条件**：
- ✅ 推送代码到 `main` 分支 → 自动构建 `dev-YYYYMMDD-{sha}` 镜像
- ✅ 打 tag（如 `v0.9.11`）→ 自动构建 `v0.9.11` 和 `v0.9` 镜像

**镜像地址**：
```
ghcr.io/coapis-ai/coapis-agent/server
```

---

## ⚙️ 完整配置（可选）

```bash
# 下载配置文件
wget https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/.env.example -O .env

# 编辑配置
nano .env

# 启动
docker compose up -d
```

---

## 🆘 常见问题

### 未设置镜像版本

```bash
# 错误信息
ERROR: required variable COAPIS_IMAGE is missing a value

# 解决方法
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11
docker compose up -d
```

### 端口被占用

```bash
export COAPIS_SERVER_PORT=8080
docker compose up -d
```

### 查看日志

```bash
docker compose logs -f server
```

### 停止服务

```bash
docker compose down
```

---

**完整文档**：[DEPLOYMENT.md](./DEPLOYMENT.md)
