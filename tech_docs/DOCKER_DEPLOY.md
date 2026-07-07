# CoApis Docker 部署指南

> **版本**: v0.9.5  
> **更新时间**: 2026-07-07  
> **适用场景**: 发布镜像构建、从零环境验证、生产部署

---

## 一、核心原则

**一份 docker-compose.yml，通过 `.env` 区分环境。**

```
docker/
├── docker-compose.yml      ← 唯一的 compose 文件，所有环境共用
├── .env                    ← 环境变量（端口、数据目录、版本号等）
├── docker-compose.dev.yaml ← 仅 dev 环境使用（源码挂载、热更新）
└── nginx/conf/default.conf ← Nginx 配置
```

**不允许：**
- 为每个版本单独写一份 docker-compose.yml
- 在 compose 文件中硬编码路径、端口、版本号
- 发布目录中复制一份独立的 compose 文件

---

## 二、镜像构建

### 2.1 构建上下文

```
项目根目录/
├── server/deploy/Dockerfile      ← 构建文件
├── server/coapis/                ← Python 包（复制进镜像）
├── server/pyproject.toml         ← 包定义
├── server/setup.py               ← 安装脚本
├── client/dist/                  ← 前端静态文件（构建前须先 npm run build）
└── server/deploy/entrypoint.sh   ← 容器入口脚本
```

### 2.2 构建命令

```bash
cd <项目根目录>

# 构建并打版本 tag（版本号从 .env 读取，或手动指定）
docker build -f server/deploy/Dockerfile \
  -t coapis-server:<版本号> \
  -t coapis-server:latest \
  .
```

### 2.3 前置条件

| 项目 | 要求 |
|------|------|
| 前端产物 | `client/dist/` 必须存在（`npm run build` 生成） |
| Dockerfile | `server/deploy/Dockerfile` |
| 构建上下文 | 项目根目录（Dockerfile 中 `COPY` 使用相对路径） |

### 2.4 镜像导出

```bash
# 导出为压缩包（用于离线分发）
docker save coapis-server:<版本号> | gzip > coapis-server-<版本号>.tar.gz

# 导入（目标机器）
docker load < coapis-server-<版本号>.tar.gz
```

---

## 三、环境变量（`.env`）

`.env` 文件是区分环境的**唯一手段**。不同环境/版本只改 `.env`，不改 `docker-compose.yml`。

### 3.1 生产环境 `.env` 示例

```bash
# ═══════════════════════════════════════════════
# CoApis 生产环境
# ═══════════════════════════════════════════════

COAPIS_VERSION=0.9.5
COAPIS_WORKING_DIR=/apps/ai/coapis
COAPIS_WORKSPACES_DIR=${COAPIS_WORKING_DIR}/workspaces

# 端口
COAPIS_WEB_PORT=4200
COAPIS_SERVER_PORT=4208
COAPIS_PLAYWRIGHT_PORT=4201
```

### 3.2 版本验证环境 `.env` 示例

```bash
# ═══════════════════════════════════════════════
# CoApis v0.9.5 — 独立验证环境
# ═══════════════════════════════════════════════

COAPIS_VERSION=0.9.5
COAPIS_WORKING_DIR=/apps/ai/coapis-pubs/v0.9.5/data
COAPIS_WORKSPACES_DIR=${COAPIS_WORKING_DIR}/workspaces

# 端口（与生产环境错开）
COAPIS_WEB_PORT=4700
COAPIS_SERVER_PORT=4701
COAPIS_PLAYWRIGHT_PORT=4702

# 无 LLM 验证
COAPIS_SKIP_PROVIDERS=1
```

### 3.3 环境变量说明

| 变量 | 说明 | 生产默认值 |
|------|------|-----------|
| `COAPIS_VERSION` | 版本号（entrypoint 写入容器） | `0.9.5` |
| `COAPIS_WORKING_DIR` | 数据目录（挂载到容器内同路径） | `/apps/ai/coapis` |
| `COAPIS_WORKSPACES_DIR` | 工作空间目录 | `${COAPIS_WORKING_DIR}/workspaces` |
| `COAPIS_WEB_PORT` | Nginx 对外端口 | `4200` |
| `COAPIS_SERVER_PORT` | API Server 对外端口 | `4208` |
| `COAPIS_PLAYWRIGHT_PORT` | Playwright CDP 对外端口 | `4201` |
| `COAPIS_SKIP_PROVIDERS` | 跳过 LLM 配置（`1` = 跳过） | 不设置 |

### 3.4 端口分配规范

| 环境 | Web | API | Playwright | 说明 |
|------|-----|-----|------------|------|
| 生产 | 4200 | 4208 | 4201 | 正式环境 |
| Dev | 4300 | 4308 | 4301 | 开发环境（源码挂载） |
| v0.9.x 验证 | 4700 | 4701 | 4702 | 版本验证（4700-4799 区间） |

---

## 四、docker-compose.yml（唯一模板）

生产环境和版本验证环境**共用同一个文件** `docker/docker-compose.yml`：

```yaml
# ═══════════════════════════════════════════════════════════════════
# CoApis Docker Compose（server + nginx + playwright）
# 用法: cd docker && docker compose up -d
# 说明: 所有环境变量从 .env 读取，compose 文件中不硬编码任何值
# ═══════════════════════════════════════════════════════════════════

name: coapis-prod

services:
  server:
    image: coapis-server:latest
    container_name: coapis-server
    ports:
      - "${COAPIS_SERVER_PORT:-4208}:8000"
    volumes:
      - ${COAPIS_WORKING_DIR}:${COAPIS_WORKING_DIR}
      - ./volume/playwright:/app/volume/playwright:ro
      - ./volume/mcp:/root/.cache/pip
    env_file:
      - .env
    environment:
      - COAPIS_WORKING_DIR=${COAPIS_WORKING_DIR}
      - COAPIS_WORKSPACES_DIR=${COAPIS_WORKSPACES_DIR:-${COAPIS_WORKING_DIR}/workspaces}
      - BROWSER_CDP_URL=http://playwright:3000
      - PIP_CACHE_DIR=/root/.cache/pip
    restart: unless-stopped
    networks:
      - frontend
      - internal
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  nginx:
    image: nginx:alpine
    container_name: coapis-nginx
    ports:
      - "${COAPIS_WEB_PORT:-4200}:80"
    volumes:
      - ./nginx/conf/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ../client/dist:/usr/share/nginx/html:ro
    depends_on:
      server:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - frontend
      - internal

  playwright:
    image: browserless/chrome:latest
    container_name: coapis-playwright
    expose:
      - "3000"
    ports:
      - "${COAPIS_PLAYWRIGHT_PORT:-4201}:3000"
    shm_size: "2g"
    environment:
      - MAX_CONCURRENT_SESSIONS=5
      - MAX_QUEUE_LENGTH=10
    restart: unless-stopped
    networks:
      - internal
      - frontend

networks:
  frontend:
    driver: bridge
  internal:
    internal: true
```

**关键设计：**
- 镜像 tag 用 `latest`（构建时 `docker tag coapis-server:<版本号> coapis-server:latest`）
- 容器名不包含版本号（避免每次版本升级都要改 compose 文件）
- 所有可变值都通过 `${变量:-默认值}` 引用 `.env`

---

## 五、版本发布目录规范

每个版本的发布产物统一存放在 `/apps/ai/coapis-pubs/<版本号>/` 下，**完全自包含**：

```
/apps/ai/coapis-pubs/
└── v0.9.5/
    ├── docker/
    │   ├── docker-compose.yml      ← 从 docker/ 复制（内容完全一致）
    │   ├── .env                    ← 定制：版本号、数据目录、端口
    │   └── nginx/conf/default.conf ← 从 docker/nginx/ 复制
    ├── data/                       ← 首次运行自动生成
    ├── images/
    │   └── coapis-server-v0.9.5.tar.gz
    └── logs/
```

**关键：发布目录中的 `docker-compose.yml` 与生产环境的 `docker-compose.yml` 内容完全相同**，只通过 `.env` 中的不同值区分环境。发布目录不需要修改 compose 文件，只需复制一份即可。

---

## 六、从零部署流程

### 6.1 生产环境部署

```bash
# 1. 构建镜像
cd <项目根目录>
docker build -f server/deploy/Dockerfile \
  -t coapis-server:v0.9.5 \
  -t coapis-server:latest .

# 2. 确认 .env 配置
cat docker/.env
# COAPIS_VERSION=0.9.5
# COAPIS_WORKING_DIR=/apps/ai/coapis
# COAPIS_SERVER_PORT=4208
# ...

# 3. 启动
cd docker && docker compose up -d

# 4. 验证
docker ps                           # 全部 healthy
curl http://localhost:4208/api/health  # status: ready
```

### 6.2 版本验证环境部署

```bash
# 1. 创建发布目录（完整结构）
mkdir -p /apps/ai/coapis-pubs/v0.9.5/{docker/nginx/conf,data,images,logs}

# 2. 复制 compose 文件和 nginx 配置（与生产环境完全一致）
cp docker/docker-compose.yml /apps/ai/coapis-pubs/v0.9.5/docker/
cp docker/nginx/conf/default.conf /apps/ai/coapis-pubs/v0.9.5/docker/nginx/conf/

# 3. 创建验证环境的 .env（与生产不同的值）
cat > /apps/ai/coapis-pubs/v0.9.5/docker/.env << 'EOF'
COAPIS_VERSION=0.9.5
COAPIS_WORKING_DIR=/apps/ai/coapis-pubs/v0.9.5/data
COAPIS_WORKSPACES_DIR=/apps/ai/coapis-pubs/v0.9.5/data/workspaces
COAPIS_WEB_PORT=4700
COAPIS_SERVER_PORT=4701
COAPIS_PLAYWRIGHT_PORT=4702
COAPIS_SKIP_PROVIDERS=1
EOF

# 4. 导入镜像
docker load < coapis-server-v0.9.5.tar.gz
docker tag coapis-server:v0.9.5 coapis-server:latest

# 5. 启动
cd /apps/ai/coapis-pubs/v0.9.5/docker
docker compose up -d

# 6. 验证
docker ps --filter name=coapis --format '{{.Names}} {{.Status}}'
curl http://localhost:4701/api/health
```

### 6.3 多版本并行

通过 `.env` 中的不同端口和数据目录实现并行：

| 版本 | 数据目录 | 端口 |
|------|---------|------|
| 生产 | `/apps/ai/coapis` | 4200/4208/4201 |
| Dev | `/apps/ai/coapis-dev` | 4300/4308/4301 |
| v0.9.5 验证 | `/apps/ai/coapis-pubs/v0.9.5/data` | 4700/4701/4702 |
| v0.9.6 验证 | `/apps/ai/coapis-pubs/v0.9.6/data` | 4710/4711/4712 |

每个版本目录中的 `docker-compose.yml` 内容完全一致，仅 `.env` 不同。

---

## 七、验证清单

每次发布前，按以下清单逐项验证：

| # | 验证项 | 命令 | 预期结果 |
|---|--------|------|---------|
| 1 | 容器状态 | `docker ps \| grep coapis` | 全部 healthy |
| 2 | API Health | `curl http://localhost:<API端口>/api/health` | `status: ready` |
| 3 | Web 界面 | `curl http://localhost:<Web端口>/` | HTTP 200 |
| 4 | 版本号 | `docker exec <容器> env \| grep COAPIS_VERSION` | 正确版本 |
| 5 | 数据独立 | 检查 `COAPIS_WORKING_DIR` 下的文件 | 独立于其他环境 |
| 6 | 日志无泄露 | `docker logs <容器> \| grep -E '/apps/ai/coapis[^-]\|eaterclaw'` | 无匹配 |

---

## 八、运维命令

```bash
# 查看日志
docker logs -f coapis-server

# 重启服务
cd docker && docker compose restart

# 停止并清理
docker compose down

# 停止并删除数据（慎用）
docker compose down -v
rm -rf ${COAPIS_WORKING_DIR}

# 进入容器调试
docker exec -it coapis-server bash

# 更新镜像后重建
docker compose down
docker compose up -d
```

---

## 九、目录结构说明

### 宿主机目录

| 路径 | 用途 | 需要备份 |
|------|------|---------|
| `docker/` | 配置文件 | ✅ 是 |
| `data/` | 运行时数据（自动创建） | ✅ 是 |
| `images/` | 镜像包归档 | 可选 |

### 容器内目录

| 路径 | 说明 |
|------|------|
| `/app/coapis/` | Python 包代码 |
| `/app/coapis/console/` | 前端静态文件 |
| `${COAPIS_WORKING_DIR}` | 数据目录（挂载自宿主机） |
| `/usr/local/bin/entrypoint.sh` | 入口脚本 |
