# v18 基线与效果分析（判官模型接入前的逻辑优化起点）

日期：2026-11-05　依据：dev 台账 `decision_events` 300 行实测 + 代码行号级核查
定位：判官模型（judge_provider_id/judge_model 均空）**后续由小蜜蜂提供**；本轮目标是把**逻辑层**做扎实，
使模型一接入即可全效运转。

## 一、台账实测基线（2026-10-29 ~ 11-05，origin web 266 / test 34）

| 指标 | 实测 |
|---|---|
| 总判断 | 300（六岗全有行） |
| 真判率 | 81/300 = 30%（hit_layer ∈ {llm, cache, rule}） |
| 损耗层 | timeout 96、budget_cap 61(20%)、breaker_open 25、error 11、no_model 4、disabled 5 |
| 闭环率 | outcome 非 pending 23/300 = 7.7%（全打在 plan_gate 行） |
| 台账体积 | 判据 1024→128 字（-87%）；100% 有判据/耗时/档位，69% chat_id，30% turn，76% agent |
| 判官成本 | 64 次真判 / 51,277 tokens / ¥13.90 |
| 档位 | 合法率 30%；L0-1 占真判 91% |

各岗：

| 岗 | 次 | 真判 | 真判耗时 avg/max | 损耗 | 消费点 |
|---|---|---|---|---|---|
| acceptance 验收 | 55 | 24 (44%) | 8949 / 16963 ms | 31 | 台账 |
| skill_trigger 技能 | 93 | 39 (42%) | 5321 / 12820 ms | 54 | 台账 + 技能候选集 |
| plan_gate 判档 | 93 | 19 (20%) | 2841 / 8852 ms | 65 | 台账 + 思考形状 + 验收回填 |
| tool_gate 工具 | 46 | 8 (17%) | 11405 / 16875 ms | 38 | 台账 + 工具门禁提示 |
| plan_review 计划审查 | 6 | 0 | — | 6 | 台账 + 审查提示注入 |
| advisor 事中改道 | 7 | 0 | — | 7 | 台账 + 改道提示 |

判档"结论"文本分布（说明输出契约不统一）：
`复核为medium; thinking:low` 41、`判级=None` 24、`(空)` 11、`{'verdict': 'approved', 'source'…` 8、
`continue` 4、`plan` 2、`判为L3` 1。

## 二、对任务执行的真优化（已生效，有数据）

1. **思考档位单一来源**：真判时档位真进主链（41 行 `thinking:low` 即消费痕迹）。
2. **技能"场景强制"半闭环**：判官真判 39 次 → 命中技能 3 次（`预激活docx`×3，台账
   `action_text='预激活docx' source='intent'`），且仅出现在 pdf/docx 类请求——**判得准**。
3. **闭环起点**：`outcome=accepted` 20 行，`result_detail` 带验收理由。
4. **台账成为可度量对象**：六岗全有行、字段大体齐全、体积降 87%。

## 三、未兑现的五条（判官模型到位后仍会卡住）

1. 真判率 30%，70% 损耗。
2. 档位合法率 30%，且 91% 落 L0-1 → 复杂任务拿不到深思考。
3. 前摇（同步 await 岗）：plan_gate avg 2.8s(max 8.9s)、技能岗 avg 5.3s(max 12.8s)。
4. 闭环 7.7%，且 23 行闭环全打在 plan_gate 行 → 验收回填键归属错。
5. 六岗"只记录不干预"：改道岗 7 行 0 真判、计划审查 6 行 0 真判。

## 四、已证实缺陷（本轮新发现）

**技能岗"真判率最高、命中最低"的断链根因（待行号级复核）**：
`server/coapis/agents/utils/skill_selector.py` 约 547 与 586 行调用

```python
classify_intent_llm(message, skill_summaries, timeout=timeout)
```

而 `server/coapis/agents/utils/intent_classifier.py:191` 签名为
`async def classify_intent_llm(user_message, skill_summaries, scope=None)` —— **无 `timeout` 形参**
→ `TypeError` → 被外层宽 `except` 吞 → 加载层 Stage2（意图驱动技能装载）从未成功过一次。
台账铁证：技能岗真判 39 次，仅 3 次命中技能，其余 75 次"无技能命中"。

> 状态：已定位，**未改代码**，等 v19 方案拍板。

## 五、待体检清单（三路并行审查中）

- A 治理层：尺子读取链、轮内预算归属与污染、熔断失败定义、缓存键与串答案、降级契约完备性
- B 六岗与主链：接线矩阵、双头决策是否真消灭、hint 是否真进模型上下文、验收回填键、前摇并行空间
- C 技能链：三档匹配质量（过宽/误命中/幽灵映射）、索引与装载成本、指定技能链路、判官协同效能
