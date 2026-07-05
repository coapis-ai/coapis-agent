# CoApis Docker 部署指南

> **版本**: v0.9.3  
> **更新时间**: 2026-07-05  
> **适用场景**: 发布镜像构建、从零环境验证、生产部署

---

## 一、镜像构建

### 1.1 构建上下文

```
项目根目录/
├── server/deploy/Dockerfile      ← 构建文件
├── server/coapis/                ← Python 包（复制进镜像）
├── server/pyproject.toml         ← 包定义
├── server/setup.py               ← 安装脚本
├── client/dist/                  ← 前端静态文件（构建前须先 npm run build）
└── server/deploy/entrypoint.sh   ← 容器入口脚本
```

### 1.2 构建命令

```bash
cd <项目根目录>

# 构建并打版本 tag
docker build -f server/deploy/Dockerfile \
  -t coapis-server:<版本号> \
  -t coapis-server:latest \
  .
```

### 1.3 前置条件

| 项目 | 要求 |
|------|------|
| 前端产物 | `client/dist/` 必须存在（`npm run build` 生成） |
| Dockerfile | `server/deploy/Dockerfile` |
| 构建上下文 | 项目根目录（Dockerfile 中 `COPY` 使用相对路径） |

### 1.4 镜像导出

```bash
# 导出为压缩包（用于离线分发）
docker save coapis-server:<版本号> | gzip > coapis-server-<版本号>.tar.gz

# 导入（目标机器）
docker load < coapis-server-<版本号>.tar.gz
```

---

## 二、版本发布目录规范

每个版本的发布产物统一存放在 `/apps/ai/coapis-pubs/<版本号>/` 下：

```
/apps/ai/coapis-pubs/
└── v0.9.3/                           ← 版本号子目录
    ├── docker/                        ← 用户部署所需的全部配置
    │   ├── docker-compose.yml         ← 服务编排
    │   ├── .env                       ← 环境变量（端口、数据目录等）
    │   └── nginx/conf/default.conf    ← Nginx 反向代理配置
    ├── data/                          ← 首次运行自动生成（无需手动创建）
    │   ├── config.json                ← 全局配置
    │   ├── system/                    ← 系统配置（权限、用户、审计等）
    │   ├── workspaces/                ← 智能体工作空间
    │   ├── agents/                    ← 智能体配置
    │   ├── skill_pool/                ← 技能池
    │   └── ...
    ├── images/                        ← 镜像包归档
    │   └── coapis-server-v0.9.3.tar.gz
    └── logs/                          ← 可选，挂载日志
```

**原则：** `docker/` 目录自包含，用户只需拿到 `docker/` + 镜像即可部署。

---

## 三、环境变量说明

### 3.1 `.env` 文件（放在 `docker/` 目录下）

```bash
# ═══════════════════════════════════════════════
# CoApis 版本号 — 独立验证环境
# ═══════════════════════════════════════════════

# 数据目录（完全独立，不同版本/环境使用不同路径）
COAPIS_WORKING_DIR=/apps/ai/coapis-pubs/v0.9.3/data

# 端口分配（根据实际环境调整）
COAPIS_WEB_PORT=4700
COAPIS_SERVER_PORT=4701
COAPIS_PLAYWRIGHT_PORT=4702

# 容器名前缀（避免多版本/多环境冲突）
COMPOSE_PROJECT_NAME=coapis-v093
```

### 3.2 容器内环境变量（在 `docker-compose.yml` 的 `environment` 中设置）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `COAPIS_WORKING_DIR` | 数据目录 | `/opt/coapis` |
| `COAPIS_SKIP_PROVIDERS` | 跳过 LLM 配置（`1` = 跳过） | 不设置 |
| `BROWSER_CDP_URL` | Playwright CDP 地址 | `http://playwright:9223` |
| `COAPIS_VERSION` | 服务版本号（写入镜像） | `0.0.0-dev` |

### 3.3 端口分配规范

| 服务 | 端口变量 | 默认值 | 说明 |
|------|---------|--------|------|
| Web UI（Nginx） | `COAPIS_WEB_PORT` | 4700 | 用户访问入口 |
| API Server | `COAPIS_SERVER_PORT` | 4701 | 后端 API |
| Playwright CDP | `COAPIS_PLAYWRIGHT_PORT` | 4702 | 浏览器自动化 |

**多环境并行时**，不同版本使用不同端口区间（如 v0.9.3 用 4700-4702，v0.9.4 用 4710-4712）。

---

## 四、docker-compose.yml 模板

```yaml
name: coapis-v093                        # 与 COMPOSE_PROJECT_NAME 一致

services:
  server:
    image: coapis-server:v0.9.3          # 使用版本 tag
    container_name: coapis-v093-server   # 包含版本标识
    ports:
      - "${COAPIS_SERVER_PORT:-4701}:8000"
    volumes:
      - ${COAPIS_WORKING_DIR}:${COAPIS_WORKING_DIR}   # 数据目录挂载
    env_file:
      - .env                               # 从 docker/ 同目录加载
    environment:
      - COAPIS_WORKING_DIR=${COAPIS_WORKING_DIR}
      - COAPIS_SKIP_PROVIDERS=1            # 无 LLM 环境设为 1
      - BROWSER_CDP_URL=http://playwright:9223
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
    container_name: coapis-v093-nginx
    ports:
      - "${COAPIS_WEB_PORT:-4700}:80"
    volumes:
      - ./nginx/conf/default.conf:/etc/nginx/conf.d/default.conf:ro
      - <项目根目录>/client/dist:/usr/share/nginx/html:ro  # 前端静态文件
    depends_on:
      server:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - frontend
      - internal

  playwright:
    image: chromedp/headless-shell:latest
    container_name: coapis-v093-playwright
    expose:
      - "9223"
    ports:
      - "${COAPIS_PLAYWRIGHT_PORT:-4702}:9223"
    shm_size: "2g"
    restart: unless-stopped
    networks:
      - internal
    healthcheck:
      test: ["CMD-SHELL", "timeout 3 bash -c '</dev/tcp/127.0.0.1/9223' 2>/dev/null"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 10s

networks:
  frontend:
    driver: bridge
  internal:
    internal: true
```

**注意事项：**
- `nginx` 的前端静态文件挂载路径需要指向实际的 `client/dist` 目录
- 生产环境可将前端文件复制到 `docker/nginx/html/` 并改为挂载该目录
- `COAPIS_SKIP_PROVIDERS=1` 仅用于无 LLM 的验证环境，生产环境不要设置

---

## 五、从零部署流程

### 5.1 标准部署

```bash
# 1. 创建版本目录
mkdir -p /apps/ai/coapis-pubs/<版本号>/{data,images,logs}

# 2. 准备 docker 配置目录
mkdir -p /apps/ai/coapis-pubs/<版本号>/docker/nginx/conf

# 3. 复制配置文件
cp docker-compose.yml  /apps/ai/coapis-pubs/<版本号>/docker/
cp .env                /apps/ai/coapis-pubs/<版本号>/docker/
cp nginx/conf/default.conf /apps/ai/coapis-pubs/<版本号>/docker/nginx/conf/

# 4. 加载镜像（如果是离线包）
docker load < coapis-server-<版本号>.tar.gz

# 5. 启动
cd /apps/ai/coapis-pubs/<版本号>/docker
docker compose up -d

# 6. 验证
docker ps --format '{{.Names}} {{.Status}}'   # 全部 healthy
curl http://localhost:<API端口>/api/health       # status: ready
curl -o /dev/null -w '%{http_code}' http://localhost:<Web端口>/  # HTTP 200
```

### 5.2 无 LLM 验证环境

在 `.env` 或 `docker-compose.yml` 中设置 `COAPIS_SKIP_PROVIDERS=1`，跳过 LLM 配置步骤。

适用于：
- 从零环境验证部署流程
- 不需要 LLM 的纯功能测试
- CI/CD 自动化测试

### 5.3 多版本并行

```bash
# 不同版本使用不同的：
# - 版本目录：/apps/ai/coapis-pubs/v0.9.3/ vs v0.9.4/
# - 端口：4700-4702 vs 4710-4712
# - COMPOSE_PROJECT_NAME：coapis-v093 vs coapis-v094
# - 容器名：coapis-v093-server vs coapis-v094-server
```

---

## 六、验证清单

每次发布前，按以下清单逐项验证：

| # | 验证项 | 命令 | 预期结果 |
|---|--------|------|---------|
| 1 | 容器状态 | `docker ps \| grep coapis` | 全部 healthy |
| 2 | API Health | `curl http://localhost:<API端口>/api/health` | `status: ready` |
| 3 | Web 界面 | `curl http://localhost:<Web端口>/` | HTTP 200 |
| 4 | 数据独立 | 检查 `COAPIS_WORKING_DIR` 下的文件 | 独立于其他环境 |
| 5 | 日志无泄露 | `docker logs <容器名> \| grep -E '/apps/ai/coapis[^-]\|eaterclaw'` | 无匹配 |
| 6 | 初始化日志 | `docker logs <容器名> \| grep -E '✅\|✓\|⏭️'` | 全部成功 |

---

## 七、运维命令

```bash
# 查看日志
docker logs -f coapis-v093-server

# 重启服务
cd /apps/ai/coapis-pubs/<版本号>/docker
docker compose restart

# 停止并清理
docker compose down

# 停止并删除数据（慎用）
docker compose down -v
rm -rf /apps/ai/coapis-pubs/<版本号>/data

# 进入容器调试
docker exec -it coapis-v093-server bash

# 更新镜像后重建
docker compose down
docker compose up -d
```

---

## 八、目录结构说明

### 宿主机目录

| 路径 | 用途 | 需要备份 |
|------|------|---------|
| `docker/` | 配置文件 | ✅ 是 |
| `data/` | 运行时数据（自动创建） | ✅ 是 |
| `images/` | 镜像包归档 | 可选 |
| `logs/` | 日志（可选挂载） | 可选 |

### 容器内目录

| 路径 | 说明 |
|------|------|
| `/app/coapis/` | Python 包代码 |
| `/app/coapis/console/` | 前端静态文件 |
| `${COAPIS_WORKING_DIR}` | 数据目录（挂载自宿主机） |
| `/usr/local/bin/entrypoint.sh` | 入口脚本 |
| `/usr/local/bin/init_workspace.sh` | 工作空间初始化脚本 |
