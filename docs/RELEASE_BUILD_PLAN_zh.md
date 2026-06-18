# CoApis 构建、发布与安装方案

> 分析日期: 2026-06-01
> 当前版本: v0.1.0
> 目标: 最低用户安装成本 + 提供源码安装备选

---

## 1. 现状分析

### 1.1 当前构建体系

| 组件 | 构建方式 | 状态 |
|------|---------|------|
| Server | `docker/Dockerfile.server` (Python 3.12-slim) | ✅ 可用，但 compose 挂载源码 |
| Frontend+Nginx | `docker/Dockerfile.nginx` (node→nginx 多阶段) | ✅ 可用 |
| CI/CD | `.github/workflows/docker-build.yml` → GHCR | ✅ 框架就绪，未配远程 |
| 企业版 | `server/deploy/Dockerfile.enterprise` (旧式) | ⚠️ 引用旧镜像源 |

### 1.2 核心问题

1. **docker-compose.yaml 是开发模式** — 挂载源码卷做热更新，用户无法直接使用
2. **无生产级 docker-compose** — 缺少镜像拉取、数据持久化、首次初始化的完整配置
3. **无一键安装脚本** — 用户需要手动 clone + 配置 .env + docker compose up
4. **Dockerfile.server 缺少前端打包** — 前端需要单独构建，用户需要两个 compose 服务
5. **无 GitHub Release 流程** — 未配置 tag 触发自动构建 + 推送 + Release 创建

---

## 2. 发布方案设计

### 2.1 发布产物

```
GitHub Release v0.1.0
├── coapis-v0.1.0.tar.gz          # 源码包（自动）
├── install.sh                       # 一键安装脚本（核心）
├── docker-compose.yml               # 生产级 compose（内嵌在 install.sh 中生成）
└── checksums.txt                    # SHA256 校验
```

**Docker 镜像（GHCR）**:
```
ghcr.io/coapis/server:1.0       # 后端（含前端静态文件）
ghcr.io/coapis/server:latest
ghcr.io/coapis/nginx:1.0        # Nginx 反代（含前端）
ghcr.io/coapis/nginx:latest
```

### 2.2 用户安装流程（目标）

**Docker 一键安装（推荐）**:
```bash
# 一行命令完成安装
curl -fsSL https://get.coapis.com | bash

# 或手动
wget https://github.com/coapis/coapis/releases/download/v0.1.0/install.sh
chmod +x install.sh
./install.sh
```

**安装脚本自动完成**:
1. 检测 Docker 环境
2. 创建安装目录 `/opt/coapis/`
3. 生成 `.env` 配置（交互式引导 LLM API Key）
4. 下载 `docker-compose.yml`
5. 拉取预构建镜像
6. 启动服务
7. 输出访问地址和初始密码

**源码安装（高级用户）**:
```bash
git clone https://github.com/coapis/coapis.git
cd coapis
cp .env.example .env
# 编辑 .env 填写 API Key
docker compose -f docker-compose.build.yml up -d --build
```

---

## 3. 需要创建/修改的文件

### 3.1 新建: `docker-compose.prod.yml`（生产级 compose）

**设计原则**:
- 使用预构建镜像（`ghcr.io/coapis/server:latest`）
- 不挂载源码卷
- 数据持久化到命名卷
- 自动初始化

```yaml
services:
  server:
    image: ghcr.io/coapis/server:${COAPIS_VERSION:-latest}
    container_name: coapis-server
    ports:
      - "${COAPIS_PORT:-4200}:8000"
    volumes:
      - coapis-data:/data
    env_file:
      - .env
    environment:
      - COAPIS_WORKING_DIR=/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s

volumes:
  coapis-data:
```

> **关键**: 后端镜像内嵌前端静态文件（多阶段构建），Nginx 内嵌于容器内，用户只需一个容器。

### 3.2 修改: `docker/Dockerfile.server`（生产镜像）

**改造要点**:
- 多阶段构建：先编译前端，再打入后端
- 内嵌 Nginx 或由 FastAPI 直接 serve 静态文件
- Playwright chromium 预装（避免运行时下载）
- 不需要 `docker/Dockerfile.nginx` 单独容器

### 3.3 新建: `install.sh`（一键安装脚本）

**功能**:
- 检测 Docker/Docker Compose
- 交互式配置（LLM API Key、端口）
- 下载 docker-compose.yml
- 拉取镜像并启动
- 输出访问信息

### 3.4 修改: `.github/workflows/docker-build.yml`（CI/CD）

**增强**:
- Tag 推送触发（`v*`）
- 构建 server 生产镜像（含前端）
- 推送至 GHCR
- 创建 GitHub Release（含 install.sh）
- 生成 checksums

### 3.5 新建: `docker-compose.build.yml`（源码构建 compose）

**用途**: 高级用户从源码构建

---

## 4. 实施计划

| # | 任务 | 工作量 | 依赖 |
|---|------|--------|------|
| 1 | 改造 Dockerfile.server 为多阶段（前端+后端+Nginx 一体化） | 2h | - |
| 2 | 创建 docker-compose.prod.yml | 30min | #1 |
| 3 | 创建 install.sh 一键安装脚本 | 1h | #2 |
| 4 | 创建 docker-compose.build.yml（源码构建） | 30min | - |
| 5 | 改造 GitHub Actions CI/CD | 1h | #1 |
| 6 | 更新 README.md 安装说明 | 30min | #3 |
| 7 | 本地构建测试 | 1h | #1-4 |
| 8 | 端到端安装测试 | 1h | #3 |

**总计**: ~7 小时

---

## 5. 架构对比

### 方案 A: 一体化容器（推荐 ✅）

```
用户机器
└── coapis-server 容器
    ├── FastAPI (后端 API :8000)
    ├── Nginx (前端静态 :80→用户端口)
    └── 数据卷 (/data)
```

**优点**: 一个容器搞定，安装最简
**缺点**: 容器稍大（~1.5GB，含 Python + Chromium）

### 方案 B: 双容器

```
用户机器
├── coapis-server 容器 (:8000)
└── coapis-nginx 容器 (:80→用户端口)
```

**优点**: 关注点分离
**缺点**: 用户需要管理两个容器，compose 更复杂

**决策**: 采用方案 A（一体化），降低安装成本。

---

## 6. Dockerfile.server 改造方案

```dockerfile
# ── Stage 1: 编译前端 ──
FROM node:20-alpine AS frontend-builder
WORKDIR /build
COPY client/package*.json ./
RUN npm ci
COPY client/ ./
RUN npm run build

# ── Stage 2: Python 后端 ──
FROM python:3.12-slim AS backend-builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential && rm -rf /var/lib/apt/lists/*
COPY server/pyproject.toml server/setup.py ./
COPY server/coapis ./coapis
RUN pip install --no-cache-dir .

# ── Stage 3: 最终运行镜像 ──
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl nginx chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# 复制后端
COPY --from=backend-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=backend-builder /usr/local/bin/coapis /usr/local/bin/coapis
COPY server/coapis /opt/coapis/coapis

# 复制前端到 Nginx 目录
COPY --from=frontend-builder /build/dist /usr/share/nginx/html

# 复制配置
COPY docker/nginx/conf/default.conf /etc/nginx/conf.d/default.conf
COPY docker/init_workspace.sh /usr/local/bin/
COPY server/deploy/entrypoint.sh /usr/local/bin/

# 内嵌启动脚本（同时启动 Nginx + FastAPI）
COPY docker/entrypoint-all-in-one.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/*.sh

ENV COAPIS_HOME=/opt/coapis
ENV PYTHONPATH=/opt/coapis
ENV COAPIS_WORKING_DIR=/data

EXPOSE 80 8000
ENTRYPOINT ["/usr/local/bin/entrypoint-all-in-one.sh"]
```

---

## 7. install.sh 设计

```bash
#!/bin/bash
# CoApis 一键安装脚本
set -e

REPO="coapis/coapis"
INSTALL_DIR="/opt/coapis"
COMPOSE_URL="https://raw.githubusercontent.com/${REPO}/main/docker-compose.prod.yml"

# 1. 检测 Docker
if ! command -v docker &>/dev/null; then
    echo "❌ Docker 未安装。请先安装 Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

# 2. 创建目录
mkdir -p "${INSTALL_DIR}"

# 3. 下载 docker-compose.yml
curl -fsSL "${COMPOSE_URL}" -o "${INSTALL_DIR}/docker-compose.yml"

# 4. 交互式配置
echo "🦀 CoApis 安装向导"
read -p "LLM API Key (如 OpenAI): " API_KEY
read -p "访问端口 [4200]: " PORT
PORT=${PORT:-4200}

cat > "${INSTALL_DIR}/.env" <<EOF
COAPIS_WORKING_DIR=/data
OPENAI_API_KEY=${API_KEY}
COAPIS_PORT=${PORT}
EOF

# 5. 拉取并启动
cd "${INSTALL_DIR}"
docker compose pull
docker compose up -d

# 6. 输出信息
echo ""
echo "✅ CoApis 安装成功！"
echo "🌐 访问: http://localhost:${PORT}"
echo "👤 默认账号: admin / admin123"
echo "📁 安装目录: ${INSTALL_DIR}"
echo ""
echo "常用命令:"
echo "  启动: cd ${INSTALL_DIR} && docker compose up -d"
echo "  停止: cd ${INSTALL_DIR} && docker compose down"
echo "  日志: cd ${INSTALL_DIR} && docker compose logs -f"
echo "  升级: cd ${INSTALL_DIR} && docker compose pull && docker compose up -d"
```

---

## 8. GitHub Actions CI/CD 改造

```yaml
# 触发条件: tag push (v*)
# 步骤:
# 1. 构建 server 生产镜像（含前端）
# 2. 推送至 GHCR (ghcr.io/coapis/server:1.0, :latest)
# 3. 创建 GitHub Release
# 4. 上传 install.sh + docker-compose.prod.yml + checksums
```

---

## 9. 用户安装方式汇总

| 方式 | 命令 | 适用场景 |
|------|------|---------|
| **一键安装** | `curl -fsSL https://get.coapis.com \| bash` | 普通用户 |
| **手动 Docker** | 下载 compose + .env → `docker compose up -d` | 有经验用户 |
| **源码 Docker** | `git clone` → `docker compose -f docker-compose.build.yml up` | 开发者/定制需求 |
| **源码本地** | `pip install -e .` + `npm run build` + 手动启动 | 贡献者 |

---

*文档生成: 2026-06-01*
