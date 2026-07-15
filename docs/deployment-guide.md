# CoApis 部署指南

> 本文档记录 CoApis 的部署配置和操作规范

---

## 📁 目录结构

### 项目目录

```
coapis-agent/
├── client/                    # 前端 React 应用
├── server/coapis/            # 后端 Python 应用
├── docker/                    # Docker 配置 ⚠️
│   ├── docker-compose.yml     # 生产环境配置 ⚠️
│   ├── docker-compose.dev.yaml # 开发环境配置
│   ├── docker-compose.build.yml # 构建镜像
│   └── .env                   # 环境变量
├── docs/                      # 用户文档
├── tech_docs/                 # 技术文档
└── tests/                     # 测试代码
```

### 数据目录

```
/apps/ai/coapis/              # 生产数据目录
├── workspaces/               # 用户工作空间
│   ├── admin/               # 用户 admin 的空间
│   ├── test88/              # 用户 test88 的空间
│   └── ...
├── system/                   # 系统配置
├── agents/                   # 智能体配置
├── skill_pool/               # 共享技能池
└── coapis.log               # 日志文件
```

---

## 🚀 部署环境

### 开发环境

**特点**：源码挂载，代码修改后自动重启，方便调试

**配置文件**：`docker/docker-compose.dev.yaml`

**启动命令**：
```bash
cd /apps/ai/tool-dev/dev-coapis/coapis-agent/docker
docker compose -f docker-compose.dev.yaml up -d
```

**端口**：
- 前端：5173（Vite 开发服务器）
- 后端：4208
- 浏览器：4201

**容器名**：
- `coapis-server-dev`
- `coapis-nginx-dev`
- `coapis-playwright-dev`

### 生产环境

**特点**：使用镜像，数据持久化，稳定可靠

**配置文件**：`docker/docker-compose.yml` ⚠️ **重要！**

**启动命令**：
```bash
cd /apps/ai/tool-dev/dev-coapis/coapis-agent/docker
docker compose up -d
```

**端口**：
- 前端：4200（Nginx）
- 后端：4208
- 浏览器：4201

**容器名**：
- `coapis-server`
- `coapis-nginx`
- `coapis-playwright`

**⚠️ 重要提醒**：
1. **必须 cd 到 docker 目录**再执行 docker compose 命令
2. **使用 `docker-compose.yml`**，不要使用 pubs 目录
3. **数据在 `/apps/ai/coapis/`**，bind mount 持久化

---

## 🔧 部署流程

### 开发环境部署

**重启后端**：
```bash
cd /apps/ai/tool-dev/dev-coapis/coapis-agent/docker
docker compose -f docker-compose.dev.yaml restart server
```

**查看日志**：
```bash
docker logs -f coapis-server-dev
```

### 生产环境部署

**完整流程**：
```bash
# 1. 构建镜像
cd /apps/ai/tool-dev/dev-coapis/coapis-agent/docker
docker compose -f docker-compose.build.yml build server

# 2. 构建前端
cd /apps/ai/tool-dev/dev-coapis/coapis-agent/client
npm run build

# 3. 停止旧服务
cd /apps/ai/tool-dev/dev-coapis/coapis-agent/docker
docker compose down

# 4. 启动新服务
docker compose up -d

# 5. 验证服务状态
docker compose ps

# 6. 健康检查
curl http://localhost:4208/api/health
curl -I http://localhost:4200/
```

**快速重启**（不重新构建）：
```bash
cd /apps/ai/tool-dev/dev-coapis/coapis-agent/docker
docker compose restart
```

---

## 📊 服务管理

### 查看服务状态

```bash
cd /apps/ai/tool-dev/dev-coapis/coapis-agent/docker
docker compose ps
```

**预期输出**：
```
NAME                IMAGE                       STATUS
coapis-nginx        nginx:alpine                Up (healthy)
coapis-playwright   browserless/chrome:latest   Up (healthy)
coapis-server       coapis-server:latest        Up (healthy)
```

### 查看日志

**实时日志**：
```bash
# 开发环境
docker logs -f coapis-server-dev

# 生产环境
docker logs -f coapis-server
```

**最近日志**：
```bash
docker logs --tail 100 coapis-server
```

### 健康检查

**后端 API**：
```bash
curl http://localhost:4208/api/health
```

**预期返回**：
```json
{
  "status": "ready",
  "phase": "ready",
  "version": "0.9.13",
  "uptime_seconds": 36.4
}
```

**前端访问**：
```bash
curl -I http://localhost:4200/
```

**预期返回**：
```
HTTP/1.1 200 OK
```

---

## ⚙️ 环境配置

### .env 文件

**位置**：`docker/.env`

**关键配置**：
```bash
# 版本号
COAPIS_VERSION=0.9.13

# 镜像名称
COAPIS_IMAGE=coapis-server:latest

# 端口
COAPIS_WEB_PORT=4200
COAPIS_SERVER_PORT=4208
COAPIS_PLAYWRIGHT_PORT=4201

# 数据目录
COAPIS_WORKING_DIR=/apps/ai/coapis
COAPIS_WORKSPACES_DIR=${COAPIS_WORKING_DIR}/workspaces
```

### 环境区分对照表

| 项目 | 开发环境 | 生产环境 |
|------|----------|----------|
| 配置文件 | `docker-compose.dev.yaml` | `docker-compose.yml` ⚠️ |
| 容器名后缀 | `-dev` | 无 |
| 镜像 | `coapis-server:dev` | `coapis-server:latest` |
| 数据目录 | `/apps/ai/coapis` | `/apps/ai/coapis` |
| 前端端口 | 5173 (Vite) | 4200 (Nginx) |
| 后端端口 | 4208 | 4208 |
| 浏览器端口 | 4201 | 4201 |
| 挂载方式 | bind mount | bind mount |

---

## ⚠️ 重要注意事项

### Docker 操作铁律

1. **必须 cd 到 docker 目录**再执行 docker compose 命令
   ```bash
   # ✅ 正确
   cd /apps/ai/tool-dev/dev-coapis/coapis-agent/docker
   docker compose up -d
   
   # ❌ 错误
   cd /apps/ai/tool-dev/dev-coapis/coapis-agent
   docker compose -f docker/docker-compose.yml up -d
   ```

2. **生产环境使用 `docker-compose.yml`**，不要使用 pubs 目录
   - pubs 是归档目录，不是运行目录
   - 使用源码目录的配置文件

3. **数据持久化**
   - 数据在 `/apps/ai/coapis/`
   - 使用 bind mount，不是 volume
   - 容器删除后数据不会丢失

4. **重建后端后必须重启 nginx**
   ```bash
   cd /apps/ai/tool-dev/dev-coapis/coapis-agent/docker
   docker compose restart nginx
   ```

### 常见错误

**错误1：找不到配置文件**
```
原因：不在 docker 目录执行命令
解决：cd 到 docker 目录再执行
```

**错误2：数据丢失**
```
原因：使用了错误的配置文件
解决：使用 docker/docker-compose.yml，不要使用 pubs
```

**错误3：403 Forbidden**
```
原因：前端构建产物未正确复制
解决：
cd /apps/ai/tool-dev/dev-coapis/coapis-agent/client
npm run build
# 前端文件会自动挂载到容器
```

---

## 📚 相关文档

- **架构设计**：`/apps/ai/tool-dev/dev-coapis/coapis-archive/architecture/架构设计.md`
- **技术总结**：`/apps/ai/tool-dev/dev-coapis/coapis-archive/COAPIS_TECHNICAL_SUMMARY.md`
- **技术文档**：`tech_docs/`
- **用户文档**：`docs/`

---

## 📝 更新记录

- 2026-07-15: 初始版本，记录部署规范和注意事项
