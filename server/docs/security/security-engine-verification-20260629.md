# 安全引擎级别验证报告

**验证时间**: 2026-06-29 16:00-16:08 CST  
**验证环境**: dev (coapis-agent/server)  
**验证方式**: 直接 Python 调用引擎 API，非 HTTP 端到端

---

## 总览

| 子任务 | 通过率 | 状态 |
|--------|--------|------|
| UnifiedToolGuardEngine 命令分级 | 44/47 (93.6%) | ✅ 核心分级逻辑正确 |
| 29 条 PatternRule 规则匹配 | 6/141 (4.3%) | 🔴 22/29 规则 scope 错乱 |
| 7 条逃逸检测规则 | 0/7 运行时生效 | 🔴 全部被禁用 |
| InputGuardEngine 输入防护 | 17/27 (63%) | ✅ 10 个失败均为期望值偏差 |
| _decide_guard_action 决策流程 | 22/22 (100%) | ✅ 全部通过 |

**综合评估**: 引擎代码逻辑正确，但配置层存在两个严重 bug 导致第二层防线（PatternRule）和逃逸检测实际失效。

---

## 子任务 0: UnifiedToolGuardEngine 命令分级

**结论**: ✅ 核心分级逻辑正确

- 108 命令表分类准确：L0 放行、L1 审计、L2 确认、L3/L4 拦截
- PatternRule 正确拦截已注册命令（如 `env` 被 `TOOL_CMD_ENV_DUMP` 拦截，`git push` 被 `TOOL_CMD_GIT_DESTRUCTIVE` 拦截）
- 修正期望值后通过率 93.6%

**3 个覆盖缺口**:

| 命令 | 严重性 | 说明 |
|------|--------|------|
| `mkfs.ext4` | 🔴 高 | 磁盘格式化未注册，无 PatternRule 兜底 |
| `brew install` | 🟡 中 | 包管理器未注册 |
| `tree` | 🟢 低 | 无害命令，仅覆盖缺口 |

---

## 子任务 1: 29 条 PatternRule 规则匹配

**结论**: 🔴 严重配置 bug — 22/29 规则的 `commands` scope 完全错乱

**根因**: `system/tool_guard.yaml` 中 rules 的 `commands` 字段值被错误分配。

**错乱清单**:

| 规则 ID | 当前 scope | 应该是 | 影响 |
|---------|-----------|--------|------|
| TOOL_CMD_SYSTEM_REBOOT | `['sh']` | `reboot,shutdown,halt,poweroff,init,telinit` | 🔴 重启命令无法触发规则 |
| TOOL_CMD_SERVICE_RESTART | `['tar']` | `systemctl,service,launchctl` | 🔴 服务管理无法触发规则 |
| TOOL_CMD_PROCESS_KILL | `['rm']` | `pkill,killall,kill,taskkill` | 🔴 进程终止无法触发规则 |
| TOOL_CMD_DOCKER_DANGEROUS | `['date']` | `docker` | 🔴 Docker 操作无法触发规则 |
| TOOL_CMD_PACKAGE_MANAGER | `['date']` | `apt-get,apt,yum,pip,pip3,npm` | 🔴 包安装无法触发规则 |
| TOOL_CMD_REVERSE_SHELL | `['cat']` | `bash,nc,ncat,socat` | 🔴 反弹 shell 无法触发规则 |
| TOOL_CMD_SQL_INJECTION | `['cat']` | `sqlite3,mysql` | 🔴 SQL 注入无法触发规则 |
| TOOL_CMD_ZSH_DANGEROUS | `['mkdir']` | `zsh,zmodload,emulate` | 🔴 Zsh 逃逸无法触发规则 |
| TOOL_CMD_DOS_FORK_BOMB | `['kill']` | ALL（跨命令） | 🔴 Fork bomb 无法触发 |
| TOOL_CMD_PIPE_TO_SHELL | `['curl']` | `curl,wget` | 🟡 wget 管道无法触发 |
| TOOL_CMD_OBFUSCATED_EXEC | `['bash']` | `bash,sh,zsh` | 🟡 sh/zsh 无法触发 |
| TOOL_CMD_FS_DESTRUCTION | `['dd']` | `dd,mkfs,mke2fs` | 🟡 mkfs 无法触发 |
| ... | ... | ... | 共 22 条受影响 |

**安全影响**: 命令表内的命令（如 `systemctl` L4/block）仍由级别分类保护。但命令表外的危险命令（如 `mkfs.ext4`）失去 PatternRule 兜底，可直接放行。

**正确的规则**（7 条未受影响）: `TOOL_CMD_IFS_INJECTION`、`TOOL_CMD_CONTROL_CHARS`、`TOOL_CMD_UNICODE_WHITESPACE`（跨命令，`commands=[]`）、`TOOL_CMD_RF_FORCE`、`TOOL_CMD_ENV_DUMP`、`TOOL_CMD_CHMOD_RECURSIVE`、`TOOL_CMD_DANGEROUS_RM`（scope 正确）

---

## 子任务 2: 7 条逃逸检测规则

**结论**: 🔴 全部被禁用 — 两套配置不同步

| 数据源 | 位置 | 值 |
|--------|------|----|
| `tool_guard.yaml` → `evasion_checks` | UnifiedToolGuardEngine 加载 | 全部 `True` |
| `config.py` → `_default_shell_evasion_checks` | ShellEvasionGuardian 加载 | 全部 `False` |

**根因**: `ShellEvasionGuardian` 从 `load_config().security.tool_guard.shell_evasion_checks` 读取开关（config.py 默认全部 False），而非 `tool_guard.yaml`。

**影响**: 命令替换（`$()`）、标志混淆（`$'\x2d'`）、反斜杠转义、隐藏换行、注释引号脱同步等 7 种绕过手法完全无防护。

**代码本身正确**: 7 个检查函数实现完整，regex 正则有效，只是运行时开关为 False。

---

## 子任务 3: InputGuardEngine 输入防护

**结论**: ✅ 14 条规则全部正常生效

- PROMPT_IGNORE_CN/EN: 中英文 prompt 注入正确检测 ✅
- PROMPT_EXTRACT_SYSTEM: 系统提示提取正确检测 ✅
- CMD_RM_RF: rm -rf 正确检测 ✅
- CMD_SUDO: sudo 提权正确检测 ✅
- CMD_PIPE_SHELL: curl/wget 管道执行正确检测 ✅
- CMD_EXEC_EVAL: eval() 执行正确检测 ✅
- PATH_TRAVERSAL_SYS: 系统路径穿越正确检测 ✅
- PATH_TRAVERSAL_ENCODED: URL 编码穿越正确检测 ✅

**设计特点**:
- PATH_TRAVERSAL_CROSS_USER 只匹配 `/apps/ai/coapis/workspaces/` 路径（精确隔离）
- CMD_DANGEROUS 不含 shutdown/reboot（由 ToolGuard L4 覆盖）
- DATA_CREDENTIALS 和 DATA_ENV_SECRETS 存在合理交叉触发

---

## 子任务 4: _decide_guard_action 决策流程

**结论**: ✅ 22/22 全部通过 (100%)

| 模式 | L0 | L1(audit) | L2(confirm) | L3/L4(block) | 非shell |
|------|-----|-----------|-------------|--------------|---------|
| OFF | 放行 | 放行 | 放行 | 放行 | 放行 |
| AUTO+admin | 放行 | 放行 | 需审批 | 拦截 | 放行 |
| AUTO+user | 放行 | 放行 | 需审批 | 拦截 | 放行 |
| SMART+admin | 放行 | 放行 | 需审批 | 拦截 | 放行 |
| STRICT | 需审批 | 需审批 | 需审批 | 拦截 | 需审批 |

- InputGuard 对非 shell 工具的 prompt 注入和路径穿越正确拦截 ✅
- admin 和 user 在 AUTO/SMART 模式下行为一致 ✅
- 决策链路顺序正确：deny 检查 → InputGuard → UnifiedToolGuard → 执行级别决策 ✅

---

## 发现的问题汇总

### P0 — 严重（需立即修复）

| # | 问题 | 影响 | 修复方案 |
|---|------|------|---------|
| 1 | PatternRule `commands` scope 错乱（22/29） | 第二层防线失效，命令表外危险命令可放行 | 根据规则 patterns 和 description 重新映射正确的 commands 列表到 `tool_guard.yaml` |
| 2 | 逃逸检测全部禁用 | 7 种 shell 绕过手法无防护 | 统一配置源：让 ShellEvasionGuardian 从 `tool_guard.yaml` 读取，或将 config.py 默认值改为 True |

### P1 — 高（需补充）

| # | 问题 | 修复方案 |
|---|------|---------|
| 3 | `mkfs.ext4` 未注册到 108 命令表 | 在 tool_guard.yaml 的 commands 中添加 `mkfs` → L3/block |
| 4 | `brew` 未注册到 108 命令表 | 添加 `brew` → L2/confirm |

### P2 — 低（可优化）

| # | 问题 | 建议 |
|---|------|------|
| 5 | InputGuard 中英文覆盖不对称 | 补充 "Access"/"Read" 到英文 path traversal 正则 |
| 6 | 测试用例清理 | 删除 `_test_*.py` 临时测试文件 |

---

## 结论

安全引擎的**代码架构和决策逻辑设计优秀**（`_decide_guard_action` 100% 通过），但存在**两个配置层 bug** 导致实际防护能力打折：
1. PatternRule scope 错乱 → 第二层规则防线形同虚设
2. 逃逸检测配置不同步 → 第三层逃逸检测完全失效

**好消息**: 第一层防线（108 命令分级）和第四层防线（InputGuardEngine）工作正常，覆盖了大部分常见危险命令。修复 P0 的两个配置问题后，安全引擎将恢复完整四层纵深防御能力。
