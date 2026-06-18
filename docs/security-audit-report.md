# CoApis 系统级安全架构分析报告

> **日期**: 2026-06-12  
> **版本**: v2.0（细化版）  
> **范围**: 系统级安全架构深度审计，覆盖沙箱/隔离/工具防护/命令权限/确认机制/容器安全/聊天窗口交互/技能触发机制

---

## 一、现有安全架构全景

### 1.1 完整交互链路（含SSE/ApprovalCard/技能触发）

```
用户在聊天窗口输入消息
  │
  ▼
前端 POST /console/chat (SSE流式请求)
  │  payload = {input: [...], biz_params: {agent_id}, session_id}
  │
  ▼
后端 ConsoleChannel.stream_one()
  │  注入 session_context (username, role, channel, workspace_dir)
  │
  ▼
CoApisAgent.process() → LLM推理
  │  ① 技能触发检查（详见1.3节）
  │  ② LLM返回 tool_calls[]
  │
  ▼
react_agent._acting(tool_call)
  │
  ├─ ① Plan Tool Gate（计划工具门控）
  │
  ├─ ② ToolGuardMixin._acting(tool_call) ← 核心拦截点
  │    │
  │    ├─ _decide_guard_action()
  │    │   ├── denied_tools → 无条件拒绝
  │    │   ├── OFF模式 → 跳过
  │    │   ├── ToolGuardEngine.guard(tool_name, tool_input)
  │    │   │   ├── RuleBasedToolGuardian（YAML 24条正则）
  │    │   │   ├── ShellEvasionGuardian（600+行混淆检测）
  │    │   │   └── FilePathToolGuardian（敏感路径拦截）
  │    │   │   → 聚合 ToolGuardResult（findings列表）
  │    │   │
  │    │   ├── STRICT模式 → 所有工具需要审批
  │    │   ├── SMART模式:
  │    │   │   ├── INFO/LOW → 自动放行
  │    │   │   └── MEDIUM+ → 需要审批
  │    │   ├── AUTO模式 → 仅guarded_tools需要审批
  │    │   └── 返回 _GuardAction(kind, tool_name, tool_input, guard_result)
  │    │
  │    ├─ _execute_guard_action()
  │    │   ├── auto_denied → _acting_auto_denied() → 拒绝+审计
  │    │   ├── needs_approval → _acting_with_approval() → 审批流
  │    │   │   ├── ApprovalService.create_pending() → 创建Future
  │    │   │   ├── _emit_waiting_for_approval_blocking() → 发送审批消息
  │    │   │   │   Msg(metadata={message_type: "tool_guard_approval", ...})
  │    │   │   │   → 前端通过SSE接收，渲染ApprovalCard组件
  │    │   │   ├── _wait_for_approval_with_heartbeat() → 阻塞等待
  │    │   │   │   ├── 用户点击「允许」→ /approval/approve → Future.resolve(APPROVED)
  │    │   │   │   ├── 用户点击「拒绝」→ /approval/deny → Future.resolve(DENIED)
  │    │   │   │   └── 超时(300s) → Future.resolve(TIMEOUT)
  │    │   │   └── 根据decision执行或拒绝
  │    │   └── pass → 跳过guard，直接执行
  │    │
  │    └─ super()._acting(tool_call) → 实际工具执行
  │
  ├─ ③ WorkspaceGuard检查
  │    ├── 路径边界检查（is_within_workspace）
  │    ├── Shell白名单（按角色: visitor/user/advanced/admin）
  │    ├── Shell黑名单（12条全局禁止）
  │    └── 危险模式检测（12条正则）
  │
  ├─ ④ SandboxedExecutor执行
  │    ├── 工具白名单（ALLOWED_TOOLS 13个）
  │    ├── 参数校验（PATH_TOOLS/COMMAND_TOOLS）
  │    ├── ToolSandbox检查（路径正则+危险命令）
  │    ├── 超时控制（默认30s）
  │    └── 输出截断（默认1MB）
  │
  └─ ⑤ 返回结果 → ToolResultBlock → SSE流 → 前端渲染
```

### 1.2 调用链路汇总（9层防护 + 2个独立层）

| 层 | 模块 | 拦截时机 | 决策能力 | 阻断能力 |
|---|---------|---------|---------|---------|
| ① Plan Tool Gate | react_agent._acting | 工具调用前 | ✅ | ✅ |
| ② ToolGuardMixin | tool_guard_mixin._acting | 工具调用前 | ✅ | ✅ |
| ③ ToolGuardEngine | tool_guard/engine.guard | 工具调用前 | ✅ | ✅（通过Mixin） |
| ④ WorkspaceGuard | workspace_guard | 工具执行中 | ✅ | ✅ |
| ⑤ SandboxedExecutor | sandboxed_executor | 工具执行中 | ✅ | ✅ |
| ⑥ ToolSandbox | tool_sandbox | 工具执行中 | ✅ | ✅ |
| ⑦ ProcessIsolator | process_isolator | 进程级 | ❌ | ✅（超时）⚠️未集成 |
| ⑧ ResourceLimiter | resource_limiter | 资源级 | ❌ | ✅（内核级）⚠️未集成 |
| ⑨ ToolCallMonitor | tool_monitor | 执行后 | ❌ | ❌（仅报警） |
| 独立A | ImportSandbox | import时 | ✅ | ✅ ⚠️需手动activate |
| 独立B | ASTSandbox | 代码解析时 | ✅ | ✅ ⚠️未集成 |

### 1.3 技能触发机制

```
用户消息到达
  │
  ▼
_load_on_demand_skills(user_message)
  │
  ├─ Phase 1: LLM意图分类（异步，尽力而为）
  │   ├── _llm_classify_skills(user_message)
  │   │   → LLM判断用户意图匹配哪些按需技能
  │   ├── 匹配成功 → toolkit.register_agent_skill(skill_dir)
  │   │   → 技能代码注册为可用工具
  │   └── ⚠️ 无安全扫描！直接注册
  │
  ├─ Phase 2: 关键词匹配（LLM未匹配的技能）
  │   ├── 遍历 _on_demand_skills[name] = (skill_dir, triggers)
  │   ├── triggers来源:
  │   │   ├── SKILL.md frontmatter description
  │   │   └── 用户覆盖: workspaces/{user}/skill_triggers/{name}.json
  │   ├── 匹配成功 → toolkit.register_agent_skill(skill_dir)
  │   └── ⚠️ 无安全扫描！直接注册
  │
  └─ 注册后的技能 → LLM可在tool_calls中调用
      → 进入正常ToolGuard拦截链路
```

**对比**：技能安装时有安全扫描（`_scan_skill_dir_or_raise`），但触发注册时无扫描。

### 1.4 SSE流式传输链路

```
后端事件生成                    前端接收
─────────────                 ──────────
ConsoleChannel.stream_one()
  → TaskTracker.put(queue, event)
    → SSE event string

                                  StreamingResponse
                                    ↓
                                  event_generator()
                                    → yield event_data
                                      ↓
                                  前端 EventSource / fetch stream
                                    ↓
                                  SSE event parser
                                    ↓
                                  ┌─ message → 渲染聊天消息
                                  ├─ tool_result → 渲染工具结果
                                  ├─ message_type: "tool_guard_approval"
                                  │   → 渲染 ApprovalCard 组件
                                  └─ heartbeat → 保持连接
```

### 1.5 ApprovalCard 组件交互流程

```
前端收到 SSE event (message_type: "tool_guard_approval")
  │
  ▼
ApprovalContext.setApprovals([...])
  │
  ▼
ConsolePollService 轮询 /console/push-messages (每2.5s)
  │  → 获取 pending_approvals 列表
  │  → 按 root_session_id 过滤当前会话
  │  → 更新 ApprovalContext
  │
  ▼
Chat/index.tsx 渲染 ApprovalCard
  │  位置: fixed bottom:80, right:24, z-index:1000
  │  最大宽度: 480px
  │
  ├─ 显示内容:
  │   ├── 工具名称 (toolName)
  │   ├── 严重度标签 (severity: CRITICAL/HIGH/MEDIUM)
  │   ├── 风险发现数 (findingsCount)
  │   ├── 风险摘要 (findingsSummary)  ⚠️ 仅纯文本
  │   ├── 工具参数 (toolParams, JSON格式)
  │   └── 倒计时 (remaining seconds)
  │
  ├─ 用户操作:
  │   ├── 点击「允许」→ handleApprove()
  │   │   → POST /approval/approve {request_id, session_id}
  │   │   → 后端 Future.resolve(APPROVED)
  │   │   → 后端继续执行工具
  │   │
  │   ├── 点击「拒绝」→ handleDeny()
  │   │   → POST /approval/deny {request_id, session_id}
  │   │   → 后端 Future.resolve(DENIED)
  │   │   → 后端拒绝执行
  │   │
  │   └── 超时 → 后端 Future.resolve(TIMEOUT)
  │       → 后端拒绝执行 + 审计日志
  │
  └─ 清理:
      ├── 执行/拒绝后从 Map 中移除
      └── 倒计时归零后自动消失
```

### 1.6 安全检查点清单

| # | 检查点 | 位置 | 时机 | 阻断能力 |
|---|--------|------|------|---------|
| 1 | 技能安装安全扫描 | SkillService._scan_skill_dir_or_raise | 技能安装时 | ✅ 阻断 |
| 2 | 技能触发注册 | react_agent._load_on_demand_skills | 用户消息到达时 | ⚠️ **无检查** |
| 3 | Plan Tool Gate | react_agent._acting | 工具调用前 | ✅ |
| 4 | ToolGuardMixin拦截 | tool_guard_mixin._acting | 工具调用前 | ✅ |
| 5 | ToolGuardEngine扫描 | tool_guard/engine.guard | 工具调用前 | ✅ |
| 6 | WorkspaceGuard | workspace_guard | 工具执行中 | ✅ |
| 7 | SandboxedExecutor | sandboxed_executor | 工具执行中 | ✅ |
| 8 | ToolSandbox | tool_sandbox | 工具执行中 | ✅ |
| 9 | ProcessIsolator | process_isolator | 进程级 | ⚠️ 未集成 |
| 10 | ResourceLimiter | resource_limiter | 资源级 | ⚠️ 未集成 |
| 11 | ToolCallMonitor | tool_monitor | 执行后 | ❌ 仅报警 |

---

## 二、命令级权限矩阵

### 2.1 工具层级权限

| 工具名 | 沙箱白名单 | 受保护 | 路径校验 | 命令校验 | 适用角色 |
|--------|:---:|:---:|:---:|:---:|------|
| read_file | ✅ | ✅ | ✅ | - | visitor+ |
| write_file | ✅ | ✅ | ✅ | - | user+ |
| edit_file | ✅ | ✅ | ✅ | - | user+ |
| append_file | ❌ | ✅ | ✅ | - | user+ |
| grep_search | ✅ | - | - | - | visitor+ |
| glob_search | ✅ | - | - | - | visitor+ |
| execute_shell_command | ✅ | ✅ | - | ✅ | user+（受白名单约束） |
| get_current_time | ✅ | - | - | - | 全部 |
| set_user_timezone | ✅ | - | - | - | 全部 |
| get_token_usage | ✅ | - | - | - | 全部 |
| view_image | ✅ | - | ✅ | - | 全部 |
| send_file_to_user | ✅ | ✅ | ✅ | - | user+ |
| desktop_screenshot | ✅ | - | - | - | user+ |
| memory_search | ✅ | - | - | - | visitor+ |
| 其他工具（未在白名单） | ❌ | - | - | - | **全部拒绝** |

### 2.2 Shell命令层级权限（角色×操作类型×执行级别）

| 操作类型 | 具体命令 | visitor | user | advanced | admin | 执行级别 | 确认机制 | 超时 | 审计 |
|----------|---------|:---:|:---:|:---:|:---:|:---:|---------|:---:|:---:|
| **文件浏览** | ls/cat/head/tail/wc/grep/find/pwd | 🔴禁止 | 🟢AUTO | 🟢AUTO | 🟢AUTO | 直接执行 | 无 | - | ❌ |
| | tree | 🔴禁止 | 🟢AUTO | 🟢AUTO | 🟢AUTO | 直接执行 | 无 | - | ❌ |
| **文件创建** | mkdir/touch | 🔴禁止 | 🟢AUTO | 🟢AUTO | 🟢AUTO | 直接执行 | 无 | - | ❌ |
| **文件删除** | rm | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM | 弹窗确认 | ApprovalCard | 60s→deny | ✅ |
| | rm -r / rm -f | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM | 弹窗确认 | ApprovalCard | 60s→deny | ✅ |
| | rm -rf / \| rm -rf /* | 🔴禁止 | 🔴BLOCK | 🔴BLOCK | 🔴BLOCK | 硬拒绝 | 直接拦截 | - | ✅ |
| **文件移动/复制** | cp/cp -r | 🔴禁止 | 🟢AUTO | 🟡CONFIRM | 🟡CONFIRM | 弹窗确认 | ApprovalCard | 60s→deny | ✅ |
| | mv | 🔴禁止 | 🟢AUTO | 🟡CONFIRM | 🟡CONFIRM | 弹窗确认 | ApprovalCard | 60s→deny | ✅ |
| **文本处理** | sort/uniq/cut/tr/sed/awk | 🔴禁止 | 🟢AUTO | 🟢AUTO | 🟢AUTO | 直接执行 | 无 | - | ❌ |
| **编程执行** | python3 *.py/node *.js | 🔴禁止 | 🟢AUTO | 🟢AUTO | 🟢AUTO | 直接执行 | 无 | - | ❌ |
| | python3 -c/node -e | 🔴禁止 | 🔴BLOCK | 🔴BLOCK | 🟡CONFIRM | 正则拦截→弹窗 | 无 | - | ✅ |
| | npm/pip/pip3 | 🔴禁止 | 🟢AUTO | 🟡CONFIRM | 🟡CONFIRM | 弹窗确认 | ApprovalCard | 60s→deny | ✅ |
| **版本控制** | git status/log/diff | 🔴禁止 | 🟢AUTO | 🟢AUTO | 🟢AUTO | 直接执行 | 无 | - | ❌ |
| | git push/commit | 🔴禁止 | 🟢AUTO | 🟡CONFIRM | 🟡CONFIRM | 弹窗确认 | ApprovalCard | 60s→deny | ✅ |
| **网络（只读）** | curl -s/curl --head/wget | 🔴禁止 | 🟢AUTO | 🟢AUTO | 🟢AUTO | 直接执行 | 无 | - | ❌ |
| **网络（数据上传）** | curl -d/@data | 🔴禁止 | 🔴禁止 | 🔴BLOCK | 🔴BLOCK | 硬拒绝 | 正则拦截 | - | ✅ |
| **系统管理** | chmod/chown | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM | 弹窗确认 | ApprovalCard | 30s→deny | ✅ |
| | kill/pkill/killall | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM | 弹窗确认 | ApprovalCard | 30s→deny | ✅ |
| | systemctl/service | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM | 弹窗确认 | ApprovalCard | 30s→deny | ✅ |
| | docker/docker * | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM | 弹窗确认 | ApprovalCard | 60s→deny | ✅ |
| | apt/apt-get/yum/dnf | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM | 弹窗确认 | ApprovalCard | 60s→deny | ✅ |
| | crontab | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM | 弹窗确认 | ApprovalCard | 30s→deny | ✅ |
| | tar/zip/unzip | 🔴禁止 | 🔴禁止 | 🟢AUTO | 🟢AUTO | 直接执行 | 无 | - | ❌ |
| **高危操作** | sudo/su/doas/pkexec | 🔴禁止 | 🔴BLOCK | 🔴BLOCK | 🟡CONFIRM | YAML拦截→弹窗 | 无 | - | ✅ |
| | curl\|bash/wget\|sh | 🔴禁止 | 🔴BLOCK | 🔴BLOCK | 🔴BLOCK | 硬拒绝 | 无 | - | ✅ |
| | 反弹shell（nc -e/socat） | 🔴禁止 | 🔴BLOCK | 🔴BLOCK | 🔴BLOCK | 硬拒绝 | 无 | - | ✅ |
| | fork bomb | 🔴禁止 | 🔴BLOCK | 🔴BLOCK | 🔴BLOCK | 硬拒绝 | 无 | - | ✅ |
| | mkfs/dd if= | 🔴禁止 | 🔴BLOCK | 🔴BLOCK | 🔴BLOCK | 硬拒绝 | 无 | - | ✅ |
| | shutdown/reboot/halt | 🔴禁止 | 🔴BLOCK | 🔴BLOCK | 🔴BLOCK | 硬拒绝 | 无 | - | ✅ |

### 2.3 Tool Guard YAML规则覆盖映射（24条→执行级别）

| 规则ID | 命令关键词 | 严重度 | user拦截 | advanced拦截 | admin拦截 | 前端行为 |
|--------|-----------|:---:|:---:|:---:|:---:|---------|
| TOOL_CMD_DANGEROUS_RM | rm | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_DANGEROUS_MV | mv | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_FS_DESTRUCTION | mkfs/dd | CRITICAL | 拦截 | 拦截 | 拦截 | 直接拒绝 |
| TOOL_CMD_DOS_FORK_BOMB | fork bomb | CRITICAL | 拦截 | 拦截 | 拦截 | 直接拒绝 |
| TOOL_CMD_PIPE_TO_SHELL | curl\|bash | CRITICAL | 拦截 | 拦截 | 拦截 | 直接拒绝 |
| TOOL_CMD_REVERSE_SHELL | nc -e/socat | CRITICAL | 拦截 | 拦截 | 拦截 | 直接拒绝 |
| TOOL_CMD_SYSTEM_TAMPERING | crontab/sudoers | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_UNSAFE_PERMISSIONS | chmod 777 | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_OBFUSCATED_EXEC | base64\|bash | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_SYSTEM_REBOOT | reboot/shutdown | CRITICAL | 拦截 | 拦截 | 拦截 | 直接拒绝 |
| TOOL_CMD_SERVICE_RESTART | systemctl restart | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_PROCESS_KILL | kill/pkill | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_PRIVILEGE_ESCALATION | sudo/su | CRITICAL | 拦截 | 拦截 | **⚠️仅弹窗** | 直接拒绝 |
| TOOL_CMD_IFS_INJECTION | $IFS | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_CONTROL_CHARS | 控制字符 | CRITICAL | 拦截 | 拦截 | 拦截 | 直接拒绝 |
| TOOL_CMD_UNICODE_WHITESPACE | Unicode空白 | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_PROC_ENVIRON | /proc/environ | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_JQ_SYSTEM | jq system() | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_JQ_FILE_FLAGS | jq -f/--rawfile | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_ZSH_DANGEROUS | zmodload/ztcp | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_SQL_INJECTION | DROP/TRUNCATE | HIGH | YAML弹窗 | YAML弹窗 | **⚠️无拦截** | SMART弹窗 |
| TOOL_CMD_RF_FORCE | rm -rf | CRITICAL | 拦截 | 拦截 | 拦截 | 直接拒绝 |
| TOOL_CMD_ENV_DUMP | env/printenv | MEDIUM | **⚠️仅SMART** | **⚠️仅SMART** | **⚠️仅SMART** | SMART弹窗 |
| TOOL_CMD_CHMOD_RECURSIVE | chmod -R 777 | MEDIUM | **⚠️仅SMART** | **⚠️仅SMART** | **⚠️仅SMART** | SMART弹窗 |

### 2.4 敏感文件路径拦截矩阵

| 拦截类型 | 匹配规则 | 严重度 | 全角色拦截 |
|----------|---------|:---:|:---:|
| 目录拦截 | `~/.ssh/`, `~/.aws/`, `~/.config/`, `~/.gnupg/` | HIGH | ✅ |
| 目录拦截 | `.coapis.secret/`, `.copaw.secret/` | HIGH | ✅ |
| 文件名拦截 | `.env`, `.env.*`, `shadow`, `passwd` | HIGH | ✅ |
| 文件名拦截 | `id_rsa`, `id_ed25519`, `*.pem`, `*.key` | HIGH | ✅ |
| Glob拦截 | `.env*`, `*.db`, `*.sqlite`, `*.sqlite3` | HIGH | ✅ |
| Glob拦截 | `credentials*`, `service_account*` | HIGH | ✅ |

---

## 三、系统级缺口清单（含交互层）

### P0 — 致命缺陷（8项）

| # | 缺口 | 位置 | 影响 |
|---|------|------|------|
| P0-1 | **Docker以root运行** | `server/deploy/Dockerfile` | 容器内进程拥有完整root权限，突破沙箱即可获取宿主机控制权 |
| P0-2 | **admin角色无任何约束** | `workspace_guard.py` | `admin: ["*"]` 通配符等同无限制 |
| P0-3 | **dangerous命令无确认机制** | `workspace_guard.py` | rm/rm -r/mv/chmod/chown/kill/pkill 在advanced角色下直接执行 |
| P0-4 | **ResourceLimiter未集成主流程** | `agent/core.py:90` | 已初始化但工具执行链路中未调用 |
| P0-5 | **无网络隔离** | 整体架构 | shell命令可自由发起出站连接 |
| P0-6 | **无内核级沙箱** | Docker层 | 无seccomp/AppArmor/namespace隔离 |
| P0-7 | **技能触发注册无安全检查** | `react_agent._load_on_demand_skills` | LLM分类和关键词匹配后直接register_agent_skill，无扫描 |
| P0-8 | **Tool Guard HIGH级规则对admin无拦截** | `tool_guard/engine.py` | 17条HIGH级规则对admin角色不生效（SMART模式下admin通配符跳过YAML检查） |

### P1 — 高危缺口（8项）

| # | 缺口 | 位置 | 影响 |
|---|------|------|------|
| P1-1 | **白名单匹配逻辑粗糙** | `workspace_guard.py` | fnmatch通配符导致合法命令被拒 |
| P1-2 | **docker/yum/apt无YAML规则** | `dangerous_shell_commands.yaml` | advanced角色可直接docker rm -f |
| P1-3 | **ToolCallMonitor仅报警不阻断** | `tool_monitor.py` | 检测到异常后仅记录alert |
| P1-4 | **无文件系统namespace隔离** | ProcessIsolator | 命令可访问容器内全部文件 |
| P1-5 | **环境变量过滤过宽** | `process_isolator.py` | 泄露PATH/HOME/USER等 |
| P1-6 | **Docker-compose无资源限制** | `docker-compose.dev.yaml` | 无memory/cpu limit |
| P1-7 | **Interpreter内联执行防护不一致** | `workspace_guard.py` | admin角色完全放行python3 -c |
| P1-8 | **ProcessIsolator未集成主流程** | `process_isolator.py` | 已初始化未使用，无临时目录隔离 |

### P2 — 中等缺口（8项）

| # | 缺口 | 位置 | 影响 |
|---|------|------|------|
| P2-1 | **前端仅显示3条规则** | API路由冲突 | 24条YAML规则前端不可见 |
| P2-2 | **敏感文件列表不完整** | `file_guardian.py` | 缺少.npmrc/*.pem等 |
| P2-3 | **ImportSandbox未集成主流程** | `import_sandbox.py` | 需手动activate |
| P2-4 | **ASTSandbox未集成主流程** | `ast_sandbox.py` | 已初始化未集成 |
| P2-5 | **审批弹窗超时硬编码** | `constant.py:410` | 300s硬编码，无配置项 |
| P2-6 | **无denied操作审计日志** | `audit_logger.py` | 被拒绝的操作未写入审计 |
| P2-7 | **ApprovalCard仅支持text不支持markdown** | `ApprovalCard.tsx` | findingsSummary显示为纯文本，无格式化 |
| P2-8 | **技能触发关键词可被用户覆盖** | `workspaces/{user}/skill_triggers/` | 用户可注入恶意触发词加载危险技能 |

### P3 — 低优先级（6项）

| # | 缺口 | 位置 | 影响 |
|---|------|------|------|
| P3-1 | **无executor级速率限制** | `sandboxed_executor.py` | 无per-user硬限制 |
| P3-2 | **无容器间网络隔离** | docker-compose | 容器间可自由通信 |
| P3-3 | **只读根文件系统未启用** | Dockerfile | 容器内文件系统可写 |
| P3-4 | **无工具调用审计可视化** | 前端 | 审计日志无前端展示 |
| P3-5 | **ConsolePollService轮询间隔固定2.5s** | `ConsolePollService` | 无法感知高优先级审批 |
| P3-6 | **审批消息不入记忆** | `tool_guard_mixin.py` | ApprovalCard消息不加入memory，无法回溯审批历史 |

### 缺口统计

| 严重度 | 数量 | 占比 |
|--------|------|------|
| P0 致命 | 8 | 27% |
| P1 高危 | 8 | 27% |
| P2 中等 | 8 | 27% |
| P3 低优 | 6 | 20% |
| **合计** | **30** | 100% |

### 缺口分布（按安全层）

| 安全层 | P0 | P1 | P2 | P3 | 合计 |
|--------|-----|-----|-----|-----|------|
| Docker/容器层 | 2 | 2 | 0 | 2 | 6 |
| Workspace Guard | 2 | 2 | 1 | 0 | 5 |
| Tool Guard Engine | 1 | 1 | 1 | 0 | 3 |
| 技能触发层 | 1 | 0 | 1 | 0 | 2 |
| 执行层（Executor/Sandbox） | 1 | 2 | 0 | 1 | 4 |
| 资源/进程层 | 1 | 1 | 0 | 1 | 3 |
| 审计/监控层 | 0 | 0 | 1 | 1 | 2 |
| 前端/交互层 | 0 | 0 | 2 | 2 | 4 |

---

## 四、命令确认机制设计方案（含前端交互）

### 4.1 三级命令分类体系

| 级别 | 行为 | 适用命令 | 超时策略 | 前端表现 |
|------|------|---------|---------|---------|
| **🟢 AUTO** | 直接执行 | ls, cat, head, tail, wc, grep, find, pwd, echo, tree, sort, uniq, cut, tr, git status/log/diff, mkdir, touch, python3 *.py, node *.js, tar/zip/unzip | N/A | 工具结果正常渲染 |
| **🟡 CONFIRM** | 弹窗确认 | rm, rm -r, rm -f, mv, cp, chmod, chown, kill, pkill, systemctl, service, apt, yum, pip install, npm install, docker, crontab, git push/commit | 普通60s / 高危30s | ApprovalCard弹窗 |
| **🔴 BLOCK** | 硬拒绝 | rm -rf /, rm -rf /*, mkfs, dd if=, shutdown, reboot, sudo, su, curl\|bash, 反弹shell, fork bomb, curl -d @, python3 -c（user/advanced） | N/A | 直接拒绝消息+审计 |

### 4.2 角色×级别矩阵

| 命令类别 | visitor | user | advanced | admin |
|----------|:---:|:---:|:---:|:---:|
| 文件浏览 | 🔴禁止 | 🟢AUTO | 🟢AUTO | 🟢AUTO |
| 文件创建 | 🔴禁止 | 🟢AUTO | 🟢AUTO | 🟢AUTO |
| 文件删除 | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM |
| 文件移动/复制 | 🔴禁止 | 🟢AUTO | 🟡CONFIRM | 🟡CONFIRM |
| 权限修改 | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM |
| 进程管理 | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM |
| 服务管理 | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM |
| 包管理 | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM |
| Docker | 🔴禁止 | 🔴禁止 | 🟡CONFIRM | 🟡CONFIRM |
| 网络（只读） | 🔴禁止 | 🟢AUTO | 🟢AUTO | 🟢AUTO |
| 网络（数据上传） | 🔴禁止 | 🔴禁止 | 🔴BLOCK | 🔴BLOCK |
| 编程执行（脚本） | 🔴禁止 | 🟢AUTO | 🟢AUTO | 🟢AUTO |
| 编程执行（内联） | 🔴禁止 | 🔴BLOCK | 🔴BLOCK | 🟡CONFIRM |
| 高危操作 | 🔴禁止 | 🔴BLOCK | 🔴BLOCK | 🔴BLOCK |

### 4.3 CommandRiskClassifier 设计

```python
class CommandRiskLevel(str, Enum):
    AUTO = "auto"       # 🟢 直接执行
    CONFIRM = "confirm"  # 🟡 弹窗确认
    BLOCK = "block"      # 🔴 硬拒绝
    DENIED = "denied"    # 🔴 禁止（角色无权限）

@dataclass
class CommandClassification:
    risk_level: CommandRiskLevel
    command_category: str  # 文件删除/系统管理/网络...
    timeout_seconds: int   # CONFIRM级超时
    reason: str            # 分类理由
```

**classify() 逻辑**：
1. 检查角色权限（visitor无shell，user无rm/kill等）→ DENIED
2. 检查全局黑名单 → BLOCK
3. 检查YAML CRITICAL规则 → BLOCK
4. 查询CONFIRM命令表 → CONFIRM（带超时）
5. 默认 → AUTO

### 4.4 确认流程（含前端交互）

```
LLM产生 tool_call: execute_shell_command("rm -rf /tmp/cache")
  │
  ▼
ToolGuardMixin._decide_guard_action()
  ├── ToolGuardEngine.guard() → findings (HIGH: rm detected)
  ├── CommandRiskClassifier.classify("rm", "advanced")
  │   → risk_level=CONFIRM, timeout=60s
  └── 返回 _GuardAction("needs_approval", ...)
  │
  ▼
_acting_with_approval()
  ├── ApprovalService.create_pending(timeout=60)
  ├── _emit_waiting_for_approval_blocking()
  │   Msg(metadata={
  │     message_type: "tool_guard_approval",
  │     approval_request_id: "uuid",
  │     risk_level: "CONFIRM",
  │     command_category: "文件删除",
  │     timeout_seconds: 60,
  │     ...
  │   })
  │
  ▼ SSE推送到前端
  │
  ▼ ConsolePollService轮询获取 pending_approvals
  │
  ▼ ApprovalContext.setApprovals([...])
  │
  ▼ Chat/index.tsx 渲染 ApprovalCard
  │
  ┌─────────────────────────────────────┐
  │ 🛡️ 命令确认请求                      │
  │                                     │
  │ 工具: execute_shell_command          │
  │ 命令: rm -rf /tmp/cache             │
  │ 角色: advanced                      │
  │ 风险等级: 🟡 需要确认                │
  │                                     │
  │ 风险说明:                           │
  │ - [HIGH] Shell command contains 'rm'│
  │   which may cause data loss         │
  │                                     │
  │ 参数:                               │
  │ {"command": "rm -rf /tmp/cache"}    │
  │                                     │
  │ [✅ 允许]  [❌ 拒绝]                 │
  │ ⏱️ 58秒后自动拒绝                    │
  └─────────────────────────────────────┘
  │
  ├── 用户点击「允许」
  │   → handleApprove(requestId)
  │   → POST /approval/approve {request_id, session_id}
  │   → ApprovalService.resolve(APPROVED)
  │   → Future.resolve() → 后端继续执行
  │   → 工具结果通过SSE返回
  │
  ├── 用户点击「拒绝」
  │   → handleDeny(requestId)
  │   → POST /approval/deny {request_id, session_id}
  │   → Future.resolve(DENIED)
  │   → 后端拒绝执行 + 审计日志
  │
  └── 超时(60s)
      → Future.resolve(TIMEOUT)
      → 后端拒绝执行 + 审计日志
```

### 4.5 ApprovalCard 增强

| 增强项 | 当前状态 | 目标状态 |
|--------|---------|---------|
| findingsSummary显示 | 纯文本 | 支持markdown渲染 |
| risk_level标签 | 无 | 显示AUTO/CONFIRM/BLOCK级别 |
| command_category | 无 | 显示命令类别（文件删除/系统管理等） |
| 超时时间 | 固定从后端获取 | 根据risk_level动态显示（普通60s/高危30s） |
| 审批历史 | 不入memory | 增加「已记录审计日志」提示 |

### 4.6 admin角色特殊处理

| 维度 | 当前 | 目标 |
|------|------|------|
| shell白名单 | `["*"]` 通配 | 改为与advanced相同的角色列表 |
| AUTO级 | 直接执行 | 与advanced相同 |
| CONFIRM级 | 无（直接放行） | 弹窗确认（与advanced相同） |
| BLOCK级 | 仅黑名单12条 | 硬拒绝（与所有角色相同） |
| 审计要求 | 仅高危操作 | 所有admin操作写审计日志（含AUTO级） |

### 4.7 超时策略

| 场景 | 超时时间 | 超时行为 | 可配置 |
|------|---------|---------|:---:|
| 普通确认（rm/mv/cp/pip install） | 60s | deny + 审计 | ✅ |
| 高危确认（kill/systemctl/crontab） | 30s | deny + 审计 | ✅ |
| CRITICAL级（直接BLOCK） | N/A | 直接拒绝 | - |

**配置方式**：
- `config.json → security.tool_guard.confirm_timeout_seconds`
- `config.json → security.tool_guard.high_risk_confirm_timeout_seconds`
- 环境变量：`COAPIS_CONFIRM_TIMEOUT` / `COAPIS_HIGH_RISK_CONFIRM_TIMEOUT`

### 4.8 实现要点

1. **新增 `CommandRiskClassifier`**：`server/coapis/security/command_risk_classifier.py`
2. **修改 `ToolGuardMixin._decide_guard_action()`**：集成CommandRiskClassifier
3. **修改 `ApprovalService`**：支持自定义timeout_seconds
4. **修改 `ApprovalCard`**：支持markdown渲染、risk_level标签
5. **修改前端ApprovalContext**：增加risk_level、command_category字段
6. **新增审计日志字段**：risk_level、command_category、confirm_result、timeout_flag

---

## 五、实施路线图

### Phase 1：命令确认机制（P0-3, 1-2周）

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 1 | 新增 `CommandRiskClassifier` | 新建 `security/command_risk_classifier.py` |
| 2 | 修改 `ToolGuardMixin._decide_guard_action()` | `agents/tool_guard_mixin.py` |
| 3 | 修改 `ApprovalService` 支持自定义timeout | `app/approvals/service.py` |
| 4 | 新增审计日志字段 | `agent/security/audit_logger.py` |
| 5 | ApprovalCard增强（markdown/risk_level） | `client/src/components/ApprovalCard/ApprovalCard.tsx` |
| 6 | ApprovalContext增加字段 | `client/src/contexts/ApprovalContext.tsx` |

### Phase 2：Docker安全加固（P0-1, P0-4, P0-6, 1周）

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 1 | Dockerfile添加非root用户 | `server/deploy/Dockerfile` |
| 2 | docker-compose添加资源限制 | `docker/docker-compose.dev.yaml` |
| 3 | 添加seccomp配置文件 | 新建 `docker/seccomp-profile.json` |
| 4 | ResourceLimiter集成到主流程 | `agent/core.py` + `security/sandboxed_executor.py` |

### Phase 3：权限规则完善（P0-2, P0-8, P1-1, P1-2, 1周）

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 1 | admin角色改为CONFIRM级别 | `agents/security/workspace_guard.py` |
| 2 | 优化白名单匹配（prefix+args） | `agents/security/workspace_guard.py` |
| 3 | 新增docker/yum/apt YAML规则 | `security/tool_guard/rules/dangerous_shell_commands.yaml` |
| 4 | 修复前端路由冲突 | `client/src/` |

### Phase 4：技能触发安全（P0-7, P2-8, 1周）

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 1 | 技能触发注册前增加安全扫描 | `agents/react_agent.py` |
| 2 | 用户覆盖触发词增加白名单校验 | `agents/react_agent.py` |
| 3 | 扫描失败时阻止注册 | `agents/react_agent.py` |

### Phase 5：隔离增强（P1-4, P1-5, P1-6, P1-8, 2周）

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 1 | ProcessIsolator环境变量白名单收紧 | `security/process_isolator.py` |
| 2 | ProcessIsolator集成到shell执行 | `security/sandboxed_executor.py` |
| 3 | docker-compose添加seccomp | `docker/docker-compose.dev.yaml` |
| 4 | 只读根文件系统挂载 | `docker/docker-compose.dev.yaml` |

### Phase 6：监控增强（P1-3, P2-6, P3-4, 1周）

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 1 | ToolCallMonitor添加阻断能力 | `security/tool_monitor.py` |
| 2 | denied操作写入审计日志 | `agent/security/audit_logger.py` |
| 3 | 审计日志前端可视化页面 | `client/src/` |

### Phase 7：代码沙箱集成（P2-3, P2-4, 1周）

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| 1 | ImportSandbox自动activate | `agent/core.py` |
| 2 | ASTSandbox集成到python3 -c链路 | `security/sandboxed_executor.py` |
| 3 | 敏感文件列表扩充 | `security/tool_guard/guardians/file_guardian.py` |

---

## 六、总结

### 缺口统计

| 严重度 | 数量 | 占比 |
|--------|------|------|
| P0 致命 | 8 | 27% |
| P1 高危 | 8 | 27% |
| P2 中等 | 8 | 27% |
| P3 低优 | 6 | 20% |
| **合计** | **30** | 100% |

### 实施优先级

| Phase | 目标 | 预计周期 | 覆盖缺口 |
|-------|------|---------|---------|
| Phase 1 | 命令确认机制 | 1-2周 | P0-3 |
| Phase 2 | Docker安全加固 | 1周 | P0-1, P0-4, P0-6 |
| Phase 3 | 权限规则完善 | 1周 | P0-2, P0-8, P1-1, P1-2 |
| Phase 4 | 技能触发安全 | 1周 | P0-7, P2-8 |
| Phase 5 | 隔离增强 | 2周 | P1-4, P1-5, P1-6, P1-8 |
| Phase 6 | 监控增强 | 1周 | P1-3, P2-6, P3-4 |
| Phase 7 | 代码沙箱集成 | 1周 | P2-3, P2-4 |
| **总计** | | **8-9周** | **覆盖P0全部 + P1全部 + P2全部** |

### 关键原则

1. **最小权限原则**: 每个角色仅获得完成任务所需的最小权限
2. **纵深防御**: 多层防护，单点突破不等于全面沦陷
3. **审计可追溯**: 所有操作（含AUTO级admin操作）可审计
4. **用户友好**: 确认弹窗清晰展示风险，不增加过多操作负担
5. **渐进式加固**: 按优先级分阶段实施，每阶段独立可用