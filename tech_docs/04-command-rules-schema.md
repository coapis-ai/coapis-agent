# 命令分级 rules 字段数据模型设计

> 版本: 1.0 | 日期: 2026-07-07

## 1. 背景与动机

### 现有 `demotion` 的局限

当前 `tool_guard.yaml` 中的 `demotion` 机制存在三个核心问题：

| 问题 | 说明 |
|------|------|
| **只支持降级** | 引擎代码 `rule_level_val < best_level_val` 硬编码了只取更低级别 |
| **路径感知太粗** | `safe_paths` 只能做前缀匹配，无法区分"用户空间"vs"系统空间" |
| **危险模式散落** | 有些命令特定的危险模式（如 `rm -rf /`）只能放在全局 `global_rules` 中 |

### 设计目标

1. **统一规则模型**：`rules` 同时支持升级和降级
2. **路径感知**：引入 `scope: workspace` 动态匹配用户空间
3. **配置驱动**：危险模式通过 rules 配置，不再硬编码
4. **向后兼容**：保留 `demotion` 字段作为 deprecated alias，引擎优先读 `rules`

## 2. 数据模型

### 2.1 命令级 rules 字段

```yaml
# tool_guard.yaml - 命令配置
rm:
  level: L3                    # 命令基础级别
  desc: 删除文件/目录
  action: confirm              # 命令默认 action（覆盖 level 的默认值）

  rules:                       # 可选：规则列表，按顺序匹配，首条命中生效
    - id: rm_system_critical   # 规则唯一标识
      desc: 禁止删除系统关键路径
      level: L4
      action: block
      patterns:                # 正则匹配命令行（含参数和路径）
        - '\s/(etc|usr|bin|sbin|boot|lib|var/lib)\b'
        - '\s--no-preserve-root'
        - '\s/\s*$'            # rm / 或 rm /*

    - id: rm_user_sensitive
      desc: 删除用户敏感文件需确认
      level: L3
      action: confirm
      patterns:
        - '\.ssh/'
        - '\.gnupg/'
        - '\.aws/'
        - 'authorized_keys'

    - id: rm_workspace
      desc: 工作空间内删除仅记录
      level: L1
      action: audit
      scope: workspace         # 特殊关键字：仅匹配用户 workspace 内路径

    - id: rm_tmp
      desc: 临时目录删除放行
      level: L0
      action: allow
      safe_paths:              # 路径前缀白名单
        - /tmp/
        - /var/tmp/
```

### 2.2 单条 Rule 的 Schema

```python
class CommandRule(BaseModel):
    """单条命令规则"""
    id: str                           # 规则唯一标识，如 "rm_system_critical"
    desc: str = ""                    # 规则描述
    level: str                        # 命中时的级别: L0-L4
    action: str                       # 命中时的 action: allow/audit/confirm/block

    # ── 匹配条件（全部可选，多个条件之间为 AND 关系）──
    patterns: list[str] = []          # 正则：命令行必须匹配至少一个
    exclude_patterns: list[str] = []  # 正则：命令行不能匹配任何一个
    safe_paths: list[str] = []        # 路径前缀：所有绝对路径必须在此范围内
    scope: str | None = None          # 特殊作用域，目前支持 "workspace"
```

### 2.3 匹配条件逻辑

```
对于每条 rule，按以下顺序检查（AND 逻辑）：

1. scope 检查
   - scope=None → 跳过
   - scope="workspace" → 命令中的所有绝对路径必须在用户 workspace 目录内
                          相对路径视为 workspace 内（安全）

2. safe_paths 检查
   - safe_paths=[] → 跳过
   - 有 safe_paths → 命令中的所有绝对路径必须匹配至少一个前缀

3. patterns 检查
   - patterns=[] → 跳过（视为匹配）
   - 有 patterns → 命令行必须匹配至少一个正则（OR 逻辑）

4. exclude_patterns 检查
   - exclude_patterns=[] → 跳过
   - 有 exclude_patterns → 命令行不能匹配任何一个正则（OR 逻辑）

全部通过 → 规则命中
```

### 2.4 优先级与冲突解决

```
规则匹配优先级：
1. rules 列表按顺序匹配，首条命中生效（first-match-wins）
2. 命中 rule 的 level/action 覆盖命令默认值
3. 如果没有任何 rule 命中，使用命令默认 level/action
4. 与 sub_commands 的关系：sub_commands 优先级高于 rules
```

## 3. 与现有 demotion 的对比

| 特性 | demotion（旧） | rules（新） |
|------|----------------|-------------|
| 方向 | 只降级 | 升级 + 降级均可 |
| 优先级 | 取最低级别 | 首条命中 |
| 路径感知 | `safe_paths` 前缀 | `safe_paths` + `scope: workspace` |
| 匹配条件 | patterns + exclude_patterns | 同左 |
| 命名 | "demotion"（暗示降级） | "rules"（中性） |
| 向后兼容 | — | 引擎同时支持 demotion（deprecated） |

## 4. 引擎层变更要点

### 4.1 替换 `_apply_demotion_rules` 为 `_apply_command_rules`

```python
def _apply_command_rules(
    command_str: str,
    cmd_name: str | None,
    current_level: str,
    current_action: str,
    command_rules: list[CommandRule],
    workspace_dir: str | None = None,  # 新增：用户 workspace 路径
) -> tuple[str, str, str]:
    """Apply command rules (first-match-wins).

    Returns (new_level, new_action, reason).
    """
    if not command_rules:
        return current_level, current_action, ""

    paths = _extract_paths_from_command(command_str)

    for rule in command_rules:
        if _match_rule(command_str, paths, rule, workspace_dir):
            return rule.level, rule.action, f"rule:{rule.id} — {rule.desc}"

    return current_level, current_action, ""
```

### 4.2 新增 `_match_rule` 函数

```python
def _match_rule(
    command_str: str,
    paths: list[str],
    rule: CommandRule,
    workspace_dir: str | None,
) -> bool:
    """Check if a single rule matches the command."""

    # 1. scope: workspace
    if rule.scope == "workspace":
        if not workspace_dir:
            return False  # 无 workspace 信息，不匹配
        for p in paths:
            if p.startswith("/") and not p.startswith(workspace_dir):
                return False  # 有路径在 workspace 外

    # 2. safe_paths
    if rule.safe_paths and paths:
        for p in paths:
            if p.startswith("/") and not any(p.startswith(sp) for sp in rule.safe_paths):
                return False

    # 3. patterns（OR 逻辑：至少匹配一个）
    if rule.patterns:
        if not any(re.search(p, command_str, re.I) for p in rule.patterns):
            return False

    # 4. exclude_patterns（OR 逻辑：不能匹配任何一个）
    if rule.exclude_patterns:
        if any(re.search(ep, command_str, re.I) for ep in rule.exclude_patterns):
            return False

    return True
```

### 4.3 `scope: workspace` 的 workspace_dir 传递

workspace_dir 需要从调用链上层传入：

```
process_command(command_str, owner="admin", ...)
  → _apply_command_rules(..., workspace_dir="/apps/ai/coapis/workspaces/admin")
```

owner 信息在 `UnifiedToolGuardEngine.process_command()` 的 context 参数中已有。

## 5. 向后兼容策略

1. **Pydantic model**：`CommandEntry` 新增 `rules: list[CommandRule] = []`，保留 `demotion: dict = {}`
2. **引擎逻辑**：优先使用 `rules`，`rules` 为空时 fallback 到 `demotion`
3. **前端 API**：`/commands` 端点返回数据同时包含 `rules` 和 `demotion`（前端只展示 rules）
4. **迁移**：逐步将现有 `demotion` 转换为 `rules`，转换完成后删除 `demotion` 字段

## 6. 需要添加 rules 的命令清单

| 命令 | 当前 action | 建议默认 action | rules 设计 |
|------|-------------|-----------------|------------|
| `rm` | block | **confirm** | 系统路径→block, 敏感文件→confirm, 空间内→audit, /tmp→allow |
| `rmdir` | block | **confirm** | 系统路径→block, 空间内→audit |
| `kill` | block | **confirm** | SIGKILL(-9)→block, SIGTERM→confirm |
| `killall` | block | **confirm** | 同 kill |
| `pkill` | block | **confirm** | 同 kill |
| `taskkill` | block | **confirm** | /F 强制→block, 普通→confirm |
| `tar` | block | **audit** | 写系统路径→block, 只读→allow, 空间内→audit |
| `docker` | block | **confirm** | rm volume/system→block, run/exec→confirm, ps/images→allow |
| `docker-compose` | block | **confirm** | down -v→block, up→confirm, ps→allow |
| `systemctl` | block | **confirm** | restart/stop→confirm, status→allow |
| `service` | block | **confirm** | stop/restart→confirm, status→allow |
| `curl` | confirm | confirm | pipe to bash→block, GET→audit, POST/PUT→confirm |
| `wget` | confirm | confirm | pipe to bash→block, 下载→audit |
| `chmod` | audit | audit | 777→block, -R→confirm, 空间内→audit |
| `chown` | audit | audit | -R root→block, 空间内→audit |
| `dd` | block | **block** | of=/dev/→block (保持), 空间内文件→confirm |
| `ssh` | confirm | confirm | root@→block, 普通→confirm |
| `mv` | confirm | confirm | 覆盖系统文件→block, 空间内→audit |
