# CoApis v0.8.7 Bug 分析与修复清单

> 测试文档来源：CoApis测试文档.xlsx（王静 6/15-6/16，雷浩 6/16-6/17）
> 分析时间：2026-06-17

---

## 一、Bug 汇总表

| # | 优先级 | 模块 | 问题 | 测试人 | 状态 |
|---|--------|------|------|--------|------|
| 1 | P0 | 聊天/技能 | 安装了 docx 技能但无法使用 | 王静 | 待修复 |
| 2 | P0 | 聊天/工具 | browser_use 浏览器工具不可用 | 王静 | 待排查 |
| 3 | P1 | 聊天/前端 | 切换智能体后第一次消息不显示 | 王静 | 待修复 |
| 4 | P1 | 聊天/前端 | 思考过程与回答内容混合，未区分 | 王静 | 待修复 |
| 5 | P0 | 后台/用户管理 | 修改用户角色失败，提示"更新失败" | 王静 | 待修复 |
| 6 | - | 访客角色 | 访客无意义 | 王静 | ✅ 已修复(v0.8.6删除) |
| 7 | P0 | 模型/权限 | A账号个人模型B账号可见，token泄露风险 | 王静 | 待修复 |
| 8 | P1 | 聊天/交互 | 暂停后继续提问，AI仍回答第一个问题 | 雷浩 | 待修复 |
| 9 | P1 | 心跳/权限 | 非admin用户进入心跳页面403，菜单不应显示 | 雷浩 | 待修复 |
| 10 | P1 | 会话/管理 | 修改会话名称失败，提示"会话保存失败" | 雷浩 | 待修复 |
| 11 | P1 | 我的空间 | 上传图片失败，提示"upload failed" | 雷浩 | 待修复 |
| 12 | P1 | 运行配置 | 页面异常，显示"页面出现异常" | 雷浩 | 待修复 |

---

## 二、逐项分析

### Bug #1: docx 技能无法使用 [P0]

**现象**：已安装 docx 技能，让 AI 解析文件，返回"docx 技能未安装"

**根因分析**：
- 技能安装后，workspace 的 agent.json 中可能未正确记录技能安装状态
- 或者技能的 SKILL.md 中的触发条件（trigger）未正确匹配用户请求
- 可能是技能池目录（skill_pool）与 workspace 之间的技能同步问题

**定位方向**：
- `server/coapis/agents/skills_hub.py` — 技能安装与注册逻辑
- `server/coapis/agent/workspace.py` — workspace 加载技能的逻辑
- 前端：技能安装后是否正确刷新了 workspace 的技能列表

**修复建议**：
1. 检查技能安装 API 是否正确将技能复制到 workspace 的 skills 目录
2. 检查 workspace 加载时是否扫描并注册了已安装的技能
3. 验证 agent runner 是否能正确调用已安装的技能

---

### Bug #2: browser_use 浏览器工具不可用 [P0]

**现象**：让 AI 通过浏览器搜索新闻，返回"浏览器自动化工具似乎不可用"

**根因分析**：
- browser_use 技能依赖 Playwright 服务
- Docker 部署中 Playwright 容器可能未正确配置或未启动
- `docker-compose.dev.yaml` 中 playwright 服务的端口/网络可能未正确连接
- 之前版本中 `COAPIS_PLAYWRIGHT_VOLUME` 被删除，可能导致配置问题

**定位方向**：
- `docker/docker-compose.dev.yaml` — playwright 服务配置
- `docker/docker-compose.playwright.yml` — playwright 独立配置
- `skills/browser-use/SKILL.md` — 技能依赖检查

**修复建议**：
1. 确认 docker-compose 中 playwright 容器正常启动且网络可达
2. 检查 server 容器到 playwright 容器的网络连通性
3. 验证 browser-use 技能的 SKILL.md 中的服务发现逻辑

---

### Bug #3: 切换智能体后第一次消息不显示 [P1]

**现象**：切换智能体后，第一次发送的消息在界面上没有展示

**根因分析**：
- 前端问题：切换智能体时，消息列表（chat history）可能未正确清空或刷新
- 切换智能体时 session_id 发生变化，但前端消息列表的 state 可能仍绑定旧 session
- 新 session 的第一条消息可能在前端渲染时被跳过（SSE 事件流的初始状态问题）

**定位方向**：
- 前端 React 组件：智能体切换逻辑、消息列表组件
- 后端：`server/coapis/app/routers/console.py` 中切换智能体的 API

**修复建议**：
1. 切换智能体时，前端强制清空消息列表并重置 SSE 连接
2. 确保新 session 的第一条用户消息被正确添加到消息列表中

---

### Bug #4: 思考过程与回答内容混合 [P1]

**现象**：思考过程（thinking/reasoning）和正式回答混在一起，未区分展示

**根因分析**：
- `filter_thinking` 配置未生效或默认值为 False
- 前端未对 `reasoning` 类型的 SSE 事件做折叠/隐藏处理
- `workspace.py` 中 `filter_thinking` 逻辑可能在某些路径下被跳过

**定位方向**：
- `server/coapis/agent/workspace.py:879-883` — filter_thinking 配置读取
- 前端消息渲染组件 — 是否区分 thinking 和 message 类型
- `server/coapis/cli/channels_cmd.py:140-142` — 通道配置传递

**修复建议**：
1. 前端将 thinking 内容默认折叠，可展开查看
2. 或后端默认 `filter_thinking=True`，不返回 thinking 内容
3. 确保 workspace 配置的 `chatDisplay.hideThinking` 被正确读取

---

### Bug #5: 修改用户角色失败 [P0]

**现象**：后台管理员修改用户角色时，提示"更新失败"

**根因分析**：
- `admin_users.py:251` 的 `update_user` 路由看起来逻辑正确
- 可能问题在：SQLite 更新成功但 JSON user_store 同步失败
- 或者 `payload.role` 的值不在允许范围内（如传入了不存在的角色）
- 角色删除后（如 v0.8.6 删除了 visitor），数据库中可能存在无效角色引用

**定位方向**：
- `server/coapis/app/routers/admin/admin_users.py:251-340` — update_user 路由
- 检查 role 字段的枚举值是否包含所有有效角色
- 检查 JSON user_store 同步逻辑是否抛出异常被静默吞掉

**修复建议**：
1. 添加 role 枚举校验，只允许有效角色值
2. 增强错误日志，确保 user_store 同步失败时返回明确错误信息
3. 检查前端提交的角色值是否正确

---

### Bug #6: 访客角色无意义 [已修复]

**状态**：✅ v0.8.6 已删除访客角色，无需额外修复

---

### Bug #7: 模型权限隔离 — 个人模型跨用户可见 [P0]

**现象**：A 账号新增的个人模型，B 账号也能看到并使用，存在 token 泄露风险

**根因分析**：
- Provider（模型）未做用户级隔离
- 当前 Provider 存储可能是全局的，未区分 owner
- workspace 加载 provider 时未过滤 `owner` 字段

**定位方向**：
- Provider 的数据模型 — 是否有 `owner` / `user_id` 字段
- `server/coapis/app/routers/config.py` — Provider 列表 API 是否按用户过滤
- 前端：模型选择下拉框的数据来源

**修复建议**：
1. Provider 模型添加 `owner` 字段（空/null 表示全局，非空表示用户私有）
2. Provider 列表 API 按当前用户过滤：返回全局 + 自己的 provider
3. 前端模型选择器只显示有权限的模型
4. 数据库迁移：为现有 provider 添加 owner 字段

---

### Bug #8: 暂停后继续提问，AI 仍回答第一个问题 [P1]

**现象**：点击暂停后回答停止，接着提出第二个问题，AI 继续回答第一个问题而非第二个

**根因分析**：
- `/stop` 命令通过 TaskTracker.request_stop() 取消任务，但 SSE 事件流可能未完全终止
- 用户发送第二个问题时，第一个任务的 runner 仍在执行中
- 新消息被放入同一 session 的队列中，runner 处理完第一个任务后才处理第二个

**定位方向**：
- `server/coapis/app/runner/task_tracker.py` — 任务取消机制
- `server/coapis/app/runner/control_commands/stop_handler.py` — /stop 命令处理
- 消息队列的并发控制逻辑

**修复建议**：
1. /stop 后确保 runner 完全终止当前 LLM 调用
2. 新消息到来时，如果当前有活跃任务且被 stop，应替换而非排队
3. 或者：stop 后自动创建新 session 处理后续消息

---

### Bug #9: 心跳接口 403，菜单不应显示 [P1]

**现象**：非 admin 用户进入心跳页面，接口返回 403，但菜单仍然显示

**根因分析**：
- 后端：`GET /heartbeat` 路由有 `@require_role("admin")` 装饰器，非 admin 返回 403 ✅ 正确
- 前端：心跳菜单项对所有用户可见，未根据角色隐藏
- 前端菜单渲染未检查用户角色

**定位方向**：
- 前端菜单组件 — 角色权限过滤逻辑
- 前端路由守卫 — admin 页面的访问控制

**修复建议**：
1. 前端菜单组件根据用户角色过滤：心跳、运行配置等仅 admin 可见
2. 或后端菜单 API 只返回用户有权限的菜单项

---

### Bug #10: 修改会话名称失败 [P1]

**现象**：修改会话 name，点击"保存"，提示"会话保存失败"

**根因分析**：
- 后端 `rename_session` 路由（console.py:518）逻辑看起来正确
- 可能是 `cm.patch_chat()` 内部写入 JSON 文件时出错
- 或者 `session_id` 与前端传来的 `chat.id` 不匹配
- 前端调用的 API 路径可能与后端不一致

**定位方向**：
- `server/coapis/app/routers/console.py:518-559` — rename_session 路由
- `ChatManager.patch_chat()` — 实际写入逻辑
- 前端：调用的 API URL 和参数格式

**修复建议**：
1. 检查前端调用的 API 路径是否匹配 `/console/sessions/{id}/rename`
2. 检查 `patch_chat` 写入 JSON 文件是否有权限/锁竞争问题
3. 添加更详细的错误日志

---

### Bug #11: 上传图片失败 [P1]

**现象**：在"我的空间"上传图片，提示"upload failed"

**根因分析**：
- `files.py:216` 的 `upload_file` 路由有 `@require_role("user")` 装饰器
- 可能是文件大小限制、存储空间配额、或文件扩展名白名单问题
- 或者 `FileServiceFactory.get_service()` 返回的服务实例有问题
- 媒体目录权限问题

**定位方向**：
- `server/coapis/app/routers/files.py:216-252` — upload_file 路由
- `_check_extension()` — 文件扩展名检查
- `_check_size()` — 文件大小检查
- `_get_myspace_config()` — 空间配额配置

**修复建议**：
1. 检查前端上传时的 category 参数是否为 "files"
2. 检查文件扩展名是否在白名单中
3. 检查用户存储空间配额是否充足
4. 检查媒体目录的写入权限

---

### Bug #12: 运行配置页面异常 [P1]

**现象**：进入运行配置页面，显示"页面出现异常"

**根因分析**：
- "运行配置"路由可能不存在或返回了非预期数据
- 前端组件在解析响应数据时出错
- 可能是 `/config` API 返回的数据结构与前端期望不匹配
- 或者 config API 在某些配置缺失时返回了 null/undefined

**定位方向**：
- `server/coapis/app/routers/config.py` — 配置相关路由
- 前端：运行配置页面组件、数据解析逻辑
- 检查浏览器控制台的网络请求和错误信息

**修复建议**：
1. 检查运行配置页面调用的具体 API 端点
2. 确保 API 返回的数据结构包含前端所需的所有字段
3. 添加 null/undefined 防御性检查

---

## 三、修复优先级排序

### Phase 1 — P0 安全/核心功能（立即修复）
| # | Bug | 预估工作量 | 负责 |
|---|-----|-----------|------|
| 5 | 修改用户角色失败 | 0.5天 | 后端 |
| 7 | 模型权限隔离（token泄露） | 1天 | 后端+前端 |
| 1 | docx 技能无法使用 | 1天 | 全栈 |
| 2 | browser_use 不可用 | 0.5天 | 运维+后端 |

### Phase 2 — P1 体验问题（本版本修复）
| # | Bug | 预估工作量 | 负责 |
|---|-----|-----------|------|
| 3 | 切换智能体首次消息不显示 | 0.5天 | 前端 |
| 4 | 思考过程与回答混合 | 0.5天 | 前端 |
| 8 | 暂停后继续回答第一个问题 | 1天 | 后端 |
| 9 | 心跳菜单权限控制 | 0.5天 | 前端 |
| 10 | 会话名称修改失败 | 0.5天 | 前后端联调 |
| 11 | 上传图片失败 | 0.5天 | 前后端联调 |
| 12 | 运行配置页面异常 | 0.5天 | 前后端联调 |

### 已修复
| # | Bug | 状态 |
|---|-----|------|
| 6 | 访客角色无意义 | ✅ v0.8.6 已删除 |

---

## 四、Bug 分类统计

| 分类 | 数量 | Bug编号 |
|------|------|---------|
| 前端显示/交互 | 4 | #3, #4, #9, #12 |
| 后端 API/逻辑 | 4 | #5, #7, #8, #10 |
| 全栈（前后端联调）| 2 | #10, #11 |
| 工具/技能 | 2 | #1, #2 |
| 已修复 | 1 | #6 |

---

## 五、注意事项

1. **Bug #7（模型权限隔离）** 是安全问题，应优先处理，防止 token 泄露
2. **Bug #1 和 #2** 是核心功能问题，影响用户对技能系统的信任
3. 大部分 Bug #3/#4/#9/#12 是**前端问题**，需要前端团队配合
4. Bug #5/#10/#11 需要前后端联调确认问题根因
