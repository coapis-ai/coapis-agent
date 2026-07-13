# CoApis 快速部署指南

## 🚀 一键部署

### 最简单的方式（推荐）

```bash
# 1. 下载 docker-compose.yml
wget https://raw.githubusercontent.com/coapis-ai/coapis-agent/main/docker-compose.yml

# 2. 启动服务
docker compose up -d

# 3. 访问服务
# 地址：http://localhost:4208
# 账号：admin / admin123
```

---

## 📌 指定版本部署（生产推荐）

### 查看可用版本

访问：https://github.com/coapis-ai/coapis-agent/pkgs/container/server

### 部署指定版本

```bash
# 设置版本号（与 GitHub tag 同步）
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.11

# 启动服务
docker compose up -d
```

---

## 🔄 升级版本

### 升级到最新版

```bash
docker compose pull
docker compose up -d
```

### 升级到指定版本

```bash
export COAPIS_IMAGE=ghcr.io/coapis-ai/coapis-agent/server:v0.9.12
docker compose pull
docker compose up -d
```

---

## 📝 版本说明

| 镜像标签 | 说明 | 更新频率 |
|---------|------|---------|
| `latest` | 最新正式版本 | 打 tag 时更新 |
| `v0.9.11` | 指定版本 | 不变 |
| `dev` | 开发版本 | 每次 push 到 main |

---

## 🔗 自动构建规则

**触发条件**：
- ✅ 推送代码到 `main` 分支 → 自动构建 `:dev` 镜像
- ✅ 打 tag（如 `v0.9.11`）→ 自动构建 `:v0.9.11` 和 `:latest` 镜像

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
