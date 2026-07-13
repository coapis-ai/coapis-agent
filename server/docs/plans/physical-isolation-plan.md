# 方案 A：恢复物理隔离 — 详细技术方案

> 版本：v1.0 | 日期：2026-06-29 | 作者：蜜总裁

---

## 一、背景与目标

### 1.1 问题

CoApis 原始设计是**物理隔离**（每个 agent 独立 `chats.json` + `sessions/`），但三层代码将其破坏：

1. **`config.json`**：用户默认智能体 `user:admin` 的 `workspace_dir` 指向用户根目录 `workspaces/admin/`，而非 agent 子目录
2. **`multi_agent_manager.py`**：故意用 `get_user_chat_manager(username)` 替换每个 agent 的 ChatManager
3. **`runner.py`**：优先使用 `_get_user_chat_manager(user_id)` 而非 agent 自己的 ChatManager

结果：所有 agent 的聊天混存在 `workspaces/{username}/chat/chats.json`，agent 级目录（如 `Ad-test/chats/`）始终为空。

### 1.2 目标

恢复物理隔离，恢复物理隔离，加上用户 ID 隔离：

```
coapis/
├── agents/                              ← 全局智能体
│   ├── global_default/
│   │   ├── agent.json
│   │   ├── chat/chats.json             ← agent 级聊天记录
│   │   └── sessions/                   ← agent 级会话状态
│   └── global_qa_agent/
│       ├── agent.json
│       ├── chat/chats.json
│       └── sessions/
│
└── workspaces/
    └── {username}/
        ├── agents/
        │   ├── user:{username}/         ← 用户默认智能体
        │   │   ├── agent.json
        │   │   ├── chat/chats.json      ← agent 级聊天记录
        │   │   └── sessions/            ← agent 级会话状态
        │   └── Ad-test/                 ← 用户自定义智能体
        │       ├── agent.json
        │       ├── chat/chats.json
        │       └── sessions/
        ├── files/                       ← 用户文件空间（共享）
        └── skills/                      ← 用户技能（共享）
```

### 1.3 架构对标

| 维度 | 目标架构 | CoApis（修复后） |
|------|---------|-----------------|
| ChatManager 归属 | 每个 agent workspace 独立 | ✅ 相同 |
| chats.json 位置 | `workspace_dir/chats.json` | `workspace_dir/chat/chats.json`（保持子目录） |
| sessions/ 位置 | `workspace_dir/sessions/` | `workspace_dir/sessions/` |
| Agent 隔离 | 天然（独立 workspace） | ✅ 相同 |
| 用户隔离 | 无（单用户） | ✅ 新增：`workspaces/{username}/agents/` |
| 聊天列表 API | `GET /chats`（workspace 内） | ✅ 相同：`GET /chats`（agent workspace 内） |

---

## 二、改动清单

### Phase 1：后端 — 移除 ChatManager 替换逻辑

#### 2.1 `multi_agent_manager.py` — 移除 ChatManager 替换

**文件**：`coapis/app/multi_agent_manager.py`

**改动 A**：删除 `_user_chat_managers` 字段和 `get_user_chat_manager()` / `get_all_user_chat_managers()` 方法

```python
# 删除：
self._user_chat_managers: Dict[str, Any] = {}

def get_user_chat_manager(self, username: str):
    ...  # 整个方法

def get_all_user_chat_managers(self) -> Dict[str, Any]:
    ...  # 整个方法
```

**改动 B**：移除 `create_agent()` 中的 ChatManager 替换逻辑（约第 183-196 行）

```python
# 删除这段：
if username and not is_global:
    user_cm = self.get_user_chat_manager(username)
    ...
    workspace.runner.set_chat_manager(user_cm)
```

**改动 C**：移除 `_start_user_agent()` 中的 ChatManager 替换逻辑（约第 649-660 行）

**改动 D**：移除 `destroy_agent()` 中的 `get_user_chat_manager` 调用

#### 2.2 `runner.py` — 移除用户级 ChatManager 优先逻辑

**文件**：`coapis/app/runner/runner.py`

**改动 A**：删除 `_get_user_chat_manager()` 方法

**改动 B**：修改 `query_handler` 中的 ChatManager 获取（约第 1073 行）

```python
# 改前：
effective_cm = self._get_user_chat_manager(user_id) or self._chat_manager

# 改后：
effective_cm = self._chat_manager
```

#### 2.3 `chats.py` 路由 — 改用 agent workspace 的 ChatManager

**文件**：`coapis/app/routers/chats.py`

当前路由通过 `_get_chat_manager_for_user(username)` 获取用户级 ChatManager。
改为通过 `get_agent_for_request(request)` 获取 agent workspace，再取其 ChatManager。

```python
# 改前：
def _get_chat_manager_for_user(username: str):
    from ..multi_agent_manager import get_manager
    manager = get_manager()
    return manager.get_user_chat_manager(username)

# 改后：
async def _get_chat_manager(request: Request):
    workspace = await get_agent_for_request(request)
    cm = workspace.chat_manager
    if not cm:
        raise HTTPException(500, "ChatManager not initialized for this agent")
    return cm
```

所有端点改为依赖 `_get_chat_manager(request)`。

**关键**：移除 `agent_id` 查询参数 — agent 隔离通过 `X-Agent-Id` header 天然实现。

```python
# 改前：
@router.get("", response_model=List[ChatSpec])
async def list_chats(request, agent_id=None, ...):
    cm = _get_chat_manager_for_user(username)
    chats = await cm.list_chats(user_id=username, channel=channel, agent_id=agent_id)

# 改后：
@router.get("", response_model=List[ChatSpec])
async def list_chats(request, channel=None):
    cm = await _get_chat_manager(request)
    username, _ = _get_current_user(request)
    chats = await cm.list_chats(user_id=username, channel=channel)
```

#### 2.4 `session.py` — 确保 session 使用 agent 级目录

确认 runner 的 `SafeJSONSession` 使用 `ws.workspace_dir / "sessions"` 作为 save_dir。
（当前代码已正确，无需修改）

### Phase 2：配置 — 修复用户默认智能体的 workspace_dir

#### 2.5 `config.json` — 修复用户默认智能体路径

对所有 `user:{username}` 格式的 agent：

```json
// 改前：
"user:admin": { "workspace_dir": "/apps/ai/coapis/workspaces/admin" }

// 改后：
"user:admin": { "workspace_dir": "/apps/ai/coapis/workspaces/admin/agents/user:admin" }
```

#### 2.6 创建用户默认智能体目录

对每个用户，创建目录及必要文件：

```bash
mkdir -p workspaces/{username}/agents/user:{username}/chat
mkdir -p workspaces/{username}/agents/user:{username}/sessions
# 从用户根目录复制 agent.json（如果存在）
cp workspaces/{username}/agent.json workspaces/{username}/agents/user:{username}/agent.json
```

### Phase 3：数据迁移

#### 2.7 迁移聊天记录

脚本：`scripts/migrate_chats_to_agent_isolation.py`

将 `workspaces/{username}/chat/chats.json` 中的聊天按 `agent_id` 字段拆分到各 agent 的 `chat/chats.json`。

规则：
- `agent_id` 有值 → 写入 `workspaces/{username}/agents/{agent_id}/chat/chats.json`
- `agent_id=""` 或空 → 写入 `workspaces/{username}/agents/user:{username}/chat/chats.json`（归属用户默认智能体）

#### 2.8 迁移会话文件

脚本：`scripts/migrate_sessions_to_agent_isolation.py`

将 `workspaces/{username}/sessions/` 中的 session 文件按 chat_id 归属到各 agent 的 `sessions/` 目录。

规则：
- 读取迁移后的 chats.json，建立 `chat_id → agent_id` 映射
- session 文件名格式：`{user_id}_{chat_id}.json`
- 按映射迁移到对应 agent 的 `sessions/` 目录

### Phase 4：前端适配

#### 2.9 `sessionApi/index.ts` — 移除 agent_id 参数

```typescript
// 改前：
const params: { user_id?: string; channel?: string; agent_id?: string } = {};
if (agentId) params.agent_id = agentId;

// 改后：agent 隔离通过 X-Agent-Id header 实现
const params: { user_id?: string; channel?: string } = {};
```

#### 2.10 确认 X-Agent-Id header 正确传递

确认所有 API 请求都携带 `X-Agent-Id` header。当前前端已有此逻辑（`api/request.ts` 中的 interceptor）。

#### 2.11 侧边栏添加频道标识

在聊天名称后显示 channel Tag（企微/飞书/钉钉）。

### Phase 5：清理

#### 2.12 清理遗留代码

- 删除 `multi_agent_manager.py` 中的 `_user_chat_managers` 相关代码
- 删除 `runner.py` 中的 `_get_user_chat_manager` 方法
- 删除 `chats.py` 路由中所有 `agent_id` 相关代码
- 删除 `ChatManager.list_chats()` 的 `agent_id` 参数
- 删除 `BaseChatRepository.filter_chats()` 的 `agent_id` 过滤

#### 2.13 清理旧数据

```bash
# 备份后删除旧的用户级 chats.json
for d in /apps/ai/coapis/workspaces/*/chat; do
    mv "$d/chats.json" "$d/chats.json.old" 2>/dev/null
done
```

---

## 三、影响分析

### 3.1 受影响的文件

| 文件 | 改动类型 | 风险 |
|------|---------|------|
| `coapis/app/multi_agent_manager.py` | 删除 ChatManager 替换逻辑 | 中 |
| `coapis/app/runner/runner.py` | 删除 `_get_user_chat_manager` | 低 |
| `coapis/app/routers/chats.py` | 改用 agent workspace 的 ChatManager | 中 |
| `coapis/app/runner/manager.py` | 移除 `agent_id` 参数 | 低 |
| `coapis/app/runner/repo/base.py` | 移除 `agent_id` 过滤 | 低 |
| `coapis/app/runner/models.py` | 移除 `agent_id` 字段 | 低 |
| `client/src/pages/Chat/sessionApi/index.ts` | 移除 `agent_id` 参数 | 低 |
| `config.json` | 修复 `workspace_dir` | 中 |
| 数据迁移脚本 | 新增 | 中 |

### 3.2 不受影响的部分

- 全局智能体 — 已经是物理隔离
- 用户文件空间 — 共享，不受影响
- 用户技能 — 共享，不受影响
- 定时任务 — 使用 agent workspace 的 `crons/` 目录

### 3.3 向后兼容

- 旧的 `chats.json` 备份为 `.old`
- 迁移脚本可重复执行（幂等）
- 前端 API 签名变化：移除 `agent_id` 参数（通过 header 传递）

---

## 四、验证计划

### 4.1 后端验证

1. 确认每个 agent 的 ChatManager 使用正确的 `chats.json` 路径
2. 确认 `GET /chats` 返回当前 agent 的聊天
3. 确认 `POST /chats` 写入当前 agent 的 `chats.json`
4. 确认 session 文件存储在 agent 级 `sessions/` 目录

### 4.2 端到端验证

1. admin 登录，切换不同 agent，确认聊天列表隔离
2. 在 `user:admin` 下发消息 → `workspaces/admin/agents/user:admin/chat/chats.json`
3. 在 `Ad-test` 下发消息 → `workspaces/admin/agents/Ad-test/chat/chats.json`
4. 企业微信发消息 → 对应 agent 的 `chats.json`
5. 重启服务后聊天记录正确加载

### 4.3 数据完整性

1. 迁移后聊天总数 = 各 agent 聊天数之和
2. 所有 `agent_id=""` 的旧数据已正确归属
3. session 文件已迁移

---

## 五、回滚方案

1. 恢复 `multi_agent_manager.py` 的 ChatManager 替换逻辑
2. 恢复 `runner.py` 的 `_get_user_chat_manager` 方法
3. 恢复 `chats.py` 路由的用户级 ChatManager 逻辑
4. 恢复 `config.json` 中的 `workspace_dir`
5. 将 `.old` 备份恢复为 `chats.json`

---

## 六、执行顺序

1. **备份**：所有涉及文件 + 数据目录
2. **Phase 2**：修复 config.json + 创建目录结构
3. **Phase 3**：执行数据迁移脚本
4. **Phase 1**：修改后端代码
5. **Phase 4**：修改前端代码
6. **Phase 5**：清理遗留代码
7. **重建部署**：docker compose 重建 + 验证
