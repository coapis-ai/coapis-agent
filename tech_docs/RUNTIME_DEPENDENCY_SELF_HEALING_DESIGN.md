# CoApis 运行时依赖自愈与沙箱权限机制设计

> 状态：设计稿 v1.0
> 目标：解决“调用工具即聊天中断”的机制性问题，实现运行时依赖自动安装、用户空间权限自动降级、工具失败后自愈重试。
> 参考：借鉴 QwenPaw（AgentScope 官方框架）的 ToolGuard  guardian 架构、ToolHookRegistry 和 workspace 边界检测机制。

---

## 1. 问题诊断：五个环节断裂

当前出现的现象是：用户请求生成 Word 文档等任务时，一旦涉及 `docx` / `execute_shell_command` / `unzip` / `pip` 等工具，聊天直接中断。这不是单一 bug，而是五个子系统没有形成闭环：

```
用户请求
   ↓
① 声明层：技能/工具没有统一声明 pip/npm 包依赖
   ↓
② 发现层：运行时 import 失败或命令找不到才暴露
   ↓
③ 安装层：install_dependency 工具存在，但无自动触发策略
   ↓
④ 权限层：pip/npm/node/unzip 在用户空间仍被 audit/confirm
   ↓
⑤ 执行层：工具失败后没有重试/降级，直接把错误抛给 LLM
   ↓
聊天中断
```

### 1.1 当前代码证据

| 位置 | 现状 | 问题 |
|------|------|------|
| `coapis/agents/tools/install_dependency.py` | 已注册，支持 pip/npm 安装到共享运行时池 | 有工具但无人调用 |
| `coapis/agents/skills_manager.py:SkillRequirements` | 只有 `require_bins`、`require_envs` | 缺少 `require_packages` |
| `coapis/agents/tools/doc_reader.py` | `import docx` 失败 → 直接返回 error | 不会尝试安装并重试 |
| `coapis/agents/skills/builtin/docx/SKILL.md` | 写“if missing, report and stop” | 教 LLM 放弃而非安装 |
| `coapis/system/tool_guard.yaml` | `pip/npm/node/unzip` 在用户空间为 L1 audit | 权限过严，基础操作也被打断 |
| `react_agent` 工具执行入口 | 工具失败直接返回结果给 LLM | 无依赖自愈/失败重试层 |

---

## 2. 借鉴 QwenPaw 的成熟机制

`/apps/ai/tool-dev/devs/QwenPaw/src/qwenpaw` 提供了多个可直接借鉴的设计。

### 2.1 ToolGuard 四层执行级别

`qwenpaw/security/tool_guard/execution_level.py` 定义：

- `OFF`：完全关闭权限检查（开发/测试）。
- `AUTO`：只检查显式 guarded_tools（向后兼容）。
- `SMART`：基于风险严重度自动决定 allow / ask / deny。
- `STRICT`：所有工具都需审批。

借鉴点：CoApis 当前只有“命令级别 + 路径审计”的 YAML 规则，缺少按**严重度**和**用户空间边界**的决策模型。应引入 `SMART` 级别：用户 workspace 内的低风险操作自动 allow，系统目录/危险参数才触发审批。

### 2.2 Guardian 架构

`qwenpaw/security/tool_guard/engine.py` 把检查拆成多个 guardian：

- `SharedSafetyToolGuardian`：灾难性命令（如 `rm -rf /`）。
- `FilePathToolGuardian`：路径越界检查。
- `RuleBasedToolGuardian`：YAML 规则匹配。
- `ShellEvasionToolGuardian`：壳层逃逸检测。

借鉴点：把当前单一的 `tool_guard.yaml` 拆成**独立 guardian**，每个 guardian 只负责一个安全维度。新增 `WorkspaceBoundaryGuardian` 专门判断“操作是否在用户 workspace 内”，从而统一降级 pip/npm/node/unzip 等命令。

### 2.3 Workspace 边界检测作为核心 primitive

`qwenpaw/security/tool_guard/guardians/rule_guardian.py` 中 `_is_outside_workspace()` 使用 `is_path_outside_boundary()` 统一判断路径边界。这是 ACP（Agent Communication Protocol）和 ToolGuard 共享的 primitive。

借鉴点：CoApis 应统一使用 `derive_workspace_dir()` / `get_current_workspace_dir()` 作为边界判断函数，所有 guardian 和权限降级都基于它。

### 2.4 GuardedFunctionTool 统一包装器

`qwenpaw/runtime/tool_guard.py` 中的 `GuardedFunctionTool` 在 `FunctionTool` 外面包一层 `check_permissions()`，把所有工具调用统一接入 ToolGuard 引擎。

借鉴点：CoApis 的工具执行入口也应统一包装，确保每个工具调用都经过：
1. 依赖预检；
2. 权限检查；
3. 执行；
4. 失败后重试/降级。

### 2.5 ToolHookRegistry：before/after hooks

`qwenpaw/tool_calls/_hooks.py` 提供 `ToolHookRegistry`，支持按工具名注册 `before` / `after` hooks，并支持超时、deadline、offload 等元数据。

借鉴点：依赖自愈正好可以注册为 `before` hook（执行前检查并安装依赖），失败重试可以作为 `after` hook（根据结果决定是否重试）。

### 2.6 拒绝后防重试指令

`qwenpaw/runtime/tool_guard.py` 中 `_with_no_retry_instruction()` 在被拒绝的工具结果后追加系统指令：

> “this denial is final for the current request. Do not retry this tool with similar parameters.”

借鉴点：CoApis 工具失败后返回给 LLM 的结果应区分两类：
- **可恢复错误**（缺依赖、权限被临时拦截）：附带 `recovery_hint`，允许 LLM 重试或换策略。
- **最终拒绝**（系统目录、危险命令）：附带 no-retry 指令，防止 LLM 死循环。

---

## 3. 最终方案设计

### 3.1 总体架构

新增两个核心组件：

1. **`RuntimeDependencyManager`**（运行时依赖管理器）：
   - 收集技能和工具的依赖声明；
   - 在工具调用前执行依赖检查；
   - 缺失时调用 `install_dependency` 自动安装；
   - 缓存安装结果，避免重复安装；
   - 安装失败时返回结构化降级建议。

2. **`WorkspaceSandboxPolicy`**（用户空间沙箱策略）/ `WorkspaceBoundaryGuardian`：
   - 以用户 workspace 为边界；
   - 边界内基础操作（pip/npm/node/python/unzip/zip/strings/file/cat/grep/awk 等）直接 allow；
   - 边界外系统目录和危险参数仍然 block/confirm；
   - 被多种 guardian 共享。

3. **`ToolExecutionRecoveryLayer`**（工具执行自愈层）：
   - 在工具执行入口统一包装；
   - 捕获 `ImportError`、`ModuleNotFoundError`、`CommandNotFoundError`、`PermissionBlocked`；
   - 尝试安装依赖并重试；
   - 返回结构化结果给 LLM（带 `recovery_hint`）。

### 3.2 依赖声明扩展

#### 3.2.1 技能依赖声明

扩展 `SkillRequirements`：

```python
class PackageRequirement(BaseModel):
    name: str
    manager: Literal["pip", "npm", "apt"] = "pip"
    version: Optional[str] = None
    required: bool = True
    reason: str = ""  # 用于错误提示和日志

class SkillRequirements(BaseModel):
    require_bins: list[str] = []
    require_envs: list[str] = []
    require_packages: list[PackageRequirement] = []
```

SKILL.md frontmatter 示例：

```yaml
metadata:
  coapis:
    requirements:
      packages:
        - name: python-docx
          manager: pip
          required: true
          reason: "解析 .docx 文件内容"
        - name: docx
          manager: npm
          required: false
          reason: "用 docx-js 生成复杂 Word 文档"
      bins:
        - pandoc
        - soffice
      env:
        - LIBREOFFICE_PATH
```

#### 3.2.2 工具依赖声明

`@register_tool` 增加 `dependencies` 参数：

```python
@register_tool(
    name="doc_reader",
    description="读取 docx/pptx/xlsx 等文档",
    dependencies=[
        PackageRequirement(name="python-docx", manager="pip", required=True),
        PackageRequirement(name="python-pptx", manager="pip", required=False),
    ],
)
async def doc_reader(...) -> ...:
    ...
```

### 3.3 RuntimeDependencyManager 行为

```python
class RuntimeDependencyManager:
    _install_cache: dict[str, bool] = {}

    async def ensure_for_tool(self, tool_name: str) -> EnsureResult:
        deps = registry.get_dependencies(tool_name)
        for dep in deps:
            cache_key = f"{dep.manager}:{dep.name}:{dep.version or ''}"
            if cache_key in self._install_cache:
                continue
            if is_installed(dep):
                self._install_cache[cache_key] = True
                continue
            result = await install_dependency(
                package=dep.name,
                manager=dep.manager,
                version=dep.version,
            )
            self._install_cache[cache_key] = result.ok
            if not result.ok and dep.required:
                return EnsureResult(
                    ok=False,
                    missing=[dep],
                    hint=result.hint,
                )
        return EnsureResult(ok=True)
```

关键点：
- **安装缓存**：避免每次调用都安装。
- **required vs optional**：required 失败直接返回错误，optional 失败只记录 warning。
- **共享运行时池**：pip 安装到 `/opt/coapis/shared_runtime`，npm 全局安装，所有用户/容器复用。

### 3.4 工具执行自愈层

在工具执行入口（如 `react_agent` 或新的 `ToolExecutor`）统一包装：

```python
async def execute_tool_with_recovery(tool_name, tool_func, args):
    # 1. 依赖预检
    ensure_result = await RuntimeDependencyManager.ensure_for_tool(tool_name)
    if not ensure_result.ok:
        return ToolResult(
            state="error",
            content=[TextBlock(text=ensure_result.hint)],
            recovery_hint=(
                f"依赖 {ensure_result.missing[0].name} 安装失败。"
                "请检查网络或手动安装后重试。"
            ),
        )

    try:
        # 2. 执行工具
        return await tool_func(**args)
    except ImportError as e:
        # 3. 尝试推断包并安装
        package = infer_package_from_import_error(e, tool_name)
        if package:
            install_result = await install_dependency(package)
            if install_result.ok:
                return await tool_func(**args)
        return ToolResult(
            state="error",
            content=[TextBlock(text=str(e))],
            recovery_hint=f"尝试安装 {package} 失败，请检查环境。",
        )
    except PermissionBlocked as e:
        return ToolResult(
            state="error",
            content=[TextBlock(text=str(e))],
            recovery_hint="该操作在当前权限策略下被拦截，可尝试使用 install_dependency 安装依赖，或在用户空间内执行。",
        )
```

返回给 LLM 的结果必须包含 `recovery_hint`，而不是裸异常。

### 3.5 权限沙箱策略重构

#### 3.5.1 引入 WorkspaceBoundaryGuardian

新增 guardian，职责单一：判断命令的操作路径/影响范围是否都在用户 workspace 内。

输入：解析后的命令参数（目标路径、输出路径、cwd 等）。
输出：
- `SAFE`：全部在用户 workspace 或 `/tmp` 沙箱内。
- `MEDIUM`：涉及网络或临时文件但仍在安全范围。
- `HIGH`：越界到系统目录或包含危险参数。

#### 3.5.2 权限降级规则

基于 QwenPaw 的 `execution_level` 思想，CoApis 也分为四级：

| 级别 | 含义 | 适用场景 |
|------|------|----------|
| `OFF` | 完全关闭 | 本地开发、完全可信环境 |
| `AUTO` | 只检查显式 guarded_tools | 向后兼容 |
| `SMART` | 用户空间内自动 allow，越界/危险才审批 | 推荐默认 |
| `STRICT` | 所有工具都需审批 | 高安全环境 |

默认启用 `SMART`，规则：

| 命令/工具 | 用户 workspace 内 | 系统目录/危险参数 |
|-----------|-------------------|-------------------|
| `pip install` / `pip3 install` | L0 allow | L4 block |
| `npm install` / `npx` / `node` | L0 allow | L4 block |
| `python` / `python3` 脚本执行 | L0 allow | L4 block（如果带 `-c` 等内联参数） |
| `unzip` / `zip` / `tar` | L0 allow | L4 block |
| `strings` / `file` / `cat` / `grep` / `awk` | L0 allow | L4 block |
| `rm` / `del` | L2 confirm（用户空间也确认） | L4 block |
| `curl` / `wget` POST/写入 | L2 confirm | L4 block |
| `apt` / `yum` | L4 block（始终） | L4 block |

### 3.6 与现有系统的关系

```
┌─────────────────────────────────────────────────────────────┐
│                      ReactAgent / Chat                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│           ToolExecutionRecoveryLayer                         │
│  - 调用 RuntimeDependencyManager.ensure_for_tool()           │
│  - 捕获 ImportError / PermissionBlocked / CommandNotFound    │
│  - 返回带 recovery_hint 的结构化结果                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              WorkspaceSandboxPolicy (SMART)                  │
│  WorkspaceBoundaryGuardian  +  RuleBasedGuardian  + ...        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                RuntimeDependencyManager                      │
│  - 解析技能/工具依赖声明                                     │
│  - 调用 install_dependency（共享运行时池）                    │
│  - 缓存安装结果                                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  install_dependency tool                       │
│  pip install --user / npm install -g 到 /opt/coapis/shared   │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 实施路线图

### Phase 1：权限层快速止血（1 天）

目标：让 pip/npm/node/unzip/zip/strings 等基础命令在用户 workspace 和 `/tmp` 内不再触发审批，聊天不再被基础操作打断。

改动：
1. `coapis/system/tool_guard.yaml`：
   - 为 `pip`/`pip3`/`npm`/`node`/`npx`/`unzip`/`zip`/`strings`/`file` 等增加 `workspace` scope 的 L0 allow 降级规则。
   - 保留系统目录和危险参数拦截。
2. 重启开发环境容器验证。

### Phase 2：依赖声明扩展（1-2 天）

目标：让技能和工具能声明 pip/npm 包依赖。

改动：
1. `coapis/agents/skills_manager.py`：扩展 `SkillRequirements`，支持 `require_packages`。
2. `coapis/agents/tools/registry.py`：扩展 `@register_tool`，支持 `dependencies` 参数。
3. 解析 SKILL.md frontmatter 中的 `requirements.packages`。

### Phase 3：RuntimeDependencyManager（2-3 天）

目标：实现依赖预检和自动安装。

改动：
1. 新增 `coapis/agents/runtime_dependency.py`：
   - `PackageRequirement` 模型；
   - `RuntimeDependencyManager` 类；
   - `is_installed()` 检查函数；
   - 安装缓存。
2. 在技能加载时调用 `RuntimeDependencyManager.ensure_for_skill()`：
   - `always_load=True`：启动时预安装；
   - `always_load=False`：第一次触发时安装。

### Phase 4：工具执行自愈层（2-3 天）

目标：工具失败时自动安装依赖并重试，或给出结构化 recovery_hint。

改动：
1. 在 `react_agent` 或 `coapis/agents/tools/executor.py` 中增加 `execute_tool_with_recovery()`。
2. 替换各工具中裸的 `except ImportError: return error` 为调用自愈层。
3. 从 `doc_reader.py` 开始试点，然后推广到 `docx`/`pptx`/`xlsx`/`browser_control`/`desktop_screenshot`/`image_gen` 等。

### Phase 5：核心技能与文档更新（2-3 天）

目标：让 LLM 和系统知道“缺包就安装，不要停止”。

改动：
1. 重写 `docx` / `pptx` / `xlsx` / `pdf` / `file_reader` 等 SKILL.md 的 `Prerequisites`：
   - 删除“if missing, report and stop”类描述。
   - 改为“若依赖缺失，调用 `install_dependency` 自动安装”。
2. 把这些办公技能默认设为 `always_load: true` 或提升触发优先级。
3. 系统提示中统一加入：
   > “当工具因缺少依赖失败时，优先尝试 `install_dependency` 安装，然后重试；不要直接停止。”

---

## 5. 风险与回退策略

| 风险 | 应对措施 |
|------|----------|
| 自动安装恶意包 | 包名白名单：只允许已知包（由技能/工具声明），禁止 LLM 随意安装任意包；`install_dependency` 的 `package` 参数仍做安全校验。 |
| 权限降级后用户误删系统文件 | `rm` 仍保持 L2 confirm；`python -c` 等内联执行仍 L4 block；workspace 边界 guardian 独立保护。 |
| 自动安装失败导致死循环 | 每个依赖每会话最多安装一次；失败后返回结构化错误，不自动无限重试。 |
| 影响现有生产环境 | 引入 `execution_level` 配置，默认 `SMART`；可一键切回 `AUTO` 或 `STRICT`，保持向后兼容。 |
| 共享运行时池污染 | pip 安装到 `--user` 路径，npm 安装到 `-g` 的共享路径；容器启动时初始化 `PYTHONPATH`/`PATH`。 |

---

## 6. 借鉴 QwenPaw 的关键点汇总

| QwenPaw 机制 | 文件 | CoApis 如何借鉴 |
|--------------|------|-------------------|
| 四级执行级别 | `security/tool_guard/execution_level.py` | 引入 `OFF/AUTO/SMART/STRICT`，默认 `SMART` |
| Guardian 架构 | `security/tool_guard/engine.py` | 把 `tool_guard.yaml` 拆成多个独立 guardian，新增 `WorkspaceBoundaryGuardian` |
| Workspace 边界 primitive | `security/tool_guard/guardians/rule_guardian.py` | 统一使用 `derive_workspace_dir()` 作为边界判断 |
| 统一权限包装 | `runtime/tool_guard.py` | 工具执行入口统一包装，先依赖预检、再权限检查、再执行 |
| before/after hooks | `tool_calls/_hooks.py` | 用 `ToolHookRegistry` 实现依赖预检和失败后重试 |
| 拒绝后防重试 | `runtime/tool_guard.py` | 可恢复错误附带 `recovery_hint`，最终拒绝附带 no-retry 指令 |

---

## 7. 下一步建议

推荐从 **Phase 1（权限层）** 开始，因为它改动最小、见效最快，能立即解决“聊天被 unzip/pip 打断”的问题。Phase 1 完成后，再依次实现 Phase 2-5，把机制补齐。

如果用户希望一次到位，也可以直接合并 Phase 1 + Phase 4 做一个最小闭环：先降级权限，再在 `doc_reader.py` 等核心工具中接入依赖自愈，让 `docx` 场景立刻可用。
