# CoApis 全面测试报告与修复方案

> **测试时间**: 2026-06-06 13:30 ~ 17:10  
> **测试人**: Mcq9aJ (AI Agent)  
> **测试范围**: API 层 40+ 端点 + 前端 UI + 认证系统 + 路由注册  
> **服务器**: 127.0.0.1:8000 (uvicorn, Python 3.12)  
> **版本**: 0.1.0

---

## 一、测试方法

1. **API 层**: 通过 curl 测试 40+ 端点，记录 HTTP 状态码和响应
2. **认证系统**: 分析 auth.py、user_isolation.py、user_store.py 代码逻辑
3. **路由注册**: 分析 routers/__init__.py、_app.py 的路由挂载
4. **前端 UI**: 通过浏览器测试登录页、聊天页、文件管理等
5. **配置检查**: 分析 config.json、auth.json、users.json 等配置文件

---

## 二、发现的问题

### 🔴 P0 — 严重问题（必须立即修复）

---

#### P0-1: 认证系统死锁 — 无法登录

**严重度**: 🔴 致命  
**类型**: Bug  
**影响**: 所有用户无法登录，系统不可用

**现象**:
- `GET /api/auth/status` 返回 `{"enabled":false,"has_users":true}`
- `POST /api/auth/login` 返回 `{"token":"","username":""}`（空 token，HTTP 404）
- 所有其他 API 返回 `{"detail":"需要登录"}`（HTTP 401）

**根因分析**:
1. `COAPIS_AUTH_ENABLED` 环境变量**未设置**
2. `is_auth_enabled()` 检查 `os.environ.get("COAPIS_AUTH_ENABLED", "")`，返回 `false`
3. 当 auth 被禁用时，`/api/auth/login` 直接返回空 token（不执行登录逻辑）
4. 但 `user_isolation_middleware` **没有检查 `is_auth_enabled()`**，仍然要求所有非 PUBLIC_PATHS 端点必须认证
5. 结果：登录返回空 token → 中间件拒绝空 token → 死锁

**代码位置**:
- `server/coapis/app/auth.py:132-136` — `is_auth_enabled()` 只检查环境变量
- `server/coapis/app/auth.py:361-365` — 登录端点检查 `is_auth_enabled()`
- `server/coapis/app/middleware/user_isolation.py:110-187` — 中间件不检查 `is_auth_enabled()`

**修复方案**:
```python
# 方案1: 在 user_isolation_middleware 中添加 auth 检查
from ..auth import is_auth_enabled

@app.middleware("http")
async def user_isolation_middleware(request: Request, call_next) -> Response:
    path = request.url.path
    
    # 如果认证被禁用，跳过所有检查
    if not is_auth_enabled():
        return await call_next(request)
    
    # ... 其余逻辑不变
```

```python
# 方案2: 在登录端点中，当 auth 被禁用但有用户时，自动启用
@router.post("/login")
async def login(req: LoginRequest):
    if not is_auth_enabled():
        if has_registered_users():
            logger.warning("Auth disabled but users exist — auto-enabling")
            # 自动启用认证
        else:
            return LoginResponse(token="", username="")
    # ... 正常登录逻辑
```

**推荐**: 方案1 + 在 docker-compose 中设置 `COAPIS_AUTH_ENABLED=true`

**预计工时**: 2h  
**依赖**: 无

---

#### P0-2: Console 端点缺少认证保护 — 数据泄露

**严重度**: 🔴 高危  
**类型**: Bug  
**影响**: 未认证用户可以访问 Console 推送消息、会话列表、后端日志

**现象**:
- `GET /api/console/push-messages` → 200, `{"messages":[],"pending_approvals":[]}`
- `GET /api/console/sessions` → 200, 返回会话列表（包含 session ID、名称、时间）
- `GET /api/console/debug/backend-logs` → 200, 返回后端日志路径

**根因分析**:
`user_isolation.py` 的 `PUBLIC_PATHS` 列表包含了 `/api/console/chat` 和 `/console/chat`，但 `is_public_path()` 使用**精确匹配**。然而 `/api/console/push-messages`、`/api/console/sessions`、`/api/console/debug/backend-logs` 不在 `PUBLIC_PATHS` 中。

实际测试发现这些端点返回 200，说明它们被其他中间件放行了。检查 `console.py` 代码：
- `/console/push-messages` 有 `@require_permission("chat:read")` 装饰器
- `/console/debug/backend-logs` 有 `@require_permission("debug:read")` 装饰器
- `/console/sessions` 有 `@require_permission("chat:read")` 装饰器

问题在于：当 `is_auth_enabled()=false` 时，`require_permission` 装饰器可能跳过权限检查（因为用户是 anonymous），或者 `@require_permission` 的实现有 bug。

**代码位置**:
- `server/coapis/app/routers/console.py:41-54` — Console 端点定义
- `server/coapis/app/permissions/decorators.py` — `require_permission` 实现

**修复方案**:
1. 修复 `require_permission` 装饰器：当用户是 anonymous 时，必须返回 401
2. 或者：在 `user_isolation_middleware` 中，将 `/console/*` 从 PUBLIC_PATHS 中排除（修复 P0-1 后自然解决）

**预计工时**: 1h  
**依赖**: P0-1

---

#### P0-3: 大量路由返回 404 — 路由注册不完整

**严重度**: 🔴 高  
**类型**: Bug  
**影响**: 前端功能大面积不可用

**现象**:
| 端点 | 期望 | 实际 |
|------|------|------|
| `/api/auth/login` | 200 | 404 |
| `/api/auth/register` | 200 | 404 |
| `/api/console/chat` | 200 | 404 |
| `/api/messages` | 401/200 | 404 |
| `/api/commands` | 401/200 | 404 |
| `/api/providers` | 401/200 | 404 |
| `/api/evolution` | 401/200 | 404 |
| `/api/growth` | 401/200 | 404 |
| `/api/backup` | 401/200 | 404 |
| `/api/plan` | 401/200 | 404 |
| `/api/security` | 401/200 | 404 |
| `/api/permissions` | 401/200 | 404 |
| `/api/points` | 401/200 | 404 |
| `/api/tokens` | 401/200 | 404 |

**根因分析**:
1. `routers/__init__.py` 中路由的 `prefix` 与前端调用路径不匹配
2. 例如：`auth_router` 有 `prefix="/auth"`，挂载到 `api_router` 后路径是 `/api/auth/login`，但实际测试返回 404
3. 可能原因：
   - 路由挂载顺序问题（后面挂载的路由覆盖了前面的）
   - `files_router` 被注释掉（`# router.include_router(files_router)`），在 `_app.py` 中单独挂载
   - 某些路由的 `prefix` 包含 `/api` 前缀，导致双重前缀
   - `messages_router`、`commands_router`、`providers_router` 的 prefix 配置错误

**代码位置**:
- `server/coapis/app/routers/__init__.py` — 路由注册
- `server/coapis/app/_app.py:828` — `app.include_router(api_router, prefix="/api")`

**修复方案**:
1. 检查每个 router 的 `prefix` 设置，确保不包含 `/api`
2. 确保所有 router 都被正确 include
3. 添加路由调试：启动时打印所有注册的路由

```python
# 在 _app.py 启动时添加
for route in app.routes:
    if hasattr(route, 'path'):
        logger.info(f"Route: {route.path} -> {route.name}")
```

**预计工时**: 4h  
**依赖**: 无

---

### 🟡 P1 — 重要问题（版本内修复）

---

#### P1-1: 前端 UI 加载不完整

**严重度**: 🟡 中  
**类型**: Bug  
**影响**: 登录页面元素不渲染

**现象**:
- 浏览器打开 `http://127.0.0.1:8000`，跳转到 `/login?redirect=%2Fchat`
- Snapshot 返回 `- document`（空），没有表单元素
- 页面标题 "登录 CoApis" 存在，但输入框和按钮不渲染

**根因分析**:
1. 前端是 SPA（React + Vite），需要 JS bundle 加载
2. 后端通过 `StaticFiles` 提供前端构建产物
3. 可能原因：
   - 前端构建产物不存在或路径错误
   - JS bundle 加载失败（404）
   - React hydration 失败

**修复方案**:
1. 检查 `client/dist/` 目录是否存在
2. 检查 `_app.py` 中 `StaticFiles` 配置
3. 在浏览器控制台查看 JS 错误

**预计工时**: 2h  
**依赖**: 无

---

#### P1-2: 后端日志文件不存在

**严重度**: 🟡 中  
**类型**: Bug  
**影响**: 无法排查问题，审计日志为空

**现象**:
- `GET /api/console/debug/backend-logs` 返回 `{"exists":false,"lines":0,"content":""}`
- 日志路径: `/apps/ai/coapis/logs/coapis.log` 不存在

**根因分析**:
1. `console.py` 中的日志路径硬编码为 `WORKING_DIR / "coapis.log"` 和 `LOGS_DIR / "coapis.log"`
2. 实际日志可能输出到 stdout 或其他位置
3. `audit.py` 的审计日志文件 `DATA_DIR / "logs" / "audit" / "audit.jsonl"` 可能也不存在

**修复方案**:
1. 检查 `uvicorn` 启动参数，确认日志输出位置
2. 在 `_app.py` 启动时创建日志目录和文件
3. 修复日志路径配置

**预计工时**: 2h  
**依赖**: 无

---

#### P1-3: 路由路径不一致 — 前端调用 `/api/files` 但后端注册 `/api/myfiles`

**严重度**: 🟡 中  
**类型**: Bug  
**影响**: 文件管理功能不可用

**现象**:
- 前端 `chat.ts` 调用 `/files/preview`
- 后端 `files.py` 注册 `prefix="/myfiles"`
- 实际路径是 `/api/myfiles/preview`，前端调用 `/api/files/preview` → 404

**根因分析**:
`files_router` 的 prefix 是 `/myfiles`，但前端期望的是 `/files`。这是历史遗留问题。

**修复方案**:
1. 修改 `files.py` 的 prefix 为 `/files`（向后兼容）
2. 或在 `_app.py` 中添加路径别名：`/api/files/*` → `/api/myfiles/*`

**预计工时**: 1h  
**依赖**: P0-3

---

#### P1-4: 用户隔离中间件不检查 auth 状态

**严重度**: 🟡 中  
**类型**: Bug  
**影响**: 认证禁用时系统不可用（P0-1 的根因之一）

**根因**: `user_isolation_middleware` 没有检查 `is_auth_enabled()`，即使认证被禁用也要求登录。

**修复方案**: 见 P0-1

**预计工时**: 已包含在 P0-1  
**依赖**: P0-1

---

### ⚪ P2 — 体验优化（迭代改进）

---

#### P2-1: 前端 API 路径与后端不一致

**严重度**: ⚪ 低  
**类型**: Bug  
**影响**: 部分前端功能不可用

**现象**: 前端调用 `/api/files/*`，后端注册 `/api/myfiles/*`

**修复方案**: 统一路径命名

**预计工时**: 2h  
**依赖**: P1-3

---

#### P2-2: 缺少路由健康检查

**严重度**: ⚪ 低  
**类型**: Feature Gap  
**影响**: 路由注册问题难以发现

**修复方案**: 添加启动时路由检查和测试端点

**预计工时**: 1h  
**依赖**: 无

---

#### P2-3: 认证配置 UI 缺失

**严重度**: ⚪ 低  
**类型**: Feature Gap  
**影响**: 无法通过 UI 启用/禁用认证

**修复方案**: 在管理后台添加认证配置页面

**预计工时**: 4h  
**依赖**: P0-1

---

## 三、修复优先级与路线图

### 阶段一：紧急修复（1-2天）

| 优先级 | 问题 | 工时 | 负责人 | 依赖 |
|--------|------|------|--------|------|
| P0-1 | 认证系统死锁 | 2h | 后端 | 无 |
| P0-2 | Console 端点认证泄露 | 1h | 后端 | P0-1 |
| P0-3 | 路由注册不完整 | 4h | 后端 | 无 |
| P1-1 | 前端 UI 加载不完整 | 2h | 前端 | 无 |

**阶段一验收标准**:
- [ ] 用户可以正常登录
- [ ] 所有 API 端点可访问（401 或 200，不返回 404）
- [ ] Console 端点需要认证
- [ ] 前端页面正常渲染

---

### 阶段二：版本修复（3-5天）

| 优先级 | 问题 | 工时 | 负责人 | 依赖 |
|--------|------|------|--------|------|
| P1-2 | 后端日志文件不存在 | 2h | 后端 | 无 |
| P1-3 | 路由路径不一致 | 1h | 后端 | P0-3 |
| P1-4 | 用户隔离中间件修复 | 已包含 | 后端 | P0-1 |
| P2-1 | 前端 API 路径统一 | 2h | 前端 | P1-3 |

**阶段二验收标准**:
- [ ] 日志文件存在且可访问
- [ ] 文件管理功能正常
- [ ] 前后端 API 路径一致

---

### 阶段三：迭代优化（1-2周）

| 优先级 | 问题 | 工时 | 负责人 | 依赖 |
|--------|------|------|--------|------|
| P2-2 | 路由健康检查 | 1h | 后端 | 无 |
| P2-3 | 认证配置 UI | 4h | 全栈 | P0-1 |

---

## 四、API 测试结果汇总

### 正常工作（200）

| 端点 | 状态 | 说明 |
|------|------|------|
| `/api/health` | 200 | ✅ 正常 |
| `/api/auth/status` | 200 | ⚠️ 返回 enabled=false |
| `/api/console/push-messages` | 200 | 🔴 不应公开 |
| `/api/console/sessions` | 200 | 🔴 不应公开 |
| `/api/console/debug/backend-logs` | 200 | 🔴 不应公开 |

### 需要认证（401）

| 端点 | 状态 | 说明 |
|------|------|------|
| `/api/chats` | 401 | ✅ 正确 |
| `/api/agents` | 401 | ✅ 正确 |
| `/api/settings` | 401 | ✅ 正确 |
| `/api/admin/users` | 401 | ✅ 正确 |
| `/api/workspace` | 401 | ✅ 正确 |
| `/api/tools` | 401 | ✅ 正确 |
| `/api/skills` | 401 | ✅ 正确 |
| `/api/local-models` | 401 | ✅ 正确 |
| `/api/mcp` | 401 | ✅ 正确 |
| `/api/envs` | 401 | ✅ 正确 |
| `/api/token-usage` | 401 | ✅ 正确 |
| `/api/agent-stats` | 401 | ✅ 正确 |
| `/api/myfiles/list` | 401 | ✅ 正确 |
| `/api/myfiles/config` | 401 | ✅ 正确 |
| `/api/cron/jobs` | 401 | ✅ 正确 |
| `/api/audit/logs` | 401 | ✅ 正确 |
| `/api/audit/stats` | 401 | ✅ 正确 |
| `/api/user/me` | 401 | ✅ 正确 |

### 路由未注册（404）

| 端点 | 状态 | 说明 |
|------|------|------|
| `/api/auth/login` | 404 | 🔴 致命 |
| `/api/auth/register` | 404 | 🔴 致命 |
| `/api/console/chat` | 404 | 🔴 严重 |
| `/api/messages` | 404 | 🔴 严重 |
| `/api/commands` | 404 | 🔴 严重 |
| `/api/providers` | 404 | 🔴 严重 |
| `/api/evolution` | 404 | 🔴 严重 |
| `/api/growth` | 404 | 🔴 严重 |
| `/api/backup` | 404 | 🔴 严重 |
| `/api/plan` | 404 | 🔴 严重 |
| `/api/security` | 404 | 🔴 严重 |
| `/api/permissions` | 404 | 🔴 严重 |
| `/api/points` | 404 | 🔴 严重 |
| `/api/tokens` | 404 | 🔴 严重 |

### 权限不足（403）

| 端点 | 状态 | 说明 |
|------|------|------|
| `/api/auth/users` | 403 | ✅ 正确（需要 admin） |

---

## 五、立即行动建议

### 1. 启用认证（临时方案）

```bash
# 在 docker-compose.dev.yaml 中添加
COAPIS_AUTH_ENABLED=true

# 然后重启服务
docker-compose restart
```

### 2. 检查路由注册

```python
# 在 _app.py 启动时添加路由调试
for route in app.routes:
    if hasattr(route, 'path'):
        logger.info(f"Route: {route.path}")
```

### 3. 修复前端构建

```bash
cd client
npm run build
# 确保 dist/ 目录存在且包含正确的文件
```

---

## 六、风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 认证修复后前端不兼容 | 中 | 高 | 先修复认证，再测试前端 |
| 路由修复引入新 bug | 中 | 中 | 逐个修复，逐个测试 |
| 数据泄露（Console 端点） | 高 | 高 | 立即修复 P0-2 |
| 用户数据丢失 | 低 | 高 | 修复前备份数据库 |

---

> **文档版本**: v1.0  
> **最后更新**: 2026-06-06  
> **维护人**: 开发团队  
> **下次评审**: 阶段一完成后
