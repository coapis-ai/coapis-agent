# ToolManager 实施方案 —— 全面复核报告

**日期**：2026-10-16　**性质**：对 `ToolManager实施方案_20261016.md` 的实证复核
**结论**：方案方向成立，但**发现 10 处上版遗漏/失实**，其中 3 处会改变设计；
**新增 1 项必要机制（关键词预激活）**以消除短任务回归。
**本轮代码改动：0 行。**

---

## 一、会改变设计的 3 个发现

### F1 `reset_equipped_tools` 是**绝对语义**，不是增量 ★最高风险

上游 docstring 原文（`_toolkit.py:1250+`，实测读取）：

> **Important: Each call sets the absolute final state of ALL tool groups, not
> incremental changes**. Any group not explicitly set to True will be
> **deactivated**, regardless of its previous state.

实现佐证：函数体第一行就是 `self.update_tool_groups(list(self.groups.keys()), active=False)`
——**先把所有组全关**，再按参数开指定的。

**后果**：模型调用 `reset_equipped_tools(web=True)` 时，之前激活的 `mcp`/`agent` 组**被静默关掉**，
工具从 schema 消失。这是本方案最大的行为风险，上版完全未识别。

**处置**（三层，均低成本）：
1. plan 三工具放 `basic`（`group=None`）→ 不受 reset 影响（reset 只动 `self.groups`）。
   上版设计已如此，**这条保护是必要的，保留**。
2. 覆盖 `reset_equipped_tools` 的 docstring，把"必须重列所有仍需组"写成显式契约
   （上游已写明，但埋在长 docstring 中；coapis 版前置加粗 + 中文）。
3. 保留 `FunctionInactiveError` 自愈（实测存在）作为兜底。

### F2 mission 模式会**抢占工具的 group 字段** → 双主人冲突

`mission_runner.py:178-201`：

```python
for tool_name in IMPLEMENTATION_TOOLS:
    if tool_name in toolkit.tools:
        toolkit.tools[tool_name].group = MISSION_IMPL_GROUP   # 改写 group
```

`IMPLEMENTATION_TOOLS = {edit_file, browser_use, desktop_screenshot}`（实测；注释写 shell/write 但集合里没有）。
mission 在主链路被调用（`app/runner/runner.py:1798`）→ **活的**。

**后果**：ToolManager 把 `browser_use` 归 `web` 组后，mission 会把它改写到 `mission_impl` 组
→ `web` 组失去该工具 → 激活 `web` 也不含 browser_use。**真实 bug，上版未发现。**

**处置**：mission 的 `migrate_tools_to_group` 增加**记录原组并在 `restore_tools` 时还原**（约 10 行）；
ToolManager 不主张对这 3 个工具的归属权。
（备选：把这 3 个工具设为常驻 `group=None`，但 `browser_use` 9,078 字符，常驻代价大，不推荐。）

### F3 短任务回归：S=1 时按需激活**净亏 46%** ★必须补机制

按实测数据建模（dev profile：sys_prompt 24,238 + schema 44,677 = 68,915 字符/步）：

设任务 S 步、激活组总字符 G、常驻基座 base_B = 24,238 + 6,781 + 880(目录) = 31,899

| S | 激活 G | 现状 A = S×68,915 | 方案 B = (S+1)×(base_B+G) | 结果 |
|---|---|---|---|---|
| 1 | 18,566 (web+browser) | 68,915 | 100,930 | **B 亏 46%** |
| 2 | 18,566 | 137,830 | 151,395 | **B 亏 10%** |
| 3 | 18,566 | 206,745 | 201,860 | B 省 2% |
| 10 | 15,493 (web+mcp) | 689,150 | 521,312 | B 省 24% |
| 10 | 0（纯文件任务） | 689,150 | 350,889 | **B 省 49%** |

**根因**：激活本身要占一步（`reset_equipped_tools` 是工具调用，模型拿到响应后下一步才能用真工具）。
收益来自"**不为从不使用的组付费**"，成本是"**多一步全量往返**"。首步即需重组时必亏。

**处置（推荐，且顺带统一两套机制）——关键词预激活**：

任务开始时用用户首条消息做关键词预激活，复用**已存在**的关键词资产
（`tools/registry.py:61 TOOL_GROUPS` 的 `keywords` 字段，含中英文关键词集，实测活着）：

- 命中即在建组后直接 `update_tool_groups([...], active=True)`，**不消耗额外步**
- S=1 场景：B = 1×(31,899+18,566) = 50,465 < A 68,915 → **省 27%，回归消除**
- 未命中 → 回退 LLM 自助（长任务仍享 24~49% 收益）

**收益**：消除短任务回归 + **把仓库里两套并行的分组机制统一为一套语义**（见 N6）。

---

## 二、上版遗漏/失实清单（10 条）

| # | 上版说法 | 实测真相 | 影响 |
|---|---|---|---|
| N1 | 工具来源 = `builtin_tools` 配置面 | **主来源是进程级注册表 `agents/tools/registry.py`**，`@register_tool` 装饰器注册，`_create_toolkit` 经 `get_registered_tools()` 全量注册；实测运行时 **48 个工具** | 分组需"未知工具"兜底组（插件可运行时追加） |
| N2 | 未识别 reset 语义 | **绝对语义**（F1） | 改变设计 |
| N3 | 未识别 mission 抢占 | **`group` 字段被改写**（F2） | 改变设计 |
| N4 | R4 缓解点 #19：`_acting` 策略引擎 deny 会拦截 | **死代码**：`getattr(self.toolkit,"registry",{})`，实测 `Toolkit` **无 `registry` 属性** → `reg` 恒 None → deny 路径恒不触发 | 删除该缓解点；R4 的 write 类工具风险**无治理闸门**，需独立评估 |
| N5 | L0 需改 docstring | **数据包已有 42 条精简中文描述**（`load_tool_descriptions('zh')`），实测注册表 8 字符 vs schema 477 字符 → **精简描述不进 schema**（schema 取函数 docstring） | L0 可改为"把数据包描述接入 schema"，**近零代码**即拿到大头收益 |
| N6 | 未识别第二套分组机制 | `tools/registry.py:392 _select_tools` + `TOOL_GROUPS`(5 组/keywords/always_active) **活的**，被 `agents/core.py:272/411` 消费 | 与 F3 合并为统一机制；命名须避免"同名不同义" |
| N7 | 缓解点 #12：给 experience_extractor 加 `core_only=True` | **该链路实际不传工具**（`experience_extractor.py` 无 `get_openai_tools` 调用） | 删除该点（无对象） |
| N8 | 配置新增字段兼容性未验证 | `AgentsRunningConfig` 为 `ConfigDict(extra="ignore")` → 旧 `config.json` 不会因新字段崩 | ✅ 通过，无需迁移 |
| N9 | UI 分组对齐"建议" | `app/routers/tools.py` 有 `_tool_group`、`/tools/groups`、按 group 过滤查询，消费 `TOOL_GROUPS` | 升级为**必做**（否则前端分组视图与新机制不一致） |
| N10 | 技能是否进 schema | 上游 `toolkit.skills` 原生存在，实测**不进 schema**（`_react_agent.py` 零引用） | ✅ 确认 L4 方向（技能成本在 prompt） |

---

## 三、"优化不过度"专项核查

### 3.1 组粒度：11 组是否过细

每组固定成本 = 目录 1 行(~80) + meta 参数 1 个(~40) ≈ **120 字符**；11 组 ≈ 1,320 字符常驻。
相对 44,677 基座约 **3%** → **粒度不构成过度优化**。

单工具组（`schedule` 1,197 / `meta` 1,306 / `async_task` 600）：合并进邻近组可省 240 字符常驻，
但增加"激活即附带无用工具"的浪费 → **保持独立更优**。

### 3.2 常驻组选择：哪些组应 `always_active`

判据：`常驻成本 = G × S`；`按需成本 ≈ p × (一步全量往返 ≈ 32K + G × (S-j))`，p 为使用概率。
→ **p 高则常驻，p 低则按需**。

| 组 | 字符 | 估计 p | 结论 |
|---|---|---|---|
| `basic`(文件+shell) | 6,781 | ~1.0 | 常驻（已定） |
| plan 三工具 | 7,561 | 高（流程契约） | **常驻**（已定，且 F1 要求） |
| `media` | 2,604 | ~0.3 | **按需**（阈值 p>0.77 才常驻） |
| `data` | 1,059 | ~0.2 | **按需** |
| `meta` | 1,306 | ~0.1 | **按需** |
| `async_task` | 600 | ~0.1 | **按需** |
| `docs` | 2,453 | ~0.25 | **按需** |
| `web`/`mcp`/`agent`/`devops`/`schedule` | 6,005~9,488 | 0.2~0.4 | **按需** |

→ **上版"仅 basic 常驻"的划分经核算成立，无需上调常驻集。**

### 3.3 是否存在"为省 20K 引入更大复杂度"的过度优化

- 不 fork agentscope（复用原生分组 + meta tool）✅
- 不新增第二套激活工具（复用上游 meta tool）✅
- 关键词预激活**复用已有关键词资产**，非新机制 ✅
- 唯一新增复杂度 = 分组表 + 目录注入 + 预激活映射 ≈ **150 行**
→ **不构成过度优化**。

### 3.4 反向风险（上版低估）

- **F1 绝对语义**导致中途丢工具 → 模型可能反复激活/失败，**净增步数**，抵消收益。
  这是收益能否兑现的**首要变量**，必须在 E2E 中专门度量"激活失败率"。
- 目录 + meta 工具常驻成本 1,880 字符（目录 880 + meta 描述 1,000）
  → 净收益由 37K 降至 **35K/步**（上版写 41K 未扣 meta 工具描述）。

---

## 四、方案修订清单（相对上版）

| 编号 | 修订 | 理由 |
|---|---|---|
| **R-a** | **新增"关键词预激活"**：建组后按首条消息命中 `TOOL_GROUPS.keywords` 直接激活 | 消除 F3 短任务回归；统一 N6 两套机制 |
| **R-b** | mission 侧 `migrate_tools_to_group` 增加**原组记录与还原**（约 10 行） | 消除 F2 双主人冲突 |
| **R-c** | 覆盖 `reset_equipped_tools` docstring，前置"绝对语义 + 必须重列全部所需组"契约 | 缓解 F1 |
| **R-d** | 分组表增加 `other` 兜底组（未匹配工具默认归入） | N1 插件运行时追加 |
| **R-e** | L0 改为"把数据包精简描述接入 schema"（注册时显式传 description），docstring 改动降为可选 | N5：近零代码拿大头收益 |
| **R-f** | 删除缓解点 #19（死钩子）、#12（无对象） | N4 / N7 |
| **R-g** | UI 分组对齐由"建议"升为**必做** | N9 |
| **R-h** | 净收益口径由 41K 修正为 **35K/步**（扣 meta 工具 1,000 字符描述） | 3.4 |
| **R-i** | 验收新增两项：**激活失败率**、**S≤2 短任务回归** | F1/F3 |

---

## 五、复核后结论

- 方案**方向正确、不过度**：复用上游原生分组 + meta tool，不 fork，新增约 150 行。
- 上版存在 **3 处会改变设计**的遗漏（reset 绝对语义、mission 抢占 group、短任务回归），
  以及 **7 处事实偏差**（工具主来源、死钩子、数据包描述未接入 schema、第二套分组机制、无对象缓解点等）。
- 修订后收益口径：**约 35K 字符/步**（长任务 24~49%，纯文件任务最高 49%，短任务经预激活后约 27%）。
- **建议按 R-a~R-i 修订实施方案后再开工**；M0 探针必须先测 F1 的激活失败率。

**本轮代码改动：0 行。**
