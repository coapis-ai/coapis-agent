# ToolManager 实施方案 v2（含复核修订）

**日期**：2026-10-16　**状态**：待开工
**性质**：实施方案。v1 因并发方清理未跟踪文件而丢失，本版为重建 + 合并复核修订。
**依据**：`tech_docs/ToolManager复核报告_20261016.md`（10 处遗漏/失实，3 处改变设计）
**本轮代码改动：0 行。**

---

## 0. 与 v1 的差异（9 条修订）

| 编号 | 修订 | 理由 |
|---|---|---|
| **R-a** | 新增**关键词预激活**：建组后按首条消息命中现成 `TOOL_GROUPS.keywords` 直接激活 | 消除短任务回归（S=1 净亏 46%）；统一仓库内两套并行分组机制 |
| **R-b** | mission 侧 `migrate_tools_to_group` 增加**原组记录与还原** | 消除 `group` 字段双主人冲突 |
| **R-c** | 覆盖 `reset_equipped_tools` docstring，前置"绝对语义 + 必须重列全部所需组"契约 | 上游为绝对语义，未列出的组会被关掉 |
| **R-d** | 分组表增加 `other` 兜底组 | 工具主来源是进程级注册表，插件可运行时追加 |
| **R-e** | L0 改为"把数据包精简描述接入 schema"，docstring 改动降为可选 | 数据包 42 条精简描述实测未进 schema（8 vs 477 字符） |
| **R-f** | 删除 v1 缓解点 #19（`_acting` 死钩子）、#12（experience_extractor 不传工具） | 无对象 |
| **R-g** | UI 分组对齐由"建议"升为**必做** | `app/routers/tools.py` 的 `_tool_group`/`/tools/groups` 消费 `TOOL_GROUPS` |
| **R-h** | 净收益口径 41K → **35K 字符/步** | 扣 meta 工具 1,000 字符描述 |
| **R-i** | 验收新增：**激活失败率**、**S≤2 短任务回归** | F1/F3 |

---

## 1. 事实基线（全部实测）

| 项 | 值 | 来源 |
|---|---|---|
| 工具主来源 | 进程级注册表 `agents/tools/registry.py`，`@register_tool` 注册，`_create_toolkit` 经 `get_registered_tools()` 全量注册，**运行时 48 工具** | 容器内实测 |
| 工具 schema | **44,677 字符**（52 工具） | dev profile |
| 描述占比 | 84.5%（37,791 字符） | 实测 |
| 生成时机 | `_react_agent.py:570` 每推理步调 `get_json_schemas()` | 实测 |
| 系统提示词 | 24,238 字符 | dev profile |
| 上游分组能力 | `create_tool_group`/`update_tool_groups`/`remove_tool_groups`/`reset_equipped_tools` 原生存在，coapis **零调用**（主链路） | 实测 |
| **reset 语义** | **绝对**：先全关再按参数开；未列出的组被 deactivate | `_toolkit.py:1250+` 实测 |
| 自愈 | `_react_agent.py:740-760` 捕获 `FunctionInactiveError` → 激活组 + 提示重试 | 实测 |
| 上游 skills | `toolkit.skills` 存在，**不进 schema** | 实测 |
| 数据包描述 | 42 条精简中文，**未进 schema**（注册表 8 字符 vs schema 477） | 实测 |
| 第二套分组 | `tools/registry.py:392 _select_tools` + `TOOL_GROUPS`(5 组/keywords)，被 `agents/core.py:272/411` 消费（仅辅助链路） | 实测 |
| mission 抢占 | `mission_runner.py:178` 改写 `edit_file`/`browser_use`/`desktop_screenshot` 的 `.group`；主链路 `runner.py:1798` 调用 | 实测 |
| 治理闸门 | `_acting` 内 `getattr(self.toolkit,"registry",{})` → **Toolkit 无该属性** → deny 恒不触发（死代码） | 实测 |
| 配置兼容 | `AgentsRunningConfig` = `ConfigDict(extra="ignore")` → 新字段无需迁移 | 实测 |

---

## 2. 设计

### 2.1 三层结构

```
常驻层（group=None，永在 schema）
  文件+shell：read_file write_file edit_file append_file grep_search glob_search execute_shell_command
  计划：update_plan insert_plan_subtask finish_plan        ← F1 要求的必要保护
  元：reset_equipped_tools（上游自动注册）
  ≈ 14,342 字符 + 目录 880 + meta 描述 1,000 ≈ 16.2K

按需层（11 组，默认关）
  web 9,488 | browser 9,078 | mcp 6,005 | agent 3,773 | devops 2,256
  docs 2,453 | media 2,604 | schedule 1,197 | meta 1,306 | data 1,059 | async_task 600
  合计 30,879

兜底层
  other：未匹配工具默认归入（R-d）
```

### 2.2 激活路径（两条，统一语义）

1. **关键词预激活（R-a，新增）**：任务首条消息 → 复用 `TOOL_GROUPS.keywords`
   → 命中组直接 `update_tool_groups([...], active=True)`。**零额外步**。
2. **LLM 自助**：目录注入系统提示词 → 模型调 `reset_equipped_tools(...)`。
   ⚠️ 绝对语义 → 必须重列所有仍需组（R-c 契约）。

### 2.3 收益模型（实测数据）

| 场景 | 现状 | 方案 | 结果 |
|---|---|---|---|
| S=1 无预激活 | 68,915 | 100,930 | **亏 46%** |
| S=1 有预激活 | 68,915 | 50,465 | **省 27%** |
| S=2 有预激活 | 137,830 | 100,930 | 省 27% |
| S=10 激活 web+mcp | 689,150 | 521,312 | 省 24% |
| S=10 纯文件任务 | 689,150 | 350,889 | **省 49%** |

净收益口径：**约 35K 字符/步**（R-h）。

---

## 3. 实施批次

| 批次 | 内容 | 文件 | 人日 |
|---|---|---|---|
| **M0 探针** | 建组/激活/目录/绝对语义/mission 抢占 五类实测；**测激活失败率** | 新增探针脚本 | 0.5 |
| **M1 分组表** | 分组定义 + `other` 兜底 + 注册时按组注册（`register_tool_function(group_name=)`） | 新增 `agents/tools/groups.py`；改 `react_agent.py:_create_toolkit` | 1.0 |
| **M2 目录+契约** | 目录注入系统提示词；覆盖 `reset_equipped_tools` docstring（R-c） | 改提示词装配 + `groups.py` | 0.5 |
| **M3 预激活+mission** | 关键词预激活（R-a）；mission 原组记录与还原（R-b） | 改 `react_agent.py`；改 `mission/mission_runner.py` | 0.7 |
| **M4 描述接入** | 注册时显式传数据包 description（R-e）；UI 分组对齐（R-g） | 改 `react_agent.py`；改 `app/routers/tools.py` | 0.5 |
| **M5 配置+验收** | `tool_manager` 配置节（常驻组覆盖/开关）；全量测试 + E2E + 回归项（R-i） | 改 `config/config.py`；新增测试 | 0.8 |

合计 **约 4 人日**。停机点：无（配置开关默认关，灰度开启）。

---

## 4. 风险与缓解

| 风险 | 缓解 |
|---|---|
| **绝对语义中途丢工具**（F1，首要风险） | plan 常驻 `basic`；docstring 契约（R-c）；`FunctionInactiveError` 自愈；M0 测失败率 |
| **短任务回归**（F3） | 关键词预激活（R-a）；验收含 S≤2 回归项 |
| **mission 双主人**（F2） | mission 记录并还原原组（R-b） |
| 插件运行时追加工具 | `other` 兜底组（R-d） |
| 治理闸门为死代码（N4） | R4 写类工具风险**无闸门** → 写类工具保持常驻（已如此），并单列后续治理项 |
| 前端分组视图不一致（N9） | UI 对齐升为必做（R-g） |
| 收益不及预期 | 配置开关可整体关闭，回退零成本 |

---

## 5. 验收清单

1. M0 探针：建组/激活/目录/绝对语义/mission 抢占 五类全过
2. **激活失败率** ≤ 5%（F1 度量）
3. **S≤2 短任务无回归**（F3 度量）
4. 全量测试 ≥ 基线（当前 587 绿）
5. dev E2E：纯文件任务 schema 字符数下降 ≥ 40%
6. dev E2E：web 任务经预激活后首步即含 browser_use
7. mission 模式 Phase2 后工具组归属正确还原
8. UI `/tools/groups` 与运行时分组一致
9. 配置开关关闭时行为与现状逐字节一致

---

## 6. 待确认（开工前）

| # | 事项 | 推荐 |
|---|---|---|
| C1 | 预激活关键词来源 | 复用 `TOOL_GROUPS.keywords`，不新建词表 |
| C2 | `other` 兜底组常驻还是按需 | **按需**（保守，避免未知工具常驻膨胀） |
| C3 | 数据包描述接入范围 | 全量 42 条接入；未覆盖的工具保留 docstring |
| C4 | 灰度方式 | 配置开关默认关，dev 先开、生产后开 |

---

## 7. 文档持久性提醒

`tech_docs/` 下文件**全部未被 git 跟踪**，并发方的清理会删除它们
（v1 方案与"上下文优化方案v2"均已因此丢失）。
**建议**：本方案与复核报告纳入 git 跟踪，或在仓库外留备份。

**本轮代码改动：0 行。**
