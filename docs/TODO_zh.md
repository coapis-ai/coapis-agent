# CoApis 优化路线图

_基于 2026-06-03 核心运行机制深度分析，按优先级排列_

---

## 一、全局智能体优化（P0）

### 1.1 全局智能体文件补全
- [x] 补全 default 和 CoApis_QA_Agent_0.2 的 6 个模板文件
- [x] agent.json 写入 enabled=true
- [x] 创建全局特有 AGENTS.md（在模板基础上增加组织级规范、安全策略）
- [x] 创建全局 HEARTBEAT.md（定期检查全局知识库健康度 + 梦境优化触发）

### 1.2 PromptBuilder 全局继承
- [x] system_prompt_files 增加 `global:AGENTS.md` 语法支持
- [x] PromptBuilder 自动加载全局智能体的文件作为基础层
- [x] 用户文件覆盖全局文件的同名 section（而非完全替换）
- [x] MEMORY.md 分层注入：全局记忆(core) + 用户记忆(long_term)

### 1.3 全局进化服务独立进程
- [x] CrossAgentEvolution 从 workspace 中独立出来
- [x] 作为全局服务运行（非 per-workspace 实例）
- [x] AB 桶数据放在全局共享位置（system/evolution/）
- [x] 定期扫描所有用户智能体的上报，统一评审
- [x] 评审结果写入全局文件（需管理员确认后生效）

### 1.4 全局记忆容量管理
- [x] 全局 MEMORY.md 容量限制（建议 10K tokens）
- [x] 自动淘汰低置信度 / 低使用频率的经验
- [x] 管理员可手动锁定/解锁经验条目
- [x] 全局记忆版本历史（可回滚）

---

## 二、进化引擎优化（P1）

### 2.1 CrossAgentEvolution 完善
- [x] report_experience 增加 is_generalizable 字段判断
- [x] AI 评审时判断经验是否适用于所有用户
- [x] 只有可泛化的经验才写入全局 MEMORY.md
- [x] A 桶内容需要管理员确认才写入全局文件

### 2.2 用户进化与全局进化联动
- [x] 用户智能体的 EvolutionEngine 提取经验后自动上报到全局 AB 桶
- [x] 全局进化结果自动推送到所有用户智能体（KnowledgeFlow.sync_from_foundation）
- [x] 用户可选择"全局模式"或"个人模式"
  - 全局模式: 优先使用全局 AGENTS.md，用户文件作为补充
  - 个人模式: 优先使用用户 AGENTS.md，全局文件作为兜底

### 2.3 经验质量控制
- [x] 经验提取增加"重复检测"（与已有 MEMORY.md 内容对比）
- [x] 经验置信度动态调整（基于用户反馈 / 使用频率）
- [x] 低质量经验自动降级（置信度 < 0.3 的经验标记为 archived）

---

## 三、记忆系统优化（P2）

### 3.1 MemoryInjector 完善
- [x] ReMeLight 语义检索集成（替代关键词匹配）
- [x] 基础记忆(core) 自动从全局 AGENTS.md + 全局 MEMORY.md 构建
- [x] 长期记忆(long_term) 基于 query 语义检索而非全量加载
- [x] 记忆注入日志（记录每次注入了哪些内容，便于调试）

### 3.2 梦境优化增强
- [x] 全局智能体的梦境优化改为定时任务（非会话触发）
- [x] 梦境优化增加"对比报告"（优化前后差异）
- [x] 梦境优化结果需要管理员确认（防止误删重要内容）

### 3.3 记忆检索优化
- [x] 实现 _reme_parser（ReMeLight 解析器）
- [x] MemoryInjector 使用语义检索替代关键词匹配
- [x] 检索结果按相关性排序 + 去重

---

## 四、技能系统优化（P3）

### 4.1 意图路由技能加载
- [x] 用户消息 → 轻量 LLM 判断意图 → 只加载相关技能描述
- [x] 减少 system prompt token 消耗
- [x] 技能描述分级：核心技能(始终加载) + 按需技能(意图路由)

### 4.2 技能自动创建
- [x] Nudge 审查结果自动创建技能草稿
- [x] 技能草稿需要管理员确认后才生效
- [x] 技能版本管理（支持回滚）

---

## 五、性能优化（P4）

### 5.1 PromptBuilder 缓存
- [x] mtime 缓存（已完成）
- [x] 缓存命中率统计
- [x] 缓存预热（workspace 启动时预加载）

### 5.2 经验提取采样
- [x] cooldown + min_chars 过滤（已完成）
- [x] 采样命中率统计
- [x] 动态调整采样参数（基于 LLM 调用成本）

### 5.3 LLM 调用优化
- [x] 经验提取 / Nudge 审查 / 梦境优化 共享 LLM client（避免重复创建）
- [x] LLM 调用增加重试机制
- [x] LLM 调用增加超时控制

---

## 六、监控与可观测性（P5）

### 6.1 进化引擎监控
- [x] 经验提取成功率 / 失败率统计
- [x] AB 桶容量监控
- [x] 知识流动审计日志

### 6.2 记忆系统监控
- [x] 记忆注入命中率
- [x] MEMORY.md 大小监控
- [x] 梦境优化执行日志

---

## 参考：核心架构图

```
用户聊天 → console_chat → runner.query_handler
  ├─ [进化] on_session_start / on_turn_start
  ├─ [技能] _maybe_inject_skill (/name input)
  ├─ [记忆] PromptBuilder + MemoryInjector (全局+用户分层)
  ├─ [钩子] BootstrapHook (首次引导)
  ├─ [执行] agent(msgs) → ReAct 循环
  ├─ [进化] on_turn_end → Nudge 检查
  └─ [持久化] on_session_end → 经验提取 → AB 桶 → KnowledgeFlow

全局进化循环:
  用户上报 → B 桶 → AI 评审 → A 桶 → 管理员确认 → 全局文件 → 推送所有用户
```

---

_最后更新: 2026-06-03_
_来源: 核心运行机制深度分析_
