# CoApis 项目路径架构排查报告

## 一、现状：两个独立的 coapis-agent 目录

### 目录 1：源码目录（Agent 工作目录）
- **路径**：`/apps/ai/tool-dev/dev-coapis/coapis-agent/`
- **git HEAD**：`4c8ab7a` (v0.8.21) — ✅ 最新代码
- **角色**：所有代码编辑都在这里进行
- **引用方**：
  - `docker-compose.dev.yaml` → 开发环境 server/nginx 容器
  - Agent 的工作目录就是 `dev-coapis/`

### 目录 2：生产部署目录（副本）
- **路径**：`/apps/ai/tool-dev/devs/coapis-agent/`
- **git HEAD**：`8a9f9fe` — ❌ 落后很多版本
- **角色**：生产环境容器的代码来源
- **引用方**：
  - `docker-compose.prod.yaml` → 生产环境 server/nginx 容器
- **问题**：这是源码目录的手动副本，每次改代码后需要手动同步

### 目录 3：你期望的工作目录
- **路径**：`/apps/ai/tool-dev/coapis-agent/`
- **状态**：❌ **不存在**

---

## 二、Docker Compose 路径解析

### 开发环境 `docker-compose.dev.yaml`
位于 `/apps/ai/tool-dev/dev-coapis/coapis-agent/docker/`

| 卷挂载 | 相对路径 | 实际解析路径 |
|--------|----------|-------------|
| 前端构建容器 | `../client:/app` | `/apps/ai/tool-dev/dev-coapis/coapis-agent/client` ✅ |
| server 源码 | `../server/coapis:/app/coapis` | `/apps/ai/tool-dev/dev-coapis/coapis-agent/server/coapis` ✅ |
| server 前端产物 | `../client/dist:/app/coapis/console` | `/apps/ai/tool-dev/dev-coapis/coapis-agent/client/dist` ✅ |
| nginx 前端 | `../client/dist:/usr/share/nginx/html` | `/apps/ai/tool-dev/dev-coapis/coapis-agent/client/dist` ✅ |

### 生产环境 `docker-compose.prod.yaml`
位于 `/apps/ai/tool-dev/devs/coapis-agent/docker/`

| 卷挂载 | 相对路径 | 实际解析路径 |
|--------|----------|-------------|
| nginx 前端 | `../client/dist:/usr/share/nginx/html` | `/apps/ai/tool-dev/devs/coapis-agent/client/dist` ❌ 副本！ |

> 注意：生产 server 容器使用 Docker 镜像（不挂载源码），但镜像构建时 COPY 的也是 `devs/` 目录的文件。

---

## 三、不一致的根源

```
编辑代码 → dev-coapis/coapis-agent/server/coapis/...
                    ↓
            开发容器自动热更新 ✅
                    ↓
        但生产容器读的是 devs/coapis-agent/ 的副本 ❌
                    ↓
            需要手动 rsync/cp 同步 ❌（经常忘记）
```

**git 版本差异已经证明了问题**：
- 源码：`4c8ab7a bump: v0.8.21`
- 生产副本：`8a9f9fe fix: 移除 file_guardian.py 中已删除的引用`
- 这两个之间差了几十个 commit！

---

## 四、解决方案

### 方案 A（推荐）：消除副本，生产 compose 直接引用源码

把生产 `docker-compose.prod.yaml` 中的相对路径改为**绝对路径**，指向源码目录：

```yaml
# 修改前（相对路径 → 解析到副本）
volumes:
  - ../client/dist:/usr/share/nginx/html:ro

# 修改后（绝对路径 → 直接指向源码）
volumes:
  - /apps/ai/tool-dev/dev-coapis/coapis-agent/client/dist:/usr/share/nginx/html:ro
```

**优点**：
- 彻底消除副本，一劳永逸
- 改代码后只需构建镜像，无需手动同步文件
- 两个环境始终一致

**缺点**：
- 生产 compose 不再可移植（绑定了绝对路径）

### 方案 B：搬移到你期望的路径

把源码搬移到 `/apps/ai/tool-dev/coapis-agent/`，两个 compose 都引用这个目录。

**优点**：路径干净，符合你的预期
**缺点**：需要停止所有容器、移动文件、更新所有 compose 路径、重新 git clone

### 方案 C：保持现状，但建立自动同步机制

保留两个目录，但每次代码变更后自动同步。

**优点**：改动最小
**缺点**：本质上没有解决问题，只是自动化了手动操作

---

## 五、建议

**推荐方案 A**。理由：
1. 你刚才说"之前就发现生产环境在相同情况下和开发环境不一致"——这就是根因
2. 副本机制是人为错误的温床
3. 改动最小，只需修改 compose 中的路径，不需要移动任何文件
