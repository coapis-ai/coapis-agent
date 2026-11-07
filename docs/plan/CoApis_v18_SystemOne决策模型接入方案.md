# v18 · 决策模型接入 SystemOne（`POST /v1/systemone`）+ 决策策略重构

> 状态：**方案，代码 0 行未改**。日期 2026-11-06，作者 蜜总裁。
> 前置：v15 规格（§七 硬边界）、v16 模型管理、v17 左栏/资源条。

---

## 0. 先回答小蜜蜂的问题：`/v1/systemone` 对不对？

**对，而且我们目前完全没有用它。** 三点实测结论：

1. **端点正确。** 这是 TypeSafe 的 System One（Jev）模型 API，也是 abacus **RouteLLM "Decision Models"** 的端点，
   路径就是 `{base_url}/v1/systemone`，`POST`，`Authorization: Bearer <key>`，`Content-Type: application/json`。
   权威出处：docs.typesafe.ai/api（"Send natural-language state and questions to
   `POST /v1/systemone`"）、abacus.ai/help/route-llm/systemone（"System One is a
   decision endpoint: POST natural-language state and questions to
   `https://routellm.abacus.ai/v1/systemone`"）。
2. **小蜜蜂给的示例格式基本正确**（`state` 可为对象、`choice` 带 `criteria` 字典、`noul` 带
   `instructions`），但有 **3 处必须补/改**：
   - **缺 `model` 字段**——请求体必填（`"model": "jev-latest"`）。示例原样发出去会 422。
   - **缺鉴权头**——需要 `Authorization: Bearer <key>`。
   - `criteria` 的值必须是"选项名 → 自然语言描述"的映射（描述可为 `null`），**不能是数组**；
     `score` 的 `criteria` 必须是**恰好 10 个**"等级名 → 描述"。
3. **我们仓库里 `systemone` 出现次数 = 0**（全仓 grep，含 ent/前端）。判官现在走的是
   `provider.get_chat_model_instance()` → agentscope → **OpenAI 兼容 `/chat/completions`**
   （`server/coapis/decision/gateway.py:860-879`）。也就是说：**决策模型槽位现在接的是
   聊天模型，不是决策模型**；且 dev 实值 `judge_provider_id=""`、`judge_model=""`
   （`/apps/ai/coapis-dev/config/decision_hub.json`），判官长期处于"无决策模型"状态。

---

## 1. 实证：为什么"现在这套"不具可用性

台账 `decision_events` 全量 300 行（`/apps/ai/coapis-dev/system/coapis.db`，
脚本 `scripts/dev/judge_probe.py`，2026-11-06 22:xx 实测）：

| 指标 | 实测 | 含义 |
|---|---|---|
| 消费点分布 | plan_gate 93 / skill_trigger 93 / acceptance 55 / tool_gate 46 / advisor 7 / plan_review 6 | 只有 advisor、plan_review 几乎不产数 |
| hit_layer | **timeout 105 (35%)** / llm 81 / **budget_cap 61 (20%)** / **breaker_open 24 (8%)** / error 11 / rule 7 / disabled 5 / no_model 4 / cache 2 | 真判仅 27%；63% 是被时间/预算/熔断吃掉 |
| latency | **p50 2003ms · p90 9871ms · max 16963ms** | 聊天模型跑"只输出JSON"的判则，天然慢 |
| cost/tokens | **240/300 行为 0** | 计费链路等于没有 |
| outcome | **pending 277 (92%)** · hit 21 · miss 2 | **判了不认账**，命中率无从计算 |
| judgment 内容 | `{'verdict':'allow','why':'判断失败，闸门放行'}` 38 行；`{'verdict':'abstain',...无可用判官，弃权}` 31 行；`select:low,medium` 41 行 | 解析失败/弃权被当结果写进台账 |
| 近 24h 新增 | **0 行** | dev 无真实流量，效果无法验证 |

**根因不是"没配模型"这么轻，是三层叠加：**

- **L1 形态错**：判官要求聊天模型"只输出一个 JSON 对象"，四个岗位各写一套自由文本解析
  （`hub_tool_gate.py:176-183`、`hub_acceptance.py:132/304/312`、`hub_plan_review.py:233/239`、
  `hub_advisor.py:152`）。自由文本 → 解析失败 → 弃权 → 主链拿不到任何东西。
- **L2 时延错**：判则全文 + 状态塞进 chat prompt，p50 2s / p90 9.9s，直接撞熔断与预算闸
  （`judge_soft_ms=2000`、`llm_timeout_ms_api=5000`）。**超时/预算/熔断占 63% 不是模型慢，
  是"用聊天模型做判定"这件事本身慢。**
- **L3 策略闭环缺**：判定 → 主链动作 → 结果对账，三段断开。验收 92% pending，
  advisor 仅 7 行、plan_review 6 行——**判官对任务/计划/工作流"没有手"**。

SystemOne 的存在恰好把 L1/L2 直接抹掉：**返回类型化答案（`choice` 只可能给你定义过的选项、
`noul` 给 [0,1] 概率），0% 结构化输出错误，不需要解析；单次调用典型 ~100ms（TypeSafe 直连）、
0.2-0.5s（RouteLLM），输出 token 免费。**

---

## 2. API 契约（实现依据，逐条来自官方文档）

### 2.1 请求

```
POST {base_url}/v1/systemone
Authorization: Bearer <key>
Content-Type: application/json
[TypeSafe-Danger-Zone-Long-Context: true]   # 可选，把上下文抬到 262k
{
  "model": "jev-latest",          # 必填：jev-latest / jev-preview / jev-1.14.0 / jev-1.13.0
  "state": "字符串 | 对象 | 数组",  # 必填：要判断的现场（自然语言）
  "questions": {                  # 必填：命名问题字典
    "档位": {"type": "choice", "instructions": "...",
             "criteria": {"simple": "判则原文…", "medium": "…", "complex": "…"}},
    "越界": {"type": "noul", "instructions": "...",
             "criteria": {"true": "…", "false": "…"}},          # 可选：给两端命名
    "严重度": {"type": "score", "instructions": "...",
               "criteria": {"calm": "…", ..., "furious": "…"}}   # 必须恰好 10 级
  }
}
```

### 2.2 响应

```
{ "model": "jev-1.14.0",
  "answers": {
     "档位":   {"type": "choice", "choice": "complex", "probability": 0.66,
                "probabilities": {"simple":0.11,"medium":0.23,"complex":0.66}},
     "越界":   {"type": "noul",   "noul": 0.95, "probability": 0.95,
                "name": {"true":"…","false":"…"}},
     "严重度": {"type": "score",  "score": 4.1, "probability": 0.41}
  },
  "usage": { "input_tokens": 142, "output_tokens": 426 } }
```

### 2.3 限制（**必须进我们的闸门**）

| 限制 | TypeSafe 直连 | RouteLLM 自助版 | 我们的处置 |
|---|---|---|---|
| 每题选项数 | 255 | 255 | 技能选择 ≤255，超出截断+记 `truncated` |
| 每请求问题数 | 无硬上限（受上下文约束） | **10（自助）/ 500（企业）** | 复合请求按阶段分组，单请求 ≤10 |
| state 长度 | 64k/请求、32k/题（长上下文 262k） | 32k token / 128k 字符（序列化后） | 超 128k 字符直接压缩/裁剪并记 `state_truncated` |
| 嵌套深度 | ≤64 层 | 同 | state 扁平化构造 |
| 体积 | ≤32MiB，UTF-8 无 BOM | 同 | 发送前自检 |
| 速率 | 按组织（429 退避） | **60 req/min（自助）** | 全局令牌桶 + 429/529 指数退避 |
| 时延 | 多数 ~100ms | 0.2-0.5s | 预算：判官 1500ms 足够 |
| 价格 | $0.042/Mtok 输入，**输出免费** | 同 | 计费只按 input_tokens |
| 状态码 | 400/401/413/415/422/**429**/**529** | 同 | 429/529→退避重试；422→判则缺陷直接落台账 `schema_error` |
| Box 原语 | 仅 `jev-1.14.0` | 文档未列 | 一期不用 Box |

---

## 3. 目标架构（四层，判定变动作）

```
L0 规则层（保留，零成本）      ── 现状已有：rule=7 行
L1' SystemOne 结构化决策层      ── 新增：POST /v1/systemone，类型化答案，无解析
L2 策略层（新增，"判则→问题+阈值"）─ 复合评分/概率路由/影子模式
L3 动作与对账层（新增）         ── 判定→主链动作→outcome 回填，命中率可算
```

### 3.1 六岗 → 问题编译表（**这是"策略"的落点**）

| 岗位 | 现状（自由文本 JSON） | SystemOne 问题组 | 主链动作（阈值 → 动作） |
|---|---|---|---|
| 判档 plan_gate | 请求"只答一个词" | `choice(档位)` + `noul(不可逆)` + `noul(跨对象)` | complex→升预算/开计划；p(不可逆)≥0.7→ 强制走 plan_review |
| 计划审查 plan_review | 要求 `{action,why}` JSON | `choice(pass/revise/replan)` + `noul(有终点标准)` + `noul(每步可验收)` + `noul(步骤与目标对症)` | 任一 noul≥0.7 且 choice=pass → 强制 revise；复合分 `S=0.5·choice+0.5·min(noul)` |
| 技能选择 skill_trigger | `select:low,medium` 这类残缺串 | `choice(候选技能≤255)` + `noul(需要外部副作用)` | 最大概率项唯一胜出才注入；`p_max-p_second<0.15` → 不注入（避免瞎选） |
| 工具闸 tool_gate | `{verdict:allow/reroute, why}` | `noul(对症)` + `noul(重复)` + `noul(越界)` + `noul(更短做法)` | 越界≥0.8 → reroute；重复≥0.8 → 提示换参数；全 <0.5 → allow（一期建议权不变） |
| 事中改道 advisor | `{verdict,evidence,next}` | `choice(continue/change/stop)` + `noul(目标变了)` + `noul(手段偏了)` | change 需 p≥0.7 才注入提示（现状 7 行→目标每轮可判） |
| 验收 acceptance | `{verdict,overreach,overdesign,missing}` | `choice(satisfied/partial/failed)` + `noul(越界)` + `noul(过度设计)` + `score(10级满足度)` | 结果写 outcome（hit/miss），p<0.6 记 `abstain_lowconf` 不算战绩 |

**关键点**：`criteria` 里塞的正是 v14 那套判则原文（`rubric.py` 现有 5 份文本），
判则从"prompt 里的一段话"升级成"选项的定义"——判官不再发挥，台账才可能算命中率。

### 3.2 复合策略（一期只做这 4 条，别贪）

1. **复合评分**：一个结论由多题组合（如上表公式），组合规则写在代码里，可测可解释。
2. **概率路由 + 置信阈值**：`p<0.6` 一律弃权并记 `abstain_lowconf`（**不计战绩、不进熔断**）。
3. **单请求多题**：同阶段多题合并成 1 个请求（RouteLLM 自助 ≤10 题）；每轮目标 ≤3 请求。
4. **影子模式（灰度）**：新策略上线先"只写台账不动主链"，跑满 500 行且命中率显著优于
   旧自由文本路径，才逐岗开动作权。

### 3.3 对账闭环（治 92% pending）

- 验收判定 → 写 `outcome`(hit/miss) + 回填 `judgment`，并新增 `action_taken`
  （主链**实际**采纳了什么动作）。
- 每轮结束把"判定/建议/实际动作/用户后续行为（是否追问、是否纠正）"落同一行，
  命中率 = hit/(hit+miss+abstain_executed)。
- 新增只读预检报表：真判率、弃权率、命中率、p50/p90、每轮 SystemOne 请求数与 input_tokens。

---

## 4. 实施批次（每批独立可验收；代码量与文件明说）

| 批次 | 内容 | 主要文件 | 规模 | 验收标准 |
|---|---|---|---|---|
| **B0 冒烟**（先做，1 人日） | 用 curl/脚本对给定 base_url+key 打通 1 次：判档 3 选项 + 越界 noul | `scripts/dev/systemone_smoke.py`（新建） | 新增 ~80 行 | 拿到 `answers`，时延 <500ms，`usage.input_tokens>0`；失败给出精确 422/401 原因 |
| **B1 传输层**（1.5 人日） | 新增 SystemOne provider 形态 + 专用 transport（裸 httpx，不走 agentscope）；能力位 `is_decision_model` | `server/coapis/providers/systemone_provider.py`(新)、`provider_manager.py`、`providers/const.py` | 新增 ~260 行 + 改 ~40 行 | 单测覆盖：请求构造/401/422/429/529/超时；不污染 chat provider |
| **B2 决策层接入**（2 人日） | gateway 增加"结构化决策"通道：`decide(questions, state)` → 类型化答案；复用熔断/预算/缓存/台账；`no_model` 闸门语义不变 | `gateway.py`（新分支 ~150 行）、`types.py`、`config.py`(新键)、`ledger_contract.py` | ~220 行 | 现有 1500+ 测试全绿；台账新增 `answer_type/probability/schema_error` |
| **B3 六岗编译器**（2.5 人日） | 六岗从"prompt+解析"改为"问题编译+阈值"；删除四套自由文本解析 | `rubric.py`(问题化)、`hub_*.py`×4、`plan_gate.py` | ~300 行，删除 ~180 行 | 台账 judgment 100% 为合法取值；解析失败率 = 0 |
| **B4 策略+影子**（1.5 人日） | 复合公式、置信阈值、单请求多题、令牌桶（60/min）、影子模式开关 | `strategy.py`(新)、`config.py` | ~200 行 | 影子报表：新策略命中率 ≥ 旧路径 +10pp 才允许开动作权 |
| **B5 对账闭环**（1.5 人日） | outcome 回填 + `action_taken` + 预检报表 | `hub_acceptance.py`、`ledger_contract.py`、`scripts/dev/judge_probe.py` | ~180 行 | pending 占比 <30%；命中率可在预检里一行读出 |
| **B6 UI 收口**（1 人日） | 模型管理加"决策模型"槽位形态选择（SystemOne），显示时延/价格/限制；槽位清空沿用 v16 修复 | `client/src/...`模型管理页 | ~150 行 | 社区版无 404 刷屏；槽位可设可清 |

合计 ~7 人日。**B0 未通过（无 key 或 401）→ 后续批次不开工**，判官保持现状（弃权安全）。

---

## 5. 拍板项（我要你点头我才动代码）

- **D1 用哪个网关**：① TypeSafe 直连 `api.typesafe.ai`（题数最宽、~100ms）；
  ② RouteLLM 自助 `routellm.abacus.ai/v1`（≤10 题/请求、60 req/min）；③ 企业
  `https://<workspace>.routellm.abacus.ai/v1`（500 题/请求）。→ **需要你给 base_url + key**。
- **D2 数据外发合规**：state 里会带对话内容与工具上下文，要发给境外推理服务。
  需要明确：**哪些字段允许外发**（我建议默认脱敏：不发文件正文，只发摘要+动作序号）。
- **D3 成本口径**：按 input_tokens 计费（输出免费）。判官每轮 3 请求 × ~3k token
  ≈ $0.0004/轮，可接受；要不要设每用户日预算闸？
- **D4 动作权节奏**：影子模式跑多久（我建议 500 行有效样本）后开动作权，还是先给
  tool_gate 单岗开？
- **D5 旧自由文本路径**：保留为"SystemOne 不可用时的降级"，还是彻底删（省 180 行）？
  我倾向**保留 30 天降级**，因为它是我们唯一的历史对照。
- **D6 Box 原语**（jev-1.14.0，可在答案里带证据片段）：要不要用？用了 `why` 字段就能真起来。
- **D7 部署**：dev 先行、生产默认不动（老规矩）。

---

## 6. 风险清单

1. **无 key 则全案停摆**：B0 是唯一前置，拿不到 key 我不动 B1 之后任何代码。
2. **限流**：自助版 60 req/min，多用户并发会把判官全打成 429 → 必须令牌桶 + 影子降级。
3. **10 题/请求**：六岗复合组题必须分组，否则 422（我把这个当作 schema_error 记台账，不静默）。
4. **别名漂移**：`jev-latest` 会随发布移动，阈值调过之后要**钉版本 ID**（`jev-1.14.0`）。
5. **state 截断**：128k 字符上限，长对话轮次要压缩，压缩即改变判定 → 台账必须记 `state_truncated`。
6. **判则改写**：判则从"给模型读的一段话"变成"选项定义"，写法要重新打磨（判则质量直接决定命中率）。
7. **台账字段扩张**：新列要走迁移（0019 之后），迁移必须带 backfill 与回滚。

---

## 7. 我建议的第一步（等你一句话）

给我 **base_url + api_key**（或告诉我用哪个网关、key 放哪个文件），我跑 **B0 冒烟**，
把真实时延、token 消耗、档位判定准确率测出来给你看——**在动任何产品代码之前**。
