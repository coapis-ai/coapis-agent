# CoApis 安全加固指南

> **CoApis** — 企业级多用户多智能体 AI 平台，内置 56+ 工具、多层记忆体系、团队协作多级智能体及技能进化引擎，为团队提供安全可控的 AI 工作空间。

---

## 📋 目录

- [安全架构总览](#安全架构总览)
- [核心安全能力一览](#核心安全能力一览)
- [P0 — 关键缺陷修复](#p0--关键缺陷修复)
- [P1 — 高危缺口加固](#p1--高危缺口加固)
- [P2 — 中等缺口修复](#p2--中等缺口修复)
- [P3 — 低优先级改进](#p3--低优先级改进)
- [环境变量参考](#环境变量参考)
- [FAQ](#faq)

---

## 安全架构总览

CoApis 采用 **七层纵深防御** 架构，在多用户、多智能体的企业场景下，确保每一条指令从输入到执行都在安全框架的监控之下：

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 7 — 审计与合规        审计日志 / SQLite 持久化 / 完整性链      │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 6 — 行为监控与阻断    ToolCallMonitor / 异常检测 / 自动封禁   │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 5 — 命令风险分类      CommandRiskClassifier / 三级分类引擎    │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 4 — 工具防护引擎      YAML 规则匹配 / 29 条危险命令规则       │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 3 — 沙箱与隔离        进程隔离 / namespace / 资源限制          │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 2 — 权限与角色        四级角色 RBAC / 白名单语义匹配          │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 1 — 工作区守卫        WorkspaceGuard / 文件路径校验           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 核心安全能力一览

| 能力 | 说明 | 版本 |
|------|------|------|
| 🛡️ **七层纵深防御** | 从工作区守卫到审计合规，每层独立拦截，纵深互补 | v0.8.0 |
| ⚡ **三级命令分类** | AUTO（自动放行）/ CONFIRM（审批确认）/ BLOCK（硬拒绝），按角色×操作类型精确控制 | v0.8.0 |
| 👥 **四级角色 RBAC** | user / advanced / admin / owner，每级独立白名单，admin 不再拥有无限权限 | v0.8.0 |
| 🔒 **56+ 内置工具** | 文件操作、Shell 执行、浏览器、代码沙箱、邮件、数据分析等，全部受工具防护引擎管控 | v0.8.0 |
| 🧠 **多层记忆体系** | 短期记忆 → 长期记忆 → 技能记忆 → 审计记忆，分层存储、分级访问 | v0.8.0 |
| 🤖 **多级智能体协作** | 主智能体 → 子智能体 → 技能智能体，层级调度、权限继承、上下文隔离 | v0.8.0 |
| 🌱 **技能进化引擎** | 从经验中学习、自动创建技能、优化流程、沉淀知识，持续自我进化 | v0.8.0 |
| 📊 **行为监控与自动封禁** | 滑动窗口检测异常行为，连续 critical 告警触发自动封禁（5 分钟冷却） | v0.8.0 |
| ⏱️ **Per-User 速率限制** | 滑动窗口限流（默认 30 次/分钟），防止单用户资源耗尽 | v0.8.0 |
| 🔐 **环境变量最小化** | 子进程仅暴露 PATH/LANG/LC_ALL/TERM 四个必要变量，杜绝身份信息泄露 | v0.8.0 |
| 🐳 **Docker 安全加固** | 资源限制（2G 内存 / 2 CPU）、internal 网络隔离、tmpfs 挂载 | v0.8.0 |
| 📝 **完整审计链路** | 所有操作（包括被拒绝的）写入 SQLite audit_logs 表，含 risk_level / command_category / confirm_result | v0.8.0 |

---

## P0 — 关键缺陷修复

### P0-2: Admin 角色权限约束

**问题：** Admin 角色 Shell 命令白名单为通配符 `["*"]`，绕过了所有安全检查。

**修复：** 将 admin 白名单与 advanced 角色统一（30 条命令），使 CommandRiskClassifier 的 CONFIRM/BLOCK 级别对 admin 同样生效。

**验证：**
```bash
# admin 执行 rm -rf 应触发审批确认
curl -X POST /api/tools/execute -d '{"tool":"execute_shell_command","input":{"command":"rm -rf /tmp/test"}}'
# 预期：返回 CONFIRM 审批卡片，而非直接执行
```

### P0-3: 危险命令确认机制

**问题：** `rm -rf`、`sudo`、`curl | bash` 等危险命令可被直接执行，无任何确认流程。

**修复：** 新增 `CommandRiskClassifier`，实现三级命令分类：
- **AUTO** — 安全命令，自动放行
- **CONFIRM** — 需审批确认，前端弹出 ApprovalCard
- **BLOCK** — 高危命令，硬拒绝

覆盖 17 种命令类别、60+ 条正则匹配规则。

**验证：** 前端发送 `sudo rm -rf /` → 弹出审批卡片 → 用户确认/拒绝 → 审计日志记录。

### P0-6: ResourceLimiter 集成

**问题：** ResourceLimiter 已实现但未接入实际执行流程，CPU/内存/进程数限制形同虚设。

**修复：** 在 shell.py 的 subprocess 创建前，通过 `preexec_fn` 注入 `ResourceLimiter._set_unix_limits`，实现内核级资源强制限制（CPU 10s / 内存 256MB / 进程数 50）。

### P0-7: 技能触发安全扫描

**问题：** 按需技能注册时未做安全扫描，恶意技能可被自动加载。

**修复：** 在 `react_agent.py` 的技能注册路径中插入 `scan_skill_directory()` 检查，BLOCKED/HIGH 风险技能不会被注册。

### P0-8: Docker 资源限制

**问题：** Docker 容器无资源限制，单容器可耗尽宿主机资源。

**修复：** server 容器限制 2G 内存 / 2 CPU，nginx 容器限制 256M 内存 / 0.5 CPU。

---

## P1 — 高危缺口加固

### P1-1: 白名单语义匹配

**问题：** 白名单使用 `fnmatch` 粗糙匹配，`python3 -c "import os; os.system('rm -rf /')"` 可绕过 `python3 *.py` 规则。

**修复：** 重写匹配逻辑为 prefix + args 语义匹配，区分三种条目：
- **base-only** — 仅匹配命令本身（如 `ls`）
- **wildcard** — 匹配任意参数（如 `cat *`）
- **file-pattern** — 要求至少一个文件参数，且禁止 `-c/-e/-i` 等内联标志

### P1-3: ToolCallMonitor 阻断能力

**问题：** ToolCallMonitor 仅告警不阻断，恶意用户可持续发起攻击。

**修复：** 新增 `should_block()` 方法，基于独立计数器（不受告警去重影响）判断阻断：
- 连续 3 次 critical 级事件 → 封禁 5 分钟
- 累计 8 次异常事件 → 封禁 5 分钟
- 解封后 60 秒冷却期，防止旧告警重触发

### P1-4: 文件系统 Namespace 隔离

**修复：** 新增 `_make_ns_preexec()` 函数，通过 `unshare(CLONE_NEWNS)` 创建独立挂载命名空间：
- 工作目录 bind mount 保持可写
- 根目录 remount 为只读
- 通过 `COAPIS_ENABLE_NS=1` 环境变量启用（默认关闭）

### P1-5: 环境变量最小化

**问题：** 子进程继承完整环境变量，泄露 HOME/USER/SHELL 等身份信息。

**修复：** ProcessIsolator 白名单从 12 个缩减到 4 个（PATH/LANG/LC_ALL/TERM），新增值消毒（null 字节剥离、超长截断）。

### P1-7: 解释器内联防护

**问题：** `python3 -c "恶意代码"` 可绕过 `python3 *.py` 白名单。

**修复：** `_args_are_files_only()` 方法显式拦截所有解释器内联标志（`-c/-e/-E/-i/-I/--eval/--command`），所有角色均已覆盖。

---

## P2 — 中等缺口修复

| 编号 | 修复项 | 说明 |
|------|--------|------|
| P2-1 | 前端规则动态展示 | API 从 YAML 动态读取 29 条规则，前端无硬编码限制 |
| P2-2 | 敏感文件列表扩展 | 从 20 条扩展到 65 条，覆盖 .npmrc/.pem/id_rsa/.env.*/shadow 等 |
| P2-3 | ImportSandbox 集成 | `python3 -c` 命令静态检查 18 个危险模块导入 |
| P2-4 | ASTSandbox 集成 | 拦截 exec/eval/\_\_import\_\_/getattr 等 AST 危险结构 |
| P2-5 | 审批超时配置化 | `COAPIS_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS` 环境变量 |
| P2-6 | Denied 操作审计 | 所有被拒绝/被阻断的操作写入 audit_logs 表 |
| P2-7 | ApprovalCard Markdown | 审批卡片 findingsSummary 支持 Markdown 格式化渲染 |
| P2-8 | 技能触发词防护 | 路径穿越校验 + 文件大小限制 + 通用词过滤 |

---

## P3 — 低优先级改进

| 编号 | 改进项 | 说明 |
|------|--------|------|
| P3-1 | Executor 速率限制 | Per-user 滑动窗口（默认 30 次/分钟），可通过环境变量调整 |
| P3-2 | Docker 网络隔离 | Internal 网络，容器间通信受限 |
| P3-3 | Docker tmpfs 挂载 | /tmp 挂载为 tmpfs（noexec + nosuid），server 256M / nginx 64M |
| P3-5 | 轮询间隔可配置 | ConsolePollService 间隔通过 localStorage 配置 |
| P3-6 | 审批消息入记忆 | 审批决策写入 memory，支持历史回溯 |

---

## 环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `COAPIS_ENABLE_NS` | `0` | 启用文件系统 namespace 隔离（需 SYS_ADMIN 权限） |
| `COAPIS_RATE_LIMIT_MAX` | `30` | Per-user 工具调用速率限制（次/窗口） |
| `COAPIS_RATE_LIMIT_WINDOW` | `60` | 速率限制窗口大小（秒） |
| `COAPIS_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS` | `300` | 审批超时时间（秒） |
| `COAPIS_AUTH_ENABLED` | `True` | 启用认证系统 |
| `COAPIS_USER_SYSTEM_ENABLED` | `True` | 启用多租户用户体系 |

---

## FAQ

### Q: Admin 用户还会被安全检查拦截吗？

**会。** 自 v0.8.0 起，admin 角色的白名单与 advanced 角色统一（30 条命令）。所有 CONFIRM/BLOCK 级别的命令对 admin 同样生效。只有 owner 角色在特定场景下拥有更高权限。

### Q: ToolCallMonitor 误封正常用户怎么办？

管理员可通过 API 手动解封：
```bash
POST /api/security/tool-monitor/unblock
Body: {"username": "被误封的用户"}
```
封禁持续 5 分钟后自动解封。解封后有 60 秒冷却期，防止旧告警重新触发。

### Q: Namespace 隔离需要什么 Docker 配置？

需要为容器添加 `--cap-add SYS_ADMIN` 或使用 `--privileged` 模式。开发环境中可通过设置 `COAPIS_ENABLE_NS=1` 启用。生产环境建议在 docker-compose 中添加：
```yaml
cap_add:
  - SYS_ADMIN
```

### Q: 如何自定义危险命令规则？

编辑 `server/coapis/security/tool_guard/rules/dangerous_shell_commands.yaml`，每条规则格式：
```yaml
- id: MY_CUSTOM_RULE
  pattern: "your_regex_pattern"
  severity: high
  description: "规则描述"
  action: block  # block / confirm
```
修改后无需重启服务，API 会动态读取。

### Q: 如何查看审计日志？

通过管理 API 查询：
```bash
GET /api/audit/logs?event_type=tool_guard_denied&limit=50
```
所有操作（包括被拒绝的）都会记录在 SQLite `audit_logs` 表中，包含 risk_level、command_category、confirm_result 字段。

### Q: 环境变量变更后需要重启服务吗？

**需要。** 大部分安全相关的环境变量在服务启动时读取。变更后执行：
```bash
docker compose -f docker/docker-compose.dev.yaml restart server
```

### Q: 速率限制是否区分工具类型？

当前为全局 per-user 限流，不区分工具类型。所有工具调用（文件操作、Shell 执行、浏览器等）共用同一个滑动窗口。可通过调整 `COAPIS_RATE_LIMIT_MAX` 和 `COAPIS_RATE_LIMIT_WINDOW` 自定义限流策略。

---

> 📌 **版本：** v0.8.0 | **最后更新：** 2026-06-13 | **维护团队：** CoApis Security
